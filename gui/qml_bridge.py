"""
QML bridge for mSense OS (PySide6 + Qt Quick).

Objects that connect the Python capture/processing layer to the QML UI:

- FrameView:    a QQuickPaintedItem that displays live RGB frames (camera, and
                the two mmWave heatmaps). Frames arrive as QImage via a slot.
- MmWaveWorker: runs the mmWave receive -> 3D-FFT -> colormap pipeline on its OWN
                QThread, off the Qt GUI thread. The FFT is ~38 ms/frame on Apple MPS
                (~210 ms on CPU); running it in the 30 Hz GUI timer callback froze the
                event loop and stuttered the camera + both heatmaps together. Here only
                finished, fully-detached QImages cross back to the GUI thread via queued
                signals. Recording is anchored here to the mmWave (master) clock.
- AppController: the GUI-thread "brain" — owns the ~30 Hz camera display loop, relays the
                worker's heatmap QImages to the FrameViews, drives recording state, and
                exposes status to QML.

All of core/ , recording/ and core/pose/ stay Qt-free; this module is the only
Qt boundary on the new GUI path.
"""

import time
import numpy as np

from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, QThread, Qt, QRectF
from PySide6.QtGui import QImage, QColor
from PySide6.QtQuick import QQuickPaintedItem

import sys
sys.path.append('..')
from config import DISPLAY_PARAMS
from recording.file_writer import FrameBundle


# ── viridis colormap LUT (ported from the old heatmap widget) ────────
def _viridis_lut() -> np.ndarray:
    anchors = np.array([
        [68, 1, 84], [72, 35, 116], [64, 67, 135], [52, 94, 141],
        [41, 120, 142], [32, 144, 140], [34, 167, 132], [68, 190, 112],
        [121, 209, 81], [189, 222, 38], [253, 231, 36]
    ], dtype=np.float32)
    lut = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0 * (len(anchors) - 1)
        idx = int(t)
        frac = t - idx
        if idx >= len(anchors) - 1:
            lut[i] = anchors[-1].astype(np.uint8)
        else:
            lut[i] = (anchors[idx] * (1 - frac) + anchors[idx + 1] * frac).astype(np.uint8)
    return lut


_VIRIDIS = _viridis_lut()


def rgb_to_qimage(rgb: np.ndarray) -> QImage:
    """Convert a contiguous HxWx3 uint8 RGB array to a DETACHED QImage.

    The trailing .copy() detaches the QImage from the numpy buffer -- required so the
    image is safe to hand to another thread (the source frame buffer may be reused/freed)."""
    if not rgb.flags['C_CONTIGUOUS']:
        rgb = np.ascontiguousarray(rgb)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()


def heatmap_to_qimage(data: np.ndarray) -> QImage:
    """Apply the viridis colormap to a normalized [0,1] heatmap -> DETACHED QImage.

    Emits a 32-bit RGBA image (4 bytes/px), NOT RGB888. The RD heatmap is 255
    wide -> an RGB888 row is 255*3 = 765 bytes, which is not 4-byte aligned;
    the Qt Quick scene-graph texture path renders that with a per-row shear
    that shows up as equidistant vertical stripes in RD (but not RA, which is
    256 wide -> 768, aligned). A 4-channel image is always row-aligned
    (4*w), so this is width-agnostic and stripe-free."""
    data = np.clip(data.astype(np.float32), 0.0, 1.0)
    idx = (data * 255).astype(np.uint8)
    h, w = data.shape
    rgba = np.empty((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = _VIRIDIS[idx.reshape(-1)].reshape(h, w, 3)
    rgba[:, :, 3] = 255
    rgba = np.ascontiguousarray(rgba)
    return QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy()


class FrameView(QQuickPaintedItem):
    """QML item that paints the latest frame, scaled to fit (aspect-preserved)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self.setFillColor(QColor("#0b0b0c"))
        # Cache of the scaled image: paint() fires on ANY repaint (resize,
        # expose, scene-graph update), not just on new frames — re-running a
        # SmoothTransformation resample of a 1280x720 frame on the GUI thread
        # every paint is a multi-ms tax that caps display FPS.
        self._scaled = None
        self._scaled_key = None

    @Slot(QImage)
    def setImage(self, image: QImage):
        self._image = image
        self.update()

    @Slot()
    def clearImage(self):
        self._image = QImage()
        self._scaled = None
        self._scaled_key = None
        self.update()

    def paint(self, painter):
        if self._image.isNull():
            return
        bounds = self.boundingRect()
        size = bounds.size().toSize()
        key = (self._image.cacheKey(), size.width(), size.height())
        if self._scaled_key != key:
            self._scaled = self._image.scaled(size, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation)
            self._scaled_key = key
        target = self._scaled
        x = bounds.x() + (bounds.width() - target.width()) / 2.0
        y = bounds.y() + (bounds.height() - target.height()) / 2.0
        painter.drawImage(QRectF(x, y, target.width(), target.height()), target)


class MmWaveWorker(QObject):
    """mmWave receive -> FFT -> colormap (+ recording), OFF the GUI thread.

    Lives on its own QThread (started via `run`). Pulls complete frames from the capture
    backend, runs MmWaveProcessor.process() (FFT on MPS/CUDA/CPU), converts RD/RA to
    QImages, and emits them via QUEUED signals so FrameView.setImage runs on the GUI
    thread (QImage is an implicitly-shared metatype -> AutoConnection resolves to Queued).
    The QImages are detached (see rgb_to_qimage) so they are safe to cross the boundary.

    Recording is anchored HERE to the mmWave master clock: each completed mmWave frame
    snapshots the latest camera frame atomically (get_frame_full) and logs both stamps.
    """

    rdReady = Signal(QImage)
    raReady = Signal(QImage)
    frameProcessed = Signal(float, int)   # (mmw_ts, frame_num) -> GUI counters/sync

    def __init__(self, capture, processor):
        super().__init__()
        self._capture = capture
        self._processor = processor
        self._running = True

        # True while an iteration is in flight — used by wait_idle() so the
        # stop flow can quiesce before finalizing the session (a bundle
        # landing after the session close would otherwise be lost)
        self._busy = False

        # Recording wiring, set from the GUI thread before enabling recording.
        self._recording = False
        self._recorder = None
        self._file_writer = None
        self._camera_capture = None
        self._timestamp_logger = None

    @Slot()
    def run(self):
        """Worker loop: pull -> process -> emit, until stop()."""
        while self._running:
            result = self._capture.get_frame()
            if isinstance(result[0], str):           # 'wait new frame' sentinel
                QThread.msleep(2)                    # yield (releases the GIL for the receiver)
                continue

            # Live display: when NOT recording, skip to the NEWEST available frame so a
            # startup backlog (frames buffered by the receiver while the camera/model loaded)
            # isn't replayed fast-forward, and a transient stall self-heals to real time.
            # When recording, process every frame in order (lossless).
            if not self._recording:
                while True:
                    nxt = self._capture.get_frame()
                    if isinstance(nxt[0], str):
                        break
                    result = nxt

            self._busy = True
            try:
                data, mmw_ts, fnum, lost = result
                try:
                    rd, ra, _ = self._processor.process(data, compute_da=False)
                except Exception as e:
                    print(f"[mmWave] process error: {e}")
                    rd = ra = None

                if rd is not None:
                    # Emit finished heatmaps (queued -> painted on the GUI thread).
                    self.rdReady.emit(heatmap_to_qimage(rd))
                    self.raReady.emit(heatmap_to_qimage(ra))

                # Raw recording must NOT depend on the FFT succeeding — the
                # raw stream is the ground truth everything else derives from
                if self._recording and self._recorder is not None and self._recorder.is_recording:
                    self._record(data, rd, ra, fnum, mmw_ts, lost)

                self.frameProcessed.emit(mmw_ts, fnum)
            except Exception as e:
                # The worker must NEVER die: an unhandled exception here
                # (e.g. a stop-flow race) would silently freeze the RD/RA
                # views for the rest of the app session
                print(f"[mmWave] worker iteration error: {e}")
            finally:
                self._busy = False

    def _record(self, data, rd, ra, fnum, mmw_ts, lost):
        """Persist one mmWave frame + the atomically-snapshotted latest camera
        frame as a single atomic FrameBundle (whole frame queued or whole
        frame dropped — no per-modality holes)."""
        fw, rec = self._file_writer, self._recorder
        if fw is None or rec is None:
            return

        raw_path = rec.get_raw_path()
        if raw_path is None:
            return   # session is closing concurrently

        # Snapshot raw+overlay+ts+landmarks from the SAME camera capture under one lock,
        # so the saved camera frame, its skeleton and its timestamp cannot skew apart.
        # The CLEAN frame is recorded (skeleton stays in the landmarks JSON, never
        # burned into pixels — the overlay is reproducible from clean + landmarks,
        # the reverse is not).
        cam_ts = 0.0
        frame = None
        landmarks = None
        if self._camera_capture is not None:
            frame, _, cam_ts, landmarks = self._camera_capture.get_frame_full()

        bundle = FrameBundle(
            frame_num=fnum,
            mmwave_ts=mmw_ts,
            camera_ts=cam_ts,
            lost_packet=bool(lost),
            raw=data,
            raw_path=raw_path,
            rd=rd,
            rd_path=rec.get_frame_path(fnum, 'rd'),
            ra=ra,
            ra_path=rec.get_frame_path(fnum, 'ra'),
            camera_frame=frame,
            camera_path=rec.get_frame_path(fnum, 'camera'),
            skeleton=landmarks,
            skeleton_path=rec.get_frame_path(fnum, 'skeleton'),
        )

        # Only count/log frames that actually made it into the write queue,
        # so metadata.frame_count and timestamps.csv match the data on disk
        if fw.submit_bundle(bundle):
            rec.increment_frame_count()
            logger = self._timestamp_logger
            if logger:
                logger.log(fnum, mmw_ts, cam_ts, bool(lost))

    def wait_idle(self, timeout: float = 3.0) -> bool:
        """
        Wait until no worker iteration is in flight.

        Called by the stop flow AFTER _recording=False: an in-flight _record
        finishes submitting its bundle before the caller finalizes the
        session, so no late bundle can land behind the session close.
        """
        deadline = time.monotonic() + timeout
        while self._busy and time.monotonic() < deadline:
            time.sleep(0.005)
        return not self._busy

    def stop(self):
        self._running = False


class AppController(QObject):
    """Owns the GUI-thread camera display loop and exposes state/commands to QML."""

    # Frame channels (QImage to the three FrameViews)
    cameraFrameReady = Signal(QImage)
    rdFrameReady = Signal(QImage)
    raFrameReady = Signal(QImage)

    # Single notify for all scalar display properties (updated ~1 Hz)
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._mmwave_capture = None
        self._camera_capture = None
        self._mmwave_processor = None
        self._recorder = None
        self._file_writer = None
        self._timestamp_logger = None

        # mmWave worker (created lazily in start_preview when capture+processor exist)
        self._mmw_worker = None
        self._mmw_thread = None
        self._mmw_active = False

        # display state
        self._mode = "Preview"
        self._skeleton = True
        self._recording = False
        self._fps = 0.0
        self._sync_text = "--"
        self._pose_text = "pose: --"
        self._frame_count = 0
        self._elapsed = "00:00:00"

        # timing
        self._last_fps_time = time.time()
        self._fps_frame_count = 0
        self._record_start = None
        self._last_cam_ts = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_update)
        self._timer.setInterval(int(1000 / DISPLAY_PARAMS['update_rate_hz']))

    # ── wiring (called from main.py) ─────────────────────────────
    def set_mmwave_capture(self, c): self._mmwave_capture = c
    def set_camera_capture(self, c): self._camera_capture = c
    def set_mmwave_processor(self, p): self._mmwave_processor = p
    def set_recorder(self, r): self._recorder = r
    def set_file_writer(self, w): self._file_writer = w

    def start_preview(self):
        """Go live immediately (camera + heatmaps); recording stays off."""
        self._last_fps_time = time.time()
        self._fps_frame_count = 0
        self._start_mmwave_worker()
        if not self._timer.isActive():
            self._timer.start()

    def _start_mmwave_worker(self):
        """Spin up the off-GUI-thread mmWave pipeline (idempotent)."""
        if self._mmw_worker is not None:
            return
        if not (self._mmwave_capture and self._mmwave_processor):
            return
        self._mmw_thread = QThread()
        self._mmw_worker = MmWaveWorker(self._mmwave_capture, self._mmwave_processor)
        self._mmw_worker._recorder = self._recorder
        self._mmw_worker._file_writer = self._file_writer
        self._mmw_worker._camera_capture = self._camera_capture
        self._mmw_worker.moveToThread(self._mmw_thread)
        # Cross-thread (worker -> GUI): queued. Signal->signal relay keeps QML wiring intact.
        self._mmw_worker.rdReady.connect(self.rdFrameReady)
        self._mmw_worker.raReady.connect(self.raFrameReady)
        self._mmw_worker.frameProcessed.connect(self._on_mmw_frame)
        self._mmw_thread.started.connect(self._mmw_worker.run)
        self._mmw_thread.start()

    # ── QML-exposed scalar properties ────────────────────────────
    @Property(str, notify=changed)
    def statusText(self):
        return "Recording" if self._recording else "Ready"

    @Property(bool, notify=changed)
    def recording(self):
        return self._recording

    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    @Property(bool, notify=changed)
    def skeletonEnabled(self):
        return self._skeleton

    @Property(str, notify=changed)
    def fpsText(self):
        return f"{self._fps:.1f} FPS"

    @Property(str, notify=changed)
    def frameText(self):
        return f"{self._frame_count:,} frames"

    @Property(str, notify=changed)
    def syncText(self):
        return self._sync_text

    @Property(str, notify=changed)
    def poseText(self):
        return self._pose_text

    @Property(str, notify=changed)
    def elapsedText(self):
        return self._elapsed

    # ── QML-invoked commands ─────────────────────────────────────
    @Slot(bool)
    def setSkeleton(self, enabled: bool):
        self._skeleton = enabled
        if self._camera_capture:
            self._camera_capture.set_skeleton_enabled(enabled)
        self.changed.emit()

    @Slot(str)
    def setPoseBackend(self, name: str):
        if self._camera_capture:
            self._camera_capture.set_pose_backend(name)

    @Slot(str)
    def setKeypointGroup(self, group: str):
        if self._camera_capture:
            self._camera_capture.set_keypoint_group(group)

    @Slot(str)
    def setMode(self, mode: str):
        self._mode = mode
        self.changed.emit()

    def _capture_info(self) -> dict:
        """Describe the active mmWave backend for session metadata, so
        recorded timestamps/frame numbers are interpretable offline (the C
        and Python backends have different semantics)."""
        cap = self._mmwave_capture
        if cap is None:
            return {}
        return {
            "backend": type(cap).__name__,
            "timestamp_semantics": getattr(cap, "timestamp_semantics", "assembly_time"),
            "frame_num_semantics": getattr(cap, "frame_num_semantics", "radar_absolute_index"),
        }

    @Slot()
    def start(self):
        """Start a recording session (only meaningful in Recording mode)."""
        if self._mode == "Recording" and self._recorder and not self._recording:
            skeleton = self._skeleton
            path = self._recorder.start_session(skeleton, capture_info=self._capture_info())
            print(f"[Rec] {path}")
            if self._recorder.session_path:
                from recording.recorder import TimestampLogger
                self._timestamp_logger = TimestampLogger(self._recorder.get_timestamps_path())
                self._timestamp_logger.open()
            self._recording = True
            self._record_start = time.time()
            self._frame_count = 0
            if self._file_writer:
                self._file_writer.reset_stats()
            # Hand recording state to the worker LAST, after the session + logger exist.
            if self._mmw_worker is not None:
                self._mmw_worker._timestamp_logger = self._timestamp_logger
                self._mmw_worker._recording = True
            self.changed.emit()
        self.start_preview()

    @Slot()
    def stop(self):
        """Stop recording; live preview keeps running."""
        # Tell the worker to stop recording FIRST, then QUIESCE: an iteration
        # already past the _recording check must finish submitting its bundle
        # before we close the logger / finalize the session, or its data
        # files land without a CSV row (and a late raw write could follow
        # the session close).
        if self._mmw_worker is not None:
            self._mmw_worker._recording = False
            if not self._mmw_worker.wait_idle(timeout=3.0):
                print("[Rec] WARNING: mmWave worker still busy at stop")
        if self._recorder and self._recorder.is_recording:
            if self._timestamp_logger:
                self._timestamp_logger.close()
                self._timestamp_logger = None
                if self._mmw_worker is not None:
                    self._mmw_worker._timestamp_logger = None
            # Close session files after all queued bundles (FIFO), then wait
            # with a REAL timeout — the GUI thread can never freeze here
            if self._file_writer:
                if not self._file_writer.end_session():
                    # Queue full: let it drain, then retry once
                    self._file_writer.wait_completion(timeout=10.0)
                    self._file_writer.end_session()
                if not self._file_writer.wait_completion(timeout=10.0):
                    print("[Rec] WARNING: disk writer did not drain in time — "
                          "the session may be missing trailing frames")
                stats = self._file_writer.get_stats()
                if stats["writes_dropped"]:
                    print(f"[Rec] WARNING: {stats['writes_dropped']} whole frames "
                          f"dropped by the disk writer during this session")
            info = self._recorder.stop_session()
            print(f"[Rec] Done: {info.get('frame_count', 0)} frames")
        self._recording = False
        self._record_start = None
        self.changed.emit()

    # ── GUI-thread camera display loop ───────────────────────────
    def _on_update(self):
        """30 Hz on the GUI thread: camera display + status only. The mmWave FFT runs in
        MmWaveWorker on its own thread and arrives via rdFrameReady/raFrameReady."""
        cam_updated = False

        if self._camera_capture:
            if self._skeleton:
                frame, cam_ts, _ = self._camera_capture.get_frame_with_overlay()
            else:
                frame, cam_ts, _ = self._camera_capture.get_frame()
            if frame is not None:
                self.cameraFrameReady.emit(rgb_to_qimage(frame))
                self._last_cam_ts = cam_ts
                cam_updated = True

        if cam_updated:
            self._frame_count += 1
            self._fps_frame_count += 1
            if not self._mmw_active:
                self._sync_text = "cam only"

        now = time.time()
        if now - self._last_fps_time >= 1.0:
            self._fps = self._fps_frame_count / (now - self._last_fps_time)
            self._last_fps_time = now
            self._fps_frame_count = 0
            if self._camera_capture:
                self._pose_text = self._pose_label(self._camera_capture.get_pose_info())
            if self._record_start is not None:
                el = int(now - self._record_start)
                self._elapsed = f"{el//3600:02d}:{(el%3600)//60:02d}:{el%60:02d}"
            self.changed.emit()

    @Slot(float, int)
    def _on_mmw_frame(self, mmw_ts: float, fnum: int):
        """GUI-thread slot: a new mmWave frame was processed by the worker. Update the
        sync indicator against the latest camera timestamp."""
        self._mmw_active = True
        if self._last_cam_ts > 0 and mmw_ts > 0:
            self._sync_text = self._sync_label(abs(mmw_ts - self._last_cam_ts) * 1000)
        else:
            self._sync_text = "mmwave only"

    @staticmethod
    def _sync_label(ms: float) -> str:
        return f"sync {ms:.0f}ms"

    @staticmethod
    def _pose_label(info: dict) -> str:
        if not info:
            return "pose: --"
        s = info.get("status")
        if s == "loading":
            return f"{info.get('backend')}: loading…"
        if s == "error":
            return f"{info.get('backend')}: error"
        if s == "ready":
            return f"{info.get('backend')} · {info.get('device')} · {info.get('inference_fps',0):.1f} ip/s"
        return f"{info.get('backend')}: {s}"

    def shutdown(self):
        self._timer.stop()
        if self._mmw_worker is not None:
            self._mmw_worker.stop()
        if self._mmw_thread is not None:
            self._mmw_thread.quit()
            self._mmw_thread.wait(2000)

"""
QML bridge for Vomee (PySide6 + Qt Quick).

Two objects connect the Python capture/processing layer to the QML UI:

- FrameView:    a QQuickPaintedItem that displays live RGB frames (camera, and
                the two mmWave heatmaps). Frames arrive as QImage via a slot.
- AppController: the "brain" — owns the 30 Hz update loop, pulls frames from the
                capture threads, runs the mmWave processor, pushes QImages to the
                FrameViews, drives recording, and exposes status to QML.

All of core/ , recording/ and core/pose/ stay Qt-free; this module is the only
Qt boundary on the new GUI path.
"""

import time
import numpy as np

from PySide6.QtCore import QObject, Signal, Slot, Property, QTimer, Qt, QRectF
from PySide6.QtGui import QImage, QColor
from PySide6.QtQuick import QQuickPaintedItem

import sys
sys.path.append('..')
from config import DISPLAY_PARAMS


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
    """Convert a contiguous HxWx3 uint8 RGB array to a detached QImage."""
    if not rgb.flags['C_CONTIGUOUS']:
        rgb = np.ascontiguousarray(rgb)
    h, w, ch = rgb.shape
    return QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()


def heatmap_to_qimage(data: np.ndarray) -> QImage:
    """Apply the viridis colormap to a normalized [0,1] heatmap -> QImage."""
    data = np.clip(data.astype(np.float32), 0.0, 1.0)
    idx = (data * 255).astype(np.uint8)
    h, w = data.shape
    rgb = _VIRIDIS[idx.flatten()].reshape(h, w, 3)
    return rgb_to_qimage(rgb)


class FrameView(QQuickPaintedItem):
    """QML item that paints the latest frame, scaled to fit (aspect-preserved)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self.setFillColor(QColor("#0b0b0c"))

    @Slot(QImage)
    def setImage(self, image: QImage):
        self._image = image
        self.update()

    @Slot()
    def clearImage(self):
        self._image = QImage()
        self.update()

    def paint(self, painter):
        if self._image.isNull():
            return
        bounds = self.boundingRect()
        target = self._image.scaled(bounds.size().toSize(),
                                    Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = bounds.x() + (bounds.width() - target.width()) / 2.0
        y = bounds.y() + (bounds.height() - target.height()) / 2.0
        painter.drawImage(QRectF(x, y, target.width(), target.height()), target)


class AppController(QObject):
    """Owns the live loop and exposes state/commands to QML."""

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
        if not self._timer.isActive():
            self._timer.start()

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

    @Slot()
    def start(self):
        """Start a recording session (only meaningful in Recording mode)."""
        if self._mode == "Recording" and self._recorder and not self._recording:
            skeleton = self._skeleton
            path = self._recorder.start_session(skeleton)
            print(f"[Rec] {path}")
            if self._recorder.session_path:
                from recording.recorder import TimestampLogger
                self._timestamp_logger = TimestampLogger(self._recorder.get_timestamps_path())
                self._timestamp_logger.open()
            self._recording = True
            self._record_start = time.time()
            self._frame_count = 0
            self.changed.emit()
        self.start_preview()

    @Slot()
    def stop(self):
        """Stop recording; live preview keeps running."""
        if self._recorder and self._recorder.is_recording:
            if self._timestamp_logger:
                self._timestamp_logger.close()
                self._timestamp_logger = None
            info = self._recorder.stop_session()
            print(f"[Rec] Done: {info.get('frame_count', 0)} frames")
            if self._file_writer:
                self._file_writer.wait_completion(timeout=5.0)
        self._recording = False
        self._record_start = None
        self.changed.emit()

    # ── live loop (ported from MainWindow._on_update) ────────────
    def _on_update(self):
        cam_updated = mmw_updated = False
        sync_ms = -1.0
        cam_ts = 0
        frame = None
        landmarks = None

        if self._camera_capture:
            if self._skeleton:
                frame, cam_ts, landmarks = self._camera_capture.get_frame_with_overlay()
            else:
                frame, cam_ts, landmarks = self._camera_capture.get_frame()
            if frame is not None:
                self.cameraFrameReady.emit(rgb_to_qimage(frame))
                cam_updated = True

        if self._mmwave_capture:
            result = self._mmwave_capture.get_frame()
            if not isinstance(result[0], str):
                data, mmw_ts, fnum, lost = result
                if cam_updated and cam_ts > 0 and mmw_ts > 0:
                    sync_ms = abs(mmw_ts - cam_ts) * 1000
                if self._mmwave_processor:
                    try:
                        rd, ra, _ = self._mmwave_processor.process(data)
                        self.rdFrameReady.emit(heatmap_to_qimage(rd))
                        self.raFrameReady.emit(heatmap_to_qimage(ra))
                        mmw_updated = True
                        if self._recorder and self._recorder.is_recording:
                            self._record(data, rd, ra, fnum, mmw_ts,
                                         cam_ts if cam_updated else 0, frame, landmarks)
                    except Exception as e:
                        print(f"[Err] {e}")

        # sync indicator
        if mmw_updated and cam_updated:
            self._sync_text = self._sync_label(sync_ms)
        elif cam_updated:
            self._sync_text = "cam only"
        elif mmw_updated:
            self._sync_text = "mmwave only"

        if cam_updated or mmw_updated:
            self._frame_count += 1
            self._fps_frame_count += 1

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

    def _record(self, data, rd, ra, fnum, mmw_ts, cam_ts, frame, landmarks):
        if not self._file_writer or not self._recorder:
            return
        self._recorder.increment_frame_count()
        raw_path = self._recorder.get_raw_path()
        if raw_path:
            self._file_writer.write_raw_mmwave(raw_path, data, fnum)
        rd_path = self._recorder.get_frame_path(fnum, 'rd')
        if rd_path:
            self._file_writer.write_rd_heatmap(rd_path, rd, fnum)
        ra_path = self._recorder.get_frame_path(fnum, 'ra')
        if ra_path:
            self._file_writer.write_ra_heatmap(ra_path, ra, fnum)
        if frame is not None:
            cam_path = self._recorder.get_frame_path(fnum, 'camera')
            if cam_path:
                self._file_writer.write_camera_frame(cam_path, frame, fnum)
        if landmarks:
            skel_path = self._recorder.get_frame_path(fnum, 'skeleton')
            if skel_path:
                self._file_writer.write_skeleton(skel_path, landmarks, fnum)
        if self._timestamp_logger:
            self._timestamp_logger.log(fnum, mmw_ts, cam_ts)

    def shutdown(self):
        self._timer.stop()

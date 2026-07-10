"""Bus-driven QML controller — the GUI as an OPTIONAL bus consumer.

Exposes exactly the API the existing ``gui/qml/Main.qml`` expects (signals
``cameraFrameReady``/``rdFrameReady``/``raFrameReady``; the status properties; the
``setSkeleton``/``setMode``/``start``/``stop``/... slots) but is driven by the
:class:`FrameBus` instead of polling the capture objects. So the same QML renders the
rebuilt pipeline, and the pipeline runs fine headless (this controller simply isn't
created). Presentation helpers (colormap → QImage, the FrameView item) are reused from the
existing ``gui.qml_bridge`` module — no visual change.

Threading: bus callbacks fire on the source threads; Qt delivers the emitted QImage signals
to the GUI thread via a queued connection automatically. Stats are refreshed by a 1 Hz
timer on the GUI thread.
"""
from __future__ import annotations

import os
import sys
import threading
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QImage  # noqa: F401  (QImage flows through the signals)

from ..core.logging import get_logger
from ..core.types import Topic

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Reuse the existing presentation layer (colormap + QImage helpers + FrameView item).
from gui.qml_bridge import heatmap_to_qimage, rgb_to_qimage  # noqa: E402

_log = get_logger("gui")


class BusController(QObject):
    cameraFrameReady = Signal(QImage)
    rdFrameReady = Signal(QImage)
    raFrameReady = Signal(QImage)
    changed = Signal()

    def __init__(self, pipeline, recorder=None, camera_source=None):
        super().__init__()
        self._pipeline = pipeline
        self._recorder = recorder
        self._camera = camera_source

        self._mode = "Preview"
        self._skeleton = pipeline.config.record.show_skeleton
        self._recording = False
        self._fps = 0.0
        self._frame_count = 0
        self._sync_text = "--"
        self._pose_text = "pose: --"
        self._elapsed = "00:00:00"

        self._lock = threading.Lock()
        self._fps_count = 0
        self._last_fps_t = time.time()
        self._record_start = None
        self._last_cam_ts = 0.0
        self._last_mmw_ts = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(1000)

        # subscribe to the bus
        pipeline.bus.subscribe(Topic.CAMERA, self._on_camera)
        pipeline.bus.subscribe(Topic.RADAR_RD, self._on_rd)
        pipeline.bus.subscribe(Topic.RADAR_RA, self._on_ra)

    # -- bus callbacks (source threads) ---------------------------------------
    def _on_camera(self, frame):
        img = frame.meta.get("overlay") if self._skeleton else frame.data
        if img is None:
            img = frame.data
        self.cameraFrameReady.emit(rgb_to_qimage(img))
        with self._lock:
            self._fps_count += 1
            self._frame_count += 1
            self._last_cam_ts = frame.ts

    def _on_rd(self, frame):
        self.rdFrameReady.emit(heatmap_to_qimage(frame.data))
        with self._lock:
            self._last_mmw_ts = frame.ts

    def _on_ra(self, frame):
        self.raFrameReady.emit(heatmap_to_qimage(frame.data))

    # -- lifecycle ------------------------------------------------------------
    def start_preview(self) -> None:
        with self._lock:
            self._last_fps_t = time.time()
            self._fps_count = 0
        if not self._timer.isActive():
            self._timer.start()

    def _tick(self) -> None:
        now = time.time()
        with self._lock:
            dt = now - self._last_fps_t
            if dt > 0:
                self._fps = self._fps_count / dt
            self._fps_count = 0
            self._last_fps_t = now
            cam, mmw = self._last_cam_ts, self._last_mmw_ts
            if self._record_start is not None:
                el = int(now - self._record_start)
                self._elapsed = f"{el // 3600:02d}:{(el % 3600) // 60:02d}:{el % 60:02d}"
        if cam and mmw:
            self._sync_text = f"{abs(mmw - cam) * 1000:.0f} ms"
        if self._camera is not None:
            info = self._camera.pose_info()
            if info:
                self._pose_text = f"{info.get('backend','?')}:{info.get('status','?')}@{info.get('device','?')}"
        self.changed.emit()

    # -- QML properties -------------------------------------------------------
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

    # -- QML slots ------------------------------------------------------------
    @Slot(bool)
    def setSkeleton(self, enabled: bool):
        self._skeleton = enabled
        if self._camera is not None:
            self._camera.set_skeleton_enabled(enabled)
        self.changed.emit()

    @Slot(str)
    def setPoseBackend(self, name: str):
        if self._camera is not None and self._camera._cap is not None:
            self._camera._cap.set_pose_backend(name)

    @Slot(str)
    def setKeypointGroup(self, group: str):
        if self._camera is not None and self._camera._cap is not None:
            self._camera._cap.set_keypoint_group(group)

    @Slot(str)
    def setMode(self, mode: str):
        self._mode = mode
        self.changed.emit()

    @Slot()
    def start(self):
        if self._mode == "Recording" and self._recorder is not None and not self._recording:
            path = self._recorder.start_session()
            _log.info("recording: %s", path)
            with self._lock:
                self._recording = True
                self._record_start = time.time()
                self._frame_count = 0
            self.changed.emit()
        self.start_preview()

    @Slot()
    def stop(self):
        if self._recorder is not None and self._recorder.is_recording:
            self._recorder.stop_session()
        with self._lock:
            self._recording = False
            self._record_start = None
        self.changed.emit()

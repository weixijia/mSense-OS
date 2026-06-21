"""Camera source — wraps the existing ``core/camera_capture`` (camera + ViTPose).

Publishes the **raw** RGB frame on :data:`Topic.CAMERA` (for saving) and the pose result
on :data:`Topic.SKELETON`; the drawn overlay is carried in the CAMERA frame's ``meta``
so a display consumer can choose to show it — i.e. *show/overlay is independent of what
gets recorded*. The vendored ViTPose backend already selects CUDA → MPS → CPU, matching
:class:`ComputeManager`'s policy, so device behavior is preserved.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional

from ..core.bus import FrameBus
from ..core.logging import get_logger
from ..core.types import Frame, Topic
from ..sources.base import Source

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_log = get_logger("source.camera")


class CameraSource(Source):
    topic = Topic.CAMERA

    def __init__(self, config, enable_skeleton: Optional[bool] = None):
        self.config = config
        self._enable_skeleton = (config.record.show_skeleton if enable_skeleton is None else enable_skeleton)
        self._cap = None
        self._thread = None
        self._running = False
        self._fid = 0

    def start(self, bus: FrameBus) -> None:
        from core.camera_capture import CameraCapture  # existing camera+pose
        self._cap = CameraCapture(
            device_id=self.config.camera.device,
            enable_skeleton=self._enable_skeleton,
            pose_backend=self.config.pose.backend,
            keypoint_group=self.config.pose.keypoint_group,
        )
        self._cap.start()
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=(bus,), daemon=True, name="camera-source")
        self._thread.start()
        _log.info("camera source started (device=%s skeleton=%s)", self.config.camera.device, self._enable_skeleton)

    def _loop(self, bus: FrameBus) -> None:
        last_ts = None
        while self._running:
            # one atomic fetch -> raw (for saving), overlay (for display), ts, landmarks all
            # from the SAME camera frame (frame-aligned; fixes inter-call skew).
            raw, overlay, ts, landmarks = self._cap.get_frame_full()
            if raw is None or ts == last_ts:
                time.sleep(0.005)
                continue
            last_ts = ts
            self._fid += 1
            bus.publish(Frame(Topic.CAMERA, ts, self._fid, raw, {"overlay": overlay}))
            if landmarks is not None:
                bus.publish(Frame(Topic.SKELETON, ts, self._fid, landmarks, {}))

    # passthrough controls (used by the GUI)
    def set_skeleton_enabled(self, enabled: bool) -> None:
        self._enable_skeleton = enabled
        if self._cap is not None:
            self._cap.set_skeleton_enabled(enabled)

    def pose_info(self) -> dict:
        return self._cap.get_pose_info() if self._cap is not None else {}

    @property
    def is_ready(self) -> bool:
        return bool(self._cap is not None and self._cap.is_ready)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.stop()
            except Exception:
                _log.exception("camera stop error")
            self._cap = None

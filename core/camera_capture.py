"""
Camera Capture Module

Webcam capture with pluggable pose estimation. ViTPose (smallest 's' model) is
the skeleton-tracking backend, running cross-platform (CUDA / Apple MPS / CPU).

The heavy pose model is loaded asynchronously so the camera preview stays live
while the model initializes, and backend/keypoint-group switches happen without
blocking the capture loop.
"""

import threading
import platform
import numpy as np
import cv2
from datetime import datetime
from typing import Tuple, Optional, Dict
import time

import sys
sys.path.append('..')
from config import CAMERA_PARAMS, POSE_PARAMS

from .pose import create_pose_backend


class CameraCapture(threading.Thread):
    """Camera capture thread with a swappable pose-estimation backend."""

    def __init__(self,
                 device_id: int = None,
                 width: int = None,
                 height: int = None,
                 fps: int = None,
                 enable_skeleton: bool = False,
                 pose_backend: str = None,
                 keypoint_group: str = None):
        threading.Thread.__init__(self, daemon=True)

        self.device_id = device_id if device_id is not None else CAMERA_PARAMS['device']
        self.width = width or CAMERA_PARAMS['width']
        self.height = height or CAMERA_PARAMS['height']
        self.fps = fps or CAMERA_PARAMS['fps']

        self._running = True
        self._lock = threading.Lock()
        self._enable_skeleton = False
        self._frame = None
        self._frame_with_skeleton = None
        self._timestamp = 0.0
        self._landmarks = None
        self._frame_count = 0

        # Inference timing
        self._inference_fps = 0.0

        self.cap = None

        # Pose backend (loaded asynchronously)
        self._backend = None
        self._backend_name = pose_backend or POSE_PARAMS['backend']
        self._keypoint_group = keypoint_group or POSE_PARAMS['keypoint_group']
        self._backend_status = "loading"   # loading | ready | error | none
        self._backend_lock = threading.Lock()

        # Init camera (fast) then kick off async backend load (slow).
        self._init_camera()
        self._want_skeleton = enable_skeleton
        self._load_backend_async(self._backend_name)

    # ── camera ───────────────────────────────────────────────────

    def _camera_backends(self):
        """Return ordered (cv2 backend, name) candidates for this OS."""
        system = platform.system()
        candidates = []
        if system == "Windows":
            candidates = [("CAP_DSHOW", "DirectShow"), ("CAP_MSMF", "MSMF")]
        elif system == "Darwin":
            candidates = [("CAP_AVFOUNDATION", "AVFoundation")]
        else:  # Linux and others
            candidates = [("CAP_V4L2", "V4L2")]
        candidates.append(("CAP_ANY", "Auto"))

        resolved = []
        for attr, name in candidates:
            backend = getattr(cv2, attr, None)
            if backend is not None:
                resolved.append((backend, name))
        return resolved

    def _init_camera(self):
        """Open the camera using the best backend for the current OS."""
        for backend, name in self._camera_backends():
            try:
                cap = cv2.VideoCapture(self.device_id, backend)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    cap.set(cv2.CAP_PROP_FPS, self.fps)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    ret, test = cap.read()
                    if ret:
                        self.cap = cap
                        print(f"[Camera] {name}: {test.shape[1]}x{test.shape[0]}")
                        return
                cap.release()
            except Exception:
                pass
        raise RuntimeError(f"Cannot open camera {self.device_id}")

    # ── pose backend management ──────────────────────────────────

    def _load_backend_async(self, name: str):
        """Load (or swap) the pose backend on a worker thread."""
        with self._backend_lock:
            self._backend_status = "loading"
            self._backend_name = name

        def worker():
            old = None
            try:
                kwargs = {}
                if name == "vitpose":
                    kwargs = dict(
                        model_size=POSE_PARAMS['vitpose_model'],
                        dataset=POSE_PARAMS['vitpose_dataset'],
                        keypoint_group=self._keypoint_group,
                        yolo_size=POSE_PARAMS['yolo_size'],
                        device=POSE_PARAMS['device'],
                        confidence_threshold=POSE_PARAMS['confidence_threshold'],
                        skeleton_thickness=POSE_PARAMS['skeleton_thickness'],
                    )
                backend = create_pose_backend(name, **kwargs)
                with self._backend_lock:
                    old = self._backend
                    self._backend = backend
                    self._backend_status = "ready"
                # Honor the requested skeleton state once the backend is ready.
                with self._lock:
                    if self._want_skeleton:
                        self._enable_skeleton = True
                print(f"[Camera] Pose backend '{name}' ready on {backend.device}")
            except Exception as e:
                with self._backend_lock:
                    self._backend_status = "error"
                print(f"[Camera] Failed to load pose backend '{name}': {e}")
                import traceback
                traceback.print_exc()
            finally:
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass

        threading.Thread(target=worker, daemon=True).start()

    def set_pose_backend(self, name: str):
        """Switch the pose backend at runtime (loads asynchronously)."""
        if name == self._backend_name and self._backend_status == "ready":
            return
        self._load_backend_async(name)

    def set_keypoint_group(self, group: str):
        """Change which keypoint group is drawn/recorded."""
        self._keypoint_group = group
        with self._backend_lock:
            if self._backend is not None:
                self._backend.set_keypoint_group(group)

    # ── capture loop ─────────────────────────────────────────────

    def run(self):
        while self._running:
            if not self.cap or not self.cap.isOpened():
                time.sleep(0.1)
                continue

            ret, frame_bgr = self.cap.read()
            if not ret:
                continue

            frame_bgr = cv2.flip(frame_bgr, 1)              # mirror
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            timestamp = datetime.now().timestamp()

            frame_with_skeleton = frame_rgb
            landmarks_dict = None

            with self._backend_lock:
                backend = self._backend if self._backend_status == "ready" else None
            run_pose = backend is not None and self._enable_skeleton

            if run_pose:
                try:
                    t0 = time.time()
                    overlay, landmarks_dict = backend.infer(frame_rgb)
                    dt = time.time() - t0
                    if overlay is not None:
                        frame_with_skeleton = overlay
                    inf_fps = (1.0 / dt) if dt > 0 else 0.0
                except Exception as e:
                    inf_fps = 0.0
                    if self._frame_count % 60 == 0:
                        print(f"[Camera] Pose inference error: {e}")
            else:
                inf_fps = 0.0

            with self._lock:
                self._frame = frame_rgb
                self._frame_with_skeleton = frame_with_skeleton
                self._timestamp = timestamp
                self._landmarks = landmarks_dict
                self._inference_fps = inf_fps
                self._frame_count += 1

    # ── accessors ────────────────────────────────────────────────

    # NOTE on the accessors below: frames are returned BY REFERENCE, not
    # copied. This is safe because the capture loop only ever REBINDS
    # self._frame / self._frame_with_skeleton to freshly-allocated arrays
    # (cvtColor / backend.infer both allocate) and never mutates a published
    # array in place — so a published frame is effectively immutable.
    # Consumers must treat them as read-only. Removing the under-lock copies
    # saves ~166 MB/s of GUI-thread memcpy at 30 fps 1280x720.

    def get_frame(self) -> Tuple[Optional[np.ndarray], float, Optional[Dict]]:
        """Get the latest raw RGB frame (no overlay). Read-only reference."""
        with self._lock:
            if self._frame is None:
                return None, 0.0, None
            return self._frame, self._timestamp, self._landmarks

    def get_frame_with_overlay(self) -> Tuple[Optional[np.ndarray], float, Optional[Dict]]:
        """Get the latest frame with skeleton overlay (if enabled). Read-only reference."""
        with self._lock:
            if self._frame is None:
                return None, 0.0, None
            frame = self._frame_with_skeleton if self._enable_skeleton else self._frame
            return frame, self._timestamp, self._landmarks

    def get_frame_full(self):
        """Return (raw, overlay, timestamp, landmarks) atomically from the SAME camera
        frame under one lock — so a saved raw frame, its displayed overlay, its timestamp
        and its skeleton stay aligned (no inter-call frame skew). Read-only references."""
        with self._lock:
            if self._frame is None:
                return None, None, 0.0, None
            overlay = self._frame_with_skeleton if self._enable_skeleton else self._frame
            return self._frame, overlay, self._timestamp, self._landmarks

    def set_skeleton_enabled(self, enabled: bool):
        with self._lock:
            self._want_skeleton = enabled
            ready = self._backend is not None and self._backend_status == "ready"
            self._enable_skeleton = bool(enabled and ready)
        if enabled and not ready:
            print("[Camera] Skeleton requested; pose backend still loading…")

    def is_skeleton_enabled(self) -> bool:
        return self._enable_skeleton

    def get_pose_info(self) -> dict:
        """Backend status for the GUI status bar."""
        with self._backend_lock:
            device = self._backend.device if self._backend else "-"
            return {
                "backend": self._backend_name,
                "status": self._backend_status,
                "device": device,
                "inference_fps": self._inference_fps,
                "keypoint_group": self._keypoint_group,
            }

    def stop(self):
        self._running = False
        with self._backend_lock:
            if self._backend:
                try:
                    self._backend.close()
                except Exception:
                    pass
        if self.cap:
            self.cap.release()

    @property
    def is_running(self) -> bool:
        return self._running and self.is_alive()

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return self._frame is not None

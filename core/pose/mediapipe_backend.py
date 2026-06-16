"""
MediaPipe backend (fallback / lightweight CPU option).

Wraps MediaPipe Pose (33 body landmarks, single person) behind the common
PoseBackend interface, emitting the same landmark schema as the ViTPose backend.
Defensive multi-path import handles MediaPipe's version-dependent package layout.
"""

from typing import Optional, Tuple, Dict, Any

import cv2
import numpy as np

from .base import PoseBackend

import sys
sys.path.append("..")
from config import MEDIAPIPE_PARAMS


def _init_mediapipe():
    """Locate MediaPipe Pose across the various package layouts."""
    try:
        import mediapipe
        if hasattr(mediapipe, "solutions"):
            try:
                return (True, mediapipe.solutions.pose,
                        mediapipe.solutions.drawing_utils,
                        mediapipe.solutions.drawing_styles)
            except Exception:
                pass
        try:
            import mediapipe.python.solutions.pose as mp_pose
            import mediapipe.python.solutions.drawing_utils as mp_drawing
            import mediapipe.python.solutions.drawing_styles as mp_drawing_styles
            return True, mp_pose, mp_drawing, mp_drawing_styles
        except ImportError:
            pass
        return False, None, None, None
    except ImportError:
        return False, None, None, None


class MediaPipeBackend(PoseBackend):
    name = "mediapipe"

    def __init__(self):
        ok, mp_pose, mp_drawing, mp_drawing_styles = _init_mediapipe()
        if not ok:
            raise RuntimeError("MediaPipe is not available")
        self._mp_pose = mp_pose
        self._mp_drawing = mp_drawing
        self._mp_drawing_styles = mp_drawing_styles
        self._pose = mp_pose.Pose(
            model_complexity=MEDIAPIPE_PARAMS["model_complexity"],
            min_detection_confidence=MEDIAPIPE_PARAMS["min_detection_confidence"],
            min_tracking_confidence=MEDIAPIPE_PARAMS["min_tracking_confidence"],
            static_image_mode=False,
            enable_segmentation=False,
        )

    def infer(self, frame_rgb: np.ndarray) -> Tuple[np.ndarray, Optional[Dict[str, Any]]]:
        results = self._pose.process(frame_rgb)
        if not results.pose_landmarks:
            return frame_rgb, None

        # Draw on a BGR copy (MediaPipe drawing expects BGR), then back to RGB.
        bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        self._mp_drawing.draw_landmarks(
            bgr,
            results.pose_landmarks,
            self._mp_pose.POSE_CONNECTIONS,
            landmark_drawing_spec=self._mp_drawing_styles.get_default_pose_landmarks_style(),
        )
        overlay = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        h, w = frame_rgb.shape[:2]
        kpts = []
        for lm in results.pose_landmarks.landmark:
            kpts.append([round(lm.x * w, 2), round(lm.y * h, 2), round(lm.visibility, 4)])
        landmarks = {
            "backend": self.name,
            "dataset": "mediapipe_pose",
            "keypoint_group": "body",
            "image_size": [w, h],
            "persons": {0: {"keypoints": kpts}},
        }
        return overlay, landmarks

    def close(self) -> None:
        if self._pose:
            try:
                self._pose.close()
            except ValueError:
                pass
            self._pose = None

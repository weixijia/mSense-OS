"""
Pose Backend Interface

Defines the common contract every pose-estimation backend must implement so the
camera capture / GUI layers can stay backend-agnostic. A backend takes an RGB
frame and returns (overlay_rgb, landmarks_dict).

The landmarks dict is JSON-serializable and shares a common schema across
backends so recordings remain comparable:

    {
        "backend": "vitpose" | "mediapipe",
        "dataset": "wholebody" | "coco" | "mediapipe_pose",
        "keypoint_group": "body" | "body_face" | "body_hands" | "wholebody",
        "image_size": [width, height],
        "persons": {
            <person_id>: {
                "keypoints": [[x, y, confidence], ...]   # pixel coords
            },
            ...
        }
    }
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any

import numpy as np


class PoseBackend(ABC):
    """Abstract base class for all pose-estimation backends."""

    #: Short identifier (e.g. "vitpose", "mediapipe").
    name: str = "base"

    @abstractmethod
    def infer(self, frame_rgb: np.ndarray) -> Tuple[np.ndarray, Optional[Dict[str, Any]]]:
        """
        Run pose estimation on an RGB frame.

        Args:
            frame_rgb: HxWx3 uint8 RGB image.

        Returns:
            (overlay_rgb, landmarks)
                overlay_rgb: RGB image with the skeleton drawn on it.
                landmarks:   JSON-serializable dict (see module docstring) or
                             None if no person was detected.
        """
        raise NotImplementedError

    def set_keypoint_group(self, group: str) -> None:
        """Select which keypoint group is drawn/recorded (backend-dependent)."""
        # Default: no-op for backends with a fixed keypoint set.
        return None

    @property
    def device(self) -> str:
        """Device the backend runs on ('cuda' | 'mps' | 'cpu')."""
        return "cpu"

    def close(self) -> None:
        """Release any held resources (models, sessions)."""
        return None

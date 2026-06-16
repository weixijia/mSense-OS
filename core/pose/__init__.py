"""
Pluggable pose-estimation backends for Vomee.

ViTPose (smallest 's' model) is the default; MediaPipe is kept as a lightweight
fallback. Use `create_pose_backend(name, ...)` to instantiate one.
"""

from .base import PoseBackend
from .groups import KEYPOINT_GROUPS, KEYPOINT_GROUP_LABELS

# Available backends, in display order.
POSE_BACKENDS = ["vitpose", "mediapipe"]
POSE_BACKEND_LABELS = {
    "vitpose": "ViTPose (s)",
    "mediapipe": "MediaPipe",
}


def create_pose_backend(name: str, **kwargs) -> PoseBackend:
    """
    Instantiate a pose backend by name.

    Args:
        name: 'vitpose' or 'mediapipe'.
        **kwargs: forwarded to the backend constructor (ViTPose accepts
                  model_size, dataset, keypoint_group, device, ...).
    """
    name = (name or "vitpose").lower()
    if name == "vitpose":
        from .vitpose_backend import ViTPoseBackend
        return ViTPoseBackend(**kwargs)
    if name == "mediapipe":
        from .mediapipe_backend import MediaPipeBackend
        return MediaPipeBackend()
    raise ValueError(f"Unknown pose backend: {name!r} (expected one of {POSE_BACKENDS})")


__all__ = [
    "PoseBackend",
    "create_pose_backend",
    "POSE_BACKENDS",
    "POSE_BACKEND_LABELS",
    "KEYPOINT_GROUPS",
    "KEYPOINT_GROUP_LABELS",
]

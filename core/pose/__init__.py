"""
Pose-estimation backend for Vomee.

ViTPose (smallest 's' model) is the skeleton-tracking backend and runs cross-platform
(CUDA on NVIDIA, Apple Silicon MPS, or CPU — selected automatically).
Use `create_pose_backend(name, ...)` to instantiate it.
"""

from .base import PoseBackend
from .groups import KEYPOINT_GROUPS, KEYPOINT_GROUP_LABELS

# Available backends, in display order.
POSE_BACKENDS = ["vitpose"]
POSE_BACKEND_LABELS = {
    "vitpose": "ViTPose (s)",
}


def create_pose_backend(name: str, **kwargs) -> PoseBackend:
    """
    Instantiate a pose backend by name.

    Args:
        name: 'vitpose'.
        **kwargs: forwarded to the backend constructor (ViTPose accepts
                  model_size, dataset, keypoint_group, device, ...).
    """
    name = (name or "vitpose").lower()
    if name == "vitpose":
        from .vitpose_backend import ViTPoseBackend
        return ViTPoseBackend(**kwargs)
    raise ValueError(f"Unknown pose backend: {name!r} (expected one of {POSE_BACKENDS})")


__all__ = [
    "PoseBackend",
    "create_pose_backend",
    "POSE_BACKENDS",
    "POSE_BACKEND_LABELS",
    "KEYPOINT_GROUPS",
    "KEYPOINT_GROUP_LABELS",
]

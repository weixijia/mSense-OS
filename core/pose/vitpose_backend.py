"""
ViTPose backend.

Wraps the vendored `pose_studio_engine.VitInference` (YOLOv8 person detection +
SORT tracking + ViTPose 2D keypoints) behind the common PoseBackend interface.

Keypoints returned by the engine are ordered [y, x, confidence]; this backend
re-orders them to [x, y, confidence] for recording and applies the active
keypoint-group filter for both drawing and recording.
"""

import os
import urllib.request
from typing import Optional, Tuple, Dict, Any

import numpy as np

from .base import PoseBackend
from .groups import active_indices

# Vomee project root (…/Vomee) and default model directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MODELS_DIR = os.path.join(_PROJECT_ROOT, "models")

# HuggingFace mirror (easy_ViTPose) used as an auto-download fallback.
_HF_BASE = "https://huggingface.co/JunkyByte/easy_ViTPose/resolve/main/torch"


def _resolve_device(requested: Optional[str]) -> str:
    """Resolve 'auto'/None to the best available device (cuda > mps > cpu)."""
    if requested and requested != "auto":
        return requested
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


class ViTPoseBackend(PoseBackend):
    name = "vitpose"

    def __init__(self,
                 model_size: str = "s",
                 dataset: str = "wholebody",
                 keypoint_group: str = "body",
                 model_path: Optional[str] = None,
                 yolo_path: Optional[str] = None,
                 yolo_size: int = 320,
                 device: Optional[str] = None,
                 confidence_threshold: float = 0.3,
                 skeleton_thickness: int = 2):
        from pose_studio_engine import VitInference

        self.model_size = model_size
        self.dataset = dataset
        self.keypoint_group = keypoint_group
        self.confidence_threshold = confidence_threshold
        self.skeleton_thickness = skeleton_thickness
        self._device = _resolve_device(device)

        model_path = model_path or os.path.join(_MODELS_DIR, f"vitpose-{model_size}-{dataset}.pth")
        yolo_path = yolo_path or os.path.join(_MODELS_DIR, "yolov8n.pt")

        os.makedirs(_MODELS_DIR, exist_ok=True)
        self._ensure_model(model_path, model_size, dataset)
        self._ensure_yolo(yolo_path)

        self._vit = VitInference(
            model_path,
            yolo_path,
            model_name=model_size,
            dataset=dataset,
            yolo_size=yolo_size,
            is_video=True,
            device=self._device,
            yolo_step=1,
        )
        # Cache the active keypoint index set.
        self._refresh_active_indices()

    # ── model provisioning ───────────────────────────────────────

    def _ensure_model(self, model_path: str, size: str, dataset: str):
        if os.path.exists(model_path):
            return
        url = f"{_HF_BASE}/{dataset}/vitpose-{size}-{dataset}.pth"
        print(f"[ViTPose] Downloading {os.path.basename(model_path)} from HuggingFace (one-time)…")
        urllib.request.urlretrieve(url, model_path)
        print("[ViTPose] Model download complete.")

    def _ensure_yolo(self, yolo_path: str):
        if os.path.exists(yolo_path):
            return
        # Ultralytics fetches yolov8n.pt automatically; copy it to our models dir.
        print("[ViTPose] Fetching yolov8n.pt via Ultralytics…")
        from ultralytics import YOLO
        m = YOLO("yolov8n.pt")  # downloads to CWD/cache
        try:
            import shutil
            src = getattr(m, "ckpt_path", None) or "yolov8n.pt"
            if src and os.path.exists(src) and os.path.abspath(src) != os.path.abspath(yolo_path):
                shutil.copy(src, yolo_path)
        except Exception:
            pass

    # ── group filtering ──────────────────────────────────────────

    def _refresh_active_indices(self):
        num_kp = 133 if self.dataset == "wholebody" else 17
        self._active = active_indices(self.dataset, self.keypoint_group, num_kp)
        self._num_kp = num_kp

    def set_keypoint_group(self, group: str) -> None:
        self.keypoint_group = group
        self._refresh_active_indices()

    def _mask_inactive(self, keypoints_by_id: Dict[Any, np.ndarray]):
        """Zero the confidence of out-of-group keypoints (in place) so draw()
        and recording both skip them."""
        if self._num_kp == len(self._active):
            return  # all active, nothing to mask
        inactive = [i for i in range(self._num_kp) if i not in self._active]
        for arr in keypoints_by_id.values():
            if arr.shape[0] >= self._num_kp:
                arr[inactive, 2] = 0.0

    # ── inference ────────────────────────────────────────────────

    def infer(self, frame_rgb: np.ndarray) -> Tuple[np.ndarray, Optional[Dict[str, Any]]]:
        keypoints_by_id = self._vit.inference(frame_rgb)

        # Apply group filter to the engine's cached state (used by draw()).
        self._mask_inactive(self._vit._keypoints)

        overlay = self._vit.draw(
            show_yolo=False,
            confidence_threshold=self.confidence_threshold,
            skeleton_thickness=self.skeleton_thickness,
        )

        landmarks = self._build_landmarks(self._vit._keypoints, frame_rgb.shape)
        return overlay, landmarks

    def _build_landmarks(self, keypoints_by_id: Dict[Any, np.ndarray], shape) -> Optional[Dict[str, Any]]:
        if not keypoints_by_id:
            return None
        h, w = shape[:2]
        persons = {}
        for pid, arr in keypoints_by_id.items():
            kept = []
            for idx in range(min(self._num_kp, arr.shape[0])):
                if idx not in self._active:
                    continue
                y, x, conf = float(arr[idx, 0]), float(arr[idx, 1]), float(arr[idx, 2])
                kept.append([round(x, 2), round(y, 2), round(conf, 4)])
            persons[int(pid)] = {"keypoints": kept}
        return {
            "backend": self.name,
            "dataset": self.dataset,
            "keypoint_group": self.keypoint_group,
            "image_size": [w, h],
            "persons": persons,
        }

    @property
    def device(self) -> str:
        return self._device

    def close(self) -> None:
        self._vit = None

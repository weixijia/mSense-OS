"""Action-recognition feature — INERT STUB (Phase C fills in the model).

Declares the exact contract the trained model will use: consume a sliding window of the
**last 20 Range-Doppler frames** (Topic.RADAR_RD) and publish an action label on
``feature.action``. The pipeline already maintains the 20-frame window and calls
:meth:`on_window`; here it is a no-op so the rebuild ships with the plumbing live but no
inference. Phase C only implements :meth:`open` (load the model onto ``compute.device``)
and :meth:`on_window` (stack 20 RD → tensor → model → label).
"""
from __future__ import annotations

from typing import List, Optional

from ..core.compute import ComputeManager
from ..core.logging import get_logger
from ..core.types import Frame, Topic
from .base import Feature
from .registry import register

_log = get_logger("feature.action")

#: number of RD frames the model consumes (the trained model's input length)
ACTION_WINDOW = 20


@register("action")
class ActionClassifier(Feature):
    name = "action"
    input_topics = [Topic.RADAR_RD]
    window = ACTION_WINDOW
    output_topic = Topic.feature("action")

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._model = None
        self._compute: Optional[ComputeManager] = None

    def open(self, compute: ComputeManager) -> None:
        self._compute = compute
        # PHASE C: load the trained classifier onto compute.device (CUDA→MPS→CPU) here.
        self._model = None
        _log.info("action_classifier stub ready (inert; window=%d, device=%s)", self.window, compute.device)

    def on_window(self, frames: List[Frame], compute: ComputeManager) -> Optional[Frame]:
        # PHASE C: stack the 20 RD arrays -> tensor on compute.device -> model -> action label,
        # then `return Frame(self.output_topic, frames[-1].ts, frames[-1].frame_id, {"action": label, "prob": p})`.
        if self._model is None:
            return None  # inert until the model is integrated
        return None

    def close(self) -> None:
        self._model = None

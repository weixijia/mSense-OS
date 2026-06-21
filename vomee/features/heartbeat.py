"""Heartbeat-detection feature — INERT STUB (Phase B, collaborative, fills it in).

Heartbeat needs the slow phase variation of a *single occupied range bin* over time
(not the RD heatmap), so Phase B will add a small DSP processor that publishes a
per-range-bin phase stream (``Topic.feature("range_phase")``); this feature will then
window that stream (~a few seconds) and estimate BPM via band-pass + FFT in the
0.8–3 Hz band. For now it subscribes to nothing real and is a no-op, reserving the API.
"""
from __future__ import annotations

from typing import List, Optional

from ..core.compute import ComputeManager
from ..core.logging import get_logger
from ..core.types import Frame, Topic
from .base import Feature
from .registry import register

_log = get_logger("feature.heartbeat")

#: Phase B publishes the per-range-bin phase here; until then this topic is never produced
RANGE_PHASE_TOPIC = Topic.feature("range_phase")


@register("heartbeat")
class HeartbeatFeature(Feature):
    name = "heartbeat"
    #: Phase B: switch to [RANGE_PHASE_TOPIC] and a multi-second window.
    input_topics = [RANGE_PHASE_TOPIC]
    window = 1
    output_topic = Topic.feature("heartbeat")

    def open(self, compute: ComputeManager) -> None:
        _log.info("heartbeat stub ready (inert; Phase B adds the range-phase stream + BPM estimator)")

    def on_window(self, frames: List[Frame], compute: ComputeManager) -> Optional[Frame]:
        return None  # PHASE B: band-pass the range-bin phase, FFT, return {"bpm": ...}

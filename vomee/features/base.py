"""Feature interface — the extension point for sensing algorithms.

A :class:`Feature` consumes a sliding window of frames from one or more input topics and
optionally publishes a result frame back onto the bus. This is where future capabilities
plug in **without touching the pipeline**:

* the action-recognition model = ``Feature(input_topics=[Topic.RADAR_RD], window=20)``
  → its :meth:`on_window` receives the last 20 RD frames and returns an action label.
* heartbeat detection = a ``Feature`` over a per-range-bin phase stream.

The :class:`Pipeline` maintains the per-feature :class:`SlidingWindow`\\s and calls
:meth:`on_window` when the window is full.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..core.compute import ComputeManager
from ..core.types import Frame


class Feature(ABC):
    name: str = "feature"
    #: bus topics this feature consumes (the first is the "trigger" topic)
    input_topics: List[str] = []
    #: number of most-recent frames handed to :meth:`on_window` (1 = per-frame)
    window: int = 1
    #: fire :meth:`on_window` at most once per ``stride`` trigger-topic frames (after the
    #: window is full). ``1`` = every frame (sliding, max overlap); ``= window`` = adjacent,
    #: non-overlapping windows. Lets a heavy model (e.g. the 20-frame action net) throttle.
    stride: int = 1
    #: topic to publish results on, or None for a side-effect-only feature
    output_topic: Optional[str] = None

    def open(self, compute: ComputeManager) -> None:
        """Load models / allocate resources (called once at pipeline start)."""

    @abstractmethod
    def on_window(self, frames: List[Frame], compute: ComputeManager) -> Optional[Frame]:
        """Process the latest ``window`` frames of the trigger topic. Return a result
        :class:`Frame` to publish, or ``None``."""

    def close(self) -> None:
        """Release resources (called at pipeline stop)."""

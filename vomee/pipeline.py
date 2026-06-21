"""Composition root: wires Sources → FrameBus → Processors / Sinks / Features.

This is the generic orchestrator; concrete sources/processors/sinks/features are
registered by later rebuild stories. It owns lifecycle (:meth:`start`/:meth:`stop`) and
the per-feature sliding windows (e.g. the 20-frame RD window for the action model).
"""
from __future__ import annotations

from typing import List, Optional

from .core.bus import FrameBus
from .core.buffers import SlidingWindow
from .core.compute import ComputeManager
from .core.logging import get_logger
from .core.types import Frame
from .features.base import Feature
from .processing.base import Processor
from .sinks.base import Sink
from .sources.base import Source

_log = get_logger("pipeline")


class Pipeline:
    """Holds the bus + compute manager and the registered components.

    Wiring rules:
      * a :class:`Processor` subscribes to its ``input_topic``; each output frame is
        re-published on the bus (so downstream consumers see it).
      * a :class:`Sink` subscribes to the topics passed to :meth:`add_sink`.
      * a :class:`Feature` gets a :class:`SlidingWindow` per input topic; when its
        trigger topic's window is full (and every other input has data) its
        :meth:`on_window` runs and any result is published.
    """

    def __init__(self, config, compute: Optional[ComputeManager] = None, bus: Optional[FrameBus] = None):
        self.config = config
        prefer = getattr(getattr(config, "compute", None), "prefer_device", None)
        self.compute = compute or ComputeManager(prefer)
        self.bus = bus or FrameBus()
        self._sources: List[Source] = []
        self._processors: List[Processor] = []
        self._sinks: List[Sink] = []
        self._features: List[Feature] = []
        self._started = False

    # -- registration ----------------------------------------------------------
    def add_source(self, source: Source) -> Source:
        self._sources.append(source)
        return source

    def add_processor(self, proc: Processor) -> Processor:
        def handler(frame: Frame) -> None:
            out = proc.process(frame)
            if out is None:
                return
            for f in (out if isinstance(out, list) else [out]):
                self.bus.publish(f)

        self.bus.subscribe(proc.input_topic, handler)
        self._processors.append(proc)
        return proc

    def add_sink(self, sink: Sink, topics: List[str]) -> Sink:
        for t in topics:
            self.bus.subscribe(t, sink.consume)
        self._sinks.append(sink)
        return sink

    def add_feature(self, feature: Feature) -> Feature:
        if not feature.input_topics:
            raise ValueError(f"feature {feature.name!r} declares no input_topics")
        windows = {t: SlidingWindow(feature.window) for t in feature.input_topics}
        primary = feature.input_topics[0]
        stride = max(1, int(getattr(feature, "stride", 1)))
        state = {"since": 0}  # trigger frames since the last on_window call

        def make_handler(topic: str):
            def handler(frame: Frame) -> None:
                windows[topic].push(frame)
                if topic != primary:
                    return
                state["since"] += 1
                # fire at most once per `stride` primary frames, once every input is full
                if state["since"] >= stride and all(w.full() for w in windows.values()):
                    state["since"] = 0
                    res = feature.on_window(windows[primary].window(), self.compute)
                    if res is not None:
                        self.bus.publish(res)

            return handler

        for t in feature.input_topics:
            self.bus.subscribe(t, make_handler(t))
        self._features.append(feature)
        return feature

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        _log.info("starting pipeline | %s", self.compute.describe())
        for s in self._sinks:
            s.open()
        for f in self._features:
            f.open(self.compute)
        for src in self._sources:
            src.start(self.bus)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        for src in self._sources:
            try:
                src.stop()
            except Exception:
                _log.exception("source stop error")
        for f in self._features:
            try:
                f.close()
            except Exception:
                _log.exception("feature close error")
        for s in self._sinks:
            try:
                s.close()
            except Exception:
                _log.exception("sink close error")
        self._started = False
        _log.info("pipeline stopped")

    def __enter__(self) -> "Pipeline":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

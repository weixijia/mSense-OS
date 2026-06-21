"""Thread-safe in-process publish/subscribe frame bus.

Producers call :meth:`publish`; subscribers register :meth:`subscribe`. Fan-out is
synchronous (the publisher's thread runs each callback), so subscribers MUST be cheap or
offload heavy work to their own queue/thread (the recorder's async FileWriter does this).
A failing subscriber is isolated (logged) and never breaks the producer or peers.
"""
from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Callable

from .logging import get_logger
from .types import Frame

_log = get_logger("bus")

Subscriber = Callable[[Frame], None]


class FrameBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Subscriber]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, topic: str, callback: Subscriber) -> None:
        with self._lock:
            self._subs[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Subscriber) -> None:
        with self._lock:
            subs = self._subs.get(topic)
            if subs and callback in subs:
                subs.remove(callback)

    def publish(self, frame: Frame) -> None:
        with self._lock:
            callbacks = tuple(self._subs.get(frame.topic, ()))
        for cb in callbacks:
            try:
                cb(frame)
            except Exception:
                _log.exception("subscriber error on topic %s", frame.topic)

    def topics(self) -> list[str]:
        with self._lock:
            return [t for t, s in self._subs.items() if s]

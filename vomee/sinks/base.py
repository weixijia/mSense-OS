"""Sink interface — consumes frames (e.g. the recorder, a network exporter)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.types import Frame


class Sink(ABC):
    """Consumes frames from one or more topics. Lifecycle: :meth:`open` / :meth:`close`."""

    def open(self) -> None:  # optional
        ...

    @abstractmethod
    def consume(self, frame: Frame) -> None:
        ...

    def close(self) -> None:  # optional
        ...

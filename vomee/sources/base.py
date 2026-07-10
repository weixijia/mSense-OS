"""Source interface — a producer of :class:`Frame` objects on one bus topic."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.bus import FrameBus


class Source(ABC):
    """Produces frames onto the bus (e.g. radar, camera).

    Concrete sources run their own acquisition thread and publish ``Frame``s tagged
    with :attr:`topic`. Lifecycle is :meth:`start` / :meth:`stop`.
    """

    topic: str = ""

    @abstractmethod
    def start(self, bus: FrameBus) -> None:
        """Begin acquiring and publishing frames to ``bus``."""

    @abstractmethod
    def stop(self) -> None:
        """Stop acquisition and release resources (idempotent)."""

    @property
    def running(self) -> bool:
        return bool(getattr(self, "_running", False))

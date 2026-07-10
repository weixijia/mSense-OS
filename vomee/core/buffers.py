"""Bounded buffers for windowed consumers.

The action-recognition model needs a sliding window of the **last 20 RD frames**;
:class:`SlidingWindow` provides exactly that (and is reusable for any windowed feature).
"""
from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Generic, List, Optional, TypeVar

T = TypeVar("T")


class RingBuffer(Generic[T]):
    """Fixed-capacity FIFO; the oldest item is dropped on overflow. Thread-safe."""

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self.capacity = capacity
        self._buf: "deque[T]" = deque(maxlen=capacity)
        self._lock = Lock()

    def push(self, item: T) -> None:
        with self._lock:
            self._buf.append(item)

    def latest(self) -> Optional[T]:
        with self._lock:
            return self._buf[-1] if self._buf else None

    def items(self) -> List[T]:
        with self._lock:
            return list(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)


class SlidingWindow(RingBuffer[T]):
    """Ring buffer that reports when it holds a full window of ``size`` items."""

    def __init__(self, size: int) -> None:
        super().__init__(size)
        self.size = size

    def push_full(self, item: T) -> bool:
        """Append ``item``; return True iff the window is now full (``size`` items)."""
        self.push(item)
        return len(self) == self.size

    def full(self) -> bool:
        return len(self) == self.size

    def window(self) -> List[T]:
        return self.items()

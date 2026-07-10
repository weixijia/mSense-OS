"""Processor interface — transforms frames from one topic into output frame(s)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Union

from ..core.types import Frame


class Processor(ABC):
    """Consumes frames on :attr:`input_topic`, emits zero or more output frames.

    Returning a list lets one processor fan out to several topics (the mmWave DSP turns
    one raw frame into RD, RA and DA frames).
    """

    input_topic: str = ""
    output_topic: str = ""

    @abstractmethod
    def process(self, frame: Frame) -> Union[Frame, List[Frame], None]:
        ...

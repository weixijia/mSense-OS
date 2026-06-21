"""mmWave DSP processor — wraps the FINALIZED ``core/mmwave_processor`` UNCHANGED.

This adapter delegates 100% to ``core.mmwave_processor.MmWaveProcessor`` (the explored-
and-finalized 3D-FFT → RD/RA/DA pipeline: reshape, fftshift, |·|², log10, normalize,
flip). It performs **no DSP math** itself — it only re-packages the raw-ADC :class:`Frame`
into RD/RA/DA frames on the bus. Byte-identity vs the finalized processor is locked by
``tests/test_mmwave_regression.py``.
"""
from __future__ import annotations

import os
import sys
from typing import List

from ..core.types import Frame, Topic
from ..processing.base import Processor

# The finalized DSP lives at the repo-root ``core/`` package (intentionally NOT moved).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class MmWaveDSP(Processor):
    """Raw ADC → RD/RA/DA. Thin wrapper; the math is the finalized processor's."""

    input_topic = Topic.RADAR_RAW

    def __init__(self, num_angle_bins: int = 256):
        from core.mmwave_processor import MmWaveProcessor  # finalized, unchanged
        self._proc = MmWaveProcessor(num_angle_bins=num_angle_bins)

    @property
    def processor(self):
        """Access the underlying finalized MmWaveProcessor (read-only use)."""
        return self._proc

    def process(self, frame: Frame) -> List[Frame]:
        rd, ra, da = self._proc.process(frame.data)
        ts, fid, meta = frame.ts, frame.frame_id, frame.meta
        return [
            Frame(Topic.RADAR_RD, ts, fid, rd, meta),
            Frame(Topic.RADAR_RA, ts, fid, ra, meta),
            Frame(Topic.RADAR_DA, ts, fid, da, meta),
        ]

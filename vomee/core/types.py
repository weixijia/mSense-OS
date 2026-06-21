"""Core data types that flow on the Vomee frame bus.

Every datum on the bus is a :class:`Frame`: a timestamped, identified payload tagged
with a ``topic``. Producers publish frames; subscribers (sinks, features, GUI) consume
them. Payloads are plain numpy arrays / dicts, so the bus stays decoupled from any
backend or serialization format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Topic:
    """Canonical bus topic names (channels)."""

    RADAR_RAW = "radar.raw"       # raw ADC int16 frame (np.ndarray, flat)
    RADAR_RD = "radar.rd"         # range-doppler heatmap (np.ndarray [range, doppler])
    RADAR_RA = "radar.ra"         # range-azimuth heatmap (np.ndarray [range, azimuth])
    RADAR_DA = "radar.da"         # doppler-azimuth heatmap (np.ndarray)
    CAMERA = "camera.frame"       # RGB frame (np.ndarray HxWx3, uint8)
    SKELETON = "camera.skeleton"  # pose result (dict)
    FEATURE_PREFIX = "feature."   # features publish on feature.<name>

    @staticmethod
    def feature(name: str) -> str:
        return f"{Topic.FEATURE_PREFIX}{name}"


@dataclass
class Frame:
    """A timestamped payload on the bus.

    Attributes
    ----------
    topic:    bus channel (see :class:`Topic`)
    ts:       host timestamp in seconds (``time.time()``) when produced
    frame_id: monotonically increasing id from the producing source
    data:     payload (``np.ndarray``, ``dict``, ...)
    meta:     optional per-frame metadata (e.g. ``lost_packets``, ``device``)
    """

    topic: str
    ts: float
    frame_id: int
    data: Any
    meta: dict = field(default_factory=dict)

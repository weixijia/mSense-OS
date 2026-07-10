"""G005 — bus + buffers integration: the exact data path the action model will use.

Wires the REAL pipeline: synthetic RADAR_RAW → finalized MmWaveDSP → RADAR_RD →
SlidingWindow(20) → Feature.on_window. Proves a windowed feature receives exactly the
last 20 real RD frames (shape 256×255) with no hardware. In Phase C the test feature is
swapped for the trained action classifier — the plumbing is identical.
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import config                                         # noqa: E402
from vomee import build_pipeline                      # noqa: E402
from vomee.core.types import Frame, Topic             # noqa: E402
from vomee.features.base import Feature               # noqa: E402
from vomee.processing.mmwave_dsp import MmWaveDSP     # noqa: E402


def _raw():
    p = config.ADC_PARAMS
    n = p["chirps"] * p["tx"] * p["rx"] * p["samples"] * p["IQ"]
    return np.random.RandomState(0).randint(-2048, 2048, size=n, dtype=np.int16)


def test_raw_to_dsp_to_20frame_window():
    p = build_pipeline()
    p.add_processor(MmWaveDSP())  # finalized DSP, produces RD/RA/DA on the bus
    seen = {"fires": 0, "count": 0, "shapes": set()}

    class _Win20(Feature):
        name = "action_path_test"
        input_topics = [Topic.RADAR_RD]
        window = 20

        def on_window(self, frames, compute):
            seen["fires"] += 1
            seen["count"] = len(frames)
            seen["shapes"] = {f.data.shape for f in frames}
            return None

    p.add_feature(_Win20())

    raw = _raw()
    for fid in range(22):
        p.bus.publish(Frame(Topic.RADAR_RAW, float(fid), fid, raw.copy()))

    # window fills at the 20th RD frame, then fires on the 20th/21st/22nd -> 3 times
    assert seen["fires"] == 3
    assert seen["count"] == 20
    assert seen["shapes"] == {(256, 255)}  # real RD shape from the finalized DSP


def test_sliding_window_keeps_latest_20():
    """The window must hold the *most recent* 20 frames (FIFO drop), so the model always
    sees the latest motion."""
    p = build_pipeline()
    ids = {"last": None}

    class _Probe(Feature):
        name = "probe"
        input_topics = [Topic.RADAR_RD]
        window = 20

        def on_window(self, frames, compute):
            ids["last"] = [f.frame_id for f in frames]
            return None

    p.add_feature(_Probe())
    rd = np.zeros((256, 255), np.float32)
    for fid in range(25):
        p.bus.publish(Frame(Topic.RADAR_RD, float(fid), fid, rd))
    assert ids["last"] == list(range(5, 25))  # newest 20, oldest dropped


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} action-path tests passed.")

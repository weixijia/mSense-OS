"""Smoke tests for the rebuild scaffold (G001).

Run from the repo root:  python -m pytest tests/test_scaffold.py -q
(or:  python tests/test_scaffold.py  to run the lightweight self-check.)
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vomee import build_pipeline                                   # noqa: E402
from vomee.config import AppConfig                                 # noqa: E402
from vomee.core import (ComputeManager, Frame, FrameBus,           # noqa: E402
                        RingBuffer, SlidingWindow, Topic)
from vomee.features import available, register                     # noqa: E402
from vomee.features.base import Feature                            # noqa: E402


def test_compute_manager():
    cm = ComputeManager()
    assert cm.device in ("cuda", "mps", "cpu")
    assert cm.fft_backend() in ("torch-cuda", "torch-cpu", "numpy")
    # FFT must never select MPS (torch.fft unsupported there).
    assert cm.fft_device in ("cuda", "cpu")


def test_bus_pubsub_and_isolation():
    bus = FrameBus()
    got = []
    bus.subscribe(Topic.RADAR_RD, lambda f: got.append(f))
    bus.subscribe(Topic.RADAR_RD, lambda f: (_ for _ in ()).throw(RuntimeError("boom")))  # bad sub
    bus.publish(Frame(Topic.RADAR_RD, 1.0, 7, np.zeros((4, 4))))
    assert len(got) == 1 and got[0].frame_id == 7   # good sub still fired despite the bad one


def test_sliding_window_20():
    w = SlidingWindow(20)
    for i in range(19):
        assert not w.push_full(i)
    assert w.push_full(19)            # 20th item -> full
    assert w.full() and len(w.window()) == 20
    w.push_full(20)                   # oldest (0) dropped
    assert w.window()[0] == 1 and w.window()[-1] == 20


def test_ring_buffer():
    rb = RingBuffer(3)
    for i in range(5):
        rb.push(i)
    assert rb.items() == [2, 3, 4] and rb.latest() == 4


def test_config_from_legacy_matches():
    c = AppConfig.from_legacy()
    assert c.adc.chirps == 255 and c.adc.samples == 256 and c.adc.virtual_antennas == 8
    assert c.trigger.baud == 921600 and c.trigger.com_port == "auto"
    assert c.network.data_port == 4098 and c.network.config_port == 4096
    assert c.display.rd_size == (256, 255)


def test_pipeline_with_feature_window():
    p = build_pipeline()
    fired = {"n": 0, "len": 0}

    @register("test_action")
    class _Win20(Feature):
        name = "test_action"
        input_topics = [Topic.RADAR_RD]
        window = 20

        def on_window(self, frames, compute):
            fired["n"] += 1
            fired["len"] = len(frames)
            return None

    assert "test_action" in available()
    p.add_feature(_Win20())
    for i in range(25):
        p.bus.publish(Frame(Topic.RADAR_RD, float(i), i, np.zeros((256, 255), np.float32)))
    # full at the 20th frame, then fires on every subsequent frame -> 6 times for 25 frames
    assert fired["n"] == 6 and fired["len"] == 20


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} scaffold tests passed.")

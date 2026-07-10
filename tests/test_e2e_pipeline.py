"""G007 — end-to-end smoke: registry feature stubs wired through the real pipeline.

Synthetic RADAR_RAW → finalized MmWaveDSP → RADAR_RD → the registry-created ``action``
feature's 20-frame window. Confirms the extension framework is live (stubs registered and
wired) and the pipeline runs clean. CPU-fallback policy is checked at the ComputeManager
level (the finalized DSP has its own NumPy/CPU path, covered by test_mmwave_regression).
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import config                                          # noqa: E402
from vomee import build_pipeline                       # noqa: E402
from vomee.core.compute import ComputeManager          # noqa: E402
from vomee.core.types import Frame, Topic              # noqa: E402
from vomee.features import available, create           # noqa: E402
from vomee.processing.mmwave_dsp import MmWaveDSP       # noqa: E402


def _raw():
    p = config.ADC_PARAMS
    n = p["chirps"] * p["tx"] * p["rx"] * p["samples"] * p["IQ"]
    return np.random.RandomState(0).randint(-2048, 2048, size=n, dtype=np.int16)


def test_stubs_registered():
    assert "heartbeat" in available() and "action" in available()
    a = create("action")
    assert a.window == 20 and a.input_topics == [Topic.RADAR_RD]
    assert a.output_topic == Topic.feature("action")


def test_e2e_capture_dsp_feature():
    p = build_pipeline()
    p.add_processor(MmWaveDSP())
    rd_seen = {"n": 0}
    p.bus.subscribe(Topic.RADAR_RD, lambda f: rd_seen.__setitem__("n", rd_seen["n"] + 1))
    p.add_feature(create("action"))  # inert 20-frame RD window stub
    raw = _raw()
    for fid in range(22):
        p.bus.publish(Frame(Topic.RADAR_RAW, float(fid), fid, raw.copy()))
    assert rd_seen["n"] == 22  # finalized DSP produced RD for every raw frame; feature ran clean


def test_cpu_fallback_policy():
    cm = ComputeManager("cpu")
    assert cm.device == "cpu"
    assert cm.fft_backend() in ("torch-cpu", "numpy")  # FFT never selects MPS


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} E2E tests passed.")

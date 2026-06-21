"""Golden regression that GUARDS the finalized pure-mmWave workflow (G002).

Two independent checks:

1. ``test_wrapper_byte_identical`` — the new ``MmWaveDSP`` adapter must produce
   *byte-identical* RD/RA/DA to calling the finalized ``core.mmwave_processor`` directly,
   on the same input and machine. This proves the rebuild's wrapper changed nothing.

2. ``test_golden_math_stability`` — the finalized processor's output on a fixed,
   deterministic synthetic raw frame must still match the committed golden fixtures
   (tests/fixtures/golden_*.npy). This catches ANY future change to the DSP math /
   orientation / normalization (a flip, window, or rescale fails loudly). Tolerance is
   loose enough to survive CUDA-vs-CPU last-bit FFT differences but tight enough to catch
   real changes (e.g. an orientation flip moves values by O(1)).

Run:  python -m pytest tests/test_mmwave_regression.py -q   (or run this file directly)
"""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import config                                              # noqa: E402
from core.mmwave_processor import MmWaveProcessor          # noqa: E402  (finalized)
from vomee.core.types import Frame, Topic                  # noqa: E402
from vomee.processing.mmwave_dsp import MmWaveDSP          # noqa: E402

_FX = os.path.join(_ROOT, "tests", "fixtures")


def _synth_raw() -> np.ndarray:
    """Deterministic synthetic raw ADC frame matching ADC_PARAMS (seeded)."""
    p = config.ADC_PARAMS
    n = p["chirps"] * p["tx"] * p["rx"] * p["samples"] * p["IQ"]
    return np.random.RandomState(0).randint(-2048, 2048, size=n, dtype=np.int16)


def test_wrapper_byte_identical():
    raw = _synth_raw()
    rd0, ra0, da0 = MmWaveProcessor().process(raw.copy())
    frames = MmWaveDSP().process(Frame(Topic.RADAR_RAW, 1.5, 42, raw.copy()))
    out = {f.topic: f.data for f in frames}
    assert np.array_equal(out[Topic.RADAR_RD], rd0)
    assert np.array_equal(out[Topic.RADAR_RA], ra0)
    assert np.array_equal(out[Topic.RADAR_DA], da0)
    # frame plumbing preserved
    assert {f.topic for f in frames} == {Topic.RADAR_RD, Topic.RADAR_RA, Topic.RADAR_DA}
    assert all(f.frame_id == 42 and f.ts == 1.5 for f in frames)


def test_golden_math_stability():
    raw = _synth_raw()
    rd, ra, da = MmWaveProcessor().process(raw.copy())
    gd = np.load(os.path.join(_FX, "golden_rd.npy"))
    ga = np.load(os.path.join(_FX, "golden_ra.npy"))
    gda = np.load(os.path.join(_FX, "golden_da.npy"))
    assert rd.shape == gd.shape == (256, 255)
    assert ra.shape == ga.shape == (256, 256)
    assert np.allclose(rd, gd, atol=1e-3), f"RD drift max={np.abs(rd-gd).max():.4f}"
    assert np.allclose(ra, ga, atol=1e-3), f"RA drift max={np.abs(ra-ga).max():.4f}"
    assert np.allclose(da, gda, atol=1e-3), f"DA drift max={np.abs(da-gda).max():.4f}"


def test_orientation_preserved_near_at_bottom():
    """RD/RA must keep range 0 (near) at the BOTTOM (flip=False) — the agreed orientation
    the recorded .npy / model use. Guards an accidental re-flip."""
    raw = _synth_raw()
    rd, ra, _ = MmWaveProcessor().process(raw.copy())
    gd = np.load(os.path.join(_FX, "golden_rd.npy"))
    # identical orientation to golden (not vertically mirrored)
    assert np.allclose(rd, gd, atol=1e-3)
    assert not np.allclose(rd, gd[::-1], atol=1e-3), "RD appears vertically flipped vs golden"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} mmWave regression tests passed.")

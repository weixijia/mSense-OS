"""Regression tests for the async FileWriter (v2, atomic FrameBundle).

Guards the comprehensive-review fixes in recording/file_writer.py:

- wait_completion() must honor its timeout and can never deadlock (the old
  drop-oldest path leaked the unfinished-task counter, freezing the GUI at
  Stop after any dropped write).
- FrameBundle round-trip: self-describing raw records (magic/fnum/ts/lost),
  heatmap+camera .npy, skeleton .json.
- Overflow drops whole bundles with accounting — no per-modality holes.
- A bundle landing after end_session must not reopen finalized files.
- Per-type compat API (vomee bus recorder) still works.

Run:  python tests/test_file_writer_regression.py   (or python -m pytest -q)
"""
import os
import sys
import json
import shutil
import struct
import tempfile
import time
from pathlib import Path

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from recording.file_writer import (FileWriter, FrameBundle,          # noqa: E402
                                   RAW_MAGIC, RAW_RECORD_HEADER)


def read_raw_records(bin_path):
    """Iterate (frame_num, timestamp, lost, int16 payload) records."""
    out = []
    with open(bin_path, 'rb') as f:
        while True:
            header = f.read(RAW_RECORD_HEADER.size)
            if not header:
                break
            assert len(header) == RAW_RECORD_HEADER.size, "truncated header"
            magic, fnum, ts, lost, nbytes = RAW_RECORD_HEADER.unpack(header)
            assert magic == RAW_MAGIC, f"bad magic {magic!r}"
            payload = f.read(nbytes)
            assert len(payload) == nbytes, "truncated payload"
            out.append((fnum, ts, bool(lost),
                        np.frombuffer(payload, dtype=np.int16)))
    return out


def make_bundle(tmp: Path, fnum: int):
    return FrameBundle(
        frame_num=fnum,
        mmwave_ts=1000.0 + fnum * 0.1,
        camera_ts=1000.0 + fnum * 0.1 + 0.005,
        lost_packet=(fnum == 3),
        raw=np.full(1024, fnum, dtype=np.int16),
        raw_path=tmp / "mmwave.bin",
        rd=np.full((16, 15), fnum / 10.0, dtype=np.float32),
        rd_path=tmp / f"rd_{fnum:05d}.npy",
        ra=np.full((16, 16), fnum / 10.0, dtype=np.float32),
        ra_path=tmp / f"ra_{fnum:05d}.npy",
        camera_frame=np.full((48, 64, 3), (fnum * 10) % 256, dtype=np.uint8),
        camera_path=tmp / f"cam_{fnum:05d}.npy",
        skeleton={"landmarks": [{"x": float(fnum)}]},
        skeleton_path=tmp / f"skel_{fnum:05d}.json",
    )


def test_bundle_roundtrip(tmp: Path):
    writer = FileWriter(queue_size=32)
    writer.start()
    for fnum in range(1, 6):
        assert writer.submit_bundle(make_bundle(tmp, fnum))
    writer.end_session()
    assert writer.wait_completion(timeout=15.0), "writer did not drain"

    records = read_raw_records(tmp / "mmwave.bin")
    assert [r[0] for r in records] == [1, 2, 3, 4, 5]
    for fnum, ts, lost, data in records:
        assert np.all(data == fnum)
        assert abs(ts - (1000.0 + fnum * 0.1)) < 1e-9
        assert lost == (fnum == 3)

    for fnum in range(1, 6):
        assert np.load(tmp / f"rd_{fnum:05d}.npy").shape == (16, 15)
        cam = np.load(tmp / f"cam_{fnum:05d}.npy")
        assert cam.shape == (48, 64, 3)
        skel = json.loads((tmp / f"skel_{fnum:05d}.json").read_text())
        assert skel["landmarks"][0]["x"] == float(fnum)

    writer.stop()
    writer.join(timeout=5.0)


def test_wait_completion_timeout_no_deadlock(tmp: Path):
    """Stalled writer + pending tasks: wait_completion returns False within
    the timeout instead of blocking forever (C1 regression)."""
    writer = FileWriter(queue_size=8)   # thread NOT started
    writer.submit_bundle(make_bundle(tmp, 1))
    t0 = time.monotonic()
    assert writer.wait_completion(timeout=0.5) is False
    assert time.monotonic() - t0 < 2.0, "wait_completion blocked (deadlock)"
    # After starting, the same queue must fully drain (no counter leak)
    writer.start()
    assert writer.wait_completion(timeout=10.0)
    writer.stop()
    writer.join(timeout=5.0)


def test_whole_bundle_drop_accounting(tmp: Path):
    writer = FileWriter(queue_size=3)   # thread NOT started -> queue fills
    accepted = sum(writer.submit_bundle(make_bundle(tmp, fnum), timeout=0.01)
                   for fnum in range(1, 7))
    assert accepted == 3
    assert writer.get_stats()["writes_dropped"] == 3

    writer.start()
    assert writer.wait_completion(timeout=10.0), "counter leak after drops"
    writer.end_session()
    assert writer.wait_completion(timeout=10.0)

    records = read_raw_records(tmp / "mmwave.bin")
    assert [r[0] for r in records] == [1, 2, 3]
    for fnum in (4, 5, 6):
        assert not (tmp / f"rd_{fnum:05d}.npy").exists(), \
            f"partial modality written for dropped frame {fnum}"
    writer.stop()
    writer.join(timeout=5.0)


def test_no_write_after_end_session(tmp: Path):
    """A late bundle after the session close must be dropped, never reopen
    the finalized raw file."""
    writer = FileWriter(queue_size=32)
    writer.start()
    for fnum in range(1, 4):
        assert writer.submit_bundle(make_bundle(tmp, fnum))
    writer.end_session()
    assert writer.wait_completion(timeout=15.0)

    raw_size = (tmp / "mmwave.bin").stat().st_size
    writer.submit_bundle(make_bundle(tmp, 99))
    assert writer.wait_completion(timeout=15.0)
    assert (tmp / "mmwave.bin").stat().st_size == raw_size, \
        "late bundle appended to closed raw stream"
    assert [r[0] for r in read_raw_records(tmp / "mmwave.bin")] == [1, 2, 3]
    writer.stop()
    writer.join(timeout=5.0)


def test_per_type_compat_api(tmp: Path):
    """The vomee bus recorder's per-type writes still work and the raw
    stream stays self-describing."""
    writer = FileWriter(queue_size=32)
    writer.start()
    assert writer.write_raw_mmwave(tmp / "raw.bin",
                                   np.full(512, 7, dtype=np.int16), 7, 123.456)
    assert writer.write_rd_heatmap(tmp / "RD_7.npy",
                                   np.ones((4, 4), dtype=np.float32), 7)
    assert writer.write_da_heatmap(tmp / "DA_7.npy",
                                   np.ones((4, 4), dtype=np.float32), 7)
    assert writer.write_skeleton(tmp / "sk_7.json", {"k": 1}, 7)
    writer.end_session()
    assert writer.wait_completion(timeout=10.0)

    records = read_raw_records(tmp / "raw.bin")
    assert len(records) == 1
    fnum, ts, lost, data = records[0]
    assert fnum == 7 and abs(ts - 123.456) < 1e-9 and not lost
    assert np.all(data == 7)
    assert (tmp / "RD_7.npy").exists() and (tmp / "DA_7.npy").exists()
    assert json.loads((tmp / "sk_7.json").read_text()) == {"k": 1}
    writer.stop()
    writer.join(timeout=5.0)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        tmp = Path(tempfile.mkdtemp(prefix="vomee_fw_reg_"))
        try:
            fn(tmp)
            print(f"PASS {fn.__name__}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nAll {len(fns)} file-writer regression tests passed.")

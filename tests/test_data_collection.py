"""G004 — data-collection subsystem tests (headless, no hardware).

Verifies: enabled streams are saved; per-stream toggles are respected; recorded RD/RA
``.npy`` are byte-identical to what was published (raw, model-ready); metadata carries
schema_version / rd_orientation / device / git_commit / adc_params; timestamps.csv logs
frame-aligned (topic, frame_id, ts).
"""
import json
import os
import sys
import tempfile
from dataclasses import replace

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from vomee import build_pipeline                       # noqa: E402
from vomee.config import AppConfig, RecordCfg          # noqa: E402
from vomee.core.types import Frame, Topic              # noqa: E402
from vomee.sinks.recorder import TOPICS, Recorder      # noqa: E402


def _cfg(tmp, **rec):
    base = dict(save_raw=True, save_rd=True, save_ra=True, save_da=True,
                save_skeleton=True, save_rgb=True, base_dir=tmp)
    base.update(rec)
    return replace(AppConfig.from_legacy(), record=RecordCfg(**base))


def test_records_all_enabled_streams_raw():
    tmp = tempfile.mkdtemp()
    cfg = _cfg(tmp)
    p = build_pipeline(cfg)
    rec = Recorder(cfg, compute=p.compute)
    p.add_sink(rec, TOPICS)
    d = rec.start_session(note="unit")
    rd = np.random.RandomState(1).rand(256, 255).astype(np.float32)
    ra = np.random.RandomState(2).rand(256, 256).astype(np.float32)
    raw = np.arange(100, dtype=np.int16)
    cam = np.full((4, 4, 3), 7, np.uint8)
    for fid in range(3):
        p.bus.publish(Frame(Topic.RADAR_RAW, 1.0 + fid, fid, raw))
        p.bus.publish(Frame(Topic.RADAR_RD, 1.0 + fid, fid, rd))
        p.bus.publish(Frame(Topic.RADAR_RA, 1.0 + fid, fid, ra))
        p.bus.publish(Frame(Topic.RADAR_DA, 1.0 + fid, fid, rd))
        p.bus.publish(Frame(Topic.CAMERA, 1.0 + fid, fid, cam))
        p.bus.publish(Frame(Topic.SKELETON, 1.0 + fid, fid, {"kp": [1, 2, 3]}))
    rec.stop_session()

    for rel in ("RD/0.npy", "RA/0.npy", "DA/0.npy", "camera/0.npy", "skeleton/0.json", "raw.bin"):
        assert os.path.exists(os.path.join(d, rel)), f"missing {rel}"
    # recorded .npy stays RAW (byte-identical to published)
    assert np.array_equal(np.load(os.path.join(d, "RD", "0.npy")), rd)
    assert np.array_equal(np.load(os.path.join(d, "RA", "0.npy")), ra)
    assert np.array_equal(np.load(os.path.join(d, "camera", "0.npy")), cam)
    # metadata
    meta = json.load(open(os.path.join(d, "metadata.json")))
    assert meta["schema_version"] == "2.0"
    assert meta["rd_orientation"] == "near_bottom"
    assert meta["adc_params"]["chirps"] == 255 and meta["device"]
    assert "git_commit" in meta and meta["frame_counts"][Topic.RADAR_RD] == 3
    # timestamps.csv
    rows = open(os.path.join(d, "timestamps.csv")).read().strip().splitlines()
    assert rows[0] == "topic,frame_id,ts" and len(rows) == 1 + 3 * 6  # header + 18 saved frames


def test_toggles_respected():
    tmp = tempfile.mkdtemp()
    cfg = _cfg(tmp, save_raw=False, save_rd=True, save_ra=False, save_da=False,
               save_skeleton=False, save_rgb=False)
    p = build_pipeline(cfg)
    rec = Recorder(cfg)
    p.add_sink(rec, TOPICS)
    d = rec.start_session()
    for fid in range(2):
        p.bus.publish(Frame(Topic.RADAR_RD, 1.0, fid, np.zeros((256, 255), np.float32)))
        p.bus.publish(Frame(Topic.RADAR_RA, 1.0, fid, np.zeros((256, 256), np.float32)))
        p.bus.publish(Frame(Topic.RADAR_RAW, 1.0, fid, np.zeros(10, np.int16)))
    rec.stop_session()
    assert os.path.exists(os.path.join(d, "RD", "0.npy"))
    assert not os.path.exists(os.path.join(d, "RA", "0.npy"))   # save_ra=False
    assert not os.path.exists(os.path.join(d, "raw.bin"))       # save_raw=False


def test_concurrent_writes_count_consistent():
    """Multiple source threads writing concurrently (radar + camera) must not race the
    counts/csv/FileWriter; total counts must equal frames submitted."""
    import threading
    tmp = tempfile.mkdtemp()
    cfg = _cfg(tmp)
    p = build_pipeline(cfg)
    rec = Recorder(cfg, compute=p.compute)
    p.add_sink(rec, TOPICS)
    rec.start_session()
    rd = np.zeros((256, 255), np.float32)
    errors = []

    def worker(base):
        try:
            for i in range(50):
                rec.consume(Frame(Topic.RADAR_RD, float(i), base + i, rd))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t * 1000,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    info = rec.stop_session()
    assert not errors, errors
    assert info["frame_counts"][Topic.RADAR_RD] == 200  # 4 threads * 50


def test_stop_during_concurrent_consume():
    """Tearing down a session while source threads are still calling consume() must not
    crash, and post-stop consume() must be an inert no-op (the locked _recording gate)."""
    import threading
    import time as _t
    tmp = tempfile.mkdtemp()
    cfg = _cfg(tmp)
    p = build_pipeline(cfg)
    rec = Recorder(cfg)
    p.add_sink(rec, TOPICS)
    rec.start_session()
    rd = np.zeros((256, 255), np.float32)
    errors = []
    stop = [False]

    def spam():
        try:
            i = 0
            while not stop[0]:
                rec.consume(Frame(Topic.RADAR_RD, 0.0, i, rd))
                i += 1
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    th = threading.Thread(target=spam)
    th.start()
    _t.sleep(0.05)
    rec.stop_session()           # teardown while consume() spams from the other thread
    _t.sleep(0.02)
    stop[0] = True
    th.join()
    rec.consume(Frame(Topic.RADAR_RD, 0.0, 999, rd))  # post-stop -> no-op, no crash
    assert not errors, errors


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} data-collection tests passed.")

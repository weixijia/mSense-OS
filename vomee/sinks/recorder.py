"""Recorder sink — configurable, per-stream data collection (core platform function).

Subscribes to the bus and, while a session is active, saves each enabled stream via the
existing async :class:`recording.file_writer.FileWriter`:

* ``raw_adc``  → ``raw.bin``        (appended)
* ``rd/ra/da`` → ``RD|RA|DA/<id>.npy`` (the **raw** processor output — what the model trains on)
* ``rgb``      → ``camera/<id>.npy``   (frame-aligned; ``id``+``ts`` in timestamps.csv)
* ``skeleton`` → ``skeleton/<id>.json``

Each enabled stream is toggled independently in :class:`RecordCfg` (and *show* is a
separate flag handled by the GUI — saving never depends on display). A ``timestamps.csv``
logs ``(topic, frame_id, ts)`` for every saved frame so RGB/radar streams can be aligned.
Runs headless (it is just a bus subscriber). Thread-safe across source threads.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..core.logging import get_logger
from ..core.types import Frame, Topic
from ..sinks.base import Sink

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_log = get_logger("recorder")

SCHEMA_VERSION = "2.0"
#: bus topics the recorder subscribes to
TOPICS = [Topic.RADAR_RAW, Topic.RADAR_RD, Topic.RADAR_RA, Topic.RADAR_DA, Topic.CAMERA, Topic.SKELETON]


def _git_commit() -> Optional[str]:
    try:
        return subprocess.check_output(
            ["git", "-C", _ROOT, "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return None


class Recorder(Sink):
    def __init__(self, config, compute=None):
        self.config = config
        self.rc = config.record
        self.compute = compute
        self._fw = None
        self.session_dir: Optional[Path] = None
        self._recording = False
        self._ts_fh = None
        self._ts_writer = None
        self._counts: dict = defaultdict(int)
        self._t0: Optional[float] = None
        self._lock = threading.Lock()

    # -- Sink lifecycle --------------------------------------------------------
    def open(self) -> None:
        pass  # recording is gated by start_session(), not pipeline start

    def consume(self, frame: Frame) -> None:
        # Source threads (radar + camera) call this concurrently. Do the gate-check AND the
        # writes under the lock: the writes are O(1) async enqueues (the FileWriter thread does
        # the disk I/O), so the lock is held only briefly, and a concurrent stop_session() can
        # never tear state out from under an in-flight write (closes the TOCTOU on _fw/_recording).
        with self._lock:
            if not self._recording or self._fw is None:
                return
            self._route_locked(frame)

    def close(self) -> None:
        if self.is_recording:
            self.stop_session()

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    # -- session control -------------------------------------------------------
    def start_session(self, note: str = "") -> str:
        from recording.file_writer import FileWriter
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = Path(self.rc.base_dir).expanduser() / stamp
        for sub in ("RD", "RA", "DA", "camera", "skeleton"):
            (session_dir / sub).mkdir(parents=True, exist_ok=True)
        fw = FileWriter()
        fw.start()
        ts_fh = open(session_dir / "timestamps.csv", "w", newline="")
        ts_writer = csv.writer(ts_fh)
        ts_writer.writerow(["topic", "frame_id", "ts"])
        with self._lock:
            self.session_dir = session_dir
            self._fw = fw
            self._ts_fh = ts_fh
            self._ts_writer = ts_writer
            self._counts.clear()
            self._t0 = time.time()
            self._recording = True  # publish state last; consume() gates on this under the lock
        self._write_metadata(note, {})  # no concurrent counts yet
        _log.info("recording -> %s", session_dir)
        return str(session_dir)

    def stop_session(self) -> dict:
        # Flip off + detach resources atomically under the lock; do the slow join/close OUTSIDE it.
        with self._lock:
            if not self._recording:
                return {}
            self._recording = False
            fw, self._fw = self._fw, None
            ts_fh, self._ts_fh = self._ts_fh, None
            self._ts_writer = None
            counts = dict(self._counts)
        if fw is not None:
            fw.stop()
            fw.join(timeout=3.0)
        if ts_fh is not None:
            ts_fh.close()
        info = self._write_metadata("", counts)
        _log.info("recording stopped: %s", counts)
        return info

    # -- routing (caller MUST hold self._lock) --------------------------------
    def _route_locked(self, frame: Frame) -> None:
        topic, fid, d, rc, fw = frame.topic, frame.frame_id, self.session_dir, self.rc, self._fw
        wrote = True
        if topic == Topic.RADAR_RAW and rc.save_raw:
            # frame.ts goes into the self-describing raw record header
            fw.write_raw_mmwave(d / "raw.bin", frame.data, fid, frame.ts)
        elif topic == Topic.RADAR_RD and rc.save_rd:
            fw.write_rd_heatmap(d / "RD" / f"{fid}.npy", frame.data, fid)
        elif topic == Topic.RADAR_RA and rc.save_ra:
            fw.write_ra_heatmap(d / "RA" / f"{fid}.npy", frame.data, fid)
        elif topic == Topic.RADAR_DA and rc.save_da:
            fw.write_da_heatmap(d / "DA" / f"{fid}.npy", frame.data, fid)
        elif topic == Topic.CAMERA and rc.save_rgb:
            fw.write_camera_frame(d / "camera" / f"{fid}.npy", frame.data, fid)
        elif topic == Topic.SKELETON and rc.save_skeleton:
            fw.write_skeleton(d / "skeleton" / f"{fid}.json", frame.data, fid)
        else:
            wrote = False
        if wrote:
            self._counts[topic] += 1
            if self._ts_writer is not None:
                self._ts_writer.writerow([topic, fid, f"{frame.ts:.6f}"])

    # -- metadata --------------------------------------------------------------
    def _write_metadata(self, note: str, counts: dict) -> dict:
        a = self.config.adc
        meta = {
            "schema_version": SCHEMA_VERSION,
            "created": datetime.now().isoformat(timespec="seconds"),
            "duration_s": round(time.time() - self._t0, 2) if self._t0 else 0.0,
            # Derived from config, never hardcoded: a wrong orientation label
            # silently corrupts downstream dataset interpretation
            "rd_flip_range": self.config.dsp.rd_flip_range,
            "rd_orientation": ("flipped (flip_range=True, matches Studio-era training data)"
                               if self.config.dsp.rd_flip_range
                               else "fft.py-preserved (flip_range=False)"),
            "raw_record_format": (
                "Each raw frame: header '<4sIdBI' (magic b'VMRF', frame_num uint32, "
                "timestamp float64, lost_packet uint8, payload_bytes uint32) + int16 payload"
            ),
            "device": self.compute.describe() if self.compute else None,
            "git_commit": _git_commit(),
            "adc_params": {"chirps": a.chirps, "rx": a.rx, "tx": a.tx, "samples": a.samples,
                           "iq": a.iq, "bytes": a.bytes},
            "record_cfg": {k: getattr(self.rc, k) for k in (
                "save_raw", "save_rd", "save_ra", "save_da", "save_skeleton", "save_rgb")},
            "frame_counts": {str(k): v for k, v in counts.items()},
            "note": note,
        }
        (self.session_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
        return meta

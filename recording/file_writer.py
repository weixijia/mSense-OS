"""
Async File Writer Module (v2)

Queue-based file writer for non-blocking I/O operations.

v2 design (comprehensive-review fixes):
- The recording unit is an atomic per-frame FrameBundle (raw + heatmaps +
  camera + skeleton). Either a whole frame is queued or a whole frame is
  dropped (with accounting) — per-modality holes in the dataset are
  impossible, so a disk stall can no longer silently desync raw.bin from
  the fnum-named .npy streams.
- The raw mmWave stream is self-describing: each record carries a header
  (magic 'VMRF', frame_num, timestamp, lost flag, payload length), so frame
  gaps from packet loss / ring overflow / writer drops are detectable
  offline and byte-offset alignment can never silently break.
- Every queue get() is paired with task_done(), so wait_completion() can
  never deadlock (the old drop path leaked the unfinished-task counter and
  queue.join() then froze the GUI forever); wait_completion() now honors
  its timeout.
- An EndSession sentinel flushes and closes the raw file handle at session
  stop (FIFO ordering guarantees it runs after all bundles); paths from a
  finalized session are refused so a late bundle can never reopen them.

Camera frames remain per-frame .npy (unchanged on-disk format for existing
training pipelines).
"""

import threading
import queue
import struct
import time
import numpy as np
import json
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

import sys
sys.path.append('..')
from config import BUFFER_PARAMS

# ── Raw .bin record format (format version 2) ────────────────────────────
# Each raw mmWave frame is written as:
#   header: magic 'VMRF' (4s) | frame_num (uint32) | timestamp (float64)
#           | lost_packet (uint8) | payload_bytes (uint32)
#   payload: raw int16 ADC samples
RAW_MAGIC = b'VMRF'
RAW_RECORD_HEADER = struct.Struct('<4sIdBI')
RAW_FORMAT_VERSION = 2


@dataclass
class FrameBundle:
    """All data belonging to one recorded frame, written atomically."""
    frame_num: int
    mmwave_ts: float = 0.0
    camera_ts: float = 0.0
    lost_packet: bool = False
    # Raw mmWave
    raw: Optional[np.ndarray] = None
    raw_path: Optional[Path] = None
    # Heatmaps
    rd: Optional[np.ndarray] = None
    rd_path: Optional[Path] = None
    ra: Optional[np.ndarray] = None
    ra_path: Optional[Path] = None
    da: Optional[np.ndarray] = None
    da_path: Optional[Path] = None
    # Camera frame (.npy, unchanged format)
    camera_frame: Optional[np.ndarray] = None
    camera_path: Optional[Path] = None
    # Skeleton landmarks
    skeleton: Optional[dict] = None
    skeleton_path: Optional[Path] = None


class _EndSession:
    """Sentinel task: flush and close session file handles."""
    pass


class FileWriter(threading.Thread):
    """
    Async queue-based file writer.

    Runs in a separate thread so file I/O never blocks capture or GUI.
    Consumes FrameBundle tasks; drops whole bundles (with accounting) if
    the disk cannot keep up.
    """

    def __init__(self, queue_size: int = None):
        """
        Initialize file writer thread.

        Args:
            queue_size: Maximum queue size (default from config)
        """
        threading.Thread.__init__(self, daemon=True)

        self.queue_size = queue_size or BUFFER_PARAMS['file_queue_size']
        self._queue = queue.Queue(maxsize=self.queue_size)
        self._running = True
        self._lock = threading.Lock()

        # Statistics
        self._writes_completed = 0
        self._writes_dropped = 0
        self._bytes_written = 0

        # Session file handles (owned by the writer thread)
        self._raw_file = None
        self._raw_file_path = None

        # Paths finalized by _EndSession. A bundle that lands after the
        # session close must NOT reopen these (defense in depth — the stop
        # flow also quiesces the worker before closing).
        self._finalized_paths = set()

    # ── Writer thread ────────────────────────────────────────────────────

    def run(self):
        """Main writer loop."""
        while self._running:
            try:
                task = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._dispatch(task)
            except Exception as e:
                print(f"[Writer] error: {e}")
            finally:
                # ALWAYS pair get() with task_done() so wait_completion()
                # can never leak the unfinished counter and deadlock
                self._queue.task_done()

        # Process remaining items on shutdown
        while True:
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._dispatch(task)
            except Exception as e:
                print(f"[Writer] error during drain: {e}")
            finally:
                self._queue.task_done()

        self._close_session_files()

    def _dispatch(self, task):
        if isinstance(task, _EndSession):
            self._close_session_files()
            return
        self._write_bundle(task)

    def _write_bundle(self, b: FrameBundle):
        """Write all modalities of one frame."""
        # Raw first — it is the ground-truth stream everything derives from
        if b.raw is not None and b.raw_path:
            self._write_raw_record(b.raw_path, b.raw, b.frame_num,
                                   b.mmwave_ts, b.lost_packet)

        if b.rd is not None and b.rd_path:
            np.save(b.rd_path, b.rd)
            self._count_bytes(b.rd.nbytes)

        if b.ra is not None and b.ra_path:
            np.save(b.ra_path, b.ra)
            self._count_bytes(b.ra.nbytes)

        if b.da is not None and b.da_path:
            np.save(b.da_path, b.da)
            self._count_bytes(b.da.nbytes)

        if b.camera_frame is not None and b.camera_path:
            np.save(b.camera_path, b.camera_frame)
            self._count_bytes(b.camera_frame.nbytes)

        if b.skeleton and b.skeleton_path:
            with open(b.skeleton_path, 'w') as f:
                json.dump(b.skeleton, f)

        with self._lock:
            self._writes_completed += 1

    def _write_raw_record(self, path: Path, data: np.ndarray,
                          frame_num: int, timestamp: float, lost: bool):
        """Append one self-describing raw record to the session .bin."""
        if path in self._finalized_paths:
            print(f"[Writer] dropped late raw frame {frame_num} "
                  f"(session already closed)")
            return
        if self._raw_file is None or self._raw_file_path != path:
            self._close_raw_file()
            self._raw_file = open(path, 'ab')
            self._raw_file_path = path

        payload = data.tobytes()
        header = RAW_RECORD_HEADER.pack(RAW_MAGIC, frame_num & 0xFFFFFFFF,
                                        timestamp, 1 if lost else 0,
                                        len(payload))
        self._raw_file.write(header)
        self._raw_file.write(payload)
        self._count_bytes(len(header) + len(payload))

    def _close_raw_file(self):
        if self._raw_file:
            try:
                self._raw_file.flush()
                self._raw_file.close()
            except Exception as e:
                print(f"[Writer] raw close error: {e}")
            self._raw_file = None
            self._raw_file_path = None

    def _close_session_files(self):
        """Flush and close all per-session file handles."""
        if self._raw_file_path:
            self._finalized_paths.add(self._raw_file_path)
        self._close_raw_file()

    def _count_bytes(self, n: int):
        with self._lock:
            self._bytes_written += n

    # ── Producer API ─────────────────────────────────────────────────────

    def submit_bundle(self, bundle: FrameBundle, timeout: float = 1.0) -> bool:
        """
        Submit a whole-frame bundle for writing.

        Called from the mmWave worker thread (never the GUI thread), so a
        short blocking timeout is acceptable backpressure. If the queue is
        still full after the timeout the WHOLE bundle is dropped and
        counted — never individual modalities.

        Returns:
            True if queued, False if dropped
        """
        try:
            self._queue.put(bundle, timeout=timeout)
            return True
        except queue.Full:
            with self._lock:
                self._writes_dropped += 1
                dropped = self._writes_dropped
            print(f"[Writer] queue full — dropped frame {bundle.frame_num} "
                  f"(total dropped: {dropped})")
            return False

    # ── Per-type compat API (vomee/ bus recorder) ────────────────────────
    # The bus-based rebuild recorder receives topics independently, so it
    # submits single-modality bundles. Unlike the old API, a queue-full
    # drop discards the NEW item with accounting — it can never leak the
    # unfinished-task counter (the old drop-oldest path deadlocked
    # wait_completion) and never desyncs the raw stream (records are
    # self-describing).

    def write_raw_mmwave(self, path: Path, data: np.ndarray, frame_num: int,
                         timestamp: float = 0.0, lost: bool = False) -> bool:
        return self.submit_bundle(FrameBundle(frame_num=frame_num, mmwave_ts=timestamp,
                                              lost_packet=lost, raw=data, raw_path=path),
                                  timeout=0.05)

    def write_rd_heatmap(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        return self.submit_bundle(FrameBundle(frame_num=frame_num, rd=data, rd_path=path),
                                  timeout=0.05)

    def write_ra_heatmap(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        return self.submit_bundle(FrameBundle(frame_num=frame_num, ra=data, ra_path=path),
                                  timeout=0.05)

    def write_da_heatmap(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        return self.submit_bundle(FrameBundle(frame_num=frame_num, da=data, da_path=path),
                                  timeout=0.05)

    def write_camera_frame(self, path: Path, data: np.ndarray, frame_num: int) -> bool:
        return self.submit_bundle(FrameBundle(frame_num=frame_num, camera_frame=data,
                                              camera_path=path), timeout=0.05)

    def write_skeleton(self, path: Path, data: dict, frame_num: int) -> bool:
        return self.submit_bundle(FrameBundle(frame_num=frame_num, skeleton=data,
                                              skeleton_path=path), timeout=0.05)

    def end_session(self, timeout: float = 2.0) -> bool:
        """
        Queue an end-of-session flush/close of the raw file.

        FIFO ordering guarantees it runs after every previously submitted
        bundle.
        """
        try:
            self._queue.put(_EndSession(), timeout=timeout)
            return True
        except queue.Full:
            print("[Writer] WARNING: could not queue session close (queue full)")
            return False

    def stop(self):
        """Stop the writer thread (drains queue, then closes files)."""
        self._running = False

    def wait_completion(self, timeout: float = None) -> bool:
        """
        Wait for all pending writes to complete.

        Args:
            timeout: Maximum time to wait in seconds (None = wait forever)

        Returns:
            True if the queue drained, False on timeout
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if deadline is not None and time.monotonic() >= deadline:
                print(f"[Writer] wait_completion timed out with "
                      f"~{self._queue.qsize()} tasks pending")
                return False
            time.sleep(0.02)
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get writer statistics."""
        with self._lock:
            total = self._writes_completed + self._writes_dropped
            return {
                "writes_completed": self._writes_completed,
                "writes_dropped": self._writes_dropped,
                "bytes_written": self._bytes_written,
                "queue_size": self._queue.qsize(),
                "queue_capacity": self.queue_size,
                "drop_rate": self._writes_dropped / max(1, total)
            }

    def reset_stats(self):
        """Reset statistics."""
        with self._lock:
            self._writes_completed = 0
            self._writes_dropped = 0
            self._bytes_written = 0

    @property
    def is_running(self) -> bool:
        """Check if writer thread is running."""
        return self._running and self.is_alive()

    @property
    def queue_utilization(self) -> float:
        """Get queue utilization as a fraction."""
        return self._queue.qsize() / self.queue_size

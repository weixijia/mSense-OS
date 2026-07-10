"""Regression tests for the pure-Python mmWave UDP frame-assembly state machine.

Guards the comprehensive-review fixes in core/mmwave_capture.py:

- Packet-loss recovery must NOT process the recovery packet twice (the old
  fall-through byte-shifted every post-recovery frame into garbage).
- A malformed/runt datagram must be skipped, never kill the capture thread.
- Buffer overrun must resync to the newest frame (no permanent latch).

Run:  python tests/test_capture_regression.py   (or python -m pytest -q)
"""
import os
import sys
import time

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core.mmwave_capture import (MmWaveCapture, BYTES_IN_PACKET,      # noqa: E402
                                 BYTES_IN_FRAME, UINT16_IN_FRAME,
                                 UINT16_IN_PACKET)


class _DummySocket:
    def settimeout(self, t):
        pass


class FakeCapture(MmWaveCapture):
    """MmWaveCapture fed from a scripted packet list instead of a socket."""

    def __init__(self, packets, buffer_size=100):
        self._scripted_packets = list(packets)
        super().__init__(buffer_size=buffer_size)

    def _init_sockets(self):
        self.data_socket = _DummySocket()   # only settimeout() is called

    def _read_data_packet(self):
        if not self._scripted_packets:
            self._running = False
            raise OSError("scripted stream ended")
        return self._scripted_packets.pop(0)

    def stop(self):
        self._running = False


def build_packets(num_frames, drop_packet_nums=(), runt_after=None):
    """DCA1000-style packet stream; frame k filled with int16 value k so any
    byte misalignment is immediately visible.

    Packet tuple: (packet_num from 1, byte_count = bytes sent BEFORE this
    packet, payload uint16 array). runt_after: insert a malformed short
    datagram (with a NON-consecutive packet_num, like a foreign packet)
    after that packet number.
    """
    stream = np.concatenate([
        np.full(UINT16_IN_FRAME, k, dtype=np.int16) for k in range(num_frames)
    ])
    raw = stream.tobytes()

    packets = []
    pnum = 1
    for off in range(0, len(raw) - BYTES_IN_PACKET + 1, BYTES_IN_PACKET):
        if pnum not in drop_packet_nums:
            chunk = raw[off:off + BYTES_IN_PACKET]
            packets.append((pnum, off, np.frombuffer(chunk, dtype=np.uint16)))
        if runt_after is not None and pnum == runt_after:
            # Foreign/truncated datagram: wrong size, nonsense counter
            packets.append((0, 0, np.zeros(10, dtype=np.uint16)))
        pnum += 1
    return packets


def run_capture(packets, buffer_size=100):
    cap = FakeCapture(packets, buffer_size=buffer_size)
    cap.start()
    cap.join(timeout=60)
    assert not cap.is_alive(), "capture thread did not terminate"

    frames = []
    for _ in range(buffer_size + 4):
        result = cap.get_frame()
        if isinstance(result[0], str):
            break
        frames.append(result)
    return cap, frames


def test_normal_assembly():
    """Contiguous stream: frames 1..N-2 assembled with exact contents."""
    cap, frames = run_capture(build_packets(6))
    fnums = [f[2] for f in frames]
    assert fnums == [1, 2, 3, 4], f"expected frames 1-4, got {fnums}"
    for data, ts, fnum, lost in frames:
        assert np.all(data == fnum), f"frame {fnum} contains foreign data"
        assert not lost
        assert ts > 0


def test_packet_loss_recovery_no_duplication():
    """Drop one packet mid-frame-2: frame 2 aborted; frames 3/4 must contain
    exactly their own values (the old fall-through corrupted them all)."""
    drop = int(2.5 * BYTES_IN_FRAME / BYTES_IN_PACKET)
    cap, frames = run_capture(build_packets(6, drop_packet_nums={drop}))

    fnums = [f[2] for f in frames]
    assert fnums == [1, 3, 4], f"expected frames [1, 3, 4], got {fnums}"

    by_num = {f[2]: f for f in frames}
    for fnum in (1, 3, 4):
        assert np.all(by_num[fnum][0] == fnum), \
            f"frame {fnum} corrupted after packet-loss recovery"
    assert bool(by_num[3][3]), "post-loss frame 3 should be flagged lost"
    assert not by_num[4][3]
    assert cap.lost_frames == 1


def test_runt_packet_does_not_kill_thread():
    """A malformed datagram mid-stream must be skipped; capture continues and
    subsequent frames are intact (previously: ValueError -> thread death)."""
    runt_at = int(1.5 * BYTES_IN_FRAME / BYTES_IN_PACKET)
    cap, frames = run_capture(build_packets(5, runt_after=runt_at))

    fnums = [f[2] for f in frames]
    assert len(fnums) >= 3, f"capture died after runt packet (got {fnums})"
    for data, ts, fnum, lost in frames:
        assert np.all(data == fnum), f"frame {fnum} corrupted around runt packet"


def test_buffer_overrun_resyncs_to_newest():
    """8 frames into a 4-slot buffer with no reader: get_frame must resync to
    the newest frame instead of latching 'bufferOverWritten' forever."""
    cap, frames = run_capture(build_packets(8), buffer_size=4)
    assert len(frames) >= 1, "no frames delivered after overrun"
    for data, ts, fnum, lost in frames:
        assert np.all(data == fnum), f"frame {fnum} corrupted after resync"
    result = cap.get_frame()
    assert result[0] == "wait new frame" or not isinstance(result[0], str)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nAll {len(fns)} capture regression tests passed.")

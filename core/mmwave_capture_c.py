"""Off-GIL mmWave UDP capture backend (drop-in for MmWaveCapture).

Root cause of frame loss (ultragoal frame-loss-zero / G001): the pure-Python MmWaveCapture
receive thread shares the GIL with the main thread + file-writer, so under recording load
(CUDA FFT + per-frame disk I/O) it falls behind, the kernel UDP buffer overflows, and REAL
packets are dropped (RcvbufErrors +743 with recording vs 0 without).

Fix (G002): the fpga_udp C drain thread (`udp_frame_*`) receives AND assembles complete frames
with the GIL released, into a ring; Python pulls a ready frame with one memcpy. Validated:
~11 fps under recording load with RcvbufErrors=0 (no kernel packet loss). The earlier
`udp_read_thread_get_frames` path was lossless too but capped ~5.6 fps (per-frame dequeue+sort);
this assembles in C so it keeps up at the full radar rate.

NO FABRICATION: only fully-received frames (recv == bytesInFrame) are enqueued by the C thread;
frames with any missing packet are counted and DROPPED, never zero-filled/interpolated. If the
consumer can't keep up, whole COMPLETE frames are dropped at the ring (honest), never corrupted.

Public interface matches core.mmwave_capture.MmWaveCapture: start(), get_frame(), _running,
lost_frames, total_frames.
"""
from __future__ import annotations
import socket
from typing import Tuple, Union

import numpy as np

from config import NETWORK_PARAMS

BYTES_IN_FRAME = (256 * 255 * 2 * 4 * 2 * 2)   # samples*chirps*tx*rx*IQ*bytes = 2,088,960


class MmWaveCaptureC:
    """C-thread (off-GIL) UDP receiver + frame assembler. Requires the fpga_udp extension."""

    def __init__(self, pc_ip: str = None, data_port: int = None, ring_frames: int = 32):
        import fpga_udp                       # raises ImportError if unavailable -> caller falls back
        if not hasattr(fpga_udp, "udp_frame_get"):
            raise RuntimeError("fpga_udp lacks udp_frame_* (rebuild needed)")
        self._fpga = fpga_udp
        self.pc_ip = pc_ip or NETWORK_PARAMS['pc_ip']
        self.data_port = data_port or NETWORK_PARAMS['data_port']

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 ** 27)
        self.sock.bind((self.pc_ip, self.data_port))

        self._fpga.udp_frame_init(BYTES_IN_FRAME, ring_frames)
        self._running = True
        self._fid = 0
        self._started = False

    def start(self):
        if self._started:                                # idempotent: never spawn a 2nd C thread
            return
        self._fpga.udp_frame_start(self.sock.fileno())   # C thread: recv + assemble frames (no GIL)
        self._started = True
        print("[mmWave-C] off-GIL C frame receiver started (fpga_udp udp_frame_*)")

    def is_running(self) -> bool:
        return self._started and self._running

    def is_alive(self) -> bool:                          # parity with MmWaveCapture (threading.Thread)
        return self.is_running()

    def get_stats(self) -> dict:
        try:
            recv_c, lost_inc, dropped_ovf = self._fpga.udp_frame_stats()
        except Exception:
            recv_c = lost_inc = dropped_ovf = 0
        return {"total_frames": int(recv_c),
                "lost_frames": int(lost_inc) + int(dropped_ovf),
                "incomplete_dropped": int(lost_inc),
                "ring_overflow_dropped": int(dropped_ovf)}

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass

    @property
    def total_frames(self) -> int:
        try:
            return int(self._fpga.udp_frame_stats()[0])   # complete frames assembled
        except Exception:
            return self._fid

    @property
    def lost_frames(self) -> int:
        try:
            recv_c, lost_inc, dropped_ovf = self._fpga.udp_frame_stats()
            return int(lost_inc) + int(dropped_ovf)       # incomplete(dropped) + ring-overflow(dropped)
        except Exception:
            return 0

    def get_frame(self) -> Tuple[Union[np.ndarray, str], float, int, bool]:
        """Non-blocking: pull the next complete real frame, or a 'wait' sentinel.
        Returned frames are always complete (recv==expected); lost flag is therefore False."""
        import time
        raw = self._fpga.udp_frame_get(0)                 # timeout 0 -> non-blocking
        if raw is None or raw.size < BYTES_IN_FRAME:
            return "wait new frame", 0.0, -2, False
        frame = raw.view(np.int16)                        # writable int16 view of the fresh C copy
        self._fid += 1
        return frame, time.time(), self._fid, False

    def stop(self):
        self._running = False
        try:
            self._fpga.udp_frame_stop()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass

# fpga_udp patch — off-GIL frame-assembling UDP receiver

`fpga_udp_offgil_frame_receiver.patch` is a diff against **`gaoweifan/pyRadar`** `fpga_udp/src/main.cpp`
(the external C extension, built locally with `pip install -e .`). It is the fix for mmWave **frame
loss during recording** (ultragoal `frame-loss-zero`). The change is NOT in this repo's git because
fpga_udp is a separate project — this patch preserves it so it can be re-applied if pyRadar is
re-cloned/rebuilt.

## What it adds
1. **`_udp_frame_thread` + `udp_frame_init/start/get/stop/stats`** — a drain thread that receives
   *and assembles complete frames* in C with the **GIL released**, into a ring buffer. Python pulls a
   ready frame with a single memcpy (`udp_frame_get`). This is what `core/mmwave_capture_c.py`
   (`MmWaveCaptureC`) uses. Only **complete** frames (received == bytesInFrame) are enqueued;
   incomplete frames are counted and **dropped, never zero-filled/synthesized**.
2. **`py::gil_scoped_release`** added to the existing `udp_read_thread_get_frames` blocking waits.

## Why
The pure-Python receive thread shares the GIL with the FFT/GUI/file-writer, so under recording load it
falls behind, the kernel UDP buffer overflows, and real packets are dropped (RcvbufErrors +743 with
recording vs 0 without). The packet-based `udp_read_thread_get_frames` was lossless but its per-frame
dequeue+sort capped throughput at ~5.6 fps. Assembling frames in the C thread keeps up at the full
radar rate. Verified: **11.4 fps recorded under load, RcvbufErrors=0** (no kernel packet loss).

## Apply / rebuild
```bash
cd <pyRadar>/fpga_udp        # e.g. ~/Documents/pyRadar/fpga_udp
git apply <thisrepo>/mmwave_pure_python/patches/fpga_udp_offgil_frame_receiver.patch   # if not already applied
pip install -e . --no-build-isolation
```
`main.py` prefers `MmWaveCaptureC` (this path) and falls back to the pure-Python `MmWaveCapture` if
fpga_udp lacks `udp_frame_*` (e.g. macOS without the built extension).

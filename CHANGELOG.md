# Changelog

## 2026-07-11 — Comprehensive review fixes (main + feat/vlm-caption-mode)

A full multi-angle review of the mainline turned up (and this batch fixes) a set
of correctness, data-integrity, and performance defects. All fixes are on `main`
and merged into `feat/vlm-caption-mode` (mSense OS / DopplerVLM); 24 tests pass.

### RD vertical stripes (display) — `383620c`
- **Root cause:** RD is 255 wide → an RGB888 scanline is `255×3 = 765` bytes, not
  4-byte aligned. The Qt Quick scene-graph texture upload assumes 4-byte row
  alignment and shears each row → equidistant vertical stripes in RD. RA (256
  wide → 768, aligned) and the camera (1280) were always clean — width parity is
  the tell. The raw ADC, FFT, and every raster/numpy path were provably clean; the
  artifact lived only in the GPU texture upload.
- **Fix:** `heatmap_to_qimage` emits a 32-bit RGBA8888 image (row stride `4×w`,
  always aligned), width-agnostic and stripe-free. Data is untouched.
- See `mmwave_pure_python/RD_STRIPES_DIAGNOSIS.md` → "第二个原因". Distinct from the
  2026-06-22 pure-Python-trigger firmware phase-noise stripes (a data-layer issue).

### Recording data integrity — `1b73db4`
- **Stop-freeze deadlock (critical):** the queue-full drop path did `get_nowait()`
  without `task_done()`, leaking `unfinished_tasks`; `wait_completion()` was a bare
  `queue.join()` that ignored its timeout → one dropped write froze the GUI forever
  at Stop. Now every `get()` pairs with `task_done()` and `wait_completion` honors a
  real deadline.
- **Dataset desync:** per-modality drops silently byte-shifted the headerless
  `raw.bin` vs the `fnum`-named `.npy` streams. Recording is now an atomic per-frame
  `FrameBundle` (whole frame queued or dropped, with accounting), and raw records
  are self-describing (`VMRF` header: frame_num, timestamp, lost flag, length) so
  gaps are detectable offline.
- `TimestampLogger` is thread-safe, gains a `lost_packet` column, flushes per line;
  session names get a millisecond suffix; metadata is `format_version: 2` and records
  the capture backend's timestamp/frame-number semantics.

### mmWave capture hardening — `35d1fe9`, `96068f0`
- Pure-Python receiver: packet-loss recovery no longer double-processes the recovery
  packet (which byte-shifted every subsequent frame); malformed/runt datagrams are
  skipped instead of killing the capture thread; unsigned packet counter; overrun
  resync no longer misfires at frame index 0; dead `config_socket` removed.
- C (off-GIL) receiver: `BYTES_IN_FRAME` derived from `ADC_PARAMS` at construction
  (was a hardcoded 255-chirp literal, breaking every non-255-loop `--trigger`
  profile); ring-overflow drops now surface as `lost=True` + a frame-number gap
  instead of silent contiguous numbering.

### GUI worker / recording — `41881cc`
- `stop()` quiesces the worker (`wait_idle`) before finalizing the session, so a
  late frame can't land after the session close; the worker loop is exception-guarded
  so it can never die and silently freeze RD/RA; frame_count/CSV only advance when a
  bundle was actually queued.
- **Behavior change:** the recorded camera frame is now the **clean RGB** frame
  (skeleton lives in the landmarks JSON, never burned into pixels).

### Performance — `8e876ab`
- `power = real² + imag²` instead of `abs()**2` (drops a needless sqrt over ~16.7M
  elements); `log10` epsilon guard; DA computed only when requested; one batched
  device→host transfer instead of three; the `torch.set_num_threads(1)` cap applies
  only on the MPS device (was process-global, throttling CPU/CUDA pose ops).
- Camera frame accessors return references, not under-lock copies (the capture loop
  only ever rebinds fresh arrays) — ~166 MB/s less GUI-thread memcpy at 30 fps.
- `FrameView` caches the scaled image, so `paint()` doesn't re-resample every repaint.

### vomee/ rebuild pipeline — `6e03cc1`
- `MmWaveDSP` now passes `flip_range` from `config.MMWAVE_RD_FLIP_RANGE` (was default
  False → silently mirrored RD/RA vs the model's training orientation); `DspCfg` added
  to the typed config + `from_legacy`; session metadata derives `rd_orientation`
  instead of hardcoding it; regression goldens cover both orientations.

### Not fixed / parked
- Pure-Python `--trigger` firmware phase-noise stripes (data-layer, ~10× worse clutter
  spread from studio_cli flash firmware). Unrelated to the display fix above; a display
  change cannot rescue it. Workflow bypass (Studio rf_eval → receive-only) remains the
  clean path. Re-verify numerically (static-frame skirt/DC ratio), not by eye, before
  trusting the pure-Python path.

# Vomee Rebuild Plan — industrial-standard, extension-ready

> Goal: rewrite the Vomee app into a clean, layered, testable platform that supports
> future functions **without changing the explored-and-finalized pure-Python mmWave
> sensing workflow** (radar trigger + DCA1000 UDP capture + 3D-FFT → RD/RA/DA).

## 1. Scope & planned functions

| Function | Status | Notes |
|---|---|---|
| **Pure-Python mmWave sensing** (trigger → capture → RD/RA/DA) | ✅ FINALIZED — preserve byte-identical | wrap, never rewrite the math/protocol |
| **Data collection / saving** (core platform function) | rebuild as first-class subsystem | per-stream toggles; frame-aligned RGB+timestamp; optional skeleton |
| Camera + ViTPose skeleton (show / save, independently) | rebuild behind interfaces | CUDA→MPS→CPU |
| Live GUI (camera + RD/RA heatmaps) | rebuild as an optional consumer | headless must work without it |
| **Heartbeat detection** | PHASE 2 (collaborative) — leave API + stub | needs per-range-bin phase-over-time, not RD |
| **Action-recognition ML model** (input = 20 frames of RD) | PHASE 3 — leave buffer + API + stub | sliding 20-frame RD window; device-managed inference |

**Hard constraint:** the finalized mmWave workflow code (`mmwave_trigger`, `mmwave_capture`,
`mmwave_processor`) is **moved/wrapped as-is**. A regression test asserts RD/RA byte-identity
before vs after the refactor. No protocol, reshape, FFT, normalization, or orientation change.

## 2. Architecture (layered, decoupled, headless-first)

```
            ┌─────────── Presentation (OPTIONAL) ───────────┐
            │  gui/ (PySide6/QML)  ·  cli/ (headless)         │
            └───────────────▲────────────────────────────────┘
                            │ subscribes (read-only)
   Sources ──► Frame Bus ──►├──► Sinks (Recorder, ...)
   (radar,     (timestamped │
    camera)    pub/sub)     └──► Features (heartbeat, action-ML, ...)
                                 (windowed consumers via Buffers)
        ▲                              ▲
        │ Processing (mmWave DSP, pose)│ ComputeManager (CUDA→MPS→CPU)
```

- **Sources** produce timestamped frames; **Processing** transforms them; the **Frame Bus**
  fan-outs to **Sinks** (recording) and **Features** (algorithms). **GUI is just another
  subscriber** — the whole pipeline runs headless.
- Everything behind **ABCs + dependency injection**; a single **composition root** (`app.py`)
  wires concrete implementations chosen from typed config. Industrial concerns: typed config,
  structured logging, graceful start/stop, no global state, unit-testable units.

## 3. Proposed package layout (`vomee/`)

```
vomee/
  app.py                # composition root: build + run pipeline (headless or GUI)
  cli.py                # argparse/entry; flags for record toggles, headless, device
  config/               # typed config (dataclasses): RadarCfg, CameraCfg, RecordCfg, ComputeCfg, profiles, env overrides
  core/
    types.py            # Frame dataclasses: RadarFrame(raw), Heatmaps(rd,ra,da), CameraFrame, Skeleton — all carry ts + frame_id
    compute.py          # ComputeManager: device select CUDA→MPS→CPU; fft policy (torch CUDA / CPU; numpy fallback)
    bus.py              # FrameBus: typed pub/sub, per-topic, thread-safe, drop-policy
    buffers.py          # RingBuffer / SlidingWindow(N) — incl. the 20-frame RD window
    logging.py          # structured logging setup
  sources/
    base.py             # Source ABC: start(), stop(), topic, emits Frames to bus
    mmwave.py           # WRAPS finalized trigger + capture (UNCHANGED behavior)
    camera.py           # WRAPS camera capture
  processing/
    base.py             # Processor ABC: process(in_frame) -> out_frame
    mmwave_dsp.py       # WRAPS finalized mmwave_processor (RD/RA/DA) — UNCHANGED math
    pose.py             # ViTPose (uses ComputeManager)
  sinks/
    base.py             # Sink ABC: consume(frame)
    recorder.py         # session/dir/metadata (+orientation+version+device) — configurable streams
    file_writer.py      # async writer (reuse current, extended)
  features/             # ◄── the extension space
    base.py             # Feature ABC: declares input topics + window size; on_frame()/on_window() -> result topic
    registry.py         # register/discover features (entry-point or decorator based)
    heartbeat.py        # PHASE 2 stub (interface only)
    action_classifier.py# PHASE 3 stub: consumes 20-frame RD window -> action label
  gui/                  # PySide6/QML consumer (optional)
recordings/             # output (gitignored)
tests/                  # regression (RD/RA byte-identity) + unit tests
```

`main.py` stays as a thin shim that calls `vomee.cli` (back-compat). Old modules remain until parity is proven.

## 4. Key interfaces (the "leave space / API" requirement)

```python
# core/compute.py
class ComputeManager:
    device: str                      # 'cuda' | 'mps' | 'cpu'
    def to(self, tensor): ...        # move to device
    def fft_backend(self): ...       # 'torch-cuda' | 'torch-cpu' | 'numpy' (mmWave policy)
    # ViTPose + ML model + DSP all ask the SAME manager → one place to maximize HW.

# sources/base.py
class Source(ABC):
    topic: str
    def start(self, bus: FrameBus): ...
    def stop(self): ...

# processing/base.py
class Processor(ABC):
    def process(self, frame) -> Frame | None: ...

# sinks/base.py
class Sink(ABC):
    def consume(self, frame) -> None: ...

# features/base.py  — heartbeat & action-ML implement this
class Feature(ABC):
    input_topics: list[str]          # e.g. ['radar.rd'] or ['radar.raw']
    window: int = 1                  # e.g. 20 for the action model; 1 for per-frame
    output_topic: str | None         # publishes results back on the bus (label, bpm, ...)
    def on_window(self, frames: list[Frame], compute: ComputeManager) -> Frame | None: ...
```

- The **20-frame RD ML model** = a `Feature` with `input_topics=['radar.rd']`, `window=20`; the
  bus + a `SlidingWindow(20)` buffer hand it exactly 20 RD frames; it runs on `ComputeManager`.
- **Heartbeat** = a `Feature` subscribing to a raw/range-bin phase stream (added as a small DSP
  processor that exposes per-range-bin phase over time); leaves the API ready.
- Features are inert stubs in the rebuild phase — registered, wired, but no-op — so adding the
  real algorithms later touches only `features/*.py`, nothing else.

## 5. Data-collection subsystem (core function)

- **RecordCfg** independently toggles each stream: `raw_adc`, `rd`, `ra`, `da`, `skeleton`, `rgb`.
- **Show vs Save are independent** for skeleton and RGB (a display flag and a record flag each).
- **Frame-aligned RGB + timestamp**: bus timestamps align radar/camera; per-frame manifest +
  `timestamps.csv` (mmwave_ts, camera_ts, frame_id) — extends the current TimestampLogger.
- **Session metadata** gains: `schema_version`, `rd_orientation` (near-at-bottom), `device`,
  `adc_params`, `git_commit` — fixing gaps the code review flagged.
- Recorded `.npy` stay **raw processor output** (the ML model trains on these) — never smoothed.

## 6. Compute strategy (Ubuntu-first; Mac MPS best-effort; Windows non-gating)

- One `ComputeManager` decides device once: **CUDA → MPS → CPU**.
- **mmWave FFT policy preserved**: torch CUDA on NVIDIA, torch CPU on Apple Silicon (MPS lacks
  `fft`), NumPy fallback — exactly today's finalized behavior.
- ViTPose and the action model use the same manager. If a path conflicts on Windows, Ubuntu/Mac
  win; Windows is best-effort.

## 7. Phased delivery (ordered ultragoal stories)

**Phase A — Rebuild (this initiative):**
1. **Scaffold & interfaces** — `vomee/` skeleton, typed config, ComputeManager, types, bus, buffers, ABCs. Old app still runs.
2. **Preserve mmWave core** — wrap finalized trigger+capture+DSP behind Source/Processor; regression test = RD/RA byte-identity on a saved raw frame.
3. **Camera & pose** — port camera + ViTPose behind ABCs via ComputeManager.
4. **Data collection** — configurable per-stream recording, frame-aligned RGB+timestamp, metadata+version+orientation, headless record path.
5. **Bus & buffers wiring** — timestamped sync; sliding windows incl. 20-frame RD; drop policy.
6. **GUI re-layer** — rebuild GUI as an optional bus consumer; preserve look; live show/record toggles.
7. **Extension framework + stubs** — Feature API + registry; inert heartbeat & action_classifier stubs; E2E smoke (Ubuntu CUDA + CPU fallback); FINAL gate: ai-slop-cleaner + verification + code-review.

**Phase B — Heartbeat (collaborative):** implement the heartbeat Feature (range-bin phase → BPM).

**Phase C — ML integration:** integrate the trained classifier as the action_classifier Feature (20-frame RD window → action label), device-managed, with live label + optional logging.

## 8. Verification & migration

- Keep the **old app fully runnable** until the new pipeline reaches parity (no big-bang).
- **Golden regression**: save a raw ADC frame + its current RD/RA/DA; assert the new pipeline
  reproduces them byte-identically (guards the finalized workflow).
- E2E smoke on real hardware (Ubuntu/CUDA) + CPU fallback before the final gate.
- Per-story evidence recorded in the ultragoal ledger; final story gated by full quality pass.

## 9. Risks / decisions to confirm with user
- Heartbeat needs a **phase/range stream** not currently produced — Phase B adds a small DSP path.
- Action model I/O contract (exact RD shape/dtype/normalization the model expects; 20-frame stride/overlap) — confirm before Phase C.
- Package rename `Vomee/` → `vomee/`: keep `main.py` shim for back-compat.

## 10. Backpressure & drop policy (real-time, never block acquisition)
- **FrameBus**: synchronous fan-out on the publisher's thread; subscribers MUST be cheap
  or offload (the recorder uses the async FileWriter). A failing subscriber is isolated.
- **mmWave capture** (finalized): own ring buffer; `get_frame()` resyncs to the newest
  frame on overwrite (degrades/lags, never freezes).
- **Recorder/FileWriter**: bounded queue; drops the *oldest* write on overflow (counted in
  stats) so disk I/O never stalls capture.
- **SlidingWindow / feature windows**: keep only the most-recent N frames (FIFO drop), so
  a slow feature (e.g. the action model) always sees the latest motion, never a backlog.
  Real-time "show latest" everywhere; the recorded `.npy` are the source of truth.

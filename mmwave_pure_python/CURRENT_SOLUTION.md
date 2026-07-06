# Current Solution — full reverse-engineering (mmWave Studio + Vomee)

> ## ✅ STATUS 2026-06-22 — this IS the production workflow now
>
> The Studio-bring-up → autonomous-stream → host-reboot → Ubuntu-receive flow described below is the
> validated path. Two refinements since this doc was written:
> - **Step 3 ("kill the DCA1000/record process") is replaced by rebooting the host to Ubuntu** (without
>   power-cycling the radar) and capturing with **`python main.py --no-camera --no-trigger`**. The
>   `--no-trigger` flag makes capture receive-only so it never resets/kills the live stream.
> - **Frame loss is solved** by an off-GIL C frame-assembling receiver (`core/mmwave_capture_c.py` +
>   fpga_udp `udp_frame_*`, patch in `mmwave_pure_python/patches/`): 11.4 fps under recording load,
>   kernel `RcvbufErrors=0`, complete gap-free frames only (no interpolation/zero-fill).
> - **RD orientation:** `config.MMWAVE_RD_FLIP_RANGE = True` (byte-matches the model's training data).

Source of truth: `F:\mmwave_cam2.11\lua\skeleton.lua` (+ `clothes_..._trigger.lua`,
`mmw_start_cam.lua`) and the legacy python (`steaming.py`, `capture_single.py`,
`fft.py`, `raw_decode.py`, `config.py`).

## The end-to-end pipeline today
1. **mmWave Studio runs `skeleton.lua`** — does the ENTIRE trigger chain over SPI
   (via the AR-DevPack FT4232H FTDI) + Ethernet:
   - `FullReset` → `SOPControl(2)` (SPI/dev boot mode) → `Connect(COM,921600)`
   - `DownloadBSSFw(xwr18xx_radarss.bin)` + `DownloadMSSFw(xwr18xx_masterss.bin)`
     — **radarSS + masterSS firmware loaded into the device RAM over SPI** (this is
     the eval/“mmwavelink” path, NOT the flashed mmw_demo).
   - `PowerOn`/`RfEnable`/`ChanNAdcConfig`/`RfInit` — bring up RF.
   - `ProfileConfig`/`ChirpConfig`×2/`FrameConfig` — the chirp profile (below).
   - `DataPathConfig`/`LvdsClkConfig`/`LVDSLaneConfig` — route ADC out over LVDS.
   - `CaptureCardConfig_*` — configure the **DCA1000 FPGA over UDP** (ports 4096/4098).
   - `CaptureCardConfig_StartRecord(...)` — Studio binds PC UDP 4098 → records .bin.
   - `StartFrame()` — radar starts chirping; **NumFrames=0 ⇒ infinite frames**.
2. Radar chirps forever → ADC over LVDS → DCA1000 FPGA → **UDP raw ADC → 192.168.33.30:4098**.
3. **User kills the DCA1000/record process** → frees UDP 4098; radar+FPGA keep streaming.
4. **Vomee `main.py`** (`mmwave_capture.py`, ex-`steaming.py`) binds 4098, assembles
   frames, FFT → RA/RD heatmaps. **It never triggers anything.**

So mmWave Studio is needed ONLY for the one-time per-session trigger (steps in #1).
Everything after `StartFrame()` is autonomous until power-cycle.

## Exact RF config (skeleton.lua) — the data we must reproduce
`ProfileConfig(0, 77, 20, 6, 60, 0,0,0,0,0,0, 65.998, 0, 256, 4800, 0, 0, 30)`

| Param | Value |
|-------|-------|
| startFreq | 77 GHz |
| idleTime | 20 µs |
| adcStartTime | 6 µs |
| rampEndTime | 60 µs |
| freqSlopeConst | 65.998 MHz/µs |
| numAdcSamples | 256 |
| digOutSampleRate | 4800 ksps |
| rxGain | 30 dB |

- `ChanNAdcConfig(1,0,1,1,1,1,1,2,1,0)` → **TX0+TX2 (2TX), RX0–3 (4RX), 16-bit ADC**.
- `ChirpConfig(0,...)` TX0, `ChirpConfig(1,...)` TX2 → TDM-MIMO, 2 chirps/loop.
- `FrameConfig(0, 1, 0, 255, 100, 0, 0, 1)` → chirpStart 0, chirpEnd 1, **NumFrames=0
  (infinite)**, **255 loops**, **100 ms** period. ⇒ matches `config.py` chirps=255.
- (clothes variant: slope 44.321, rampEnd 90, idle 2, sampleRate 3200 — same frame/chan.)

## DCA1000 config (skeleton.lua) — pure-python reproducible
- `CaptureCardConfig_EthInit("192.168.33.30","192.168.33.180","12:34:56:78:90:12",4096,4098)`
- `CaptureCardConfig_Mode(1, 2, 1, 2, 3, 30)` → **lvdsMode=2 (2-lane, required for 1843)**,
  dataFormatMode=3 (16-bit).
- `CaptureCardConfig_PacketDelay(5)` → 5 µs (~706 Mbps).

These map 1:1 to pyRadar/OpenRadar `DCA1000` UDP commands + a `cf.json`.

## ADC byte layout (raw_decode.py / fft.py) — the compatibility contract
Raw int16 →
`reshape(-1, 255 chirps, 2 tx, 4 rx, 128 (=samples/2), 2 IQ, 2)` →
`transpose(0,1,2,3,4,6,5)` → `reshape(-1,255,2,4,256,2)` → complex `I + jQ`.
This is **pure DCA1000 raw ADC, NO HSI/CBUFF header**. Any replacement MUST deliver
the identical header-less ADC stream, or the reshape breaks.

## What "going pure-Python" must replace
| Studio job | Pure-Python equivalent | Difficulty |
|-----------|------------------------|------------|
| SPI fw download (BSS+MSS) + mmwavelink RF config + StartFrame | **Path A:** reimplement mmwavelink-over-SPI via FTDI (pyftdi / TI MMWAVE-DFP). pyRadar does this ONLY for AWR2243. | **Very high** |
| (alt) RF config + start | **Path B:** flash `xwr18xx_mmw_demo`, send `.cfg`+`sensorStart` over CLI UART (COM4). | **Low** (one-time flash + SOP jumper) |
| DCA1000 FPGA config + start | `DCA1000` UDP commands (port 4096) — pure python, both paths. | **Low** |
| Receive + FFT + display | Vomee already does this. | **Done** |

## Key compatibility risk for Path B
mmw_demo's `lvdsStreamCfg` can prepend an **HSI header** per chirp. Studio's raw
mode does not. To keep Vomee's parser unchanged, the `.cfg` must stream **ADC-only,
header disabled** (`lvdsStreamCfg -1 0 1 0` with HSI header off), matching the
header-less layout above. This is the #1 thing to verify on first capture.

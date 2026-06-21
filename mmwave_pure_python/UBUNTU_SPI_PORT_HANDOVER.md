# Vomee — Ubuntu SPI / rf_eval Firmware Port: Handover & Plan

> **Audience:** a fresh Claude Code session running on **Ubuntu** (same machine, after the OS switch),
> in the Vomee repo. Read this top-to-bottom first. It captures the entire investigation done on
> 2026-06-21 (on Windows) and the concrete plan to finish the work on Ubuntu.
>
> **One-line goal:** make the *pure-Python* (no mmWave Studio) capture produce **the same
> phase-coherent raw ADC data as mmWave Studio** — eliminating the "equidistant vertical lines"
> in the Range-Doppler image — and run the whole system on Ubuntu.

---

## 0. How to use this document
1. Read §1–§5 for context + the confirmed root cause (don't re-derive it; it's settled with data).
2. Read §6 for the exact inventory (paths, devices, firmware, configs).
3. Read §7–§8 for the detailed technical map of the SPI/mmwavelink control we must build.
4. Execute §9 (the staged Ubuntu plan) — each stage has a verification gate. Don't skip gates.
5. §10 lists the real risks/open questions to resolve with the hardware + TI docs.
6. §11 lets you re-verify the diagnosis with the saved analysis scripts.

---

## 1. TL;DR

- **Symptom:** pure-Python Vomee's RD heatmap shows **equidistant vertical lines** around the
  zero-Doppler column; mmWave Studio's capture does not.
- **Root cause (CONFIRMED, not a guess):** the pure-Python capture uses the **flashed studio_cli
  no-DSP firmware** (mmw_demo-derived), whose **chirp-to-chirp phase coherence is ~10× worse** than
  the **`rf_eval` firmware** mmWave Studio loads into RAM over SPI. Static-clutter energy that should
  sit on a single zero-Doppler line gets smeared into a broad Doppler "skirt" → visible as the lines.
- **It is NOT:** the visualization (proven by a controlled experiment), the config (cfg is byte-for-byte
  equivalent to skeleton.lua), packet loss (skirt is consistent on clean static frames, not bursty),
  or the scene/motion (proven by motion-controlled analysis).
- **The fix (this project):** replicate exactly what Studio does — drive the **xWR1843 over SPI via
  the TI mmWaveLink protocol**, **download the `rf_eval` `xwr18xx_radarss.bin` + `xwr18xx_masterss.bin`
  into RAM**, then send the profile/chirp/frame config (the skeleton.lua values) over SPI, then StartFrame.
  The DCA1000 raw-ADC-over-UDP path stays exactly as-is.
- **Why Ubuntu:** the SPI path uses FTDI; on Linux it's clean (gcc + libftd2xx, native USB, no MSVC,
  no Zadig). It's also the project's end goal.
- **Base to adapt:** `gaoweifan/pyRadar`'s `fpga_udp` C extension bundles TI's **mmWave-DFP-2G**
  (the real mmWaveLink lib + FTDI port + a NonOS example). It implements this SPI flow **for AWR2243**;
  we must **port it AWR2243 → xWR1843**. The mmWaveLink library itself is multi-device.

---

## 2. The system

**Hardware:** TI **AWR1843BOOST** (radar) + **DCA1000EVM** (capture card), joined by the 60-pin
connector (no carrier board). Two USB links:
- **XDS110** onboard debugger — `VID:PID 0451:BEF3` — exposes the **Application/User CLI UART**
  (Windows COM4 / Linux `/dev/ttyACM0` / macOS `/dev/cu.usbmodem*`) + an Aux UART. This is what the
  current pure-Python path uses (UART CLI @ 921600).
- **FT4232H** on the DCA1000 — `VID:PID 0451:FD03`, descriptor **"AR-DevPack-EVM-012"** — a 4-channel
  USB↔serial/SPI bridge. **This is the SPI master mmWave Studio uses to control the radar.** ← the
  port will use THIS, via FTDI D2XX.

**Network (DCA1000 raw ADC):** PC `192.168.33.30`, radar `192.168.33.180`, config UDP `4096`,
data UDP `4098`. Frame = 255 chirps × 4 RX × 2 TX × 2 IQ × 256 samples × 2 bytes = **2,088,960 B**, ~10 fps.

**Two Vomee codebases on this machine:**
- `Desktop\Vomee` — the **original** (PyQt5 GUI). Visualizes the Studio-triggered stream. Reference quality.
- `Documents\vomee` (THIS repo) — the **pure-Python** version (PySide6/QML GUI) + the UART trigger we built.
  The `--trigger` path is `core/mmwave_trigger.py` (UART `.cfg` @921600 + DCA1000 UDP control).

**Ultimate goal (user, verbatim intent):** eliminate mmWave Studio entirely, run the whole system on
**Ubuntu / Mac (Apple Silicon)**; data must be **"the same or nearly same quality and reliable,
ideally exactly the same"** as the Studio version. Windows is secondary.

---

## 3. The bug and the CONFIRMED root cause (with evidence)

### 3.1 What was compared
- Studio capture, recorded: `Desktop\Vomee\recordings\session_20260621_181053` (167 frames) — **no lines**.
- Pure-Python capture, recorded: `Documents\Vomee\recordings\session_20260621_181732` (138) and
  `session_20260621_194824` (144) — **user confirmed lines visible on screen**.

### 3.2 The decisive controlled experiment (user ran it)
Using the **same** old PyQt5 visualizer (`Desktop\Vomee\main.py --no-camera`):
- fed **Studio** capture → **no lines**
- fed **pure-Python** capture (radar triggered by `trigger_only.py`, then received by the old viz) → **lines**
- lines appear in pure-Python at **both SOP=001 and SOP=011**; never in Studio.

→ Only the **capture** changed; the visualization is identical. **The lines come from the capture path.**
(Earlier I wrongly concluded "display artifact" from averaged/linear-scale analysis — that was a
methodology error; this experiment overturned it.)

### 3.3 The motion-controlled data proof
Two pure-Python recordings of *different* scenes confound a naive average, so we selected only **static
frames** (low far-Doppler energy = no moving target) and measured the **near-zero-Doppler skirt/DC ratio**:

| Capture (firmware) | static-frame skirt/DC |
|---|---|
| **Studio** (rf_eval) | **0.0002** — razor-sharp zero-Doppler line, ±3–4 bins to noise floor |
| **PurePy 194824** (studio_cli) | **0.0017–0.0028** — skirt to ±15–20 bins |
| **PurePy 181732** (studio_cli) | **0.0017–0.0021** — identical skirt shape |

→ On a static scene (no motion to explain it), pure-Python smears **~10×** more clutter energy across
Doppler, **identically in both recordings** → systematic + reproducible. Not packet loss (would be bursty),
not scene, not config. This is **chirp-to-chirp phase incoherence (phase noise)** — an RF/firmware property.

### 3.4 Why it's the firmware
- The cfg was converted **line-by-line from `skeleton.lua`** and is equivalent (see §8 / `RD_STRIPES_DIAGNOSIS.md`).
- Same silicon, same profile timing, same chirp/frame config → the only remaining variable is the firmware.
- Likely mechanism: studio_cli runs the **heavyweight mmw_demo SDK framework** (MSS/DSS tasks, CLI,
  monitoring) whose background activity couples into the RF as phase noise; **`rf_eval` is a lean
  RF-only firmware** that keeps chirps phase-coherent. **There is no `.cfg` knob to fix this** — the
  artifact is broadband phase noise, not a clean periodic comb (verified). Hence the SPI/rf_eval port.

### 3.5 Forms it took (so you recognize it)
- RD doppler profile (dB): Studio = one sharp spike to −45 dB floor; PurePy = spike **+ a broad raised
  skirt** (~bins 90–165, −25 to −35 dB).
- High-contrast RD render: Studio = one clean central vertical line; PurePy = central line **+ multiple
  flanking vertical lines** around it.

---

## 4. Why the fix = "SPI + rf_eval firmware" (and why it equals Studio)

mmWave Studio does **not** run on-chip firmware to capture raw data. Its `skeleton.lua` (see §8):
1. Puts the device in SPI/dev mode (`SOPControl`), full-resets it.
2. **Downloads `xwr18xx_radarss.bin` (RadarSS/BSS) + `xwr18xx_masterss.bin` (MSS) into RAM over SPI**
   (`DownloadBSSFw`/`DownloadMSSFw`).
3. PowerOn / RfEnable / **RfInit** (full RF calibration), then ProfileConfig / ChirpConfig×2 / FrameConfig,
   DataPath/LVDS config — **all over SPI** via mmwavelink (`ar1.*` = thin wrappers over the mmWaveLink lib).
4. Configures the DCA1000 over Ethernet, then `StartFrame`.

The `rf_eval` firmware + RfInit is exactly what gives the phase-coherent chirps (the 0.0002 skirt).
**Replicating this sequence in our own code = byte/phase-identical data to Studio, with no Studio.**
This is the same architecture pyRadar uses for AWR2243 — we adapt it to xWR1843.

---

## 5. Decision & strategy

- **Path chosen:** SPI/rf_eval port, developed **on Ubuntu**.
- **C base:** `gaoweifan/pyRadar` → its `fpga_udp` pybind11 extension, which **bundles TI mmWave-DFP-2G**
  (`fpga_udp/src/mmwaveDFP_2G/`): the full **mmWaveLink** protocol lib (`ti/control/mmwavelink/src/*.c`),
  the **FTDI port** (`FTDILib/SourceCode/mmwl_port_ftdi.cpp`, uses **D2XX**), and a **NonOS example**
  (`ti/example/mmWaveLink_SingleChip_NonOS_Example/`) that orchestrates init/firmware-download/config/start.
- **The work = port the NonOS example flow from AWR2243 → xWR1843** (device type, 2-part firmware download
  into RAM, follow skeleton.lua's sequence), build the extension on Linux, and wire it into Vomee's trigger.
- **Keep unchanged:** the DCA1000 UDP raw-capture path (`core/mmwave_capture.py`), the FFT/processing
  (`core/mmwave_processor.py`), the GUI. Only the *radar control* changes (SPI instead of UART CLI).

---

## 6. Inventory — exact paths, devices, configs

### rf_eval firmware — NOW COMMITTED IN THIS REPO ✅
- **`mmwave_pure_python/firmware/xwr18xx_radarss.bin`** — **35,728 B** (RadarSS/BSS)
- **`mmwave_pure_python/firmware/xwr18xx_masterss.bin`** — **52,904 B** (MSS)
- Provenance in `mmwave_pure_python/firmware/README.md`. Originals also at the Windows install
  `C:\ti\mmwave_studio_02_01_01_00\rf_eval_firmware\{radarss,masterss}\`; ship with TI mmWave-DFP/SDK.
- They travel with the repo → the Ubuntu clone already has them, no manual copy needed.

### FTDI SPI master (the DCA1000's FT4232H)
- `VID:PID 0451:FD03`, descriptor **"AR-DevPack-EVM-012"**, 4 channels A/B/C/D.
- pyRadar's FTDI layer already recognizes **"AR-DevPack-EVM-012 A/B/C/D"** descriptors
  (`mmwl_port_ftdi.cpp:~322`): **A=SPI, B=Host-IRQ, C=BoardControl(nRESET), D=GenericGPIO(SOP)**.
  Studio uses this same FT4232H the same way → the FTDI/SOP/reset layer is **likely reusable as-is**
  (see §7.4; the porting agent flagged it as 2243-specific, but that's for the standalone AWR2243
  BoosterPack — our DCA1000 FT4232H is the device Studio drives, and the descriptors match).

### Network / DCA1000 — unchanged
- `cf.json` (DCA config): `lvdsMode 2` (2-lane), `dataFormatMode 3` (16-bit), `packetDelay_us 5`,
  raw / LVDSCapture / ethernetStream. PC .30, radar .180, ports 4096/4098.
- Repo path: `mmwave_pure_python/configFiles/cf.json`.

### Current pure-Python radar control (the thing we're replacing for control)
- `core/mmwave_trigger.py` — `DCA1000` (UDP control, **keep**) + `RadarUART` (UART CLI, **replace with SPI**)
  + `trigger()` (sequence). `trigger_only.py` (repo root) triggers + exits leaving the radar streaming.
- Current cfg: `mmwave_pure_python/studio_cli/src/profiles/profile_vomee_256x255_cont.cfg` (the studio_cli
  CLI cfg — only relevant to the OLD firmware path).

### SOP modes (user's board: slide switch, LEFT=ON / RIGHT=OFF)
- Functional `001` (左右右) — boots flashed firmware (current pure-Python uses this).
- Flashing `101` (左右左) — UniFlash.
- Debug/SPI-dev `011` (左左右) — mmWave Studio raw-capture / SPI dev mode.
- For the rf_eval-over-SPI path, the device must be in the SPI-download mode Studio uses. Studio sets SOP
  **in software over the FTDI** (`ar1.SOPControl(2)`); pyRadar's FTDI layer drives SOP on channel D
  (SOP4 = SPI mode). On our board you may also need the physical switch in the right position. **Resolve
  empirically at Stage C** (the user observed both 001 and 011 boot *something* that answers; for SPI
  firmware *download* the device must accept SPI boot, not run flash firmware).

### pyRadar (re-clone on Ubuntu)
- `git clone https://github.com/gaoweifan/pyRadar.git`
- Key tree: `fpga_udp/` (the C extension to build), `fpga_udp/src/mmwaveDFP_2G/` (the TI DFP),
  `configFiles/AWR2243_mmwaveconfig.txt` (the SPI-path config-file format).

---

## 7. Detailed technical map of pyRadar / mmWave-DFP SPI control

> Source: read-only analysis of `C:\Users\Chuang Yu\Documents\pyRadar` (re-clone on Ubuntu; same code).
> File refs are `fpga_udp/src/...`. This is the template we adapt.

### 7.1 What it provides + build
- `fpga_udp/setup.py` compiles (pybind11, C++17): `src/main.cpp` + the NonOS example `*.c/*.cpp` +
  **all** `mmwaveDFP_2G/ti/control/mmwavelink/src/*.c` + `FTDILib/SourceCode/mmwl_port_ftdi.cpp` +
  `pevents` + a serial lib. Links **`ftd2xx`** (lib in `src/FTDI_D2XX/<system>/<machine>`, headers in
  `src/FTDI_D2XX/<system>`). Firmware is `#include`d as a C header array, not a runtime file.
- **Build deps (Linux):** `python3-dev`, `pybind11`, a C/C++ toolchain, and the **FTDI D2XX `.so`**
  (libftd2xx, install per pyRadar README §Software/Linux). Then `sudo python3 -m pip install ./fpga_udp`.

### 7.2 The AWR2243 SPI control flow (the template to mirror)
Python bindings in `main.cpp` (PYBIND11_MODULE ~L463) are thin lambdas (deviceMap=`RL_DEVICE_MAP_CASCADED_1`=0x01)
forwarding to `MMWL_App_*` in `mmw_example_nonos.cpp`:

| Python | C wrapper | mmwavelink API |
|---|---|---|
| `AWR2243_firmwareDownload` | `MMWL_App_firmwareDownload` (3700) | SOP4→reset→`rlDevicePowerOn`→`MMWL_firmwareDownload`→`rlDeviceFileDownload`→`rlDevicePowerOff` |
| `AWR2243_init(cfg)` | `MMWL_App_init(...,downloadFw=false)` (3816) | full power-up+config (below) |
| `AWR2243_setFrameCfg(n)` | `MMWL_App_setFrameCfg`→`MMWL_frameConfig` (2818) | `rlSetFrameConfig` |
| `AWR2243_sensorStart` | `MMWL_App_startSensor`→`MMWL_sensorStart` (3248) | `rlFrameStartStop(1)` |
| `AWR2243_sensorStop` | `MMWL_App_stopSensor`→`MMWL_sensorStop` (3285) | `rlFrameStartStop(0)` |
| `AWR2243_poweroff` | `MMWL_App_poweroff`→`MMWL_powerOff` (3569) | `rlDevicePowerOff` |

`MMWL_App_init` sequence (mmw_example_nonos.cpp:3816): openConfigFile → **SOP4** (`MMWL_SOPControl(map,4)`)
→ **reset** (`MMWL_ResetDevice`) → **PowerOn** (`MMWL_powerOnMaster`→`rlDevicePowerOn`, sets callbacks +
`clientCtx.arDevType` + `RL_PLATFORM_HOST`) → getMssVersion → *(optional FW download)* → setDeviceCrcType →
**RfEnable** (`rlDeviceRfStart`) → basic cfg → **RfInit** (`rlRfInit`) → progFilt → **ProfileConfig**
(`rlSetProfileConfig`) → **ChirpConfig** (`rlSetChirpConfig`) → **DataPath** (`rlDeviceSetDataPathConfig`) →
hsiClock → hsiLane. This mirrors skeleton.lua almost 1:1 (§8).

Firmware download: `MMWL_firmwareDownload`→`MMWL_fileDownload`→`rlDeviceFileDownload(map,&chunk,rem)`,
chunked (first 224 B, then 232 B), filetype tag `MMWL_FILETYPE_META_IMG=4`. **Source = embedded C array**
`metaImage[]` from `#include "xwr22xx_metaImage.h"`; runtime-appends a CRC32. It is **ONE combined
metaImage (2243 style)**.

### 7.3 What is 2243-specific → MUST change for xWR1843
| Item | Where | Change for 1843 |
|---|---|---|
| Device type | `mmw_example_nonos.cpp:793` `arDevType = RL_AR_DEVICETYPE_22XX` | → `RL_AR_DEVICETYPE_18XX` (=0x3, `mmwavelink.h:1010`) |
| Firmware include | `:69` `#include "xwr22xx_metaImage.h"` | → load **xwr18xx_radarss.bin + xwr18xx_masterss.bin** (TWO parts, into **RAM**), not a combined flash metaImage. See §10-R1. |
| FW chunk sizes | `:75-77` (224/232) | DFP-version specific; verify against xwr18xx DFP / Studio. |
| ES1.0/ES1.1 branch | `:99-100, 882-893, 3752-3760, 3890` | AWR2243 silicon-rev hack — drop/replace for 18xx. |
| SwapResetAndPowerOn magic regs | `:305-385` (`rlDeviceSetInternalConf(0xFFFFFF20,...)`) | AWR2243-ES1.0-only — drop for 18xx. |
| **APLL/Synth trims** | `:3619-3623` (hard-coded `synthIcpTrim`, `apllIcpTrim`, …) | **2243 analog trims — likely wrong for 18xx. skeleton.lua does NOT set manual trims (relies on RfInit). Prefer: skip manual trims, let RfInit calibrate.** |
| Platform | `:792` `RL_PLATFORM_HOST` | keep HOST (we ARE the external host over SPI) ✅ |

### 7.4 FTDI / SOP / reset (`mmwl_port_ftdi.cpp`) — likely reusable for our DCA1000
- Opens FTDI **by description string**, matching A=SPI / B=IRQ / C=BoardControl / D=GenericGPIO. Already
  lists **"AR-DevPack-EVM-012 A/B/C/D"** (our device) as well as "AR-MB-EVM-1_FD01 …".
- SPI = channel A, **MPSSE @ 10 MHz** (60 MHz/((2+1)*2)), CPOL0/CPHA0. Pins A: b0 CLK, b1 MOSI, b2 MISO, b3 CS.
- **SOP** bit-banged on **channel D** (D2/D3/D4); **SOP4 (SPI/functional) = D2=0,D3=0,D4=1**.
- **nRESET** on **channel C**.
- Linux-only `FT_SetVIDPID(0x0451,0xfd03)` is already present (needed for libftd2xx enumeration).
- ⚠️ The agent flagged this as "2243 EVM specific," but that warning assumed a standalone xWR1843BOOST
  using XDS110. **Our setup is the Studio raw-capture setup: the DCA1000's FT4232H drives the radar's
  SPI/SOP/reset over the 60-pin connector** — the same device Studio uses — and the descriptors match.
  So this layer should work; **verify at Stage C.**

### 7.5 Config mapping (skeleton.lua → AWR2243_mmwaveconfig.txt encoded fields)
The SPI path reads config from `mmwaveconfig.txt` (parsed by `mmw_config.c`, key=value;), then calls
`rlSet*Config`. All our numbers map cleanly (encoded units):
- start-freq GHz = `startFreqConst * 53.6441803/1e9`; slope MHz/µs = `freqSlopeConst * 48.2797623/1000`;
  times ×10 ns; periodicity ×5 ns; rxGain in dB code.

| skeleton.lua target | mmwaveconfig.txt field | encoded value |
|---|---|---|
| 77 GHz | `startFreqConst` | `1435384035` |
| idle 20 µs | `idleTimeConst` | `2000` |
| ADC start 6 µs | `adcStartTimeConst` | `600` |
| ramp 60 µs | `rampEndTime` | `6000` |
| slope 65.998 MHz/µs | `freqSlopeConst` | `1367` |
| 256 samples | `numAdcSamples` | `256` |
| 4800 ksps | `digOutSampleRate` | `4800` |
| rxGain 30 dB | `rxGain` | `30` |
| TX0+TX2 (2 TX TDM) | `channelTx` | `5` (b0+b2) |
| 4 RX | `channelRx` | `15` |
| 255 loops | `loopCount` | `255` |
| 100 ms period | `periodicity` | `20000000` (×5 ns) |
| chirp0=TX0, chirp1=TX2 | two chirp blocks `txEnable=1` then `txEnable=4`; `chirpStartIdxFCF=0`,`chirpEndIdxFCF=1` | — |
| ADC 16-bit complex | `adcBits=2`, `adcFormat=2` | — |
| LVDS 2-lane (match cf.json lvdsMode 2) | `intfSel=1` (LVDS); lane/laneEn per 2-lane | verify vs cf.json |

> Build the xWR1843 config file from these; do **not** copy the AWR2243 defaults (700/700/2500/2071/15000).

---

## 8. skeleton.lua = the exact xWR1843 SPI/mmwavelink reference

**`mmwave_pure_python/reference/lua/skeleton.lua`** (committed in this repo; original at
`F:\mmwave_cam2.11\lua\skeleton.lua` on Windows) is the **authoritative sequence for OUR device**. Each
`ar1.*` is a thin wrapper over mmWaveLink. The port should follow THIS order (not the 2243 example's
quirks). (Two variants also copied: `clothes_mmw_start_trigger.lua`, `mmw_start_cam.lua`.)

```
FullReset → SOPControl(2) → Connect(921600) → frequencyBandSelection("77G")
→ SelectChipVersion("XWR1843")
→ DownloadBSSFw(xwr18xx_radarss.bin)      # RAM download, part 1
→ DownloadMSSFw(xwr18xx_masterss.bin)     # RAM download, part 2
→ PowerOn(0,1000,0,0) → RfEnable
→ ChanNAdcConfig(TX0+TX2, RX0-3, 16-bit)  # rlSetChannelConfig + rlSetAdcOutConfig
→ LPModConfig(0,0)                         # rlSetLowPowerModeConfig
→ RfInit                                   # rlRfInit  (THE calibration that gives phase coherence)
→ DataPathConfig(513,1216644097,0) → LvdsClkConfig(1,1) → LVDSLaneConfig(0,1,1,0,0,1,0,0)
→ ProfileConfig(0,77,20,6,60,...,65.998,0,256,4800,0,0,30)   # rlSetProfileConfig
→ ChirpConfig(0,0,0,...,TX0) → ChirpConfig(1,1,0,...,TX2)     # rlSetChirpConfig ×2
→ FrameConfig(0,1,0,255,100,0,0,1)                            # rlSetFrameConfig (255 loops, infinite frames, 100ms)
→ [DCA1000 over Ethernet: EthInit / Mode(lvds2,fmt3) / PacketDelay(5)]   # we already do this via UDP
→ StartFrame                              # rlFrameStartStop(1)
```
Full line-by-line lua↔cfg mapping (and the "constructed/unmappable" notes) is in
`mmwave_pure_python/RD_STRIPES_DIAGNOSIS.md` §8 table.

---

## 9. The Ubuntu plan (staged, with verification gates — don't skip gates)

### Stage A — Ubuntu + hardware bring-up
- Install Ubuntu (22.04/24.04). `sudo apt install build-essential python3-dev git`. Recreate the Python
  env (the project uses conda `pose` on Mac; on Ubuntu make a venv/conda with: numpy, torch (CUDA if NVIDIA),
  PySide6, pyserial, opencv, the ViTPose deps). See `mmwave_pure_python/SETUP.md`.
- Install **FTDI D2XX `.so`** (libftd2xx) per pyRadar README (copy `ftd2xx.h`,`WinTypes.h` to
  `/usr/local/include`, `libftd2xx.so.*` to `/usr/local/lib`, `ldconfig`). udev rule so non-root can open
  `0451:fd03` (or run the SPI step with sudo — pyRadar notes Linux SPI needs root).
- Set PC NIC to static `192.168.33.30`. Connect both USBs (XDS110 + DCA1000 FT4232H) + 5V + RJ45.
- Copy the two `xwr18xx_*.bin` firmware files onto the machine (§6) → e.g. `mmwave_pure_python/firmware/`.
- **Gate A:** `lsusb` shows `0451:fd03` (FT4232H) and `0451:bef3` (XDS110); `ping 192.168.33.180` after a
  DCA1000 reset; the DCA1000 UDP control still works (run the existing `core/mmwave_trigger.py` DCA1000
  sys_alive_check / read_fpga_version — these are pure-UDP, no SPI).

### Stage B — build the SPI extension
- `git clone https://github.com/gaoweifan/pyRadar.git`; `python3 -m pip install ./pyRadar/fpga_udp`.
- **Gate B:** `python3 -c "import fpga_udp; print(dir(fpga_udp))"` lists `AWR2243_*`. (Build succeeds with
  libftd2xx present.)

### Stage C — verify the FTDI→SPI link to OUR xWR1843 (DE-RISK; do before porting)
- With the bundled (2243) code, attempt the lowest-level handshake against our hardware to confirm the
  FT4232H SPI reaches the 1843: e.g. SOP4 + reset + `rlDevicePowerOn` and read a version
  (`rlDeviceGetMssVersion`). The 2243 firmware download will be wrong for the 1843, but PowerOn/SPI-comms
  either ACK or not — that tells us the SPI link + FTDI channel/SOP/reset wiring works on our board.
- If pyRadar's `AWR2243_*` can't be coerced to "just power on + read version," write a tiny C/pybind shim
  calling `MMWL_SOPControl`/`MMWL_ResetDevice`/`rlDevicePowerOn`/`rlDeviceGetMssVersion`.
- **Gate C (critical):** SPI comms to the 1843 succeed (a version read returns, or a defined error that
  proves bytes flowed). If this fails, resolve FTDI descriptor/channel/SOP/reset/SOP-switch before porting.
  **This is the make-or-break gate** — everything after assumes the SPI link works.

### Stage D — port firmware download 2243 → xwr18xx (RAM, 2-part)
- Replace the embedded `xwr22xx_metaImage.h` flow with **two RAM downloads**: `xwr18xx_radarss.bin` then
  `xwr18xx_masterss.bin`, via `rlDeviceFileDownload` (mirror skeleton.lua `DownloadBSSFw`/`DownloadMSSFw`).
  Set `arDevType = RL_AR_DEVICETYPE_18XX`. Drop the ES1.0/ES1.1 + SwapResetAndPowerOn 2243 hacks. Skip the
  hard-coded APLL/synth trims (let `rlRfInit` calibrate).
- Reference TI's **xwr18xx mmWave-DFP host example** if available (the 2G DFP is 2243-only; the main
  mmWave-DFP / mmWave Studio's mmwavelink usage is the 18xx reference). mmWave Studio's `ar1.dll` is the
  proven 18xx implementation — skeleton.lua is its script form.
- **Gate D:** after download + PowerOn + RfEnable, `rlDeviceGetMssVersion`/RadarSS version reads back the
  loaded rf_eval versions (matching what Studio prints), and `rlRfInit` returns success.

### Stage E — device config + start (follow skeleton.lua / §7.5)
- Build the xwr18xx config (channel TX0+TX2/4RX, ADC 16-bit complex, profile 77/20/6/60/65.998/256/4800/30,
  2 chirps TDM, frame 255 loops / infinite / 100 ms, LVDS 2-lane to match cf.json) and send via the
  `rlSet*Config` calls. Configure DCA1000 over UDP (reuse `core/mmwave_trigger.py:DCA1000`). `StartFrame`.
- **Gate E:** raw ADC floods UDP :4098 at ~10 fps, frame = 2,088,960 B (use the existing
  `core/mmwave_capture.py` to receive a few frames).

### Stage F — integrate into Vomee + verify the FIX
- Add an SPI trigger path: either a new `core/mmwave_trigger_spi.py` (mirrors `trigger()` but uses the
  fpga_udp SPI calls instead of `RadarUART`), or extend `trigger()` with a `backend='spi'|'uart'` switch.
  Keep `DCA1000` UDP control + `core/mmwave_capture.py` + `core/mmwave_processor.py` unchanged. Wire into
  `main.py --trigger` (config `MMWAVE_TRIGGER`).
- **Gate F (the whole point):** record a **static scene** and re-run the motion-controlled check
  (`scratchpad/static_compare.py`, §11). **Success = near-zero-Doppler skirt/DC ≈ 0.0002 like Studio
  (not ~0.0017), and no vertical lines in the RD.** Compare against the Studio reference recording.

---

## 10. Key risks & open questions (resolve with hardware + TI docs)

- **R1 — RAM vs flash, 2-part vs metaImage:** AWR2243 flashes one combined metaImage to serial flash;
  xWR1843 rf_eval is **downloaded to RAM in two parts (radarss, masterss)** each power-up (what Studio does).
  Confirm the exact `rlDeviceFileDownload` flags/sequence for RAM 2-part download (TI mmWaveLink API guide
  + mmWave Studio behavior). This is the single biggest unknown.
- **R2 — SOP / boot mode:** which SOP lets the 1843 accept SPI firmware download (vs running flashed
  firmware). Studio uses `SOPControl(2)`/SOP4 over FTDI. Determine the right physical switch + software SOP
  on our board at Gate C.
- **R3 — FTDI layer fit:** confirm channel A/B/C/D mapping + descriptor match for our exact FT4232H at
  Gate C (expected to work; see §7.4).
- **R4 — Linux libftd2xx vs the VCP driver:** on Linux the `ftdi_sio` kernel module may grab the FT4232H;
  may need to unbind it (or blacklist for these interfaces) so D2XX can open it. Classic Linux-FTDI step.
- **R5 — APLL/synth trims:** ensure we are NOT applying 2243 analog trims to the 1843 (§7.3). Rely on RfInit.
- **R6 — current pure-Python (UART) path can coexist** as a fallback; don't delete it until SPI is proven.

---

## 11. Re-verify the diagnosis (scripts; Windows scratchpad — re-run on Ubuntu against the recordings)
Analysis scripts (were in the Windows scratchpad; logic is portable — re-create from this doc if needed):
- **`static_compare.py`** — THE decisive one: motion-controlled near-Doppler skirt/DC. Studio≈0.0002 vs
  PurePy≈0.0017–0.0028.
- `doppler_comb.py` / `comb_period.py` — doppler profile in dB; shows the broad skirt (not a clean comb).
- `per_frame_skirt.py` — shows the skirt is consistent (not bursty → not packet loss).
- `hi_contrast.py` — renders the actual vertical lines (Studio 1 line vs PurePy multiple).
Recordings to compare: Studio `Desktop\Vomee\recordings\session_20260621_181053`; pure-Python
`Documents\Vomee\recordings\session_20260621_{181732,194824}`. **Copy these recordings to Ubuntu** if you
want to re-verify (or just trust §3 — it's settled).

Frame reshape (shared by both versions, for any analysis):
`int16 → (-1,255,2,4,128,2,2) → transpose(0,1,2,3,4,6,5) → (-1,255,2,4,256,2) → I+jQ → [:, :,0:2] →
(255,8,256) → pad VA→256 → fftn → fftshift(0,1)`; RD = `log10(|.|².sum(VA)).T` (256 range × 255 doppler).

---

## 12. What NOT to re-investigate (settled)
- "Is it the display?" — **No.** Controlled experiment proved capture. (My earlier display fix in
  `gui/qml_bridge.py` was based on the wrong hypothesis; it's a harmless HiDPI-rendering improvement but
  did not fix the lines. Revert it if you want a clean tree.)
- "Is it the config / cfg?" — **No.** Byte-equivalent to skeleton.lua (RD_STRIPES_DIAGNOSIS.md §8).
- "Is it packet loss?" — **No** (separate quality issue; not the skirt — consistent on static frames).
- "Is there a cheap `.cfg` fix?" — **No.** Broadband phase noise, not a periodic comb; no firmware knob.
- "Is it the SOP (001 vs 011)?" — **No.** Lines appear at both; firmware is the variable.

---

### Companion docs in this repo
- `mmwave_pure_python/RD_STRIPES_DIAGNOSIS.md` — the full root-cause writeup + line-by-line lua↔cfg table.
- `mmwave_pure_python/SETUP.md` — cross-platform environment setup.
- `mmwave_pure_python/LAB_NOTES.md` — the original (no-Studio) capture investigation log.
- `README.md` — project overview + AI-agent handover.

*Authored 2026-06-21 from the Windows investigation session, for continuation on Ubuntu.*

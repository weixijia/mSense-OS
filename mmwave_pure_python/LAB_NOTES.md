# Lab Notes — Pure-Python mmWave Triggering (no mmWave Studio)

> Goal: replace the mmWave Studio + "kill DCA1000 process" workflow so that
> **everything runs from Python** — configure the IWR1843, configure the
> DCA1000, start chirping, and stream raw ADC into Vomee's `main.py`.

Master chronological log. Each candidate repo gets a section in `CANDIDATES.md`.
Keep this file updated after **every** step so context is never lost.

---

## 0. Hardware & environment baseline (confirmed 2026-06-17)

| Item | Value |
|------|-------|
| Radar | TI **AWR1843BOOST** (red board), 3TX/4RX (Vomee uses 2TX). Same xwr18xx silicon family as IWR1843 → mmw_demo/.cfg/DCA1000 all identical. |
| Capture card | **DCA1000EVM** (green board), connected via 60-pin HD connector. NO DevPack/ICBOOST carrier. |
| Control FTDI | the "AR-DevPack-EVM-012" FT4232H (COM6-9) is **on the DCA1000EVM** — Studio uses it for SPI/SOP/reset of the radar. |
| Boot mode | AWR1843BOOST uses **SOP jumpers** (SOP0/SOP1/SOP2, "Figure 13" in EVM UG) + NRST button SW2. Functional=SOP0 only (001); Flashing=SOP0+SOP2 (101); Studio raw-capture uses debug 011 / software SOPControl(2). |
| Chirp params (config.py) | 255 chirps, 256 samples, 2 TX, 4 RX, IQ, int16 |
| Frame rate | 10 Hz (periodicity = 100 ms) |
| Data path | DCA1000 → **UDP raw ADC** → PC `192.168.33.30:4098`, cfg port `4096` |
| Radar data IP | `192.168.33.180` |
| PC NIC for DCA1000 | "Ethernet 4" = `192.168.33.30` (confirmed up) |

### USB control interfaces (from `Get-PnpDevice -Class Ports`)
| Port | Device | VID/PID | Role |
|------|--------|---------|------|
| COM4 | XDS110 Class **Application/User UART** | 0451:BEF3 | radar **CLI UART** (SDK demo cfg port) |
| COM5 | XDS110 Class Auxiliary Data Port | 0451:BEF3 | aux/data UART |
| COM6–9 | **AR-DevPack-EVM-012** (FTDI FT4232H) | 0451:FD03 | **mmWave Studio control** — SPI/mmwavelink + SOP/reset |

### Toolchain
- Python 3.10.19, numpy 2.2.6
- Installed: pyserial 3.5, pyftdi 0.57.2
- gh CLI: authed as `weixijia` (scopes: repo, workflow, gist, read:org)

---

## 1. The core problem — what mmWave Studio actually does

Vomee's `core/mmwave_capture.py` is **receive-only**: it binds a UDP socket and
assembles frames. It never *triggers* anything. Today mmWave Studio performs the
three jobs Vomee can't:

1. **SOP / reset / firmware load** — via the FTDI (AR-DevPack), put the radar in
   the right boot mode and download the mmWave Studio meta-image into RAM.
2. **RF / chirp config** — send the profile/chirp/frame config to the IWR1843 via
   **mmwavelink messages over SPI** (through the FTDI). *This is the hard part.*
3. **DCA1000 config + start** — over Ethernet UDP (port 4096): configure the FPGA,
   set up the data path, and start record/streaming.
4. `sensorStart` → radar chirps → DCA1000 streams raw ADC over UDP.

The "kill the DCA1000 process" trick just releases mmWave Studio's hold on the
UDP stream so Vomee can bind the socket while the radar keeps chirping.

### Two strategic paths to "pure Python"
- **Path A — replicate mmWave Studio firmware mode in Python.** Drive mmwavelink
  over SPI through the FTDI (pyftdi) + DCA1000 UDP. No re-flash, keeps the exact
  current RF behavior, but mmwavelink-over-SPI is complex.
- **Path B — flash SDK demo firmware once, then CLI-UART control.** Use UniFlash
  (one-time GUI) to put mmWave SDK firmware that supports LVDS→DCA1000 streaming
  on the radar. Then Python = pyserial `.cfg` + `sensorStart` on COM4 + DCA1000
  UDP config. Well-trodden, clean, but RF config differs from Studio's.

Both need the **DCA1000 UDP control** piece, which is the same in either path and
is well-supported in open source (OpenRadar etc.).

---

## 2. Research log

### 2026-06-17 — GitHub sweep (gh CLI, authed as weixijia)
Queries: "DCA1000 python/EVM", "IWR1843 capture", "mmwave studio python",
"mmwavelink", "awr1843 dca1000", "OpenRadar", etc. Scored table → CANDIDATES.md.

Winner: **gaoweifan/pyRadar** (172★, exact IWR1843+DCA1000 board). Cloned all of
pyRadar, PreSenseRadar/OpenRadar, EsonJohn/mmWave_script into `downloads/`.

### Decisive code reading (pyRadar)
`captureAll.py` xWR1843 flow = reset → UART cfg → DCA1000 UDP cfg → stream_start
→ UART sensorStart → receive. The **control half is 100% pure Python**:

- **`mmwave/dataloader/adc.py` → `DCA1000` class** — DCA1000 FPGA control over UDP.
  - `__init__` defaults: `static_ip=192.168.33.30, adc_ip=192.168.33.180,
    data_port=4098, config_port=4096` → **EXACT match to Vomee config.py**.
  - `_send_command`: UDP packet = `header(a55a)+cmd+len+body+footer(aaee)` to
    `(192.168.33.180, 4096)`, waits for reply.
  - Command codes: RESET_FPGA `0100`, RESET_AR_DEV `0200`, CONFIG_FPGA_GEN `0300`,
    RECORD_START `0500`, RECORD_STOP `0600`, SYSTEM_CONNECT `0900`,
    CONFIG_PACKET_DATA `0b00`, READ_FPGA_VERSION `0e00`.
  - Methods: `reset_radar/reset_fpga/sys_alive_check/config_fpga(cf.json)/
    config_record(cf.json)/stream_start/stream_stop/configure(json,cfg)`.
- **`mmwave/dataloader/radars.py` → `TI` class** — radar UART control (pyserial).
  - `serial.Serial(cli_loc='COM4', 115200)`; `_configure_radar` writes each cfg
    line + `\n`; `setFrameCfg(n)`; `startSensor` → `sensorStart\n`; `stopSensor`.
  - The receive half (`fastRead_in_Cpp`) uses the **C/pybind11 `fpga_udp`** ext —
    NOT needed: Vomee's `mmwave_capture.py` already receives + parses this stream.

### Toolchain constraints found
- **No MSVC / VS Build Tools** (vswhere absent) → cannot compile pyRadar `fpga_udp`
  C extension as-is. `fpga_udp` not on PyPI. ⇒ avoid the C path entirely.
- conda (anaconda3) present. pyserial 3.5 / pyftdi 0.57.2 installed.

### Conclusion of research phase
A pure-Python trigger needs only: (1) pyserial UART cfg+sensorStart on COM4,
(2) DCA1000 UDP control commands on port 4096 — both available verbatim from
pyRadar/OpenRadar with zero compilation. Vomee already does the receive+display.
The *only* non-software blocker is the radar firmware/boot mode (see §1 path B).

### 2026-06-17 — Full reverse-engineering of CURRENT solution (user request)
Read `F:\mmwave_cam2.11\lua\*.lua` + legacy python. Full write-up → **CURRENT_SOLUTION.md**.
Headlines:
- mmWave Studio = the entire per-session trigger, done over **SPI/FTDI** (DownloadBSSFw
  + DownloadMSSFw = rf_eval firmware into RAM, then mmwavelink RF config, StartFrame).
- `FrameConfig(...,0,255,100,...)` → **NumFrames=0 = infinite** → why the stream persists.
- DCA1000 config (`CaptureCardConfig_*`) maps 1:1 to pure-python DCA1000 UDP commands.
- Data is **header-less raw ADC** (raw_decode.py reshape) — replacement must match exactly.

### VERDICT / recommendation
- **Path B (flash mmw_demo + UART + DCA1000 UDP, pure python)** is the realistic route.
  Proven on this exact board by pyRadar. One-time cost: flash firmware + set SOP=001.
- **Path A (reimplement Studio's SPI/mmwavelink in python)** = rebuilding mmWave Studio;
  pyRadar only does it for AWR2243 (a pure RF front-end), not the xWR1843. Not recommended.
- Equivalent `.cfg` translated from skeleton.lua ProfileConfig → see CURRENT_SOLUTION.md.

## 3. Test log

> Live hardware tests. **Blocked on a hardware decision** (SOP mode + firmware) —
> cannot test the trigger without disrupting the current mmWave Studio stream and
> physically re-jumpering the IWR1843BOOST.
> ONE non-destructive test is possible now: read-only DCA1000 FPGA version/alive
> query on UDP 4096 (validates the pure-python DCA1000 control half live). Pending OK.

### T1 — DCA1000 control, live, NON-DESTRUCTIVE ✅ (2026-06-17, Windows)
Ran `tools/probe_dca1000.py` (pure python, `tools/dca1000_control.py`) while the
mmWave-Studio-triggered stream was live. Read-only queries on UDP 4096:
```
SYSTEM_CONNECT     -> 'success'
READ_FPGA_VERSION  -> 'FPGA Version: 2.9 [Record]'
```
**Result: the pure-Python DCA1000 control half WORKS against the live FPGA.** No C
extension, no mmWave Studio. This is the capture-card half of Path B, proven.
(FPGA fw 2.9, Record mode = stock DCA1000.) Did not disturb capture (read-only).

### Remaining to test (needs radar in functional mode)
- T2 UART handshake on COM4 (needs SOP=001 + mmw_demo firmware).
- T3 full trigger (cfg + DCA config + sensorStart) → header-less raw ADC.
- T4 Vomee integration with Studio OFF.

## 4. Deliverables built (pure Python, Ubuntu-portable, zero C deps)
| File | Purpose | Status |
|------|---------|--------|
| `tools/dca1000_control.py` | DCA1000 FPGA control over UDP 4096 | ✅ proven live (T1) |
| `tools/probe_dca1000.py` | read-only FPGA alive/version probe | ✅ ran clean |
| `tools/radar_uart.py` | IWR1843 CLI-UART control (pyserial) | built, compiles; needs T2 |
| `tools/probe_uart.py` | read-only COM4 mmw_demo banner check | built; run after SOP=001 |
| `tools/trigger_all.py` | full trigger: reset→UART cfg→DCA cfg→start | built, compiles; needs T3 |
| `configFiles/vomee_1843.cfg` | RF profile = 1:1 translation of skeleton.lua | built |
| `configFiles/cf.json` | DCA1000 cfg (lvdsMode=2, 5µs delay) | built |

**Blocking checkpoint:** radar is in Studio mode (rf_eval fw in RAM). Path B needs
the board physically in functional mode (SOP0) running flashed mmw_demo. That's the
only step I can't perform from code. (Setup + re-flash steps: see SETUP.md §9.)

## 5. LIVE HARDWARE RESULTS (2026-06-17, AWR1843BOOST functional mode)
Hardware confirmed: AWR1843BOOST + DCA1000, SOP slide switch (LEFT=ON). User flipped
SOP1→OFF (001 functional). **mmw_demo SDK 03.06.00.00 already flashed** — no UniFlash
needed.

### T2 — UART handshake ✅
`probe_uart.py COM4` → `mmwDemo:/>`, version banner (xWR18xx, SDK 3.6, AWR18xx ES2.0).

### T3 — full pure-Python trigger ✅ (pipeline) / ⚠️ (heavy config)
`trigger_all.py` sends the whole cfg over UART (all `Done`), config_fpga/record/
stream_start all return 0, sensorStart issued. **All pure Python, zero mmWave Studio.**
- **64 loops (`vomee_1843_light.cfg`): WORKS.** `verify_stream` saw 10,803 pkts,
  **0% loss**, 1466 B payloads, ~10 fps. Full chain trigger→DCA1000→UDP proven.
- **128 & 255 loops: mmw_demo HANGS after "Init Calibration Status = 0x1ffe"** (CLI
  goes silent, no UDP data). Recovered every time via `DCA1000().reset_radar()`.

### KEY FINDING — stock mmw_demo can't make the production (256×255) data
mmw_demo reserves a fixed region for the range-doppler detection matrix
(`numRangeBins × numDopplerBins × 2 B`). 256×64×2 = **32 KB (fits)**; 256×128 = 64 KB
(overflows). So with 256 range bins it's capped at ~64 doppler bins. Studio's raw-
capture path does NO on-chip processing, so it streams 256×255 fine — mmw_demo can't.

⇒ Pure-Python via stock mmw_demo works but only for configs that fit (≤~64 doppler @
256 range). For EXACT 255-doppler data without Studio we need either a custom no-DSP
capture firmware, or Path A (mmwavelink-over-SPI via the DCA1000 FTDI).

### T4 — Vomee integration + full-path validation ✅ (Track 1 DONE)
Added `core/mmwave_trigger.py` (self-contained DCA1000+UART trigger), `config.py`
`MMWAVE_TRIGGER`, and `main.py --trigger/--trigger-cfg/--trigger-com` (+ sensorStop on
exit). The trigger runs before MmWaveProcessor/MmWaveCapture and auto-sets
`ADC_PARAMS['chirps']` from the cfg's frameCfg numLoops (64↔255 stays consistent).

`validate_pipeline.py` (headless, Vomee's own MmWaveCapture+MmWaveProcessor on the
live 64-loop stream):
```
BYTES_IN_FRAME=524,288 ; frames assembled ; RA(256,256) RD(256,64) DA(256,64)
RA[min=0 max=1 std=0.14] finite=True  -> real structure, layout matches Studio
```
**Pure-Python trigger → DCA1000 → UDP → Vomee FFT → RA/RD/DA proven, NO mmWave Studio.**
(CuPy absent in this env → NumPy fallback; fine for validation.)

GUI: `python main.py --trigger --trigger-cfg mmwave_pure_python/configFiles/vomee_1843_light.cfg`

### USER DECISION (2026-06-17): do both tracks; RD/doppler resolution IS important
⇒ 64 loops is validation-only; must reach ~255 doppler. Track 2 (exact 256×255 via
custom no-DSP firmware or Path A SPI) launched as background research.

### T4b — GUI freeze (RA/RD frozen, DCA1000 LED flashing) — FIXED
Cause: `vomee` conda env had **no CuPy** → MmWaveProcessor used NumPy on the Qt main
thread → FFT too slow → consumer < 10fps producer → `MmWaveCapture` circular buffer
wrapped → `get_frame()` returned `"bufferOverWritten"` FOREVER (no recovery) → freeze.
Fixes:
1. Installed **cupy-cuda12x 14.1.1** (machine has RTX 3080 Ti + CUDA 12.6). Processor
   now `CuPy ... with CUDA ready`; GPU 3D-FFT ~ms. Matches original fft.py (used cupy).
2. Hardened `core/mmwave_capture.py get_frame()`: on overwrite, **resync to newest
   frame + clear flag** instead of freezing forever (real-time show-latest semantics).
Re-validated: processor uses GPU, frames advance, real structure.

## 6. Track 2 research result — route to EXACT 256×255 (no mmw_demo)
KEY: stock mmw_demo caps at 256×64 (detection matrix = 2×16KB HWA banks = 32KB).
**The SPI-via-FT4232H idea is architecturally IMPOSSIBLE for the 1843** — TI MMWAVE-DFP
is AWR2243/1243-only (transceiver MMICs with no on-chip ARM). The 1843 has on-chip
MSS+DSP; mmwavelink runs ON the chip and is fed over **UART**. pyRadar's 2243 SPI path
has no valid 1843 target.
The ONLY way to 256×255 = run the **rf_eval radarSS+MSS firmware (no on-chip DSP)** —
the exact firmware Studio uses — which is ALREADY on disk:
`C:\ti\mmwave_studio_02_01_01_00\rf_eval_firmware\{masterss,radarss}\xwr18xx_*.bin`.
Two ways to drive it:
- **Option A (low effort, NOT Studio-free):** script Studio's RF engine via its
  RtttNetClientAPI **TCP/Lua gateway (localhost:2777)** — no GUI. Model: WiseLabCMU/rover
  (built for AWR1843BOOST+DCA1000). Requires Studio installed+running. Byte-identical.
- **Option B (high effort, truly Studio-free, Ubuntu-able):** reimplement Studio's
  flow in pure Python = UART firmware-download of the two .bin + mmwavelink binary
  frames (ProfileConfig/ChirpConfig/FrameConfig/StartFrame). Reuses our DCA1000 UDP
  receive. Hard part = reverse-engineering the mmwavelink framing + download handshake.
⇒ DECISION NEEDED from user: A (fast, Studio stays) vs B (real goal, big effort).

### USER chose B. Foundation mapped (2026-06-17) — transport CORRECTED to SPI/FTDI
Studio drives the 1843 over **SPI via the FT4232H FTDI (on the DCA1000)**, NOT UART.
Proof on disk: `mmWaveStudio\ReferenceCode\FTDILib\SourceCode\mmwl_port_ftdi.c` (110KB,
TI's mmwavelink↔FTDI/SPI transport) + `ftd2xx.h/.lib`. Firmware bins present:
`rf_eval_firmware\{masterss\xwr18xx_masterss.bin (52KB), radarss\xwr18xx_radarss.bin (35KB)}`.
(pyftdi/libftdi work on Linux, so SPI/FTDI still meets the Ubuntu goal.)

What does the xWR18xx host control: Studio's closed **`AR1xController.dll` (648KB)** +
`RadarLinkDLL.dll` (mmwavelink) in `mmWaveStudio\RunTime`. THE hard truth: TI ships the
xWR18xx host-side control ONLY as this closed Windows DLL — there is NO open cross-
platform "DFP" for xwr18xx (the open DFP/pyRadar path is AWR2243-only). So "truly
Studio-free + Ubuntu" = reconstruct what AR1xController.dll does, from:
  - OPEN transport: `mmwl_port_ftdi.c` (SOP/reset/SPI framing/fw-download) — on disk
  - OPEN protocol: mmwavelink message opcodes/structs (mmWave SDK rl_*.h / mmwavelink.h)
  - GROUND TRUTH: sniff the actual SPI bytes Studio sends for skeleton.lua, replay/verify
  - verify each step against the live DCA1000 UDP stream

Implementation sub-options:
- **B1 ctypes AR1xController.dll** — fastest, but Windows + Studio-DLL locked → fails
  the Ubuntu/no-Studio goal. (Effectively Option A.)
- **B2 wrap TI C (mmwl_port_ftdi.c + mmwavelink) via pybind11/ctypes** — cross-platform,
  pyRadar-style, needs a compiler (no MSVC here; could build on Ubuntu). Large.
- **B3 pure-Python (pyftdi + reimplement mmwavelink + fw download)** — no C, fully
  portable, largest/riskiest. 
⇒ B2 or B3 meet the goal; both are multi-day. NEXT: confirm investment + sub-approach,
then de-risk Phase 1 = SPI connect + firmware download over FTDI in Python.

### BREAKTHROUGH (2026-06-17): Studio's full SPI ground truth is logged on disk
User chose "capture Studio's SPI bytes as ground truth first" — and it ALREADY EXISTS:
**`C:\ti\mmwave_studio_02_01_01_00\mmWaveStudio\RunTime\trace.txt`** logs every
mmwavelink SPI transaction as 16-bit words:
- `[WR] 0x1234 0x4321 <opcode> <nByte> <flags> ...payload... <CRC>` = host→dev command
- `[WR] 0x5678 0x8765 ...` = host read-trigger (CNYS); `[RD] 0xDCBA 0xABCD ...` = dev response
- also logs `Host IRQ High/Low` (the SPI handshake line)
Preserved a copy → `ground_truth/trace_existing.txt`. Wrote `ground_truth/parse_trace.py`
(works): 1237 cmds, opcodes e.g. 0x0201(nByte 0x3E=62 → Profile/Chirp/Frame cfg),
0x8085 ×270 (firmware-download chunks), 0x8345/0x8005/0x05C1 (init). Multiple sessions
were concatenated in the existing file → need ONE clean skeleton.lua capture.

⇒ This collapses Option B risk massively: we don't reverse-engineer blind — we REPLAY
Studio's exact logged word sequence over FTDI SPI (pyftdi, per mmwl_port_ftdi.c framing
+ IRQ handshake), verifying against the live DCA1000 stream.

### T5 — Orientation / scale FULLY VERIFIED (2026-06-17, adversarially)
User flagged RA/RD orientation seemed different (range 0 top vs bottom). Killed
`DCA1000EVM_CLI_Record.exe` (PID 13768 = the "DCA1000 process") to free UDP 4098,
captured authoritative live 256×255 frame → `ground_truth/ref_{raw,rd,ra,da}`.
Empirical: RD zero-Doppler peaks at center col (127/254) ✅; near-range strong energy
at high row indices; processor `[::-1]` puts range 0 (near) at LAST row.

pyqtgraph queried live: `imageAxisOrder='col-major'`, `ImageView.yInverted=True`.
Derived + **independently verified (critic agent)**: NEW Vomee (QImage) and ORIGINAL
(`h_heatmap.T`→pyqtgraph) render **IDENTICAL on-screen orientation**:
- range vertical: **FAR at TOP, near(0) at BOTTOM**; RD doppler horizontal, **0=center**;
  RA azimuth left→right. Processor arrays are byte-identical between pipelines.
- The original's outer `.T` and pyqtgraph col-major+invertY CANCEL → matches QImage row0=top.
⇒ **No data-orientation difference between new Vomee and the original published pipeline.**
The diff the user saw vs "the mmWave Studio version" is one of: (a) Studio's OWN plots use a
different convention; (b) 64-loop RD is only 64 doppler-wide → stretched in the square view
vs 255; (c) layout: original stacked RA/RD/DA vertically in ONE window, new shows RD & RA as
separate squares (DA dropped in qml_bridge).

Physical scales (from skeleton.lua profile): **range_res 4.26 cm, range_max 10.91 m,
v_max ±6.09 m/s, azimuth ±90°**. Annotated refs: `ground_truth/annot_RD.png`, `annot_RA.png`;
side-by-side `cmp_RA/RD/DA.png`. Vomee currently shows pixel axes (no physical labels) — can add.

### Ground-truth capture DONE (config) — `ground_truth/trace_skeleton.txt`
User ran skeleton.lua. Fresh trace = 403 lines / 23 mmwavelink config commands = the
COMPLETE 256×255 RF-config sequence (ChanNAdcConfig, ProfileConfig 0x0201/nByte0x3E,
ChirpConfig×2, FrameConfig, LVDS cfg, etc.). **Firmware download is NOT in trace.txt**
(Studio doesn't log the 88KB bulk) → handle via `rlDeviceFileDownload` streaming the
on-disk `xwr18xx_{masterss,radarss}.bin` (mechanism in mmwl_port_ftdi.c).

### Track 2 remaining (multi-day, when user is ready)
Phase 1: pyftdi MPSSE/SPI transport (FT4232H on DCA1000) — open, SOP, reset, IRQ
handshake, msg framing per mmwl_port_ftdi.c. Phase 2: firmware download (.bin). Phase 3:
replay/construct the 23 config commands. Phase 4: StartFrame + verify vs DCA1000 stream.

## STATUS SUMMARY (2026-06-17)
- ✅ Track 1: pure-Python trigger (mmw_demo+UART+DCA1000 UDP) works end-to-end; GUI smooth
  (cupy installed + buffer-overwrite recovery); validated. Limited to ≤64 doppler by mmw_demo.
- ✅ Orientation/scale: verified new Vomee == original capture_single (far-top/near-bottom,
  0-doppler center). User confirmed this IS the desired orientation. No change needed.
- ✅ Studio-triggered 256×255 works in new Vomee NOW via `python main.py` (no --trigger).
- ◻ Track 2: pure-Python 256×255 (no Studio) = replay Studio's SPI/mmwavelink over FTDI.
  Ground-truth config captured; transport build is the remaining multi-day effort.

## 7. Deep search result (2026-06-17, 19-agent workflow + adversarial verify)
### NEW BEST LEAD (low effort): TI **mmWave Studio CLI Tool** (`mmwave_studio_cli`)
- A standalone, **UART-driven** tool (NO GUI, NO SPI) that flashes its own firmware
  `mmwave_Studio_cli_xwr18xx.bin` — a **no-on-chip-DSP / no-detection streaming image**
  (same family as rf_eval). No detection matrix ⇒ **no 32KB cap** ⇒ frameCfg numLoops up
  to 255 ⇒ **256×255 achievable**. Controlled over UART (sensorStart/Stop, ENABLE_DCA_CAPTURE=1
  auto-configs DCA1000) — exactly our familiar UART style, NOT the SPI/mmwavelink route.
- Ships in the **TI Radar Toolbox** (download from dev.ti.com/TIREX) at
  `radar_toolbox/tools/studio_cli/` (`prebuilt_binaries/mmwave_Studio_cli_xwr18xx.bin`,
  `gui/mmw_cli_tool/mmwave_studio_cli.exe`, `mmwaveconfig.txt`). NOT currently on this PC
  (only the GUI Studio is). TI marks it "no longer actively supported".
- Adoption: flash the .bin (UniFlash, SOP flash mode) → edit mmwaveconfig.txt (256 samples,
  numLoops=255, lvdsStreamCfg on, NO cfar/gui, ENABLE_DCA_CAPTURE=1) → run over COM → DCA1000.
- Verifier verdict: **actuallySolves = yes** (by architecture: identical no-detection firmware
  + LVDS path). CAVEAT: no E2E post explicitly reports 256×255 on THIS tool (inference, not a
  direct hardware report); the .exe is Windows. ⇒ **Path to Ubuntu/pure-Python:** validate with
  the .exe first, then **replicate its UART protocol in pure Python** (far simpler than SPI/
  mmwavelink) to drive the same CLI firmware → clean Studio-free + Ubuntu.

### Confirmed DEAD ENDS (don't waste time)
- RadarML/firmware `xwr18xx-custom`: README claims detection removed but `dss_main.c` still
  runs the objdet DPC → same hang at 255. NOT a fix.
- All stock mmw_demo paths (our Track 1, ConnectedSystemsLab/xwr_raw_ros [20 loops],
  mmwave-capture-std, pyRadar 1843, ibaiGorordo, AndyYu0010): on-chip detection ⇒ ≤64 doppler.
- davidmhunt/CPSL_TI_Radar: useful **Studio-free DCA1000 C++ receiver/parser**, but its IWR1843
  control path is mmw_demo (capped); ships no 256×255 config. Partial — receiver only.
- Headless Studio TCP/Lua (RtttNetClientAPI 2777; WiseLabCMU/rover): reaches 256×255 but
  REQUIRES Studio installed+running → fails the Studio-free goal.
- AWR2243 path (pyRadar/openradar): works but wrong board.

### Revised plan: try **Studio CLI Tool** first (low effort, likely 256×255 over UART);
keep **Track 2 SPI replay** as the proven fallback. Both reach the no-detection firmware.

## 8. ★ SOLVED (2026-06-18): pure-Python 256×255 raw ADC, NO mmWave Studio ★
Flashed `mmwave_Studio_cli_xwr18xx.bin` (no-DSP firmware) to the AWR1843 flash via
UniFlash (META_IMAGE1, 151620 B, SUCCESS). It boots from flash in functional mode
(SOP=001/左右右) and presents a `mmwDemo:/>` CLI at **921600 baud** (old mmw_demo was 115200).

Dropped the Windows `mmwave_studio_cli.exe` (interactive; piping 'quit' caused an
infinite `[ERROR]invalid command` loop). Instead drove the no-DSP firmware DIRECTLY in
**pure Python**: our `core/mmwave_trigger.py` RadarUART @921600 sent the 256×255 cfg
(`studio_cli/src/profiles/profile_vomee_256x255_cont.cfg`, no cfar/gui, frameCfg numLoops=255,
numFrames=0) + sensorStart, and `DCA1000` (UDP 4096) did config_fpga/config_record/stream_start.

RESULT (`tools/test_nodsp_256x255.py`): every cfg line `Done`, **255 loops accepted with NO
hang** (vs mmw_demo dying at 128/255), sensorStart `Done`, and the sniff saw
**43,050 pkts, 20.9 MB/s, 10 fps, frame = 2,088,960 B = 256×255×2TX×4RX×2×2** from 192.168.33.30.
`validate_pipeline.py 255` through Vomee's processor: **RD(256,255)**, RA(256,256), std≈0.15,
finite, layout matches → real, valid 256×255. **The trained-model blocker is resolved.**

⇒ Full Studio-free pipeline: UART(921600 cfg+sensorStart) + DCA1000(UDP) + Vomee FFT.
Cross-platform (UART+UDP only) → Ubuntu/ARM-ready. Firmware flash is one-time.
Integrated into Vomee: `config.MMWAVE_TRIGGER` (baud 921600, cont 256×255 cfg) + `main.py
--trigger` (+ stop_on_exit). Run: `python main.py --trigger`.

### Studio CLI Tool STAGED (2026-06-17) — Radar Toolbox 4.00.00.05 downloaded
User downloaded `radar_toolbox_4_00_00_05.zip` (1GB) + `uniflash_sl.9.5.0.5651.exe` +
the Getting Started Guide. Extracted studio_cli → `mmwave_pure_python/studio_cli/`:
- firmware `prebuilt_binaries/mmwave_Studio_cli_xwr18xx.bin` (148KB, no-detection streaming)
- `gui/mmw_cli_tool/mmwave_studio_cli.exe` + `mmwaveconfig.txt`
- guide → `studio_cli/GETTING_STARTED.txt`
Wrote: `src/profiles/profile_vomee_256x255_xwr18xx.cfg` (skeleton.lua RF, 256 samp,
255 loops, TX0+TX2, lvdsStreamCfg, numFrames=10 for validation) and edited
`mmwaveconfig.txt` (AWR1843, COM4, baud 921600, ENABLE_DCA_CAPTURE=1, monitor/postproc
off, DCA lane=2 fmt=3, capture → `captured_adc_vomee/`). Original saved `.orig`.
SOP for this board (slide switch, 左=ON): **Flashing=101=左右左**, **Functional=001=左右右**.
NEXT: user flashes the .bin (UniFlash, DCA1000 MIPI disconnected) → functional → reconnect;
then run mmwave_studio_cli.exe → verify captured frame = 2,088,960 B (256×255).

## 9. ★ ORIENTATION CORRECTION (2026-06-20, empirically re-measured on Ubuntu) ★
The T5 (2026-06-17) claim that the processor's `[::-1]` (flip=True) put "FAR at TOP,
near(0) at BOTTOM" is **BACKWARDS**. Re-measured on live hardware by averaging frames and
comparing top-vs-bottom row energy (and confirmed visually by the user against the original
Studio-era display):
- **flip=True  → near at TOP**   (the old default; this was the regression the user saw)
- **flip=False → near at BOTTOM** ← desired, matches the original published pipeline.
⇒ `core/mmwave_processor.py` now uses **flip=False for BOTH rd and ra** (range 0/near at the
bottom). The recorded `.npy` (what the downstream model consumes) therefore has near at the
bottom. If a model was trained on near-at-top data, revert both rd/ra to flip=True.
Any older doc/tool text saying "[::-1] ⇒ row0=far" is wrong; trust this section.

### RD looks grainier than RA — NOT a bug (2026-06-20)
RD doppler = 255 REAL chirp-FFT bins (full resolution, no padding) → grainy/“lined”.
RA azimuth = 8 virtual antennas zero-padded to 256 (32× oversampled) → inherently smooth.
Measured adjacent-column correlation: RD≈0.76 vs RA≈0.998. The RD “lines” are real data, not
rendering. Do NOT smooth the recorded arrays (the model trains on raw `.npy`); any smoothing
must be display-only. Studio’s RD looks smooth only because it oversamples the doppler FFT.

# Vomee mmWave — Setup & Run Guide: macOS / Ubuntu (pure-Python 256×255, NO mmWave Studio)

> ## ✅ STATUS 2026-06-22 — current working pipeline (READ THIS FIRST)
>
> The clean, validated capture path today is the **Studio-bring-up → reboot → receive-only bypass**,
> NOT the pure-Python `--trigger` path documented below (that path is **parked**: the Linux SPI
> bring-up hit a hardware wall and the device SFLASH was erased during that investigation).
>
> 1. **Windows / mmWave Studio:** run the `rf_eval` bring-up (`skeleton.lua`) + `StartFrame` with
>    **numFrames = 0 (infinite)**. Radar (192.168.33.180) + DCA1000 then stream autonomously over UDP.
> 2. **Hand the stream to your capture host WITHOUT power-cycling the radar/DCA1000** — either reboot
>    this machine to Ubuntu, or unplug the type-C hub (radar + DCA1000 + USB-Ethernet) and move it to
>    another host (e.g. a MacBook). rf_eval lives in RAM and self-triggers, so the stream survives.
> 3. **Capture host (Ubuntu or macOS):** just run **`python main.py`** — **receive-only + camera are
>    now the DEFAULT**, so it never touches the radar and won't kill the live stream (only `--trigger`
>    would, via `reset_radar`). Add `--no-camera` for a headless mmWave-only view. Produces clean,
>    line-free, phase-coherent RD.
>
> **macOS (M-series) note:** the same `python main.py` works (mmWave FFT runs on CPU — plenty fast for
> 256×255). Set static IP **`192.168.33.30/24`** on the moved USB-Ethernet dongle (System Settings ▸
> Network ▸ Manual; the interface name will differ from Ubuntu's `enx…`). The off-GIL C receiver needs
> `fpga_udp` built locally — without it, capture **auto-falls back to the pure-Python receiver** (fine
> for live viewing; build `fpga_udp` for zero-loss recording). See §2.2–§2.4 for the macOS deltas.
>
> **Frame loss = SOLVED** (ultragoal `frame-loss-zero`, 3/3): an off-GIL C frame-assembling receiver
> (`core/mmwave_capture_c.py` + fpga_udp `udp_frame_*`; patch in `mmwave_pure_python/patches/`) drains
> the kernel UDP buffer with the GIL released. **11.4 fps under recording load, kernel `RcvbufErrors=0`.**
> Only complete, gap-free frames are kept — incomplete/duplicate/reordered frames are honestly dropped,
> **never interpolated or zero-filled.** `main.py` prefers this backend and falls back to the pure-Python
> receiver if fpga_udp lacks `udp_frame_*`.
>
> **RD orientation:** `config.MMWAVE_RD_FLIP_RANGE = True` — byte-matches the model's training data
> (the original `mmwave_silent/fft.py`, which flips RD/RA `[::-1]`); verified to max-abs 1.2e-7.
>
> The §0–§9 below are kept as the pure-Python investigation record. The SOP labels in older notes were
> later found **mislabeled** — distrust them; the bypass above does not depend on SOP at all.

> **For a fresh Claude Code session on macOS (Apple Silicon) or Ubuntu.** Follow this
> top-to-bottom to set up a conda env and run the full pure-Python mmWave capture
> (256×255 raw ADC) + Vomee GUI. No mmWave Studio, no TI `.exe`. **macOS deltas are folded
> into §2.2** — read them if you're on a Mac. Read §0 first — it prevents you from re-doing
> solved work or chasing dead ends.

---

## 0. CONTEXT — read this before doing anything

**What this is:** a TI **AWR1843BOOST** mmWave radar + **DCA1000EVM** capture card. We
capture **raw ADC** (256 range samples × 255 doppler loops, 2 TX / 4 RX) over the network
and compute Range-Doppler / Range-Azimuth heatmaps in Vomee. A downstream model needs the
**full 256×255** Range-Doppler — that is the hard requirement.

**What was solved (on Windows, now porting to Ubuntu):**
- The radar's on-chip flash was flashed **once** with TI's **no-DSP "mmWave Studio CLI"
  firmware** (`mmwave_Studio_cli_xwr18xx.bin`). This firmware does **no on-chip detection**,
  so it streams full raw ADC at **any** doppler count (the stock `xwr18xx_mmw_demo` is
  capped at ~256×64 by a 32 KB detection-matrix — do NOT use mmw_demo).
- The radar is driven **purely in Python**: config + `sensorStart` over the **CLI UART**,
  and the DCA1000 over **UDP**. Raw ADC then floods back over Ethernet.

**HARDWARE STATE — DO NOT CHANGE (one-time, persistent, host-independent):**
- ✅ Firmware is in the radar's **flash** → survives power-off and host changes.
  **DO NOT re-flash. DO NOT need UniFlash. DO NOT use mmWave Studio.**
- ✅ Boot mode is **Functional**: SOP slide switch = **`左 右 右`** (SOP0 ON, SOP1 OFF,
  SOP2 OFF = SOP[2:0]=001). Leave it. (Only changes if someone re-flashes or reverts to Studio.)

**DON'T:**
- ❌ Don't re-flash firmware (it's on the chip).  ❌ Don't run mmWave Studio.
- ❌ Don't use `xwr18xx_mmw_demo` (256×64 cap).   ❌ Don't use the Windows `mmwave_studio_cli.exe`.
- ❌ Baud is **921600**, NOT 115200 (mmw_demo was 115200; this firmware is 921600).

**Full investigation log:** `mmwave_pure_python/LAB_NOTES.md` (read §8 for the solution).

---

## 1. Key facts / parameters

| Item | Value |
|------|-------|
| Radar | TI AWR1843BOOST (xwr18xx) |
| Capture card | DCA1000EVM |
| Firmware (flashed) | `mmwave_Studio_cli_xwr18xx.bin` (no-DSP streaming) |
| Radar CLI UART | Linux: **`/dev/ttyACM0`** (XDS110 "Application/User UART"); Windows was COM4 |
| UART baud | **921600** |
| PC static IP (NIC to DCA1000) | **192.168.33.30 / 255.255.255.0** |
| DCA1000 IP | 192.168.33.180 |
| Data port (raw ADC, UDP) | 4098 |
| Config port (DCA1000, UDP) | 4096 |
| Chirp profile | `profileCfg 0 77 20 6 60 0 0 65.998 0 256 4800 0 0 30`, TX0+TX2, 256 samples |
| Frame | `frameCfg 0 1 255 0 100 1 0` → 255 loops, numFrames=0 (continuous), 100 ms (10 fps) |
| Frame size | **2,088,960 bytes** = 256 × 255 × 2 TX × 4 RX × 2 (I/Q) × 2 bytes |
| Throughput | ~20.9 MB/s ≈ **167 Mbps** (need a real Gigabit NIC) |

---

## 2. Software setup — macOS / Ubuntu (one-time on the new machine)

### 2.1 Get the repo
```bash
# however you transfer it; it already contains mmwave_pure_python/ with everything
cd ~/  # or wherever
git clone <your Vomee repo>   # or copy the folder over
cd Vomee
```

### 2.2 Conda env + dependencies
```bash
# macOS: you can REUSE an existing env, e.g.  conda activate pose   (then skip the create)
conda create -n vomee python=3.11 -y     # 3.11-3.13 all fine (mediapipe removed -> no ceiling)
conda activate vomee
pip install -r requirements.txt          # PySide6, torch, torchvision, ultralytics, filterpy,
                                         # scipy, scikit-image, matplotlib, ffmpeg-python,
                                         # opencv-python, numpy, Pillow, pyserial
# ffmpeg BINARY (ViTPose viz):  macOS: brew install ffmpeg   |   Ubuntu: sudo apt install ffmpeg
```
> The mmWave FFT runs on **PyTorch**: CUDA on NVIDIA, **CPU on Apple Silicon** (torch.fft is
> unsupported on MPS), NumPy fallback. **Do NOT install CuPy** (NVIDIA-only; no longer used).
> `MmWaveCapture.get_frame()` self-heals from buffer overwrite (degrades/lags, never freezes).

> **macOS (Apple Silicon) deltas** for the steps below:
> - **Serial (§2.5):** no `dialout` group; the radar UART is `/dev/cu.usbmodem*` and the
>   launcher/trigger **auto-detect it** (XDS110 VID:PID 0451:BEF3) — you usually set no port.
> - **Static IP (§2.3):** set the DCA1000 NIC to `192.168.33.30 / 255.255.255.0` in
>   System Settings ▸ Network (Manual), or `sudo ifconfig <en> 192.168.33.30 netmask 255.255.255.0`
>   (find `<en>` via `networksetup -listallhardwareports`).
> - **UDP buffer (§2.4):** instead of Linux `net.core.rmem_max`, raise
>   `sudo sysctl -w kern.ipc.maxsockbuf=8388608`.
> - **FFT/GPU:** runs on CPU (fast for 256×255); the CuPy/NVIDIA lines below are N/A.

### 2.3 Network — static IP on the DCA1000 NIC
Find the Ethernet interface wired to the DCA1000 (`ip link`, look for the one that is the
direct cable, often `enpXsY` / `eth0`):
```bash
ip link                                   # identify the iface, e.g. enp3s0
# Quick (non-persistent):
sudo ip addr add 192.168.33.30/24 dev <iface>
sudo ip link set <iface> up
# Persistent (NetworkManager):
sudo nmcli con add type ethernet ifname <iface> con-name dca1000 \
     ipv4.method manual ipv4.addresses 192.168.33.30/24
sudo nmcli con up dca1000
ping 192.168.33.180                       # optional: DCA1000 may not reply to ping; that's OK
```

### 2.4 UDP receive buffer (CRITICAL — prevents packet loss at 167 Mbps)
The capture code requests `SO_RCVBUF = 128 MB`, but Linux caps it at `net.core.rmem_max`
(default ~208 KB → heavy packet loss). Raise it:
```bash
sudo sysctl -w net.core.rmem_max=134217728
sudo sysctl -w net.core.rmem_default=134217728
# make persistent:
echo -e "net.core.rmem_max=134217728\nnet.core.rmem_default=134217728" | sudo tee /etc/sysctl.d/99-dca1000.conf
```

### 2.5 Serial port permission
```bash
sudo usermod -aG dialout $USER     # then LOG OUT and back in (or reboot) for it to take effect
ls -l /dev/ttyACM*                 # expect ttyACM0 (CLI/User UART) and ttyACM1 (Aux)
```
If unsure which ACM is the CLI port, use the probe in §4.1 — the right one replies at 921600.

### 2.6 Point the config at the Linux serial device
Edit `config.py` → `MMWAVE_TRIGGER`:
```python
MMWAVE_TRIGGER = {
    'enable': False,
    'com_port': '/dev/ttyACM0',   # <-- change from 'COM4'
    'baud': 921600,               # keep
    'cfg_file': 'mmwave_pure_python/studio_cli/src/profiles/profile_vomee_256x255_cont.cfg',
    'json_file': 'mmwave_pure_python/configFiles/cf.json',
    'stop_on_exit': True,
}
```

---

## 3. Hardware connection checklist (no changes needed, just verify)
- Radar SOP = **`左 右 右`** (functional). It already is — don't touch unless no UART response.
- DCA1000 connected to radar via the **blue MIPI/LVDS ribbon**.
- DCA1000 Ethernet → the NIC you set to `192.168.33.30`.
- Radar USB (XDS110) → the Ubuntu box (gives `/dev/ttyACM0`).
- Both radar and DCA1000 powered (5 V each).

---

## 4. Verify, step by step (run these in order)

### 4.1 UART probe — confirm the firmware responds (expect 921600 + `mmwDemo:/>`)
```bash
conda activate vomee && cd <repo>
python - <<'PY'
import serial, time
p = serial.Serial('/dev/ttyACM0', 921600, timeout=0.6); time.sleep(0.3); p.reset_input_buffer()
p.write(b'version\n'); time.sleep(0.4)
print(repr(p.read(p.in_waiting or 1))[:300]); p.close()
PY
# EXPECT: b'version\nPlatform : xWR18xx\n...mmWave SDK Version : 03.06.00.00...mmwDemo:/>'
# If garbage -> wrong device (try /dev/ttyACM1) or wrong baud. If empty -> check SOP=左右右,
# power-cycle, and dialout permission.
```

### 4.2 DCA1000 link probe (read-only, over UDP)
```bash
python mmwave_pure_python/tools/dca1000_control.py 2>/dev/null || \
python - <<'PY'
import sys; sys.path.insert(0,'mmwave_pure_python/tools')
from dca1000_control import DCA1000
d=DCA1000(); print('alive:', d.sys_alive_check(), '| fpga:', d.read_fpga_version()); d.close()
PY
# EXPECT: alive: success | fpga: 2.9 [Record]   (if None -> NIC not 192.168.33.30 / DCA off)
```

### 4.3 Full trigger + raw-stream check (the money test)
Edit the COM in `tools/test_nodsp_256x255.py` if needed (it hardcodes `COM4` — change to
`/dev/ttyACM0`), then:
```bash
python mmwave_pure_python/tools/test_nodsp_256x255.py
# EXPECT: every cfg line 'Done'; sensorStart 'Done';
#         packets~43000, ~20.9 MB/s, fps~10.00, frame=2,088,960 B -> "RAW 256x255 STREAMING"
```

### 4.4 Pipeline check (real RA/RD, not noise)
```bash
python mmwave_pure_python/tools/validate_pipeline.py 255
# EXPECT: RD(256, 255), RA(256,256), std>0, finite -> "layout matches"
```

---

## 5. Run the full Vomee GUI
```bash
conda activate vomee && cd <repo>
python main.py --trigger
```
This configures the radar over UART (921600), configures the DCA1000, `sensorStart`, and
shows live camera + 256×255 RA/RD heatmaps. Closing the window sends `sensorStop`.
(`--trigger-com /dev/ttyACM0` can override the port on the CLI; `--trigger-cfg <path>` the cfg.)

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| UART probe empty/garbage | Wrong device → try `/dev/ttyACM1`; wrong baud → must be **921600**; SOP not `左右右`; power-cycle; `dialout` group not applied (re-login). |
| `cfg line -> invalid command` | Wrong firmware (mmw_demo flashed?) or garbled baud. Confirm §4.1 banner. Do NOT add `cfarCfg`/`guiMonitor` — this firmware has no detection. |
| DCA1000 `alive: None` | NIC not `192.168.33.30/24`; DCA1000 unpowered; cable to wrong port; firewall (`sudo ufw allow` or disable). |
| No packets on 4098 | `sensorStart` failed; MIPI ribbon loose; NIC IP wrong; another process bound 4098. |
| Heavy packet loss / `bufferOverWritten` | Raise `net.core.rmem_max` (§2.4); use a Gigabit NIC; install CuPy so FFT keeps up. |
| GUI heatmaps lag/freeze | FFT can't keep up — use an NVIDIA GPU (torch CUDA) or accept CPU (fine for 256×255). The buffer-overwrite recovery prevents a hard freeze. |
| Frame size ≠ 2,088,960 | cfg mismatch — `profileCfg ...256...` + `frameCfg 0 1 255 0 100 1 0` + `channelCfg 15 5 0`. |

---

## 7. File map (`mmwave_pure_python/`)
| Path | What |
|---|---|
| `core/mmwave_trigger.py` (in repo root `core/`) | pure-Python trigger: `DCA1000` (UDP) + `RadarUART` (pyserial) + `trigger()` |
| `studio_cli/src/profiles/profile_vomee_256x255_cont.cfg` | the 256×255 no-DSP cfg (continuous) |
| `studio_cli/prebuilt_binaries/mmwave_Studio_cli_xwr18xx.bin` | the flashed no-DSP firmware — **NOT committed** (TI binary; gitignored). It already persists on the chip's flash; only needed for re-flash, where you'd get it from the TI Radar Toolbox (§9). |
| `configFiles/cf.json` | DCA1000 config (lvdsMode=2, 16-bit, 5µs delay) |
| `tools/test_nodsp_256x255.py` | full trigger + raw-stream sniff |
| `tools/validate_pipeline.py` | raw ADC → Vomee FFT → RA/RD sanity |
| `tools/dca1000_control.py` | standalone DCA1000 UDP control + probe |
| `LAB_NOTES.md` | full investigation log (§8 = the solution) |
| `config.py` (repo root) | `MMWAVE_TRIGGER` block (set `com_port` to `/dev/ttyACM0`) |

---

## 8. Architecture (so you understand WHY, and don't re-investigate)
- **Two buses:** USB→UART carries config + `sensorStart` (tiny); Ethernet carries the raw
  ADC (DCA1000→UDP 4098) and DCA1000 control (UDP 4096). Both are pure Python (pyserial +
  socket) → fully cross-platform.
- **No-DSP firmware** is the key: it only chirps + dumps raw ADC over LVDS to the DCA1000,
  so there is no detection-matrix memory limit → arbitrary doppler (255) works. This is the
  same data path mmWave Studio uses, minus the GUI/Windows.
- **Trigger sequence** (`core/mmwave_trigger.trigger()`): reset_fpga → UART send cfg (stops
  before `sensorStart`) → DCA `config_fpga`/`config_record`/`stream_start` → UART `sensorStart`
  → raw ADC floods 4098. Vomee's `MmWaveCapture` assembles frames; `MmWaveProcessor` FFTs to RA/RD.
- **Why not mmw_demo / Studio:** mmw_demo runs on-chip detection (256×64 cap). Studio is
  Windows-only GUI. Both rejected. This path is the no-DSP firmware + pure-Python control.

---

## 9. Appendix — re-flashing (you should NOT need this)
The firmware persists in flash. If it ever gets wiped:
1. Get UniFlash (Linux x86 version from ti.com/tool/UNIFLASH).
2. Set SOP to **Flashing mode `左 右 左`** (SOP0 ON, SOP1 OFF, SOP2 ON), disconnect the blue
   MIPI ribbon, power-cycle.
3. UniFlash → AWR1843 → Serial (`/dev/ttyACM0`) → flash
   `mmwave_pure_python/studio_cli/prebuilt_binaries/mmwave_Studio_cli_xwr18xx.bin` (Meta Image 1).
4. Set SOP back to **Functional `左 右 右`**, reconnect MIPI, power-cycle.

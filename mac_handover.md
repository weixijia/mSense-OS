# Vomee — macOS Capture Handover (MacBook Pro M-series)

> **Goal:** capture the **live mmWave stream** that mmWave Studio already started, on a MacBook, by
> moving the type-C hub over from the Ubuntu laptop. This is the receive-only bypass — the Mac never
> touches the radar. For a fresh Claude Code session on the Mac, follow this top-to-bottom.

---

## 0. The situation (read first)

- The radar (AWR1843BOOST) was brought up **once** in **mmWave Studio on Windows** with `StartFrame`
  numFrames=0 (**infinite frames**). rf_eval firmware lives in the radar's **RAM** and self-triggers —
  so the radar + DCA1000 keep streaming raw ADC over UDP **on their own**, as long as they stay powered.
- You are carrying the **type-C hub** (radar + DCA1000 + USB-Ethernet dongle) from the Ubuntu laptop to
  the Mac. **Do NOT power-cycle the radar or DCA1000** — keep both 5 V barrel jacks connected. If they
  lose power, the RAM firmware is gone and you must redo the Windows Studio bring-up.
- The Mac only **receives** the stream (UDP is connectionless — whoever sits at `192.168.33.30:4098`
  gets the data). `python main.py` is now **receive-only by default** and will not reset/kill the stream.

**Data facts:** radar `192.168.33.180` → PC `192.168.33.30`, data UDP port **4098**, config port 4096.
Frame = 256 samples × 255 chirps × 2 TX × 4 RX × I/Q × 16-bit = **2,088,960 bytes**, ~10 fps.

---

## 1. Set up the environment (one-time)

```bash
cd <path>/Vomee
git pull                                    # get the latest (this doc + receive-only default)

# reuse an existing env (e.g. `conda activate pose`) or create one:
conda create -n vomee python=3.11 -y && conda activate vomee
pip install -r requirements.txt             # PySide6, torch, torchvision, ultralytics, filterpy,
                                            # scipy, scikit-image, matplotlib, opencv-python, numpy, ...
brew install ffmpeg                          # ffmpeg binary (ViTPose viz)
```

- **FFT runs on CPU** on Apple Silicon (torch.fft is unsupported on MPS) — plenty fast for 256×255.
  **Do NOT install CuPy** (NVIDIA-only). Pose runs on MPS→CPU automatically.
- The smallest pose weights auto-download into `./models/` on first launch.

---

## 2. Network — static IP on the moved USB-Ethernet dongle (the ONE required step)

The DCA1000 dongle gets a new interface name on the Mac. Find it and give it `192.168.33.30`:

```bash
networksetup -listallhardwareports          # find the USB-Ethernet port / device (e.g. en7)
# GUI: System Settings ▸ Network ▸ (the USB-LAN) ▸ Details ▸ TCP/IP ▸ Configure IPv4: Manually
#      IP 192.168.33.30   Subnet 255.255.255.0   (leave router blank)
# or CLI (non-persistent):
sudo ifconfig en7 192.168.33.30 netmask 255.255.255.0    # replace en7 with your device
```

Raise the UDP socket buffer ceiling so the receiver can request a large `SO_RCVBUF`:

```bash
sudo sysctl -w kern.ipc.maxsockbuf=16777216     # 16 MB (default is small)
```

---

## 3. Verify the stream is arriving (before launching the GUI)

```bash
conda activate vomee && cd <path>/Vomee
python - <<'PY'
import socket, time
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1<<24)
s.bind(("192.168.33.30",4098)); s.settimeout(2.0)
n=0; t=time.time()
try:
    while time.time()-t<2.0: s.recvfrom(2048); n+=1
except socket.timeout: pass
s.close(); print(f"packets in 2s = {n} -> {'STREAMING ✅' if n else 'NO DATA ❌'}")
PY
```

- `STREAMING ✅` → go to §4.
- `NO DATA ❌` → the IP isn't on the right interface, the dongle/hub isn't seated, or the radar lost
  power (redo the Windows Studio bring-up). Only one process can bind `:4098` at a time — close any
  other capture first.

---

## 4. Run

```bash
python main.py            # camera + RA/RD, receive-only (DEFAULT — never touches the radar)
# or, headless mmWave-only (no camera):
python main.py --no-camera
```

- macOS will prompt for **camera permission** the first time — grant it (System Settings ▸ Privacy &
  Security ▸ Camera → your terminal app).
- **Never pass `--trigger` here** — that path resets/reconfigures the radar over UART and would kill
  the Studio-started stream.
- RD orientation is already correct for the trained model: `config.MMWAVE_RD_FLIP_RANGE = True` (near
  range at the bottom; byte-matches the training pipeline).

---

## 5. What "clean" looks like (how to know the bypass worked)

A good RD shows a **single sharp vertical line at zero-Doppler (center column)** = static clutter, plus
bright spots for real targets. There should be **NO comb of equidistant vertical stripes** across the
Doppler axis (that was the old studio_cli-firmware phase-noise bug, now avoided by using Studio's
rf_eval firmware). To confirm without eyeballing the GUI, render a frame to a PNG:

```bash
python - <<'PY'
import time, numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
import config
from core.mmwave_capture_c import MmWaveCaptureC          # falls back below if fpga_udp missing
from core.mmwave_processor import MmWaveProcessor
try:
    cap = MmWaveCaptureC()
except Exception:
    from core.mmwave_capture import MmWaveCapture; cap = MmWaveCapture()
cap.start()
proc = MmWaveProcessor(flip_range=getattr(config,"MMWAVE_RD_FLIP_RANGE",False))
data=None; t=time.time()
while time.time()-t<10:
    r=cap.get_frame()
    if not isinstance(r[0],str): data=r[0]; break
    time.sleep(0.01)
rd,ra,_=proc.process(data)
for name,img in (("RD",rd),("RA",ra)):
    plt.figure(figsize=(4,4)); plt.imshow(img,cmap="viridis",aspect="auto",interpolation="nearest")
    plt.title(name); plt.xlabel("doppler" if name=="RD" else "azimuth"); plt.ylabel("range (near=bottom)")
    plt.tight_layout(); plt.savefig(f"/tmp/{name}.png",dpi=90); plt.close()
cap.stop(); print("saved /tmp/RD.png /tmp/RA.png ; int16 range", int(data.min()), int(data.max()))
PY
```

---

## 6. Off-GIL C receiver vs. pure-Python fallback

- On Ubuntu the capture uses the **off-GIL C frame receiver** (`core/mmwave_capture_c.py` + a patched
  `fpga_udp`) — zero kernel packet loss even while recording (ultragoal `frame-loss-zero`).
- On the Mac, `fpga_udp` is a C/pybind11 extension that must be **built locally**. If it isn't,
  `main.py` automatically uses the **pure-Python receiver** (`core/mmwave_capture.py`). That is:
  - ✅ **Fine for live viewing** of RA/RD.
  - ⚠️ **Can drop frames under recording load** (FFT + disk I/O starve the GIL-bound recv thread). For
    **zero-loss recording** on the Mac, build `fpga_udp` with the off-GIL patch:
    ```bash
    cd <pyRadar>/fpga_udp
    git apply <path>/Vomee/mmwave_pure_python/patches/fpga_udp_offgil_frame_receiver.patch
    pip install -e . --no-build-isolation
    ```
    (`pyRadar` = gaoweifan/pyRadar; the patch adds `udp_frame_*`. See `patches/README.md`.)
  - **No data is ever fabricated** either way — incomplete frames are honestly dropped, never
    interpolated or zero-filled.

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `NO DATA ❌` on :4098 | Static IP not on the USB-LAN device (recheck `networksetup`); hub not seated; radar lost power → redo Windows Studio bring-up. |
| `bind` fails / "address in use" | Another process holds `:4098` — close the other capture/GUI. |
| Camera black / permission error | Grant camera permission to your terminal (System Settings ▸ Privacy & Security ▸ Camera), relaunch. |
| RD shows a comb of vertical stripes | You're on the wrong firmware/path — this bypass requires the **Studio rf_eval** stream. Confirm Studio did the bring-up, not a Python `--trigger`. |
| Heatmaps lag | CPU FFT keeping up is normal for 256×255; the pure-Python receiver may lag under load — see §6. |
| Frame size ≠ 2,088,960 | The Studio frame config differs from 256×255×2TX×4RX — match `config.ADC_PARAMS`. |

---

**TL;DR:** keep the radar powered, move the hub, set `192.168.33.30/24` on the USB-LAN device, then
`python main.py`. That's it.

# mSense OS — A Multimodal Sensing Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

mSense OS is a real-time platform for **synchronized multimodal capture**:

- **mmWave** — TI IWR1843 radar, live Range-Doppler / Range-Azimuth heatmaps (GPU 3D-FFT)
- **Camera** — webcam RGB with **ViTPose** skeleton overlay (CUDA → Apple MPS → CPU, auto-selected)
- **Recording** — timestamp-synchronized, per-frame atomic sessions to disk

The radar is brought up once in mmWave Studio and streams autonomously; mSense OS is
**receive-only** — it binds the UDP data port and assembles frames, never configuring or
resetting the radar.

## Quick Start

### Prerequisites
- Python 3.10+
- GPU optional — pose estimation and the mmWave FFT auto-select **CUDA → Apple MPS → CPU**
- TI IWR1843 + DCA1000 for mmWave capture; a USB webcam for the camera modality

### Installation
```bash
git clone https://github.com/weixijia/mSense-OS.git
cd mSense-OS
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
# ffmpeg binary (ViTPose viz): macOS `brew install ffmpeg` · Ubuntu `sudo apt install ffmpeg`
```

The smallest pose weights (`vitpose-s`, `yolov8n.pt`) auto-download into `./models/` on first launch.

### Run
```bash
python main.py                 # camera + mmWave + heatmaps, live preview on launch
python main.py --no-camera     # headless mmWave-only view
python main.py --camera-only   # camera + pose only (no radar)
```

### mmWave capture workflow
1. Bring the radar up in **mmWave Studio** with `StartFrame` numFrames = 0 (infinite) — radar +
   DCA1000 then stream autonomously over UDP.
2. Free the data port (stop mmWave Studio's recorder) — the radar keeps streaming.
3. Run `python main.py`. It receives the live stream on `192.168.33.30:4098` (set this static IP
   on the NIC wired to the DCA1000).

Frame loss under recording load is eliminated by an off-GIL C receiver (`core/mmwave_capture_c.py`,
requires the `fpga_udp` extension); without it, capture auto-falls back to the Python receiver
(fine for live viewing). RD orientation matches the trained model via `config.MMWAVE_RD_FLIP_RANGE`.

## Interface

A desktop dashboard built with **PySide6 + Qt Quick (QML)**:
- **Live preview on launch** — camera and radar heatmaps stream immediately; **Start** begins *recording*.
- **Layout** — camera on the left with a telemetry HUD (device · FPS · sync · frames); Range-Doppler
  and Range-Azimuth heatmaps stacked on the right; controls in the top bar.
- **Live controls** — toggle skeleton, switch keypoint group, start/stop recording without restarting.

## Pose Estimation

Skeleton tracking uses **ViTPose** — YOLOv8 person detection + SORT tracking + Vision-Transformer 2D
keypoints (vendored under `pose_studio_engine/`), running **CUDA → Apple MPS → CPU** automatically.
It is a **2D** estimator: `(x, y, confidence)` per keypoint, no depth.

The wholebody model emits 133 keypoints; choose which group is drawn and recorded:

| Group | Keypoints | Contents |
|-------|-----------|----------|
| `body` *(default)* | 23 | 17 body + 6 feet |
| `body_face` | 91 | body + 68-point face mesh |
| `body_hands` | 65 | body + 42 hand joints |
| `wholebody` | 133 | body + face + hands |

```bash
python main.py --keypoint-group body_hands
```

Defaults live in `config.py` under `POSE_PARAMS`.

## Recording format

Sessions are written under `./recordings/session_<timestamp>/`:
- `raw/mmwave.bin` — self-describing per-frame records (`VMRF` header: frame_num, timestamp,
  lost flag, length + int16 ADC payload)
- `heatmaps/rd/*.npy`, `heatmaps/ra/*.npy` — Range-Doppler / Range-Azimuth (float32)
- `camera/*.npy` — clean RGB frames (skeleton stored separately, never burned into pixels)
- `skeleton/*.json` — per-frame keypoints
- `timestamps.csv` — `frame_num, mmwave_ts, camera_ts, diff_ms, lost_packet`
- `metadata.json` — session parameters (`format_version: 2`)

## Repository layout

```
core/        mmWave receive (C off-GIL + Python fallback), 3D-FFT processor, camera + ViTPose
gui/         PySide6 QML bridge + Main.qml dashboard
recording/   async atomic file writer + session recorder
pose_studio_engine/   vendored ViTPose model code
site/        the mSense OS website
```

## License

MIT.

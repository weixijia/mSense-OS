# Vomee: A Multimodal Sensing Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![MobiCom 2025](https://img.shields.io/badge/ANAI-2025-green.svg)](https://doi.org/10.1145/3737904.3768536)

**Official repository for the MobiCom '25 paper: "Vomee -- A Multimodal Sensing Platform for Video, Audio, mmWave and Skeleton Data Capturing"**

## Overview

Vomee is a comprehensive multimodal sensing platform designed for synchronized data collection across multiple modalities:
- **Video** - High-resolution camera capture
- **Audio** - Multi-channel audio recording
- **mmWave** - Millimeter wave radar sensing
- **Skeleton** - RGB-extracted skeleton tracking via **ViTPose** (cross-platform: CUDA / Apple MPS / CPU)

This platform enables researchers and developers to collect rich, synchronized multimodal datasets for various applications including human activity recognition, gesture detection, and environmental sensing.

Vomee synchronizes multimodal signals via the host computer's timestamp. Hardware-level synchronization is also supported by integrating a micro controller for precise sampling frequency control and avoiding the inter-sensor interference when using multiple mmWave sensors.

## Quick Start

### Prerequisites
- Python 3.8+ (developed on 3.9)
- GPU optional — pose estimation auto-selects **CUDA → Apple MPS → CPU**
- Compatible hardware sensors (TI IWR series) for mmWave capture

### Installation

```bash
# Clone the repository
git clone https://github.com/weixijia/Vomee.git
cd Vomee

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scriptsctivate

# Install dependencies
pip install -r requirements.txt
```

### AI Agent / New-Session Handover (cross-platform: macOS · Ubuntu · Windows)

Opening a **new Claude Code session** (or any AI assistant) to set up & run Vomee on a fresh machine? **macOS (Apple Silicon) and Ubuntu are first-class targets; Windows is supported.** Paste the prompt below:

> Set up the **Vomee** repository on my machine and launch it.
> 1. Detect my OS (macOS / Windows / Linux).
> 2. Python env (conda preferred). **On macOS you may reuse an existing env, e.g. `conda activate pose`**; otherwise `conda create -n vomee python=3.11 -y && conda activate vomee` (Python 3.11–3.13 all fine — mediapipe was removed, so there is no Python ceiling).
> 3. Install deps: `pip install -r requirements.txt` (PySide6, torch, torchvision, ultralytics, filterpy, scipy, scikit-image, matplotlib, ffmpeg-python, opencv-python, numpy, Pillow, and `pyserial` for the mmWave UART). Also install the **ffmpeg binary**: macOS `brew install ffmpeg`, Ubuntu `sudo apt install ffmpeg`.
> 4. GPU auto-selects. Pose runs **CUDA → Apple MPS → CPU**. The **mmWave FFT runs on PyTorch — CUDA on NVIDIA, CPU on Apple Silicon/elsewhere** (torch.fft is unsupported on MPS), with a NumPy fallback. **Do NOT install CuPy** — it is NVIDIA-only and no longer required.
> 5. No manual model download needed: the smallest weights (`vitpose-s-wholebody.pth`, `yolov8n.pt`) **auto-download into `./models/` on first launch**.
> 6. Run `python main.py` and report any errors. On macOS, grant camera permission when prompted.
> 7. **mmWave radar (TI AWR1843 + DCA1000):** read **[`mmwave_pure_python/SETUP.md`](mmwave_pure_python/SETUP.md)** §0 first (network: static IP `192.168.33.30`; UDP `rmem` tuning). **Current capture workflow (2026-06-22):** bring the radar up once in **mmWave Studio (Windows)** with `StartFrame` numFrames=0 (infinite) so radar + DCA1000 stream autonomously, then hand the stream to your capture host **without power-cycling the radar** (reboot to Ubuntu, or move the type-C hub to another host — e.g. a MacBook), and just run **`python main.py`** (receive-only + camera are the **default**; add `--no-camera` for a headless mmWave-only view). Frame loss is eliminated by an off-GIL C receiver (`core/mmwave_capture_c.py`; fpga_udp patch in `mmwave_pure_python/patches/`) — 11.4 fps under load, zero kernel packet loss, complete-frames-only (no interpolation). RD orientation matches the trained model via `config.MMWAVE_RD_FLIP_RANGE = True`. (Starting the radar from Python instead is `python main.py --trigger` — parked; see SETUP.md.)

**Required packages** (`requirements.txt`): `PySide6`, `torch`, `torchvision`, `ultralytics`, `filterpy`, `scipy`, `scikit-image`, `matplotlib`, `ffmpeg-python`, `opencv-python`, `numpy`, `Pillow`, `pyserial`. Plus the **ffmpeg binary** (`brew`/`apt`). Optional: `cupy-cuda1x` (NVIDIA-only mmWave FFT fast-path; not required — PyTorch handles it cross-platform).

## Features

### Synchronized Data Capture
- **Temporal Alignment**: Precise timestamp synchronization across all modalities
- **Hardware-level Sync**: Micro controller integration for precise sampling frequency control
- **Multi-mmWave Support**: Avoid inter-sensor interference when using multiple mmWave sensors
- **Flexible Configuration**: Customizable sensor parameters and recording settings

### Data Export Formats
- **Video**: MP4, AVI with configurable resolution and frame rates
- **Audio**: WAV, MP3 with multi-channel support
- **mmWave**: HDF5 format with radar point clouds and processing metadata
- **Skeleton**: JSON format with per-person 2D keypoints `[x, y, confidence]`, tagged with backend, dataset, and active keypoint group

## Pose Estimation

Skeleton tracking uses **ViTPose**, running cross-platform (**CUDA → Apple MPS → CPU**, auto-selected). The keypoint group can be switched live from the control panel or via a CLI flag.

### Backend
- **ViTPose** — YOLOv8 person detection + SORT tracking + Vision-Transformer 2D keypoints (vendored under `pose_studio_engine/`). The smallest model (`vitpose-s`) runs on **CUDA → Apple MPS → CPU** automatically.

> ViTPose is a **2D** pose estimator — it outputs `(x, y, confidence)` per keypoint, no depth. For 3D, lift the 2D keypoints with a separate model, use multi-view triangulation, or fuse with the mmWave/depth modalities.

### Keypoint groups (ViTPose wholebody)
The wholebody model emits 133 keypoints; you choose which group is **drawn and recorded** (this is a display/record filter — model speed is set by the model size, not the group count):

| Group | Keypoints | Contents |
|-------|-----------|----------|
| `body` *(default)* | 23 | 17 body + 6 feet |
| `body_face` | 91 | body + 68-point face mesh |
| `body_hands` | 65 | body + 42 hand joints |
| `wholebody` | 133 | body + face + hands |

### Models
The smallest weights (`vitpose-s-wholebody.pth`, `yolov8n.pt`) live in `./models/` and **auto-download on first launch** if absent. Model weights are git-ignored.

### Configuration
Defaults live in `config.py` under `POSE_PARAMS` (backend, model size, dataset, keypoint group, device). Override at launch:

```bash
python main.py --keypoint-group body
```

## Interface

Vomee ships a desktop dashboard built with **PySide6 + Qt Quick (QML)**:

- **Live preview on launch** — the camera and radar heatmaps stream the moment the app opens; **Start** only begins *recording* (it no longer gates the preview).
- **Layout** — camera on the left with a live telemetry HUD (engine · device · FPS · sync · frames); Range-Doppler and Range-Azimuth heatmaps stacked on the right; all controls in the top bar.
- **Live controls** — toggle the skeleton, switch keypoint group, and start/stop recording without restarting.

```bash
python main.py
```

## Hardware Requirements

### Recommended Setup
- **Camera**: USB 3.0 or higher (1080p @ 30fps)
- **Microphone**: USB or 3.5mm audio input
- **mmWave Radar**: Texas Instruments IWR6843 or similar
- **Depth Camera**: Intel RealSense, Azure Kinect, or similar

## Citation

If you use Vomee in your research, please cite our paper:

```bibtex
@inproceedings{10.1145/3737904.3768536,
  author = {Wei, Xijia and Fang, Yuan and Chetty, Kevin and Cho, Youngjun and Bianchi-Berthouze, Nadia},
  title = {Vomee: A Multimodal Sensing Platform for Video, Audio, mmWave and Skeleton Data Capturing},
  year = {2025},
  isbn = {9798400719813},
  publisher = {Association for Computing Machinery},
  address = {New York, NY, USA},
  url = {https://doi.org/10.1145/3737904.3768536},
  doi = {10.1145/3737904.3768536},
  booktitle = {Proceedings of the 2025 ACM Workshop on Access Networks with Artificial Intelligence},
  pages = {36--40},
  numpages = {5},
  keywords = {mmWave Sensing, Human Activity Recognition, Multimodal Motion Capture},
  series = {MobiCom '25}
}
```

## Contributing

We welcome contributions!

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License.

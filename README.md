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
- **Skeleton** - RGB-extracted skeleton tracking

This platform enables researchers and developers to collect rich, synchronized multimodal datasets for various applications including human activity recognition, gesture detection, and environmental sensing.

Vomee synchronizes multimodal signals via the host computer's timestamp. Hardware-level synchronization is also supported by integrating a micro controller for precise sampling frequency control and avoiding the inter-sensor interference when using multiple mmWave sensors.

## Quick Start

### Prerequisites
- Python 3.8 or higher
- CUDA-capable GPU (recommended)
- Compatible hardware sensors (TI IWR series)

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
- **Skeleton**: JSON format with 3D joint coordinates and confidence scores

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

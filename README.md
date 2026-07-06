<div align="center">

<img src="assets/logo.svg" width="60" alt="mSense OS" />

# mSense OS

**The full stack behind mmWave intelligence.**

Controllable sensing hardware · synchronized raw multimodal data · radar-native foundation models.

[![Website](https://img.shields.io/badge/website-live-003c33)](https://weixijia.github.io/mSense-OS/)
[![Built with](https://img.shields.io/badge/built%20with-HTML%20%2B%20CSS-17171c)](#tech-stack)
[![Design system](https://img.shields.io/badge/design-cohere--inspired-ff7759)](DESIGN.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-1863dc)](LICENSE)

<img src="assets/hero.png" width="880" alt="mSense OS — The full stack behind mmWave intelligence." />

</div>

---

## Overview

This repository holds the **official website** for **mSense OS**, a full-stack, self-controlled
mmWave sensing platform. We turn mmWave radar from coarse detection into rich spatial and human
intelligence — by controlling the sensing hardware, the synchronized raw data, and the radar-native
models built on top of it.

> Off-the-shelf hardware gives you a sensor. Full-stack control lets us design a sensing system.

## The stack

| Layer | What it is | Why it matters |
|-------|------------|----------------|
| **01 · Hardware** | Custom radar platform, PCB & capture design, expandable RGB/RGB-D/LiDAR/IMU/RTK modules, hardware-level sync | Direct access to the raw signal path — no OEM/SDK ceiling |
| **02 · Data** | Synchronized raw RA/RD/RAD streams with cross-modal supervision, collected across scenes | A raw, time-aligned data engine no processed output can reproduce |
| **03 · Model** | DopplerMAE encoder + DopplerVLM radar-language foundation model | Radar-native intelligence trained on the platform's own data |
| **04 · Applications** | HAR, pose/rehab, driving, drone detection, industrial safety | One platform philosophy, many sensing domains |

## Why hardware control matters

Most commercial mmWave systems expose **processed outputs** (sparse point clouds, coarse detection),
not the rich raw signals advanced AI needs. Because mSense OS controls the whole stack, it adapts to
each customer's real constraints across four dimensions:

- **Signal fidelity** — raw-data access, RA/RD/RAD, frame rate, and synchronization tuned to the task.
- **Deployment environment** — radar placement, sensor mix, and calibration tuned per scene.
- **Cost & form factor** — low-cost, research, vehicle, and high-resolution kits.
- **Privacy & data policy** — RGB/skeleton as development-time supervision; camera-free at deployment.

## The website (this repo)

A fast, dependency-free static page presenting the platform narrative: the problem, full-stack
hardware capability, use-case design, the raw-data engine, the foundation-model pipeline, the data
flywheel, the platform offering, and the partner ask.

> **Design note:** the site is intentionally **typographic and diagram-led — no photographic or
> mocked product imagery.** Visuals are functional line icons and CSS-drawn diagrams only.

### Tech stack

- **Static & dependency-free** — a single `index.html` plus `styles.css`. No build step, no framework.
- **Design system** — [`DESIGN.md`](DESIGN.md), a cohere-inspired reference: stark white editorial
  canvas, deep green-black product bands, monumental tight display type, rounded cards, near-black
  pill CTAs, coral editorial accent. **Read it before changing any UI.**
- **Typography** — Space Grotesk (display) + Inter (UI) via Google Fonts, with system fallbacks.

### Local development

```bash
git clone https://github.com/weixijia/mSense-OS.git
cd mSense-OS
python3 -m http.server 8000     # → http://localhost:8000
```

### Deployment

Served via **GitHub Pages** (Settings → Pages → *Deploy from a branch* · `main` / root) at
[weixijia.github.io/mSense-OS](https://weixijia.github.io/mSense-OS/). Any static host works.

## Project structure

```
mSense-OS/
├── index.html        # hero · problem · hardware · use-case · data engine · model · flywheel · platform · why · partner
├── styles.css        # design tokens + components mapped from DESIGN.md
├── DESIGN.md         # cohere-inspired design reference (keep in sync as the site evolves)
├── assets/
│   ├── hero.png      # README hero (real render of the live site)
│   └── logo.svg      # brand glyph
└── README.md
```

## Contributing

1. Read [`DESIGN.md`](DESIGN.md) — the source of truth for tokens, components, and tone.
2. Keep the site static, dependency-free, and **free of mocked/photographic product imagery** —
   functional line icons and CSS diagrams only.
3. Preserve the display/UI type split and the flat, whitespace-led layout.

## License

Released under the [MIT License](LICENSE).

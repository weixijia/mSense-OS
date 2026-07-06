# mSense OS — official website

The marketing site for **mSense OS**, a multimodal sensing platform that captures video, audio,
mmWave radar, and skeletal motion in a single time-synchronized stream — GPU-accelerated,
frame-accurate, and research-ready.

## Stack

- Static, dependency-free: `index.html` + `styles.css`.
- Design system: see [`DESIGN.md`](DESIGN.md) (cohere-inspired) — read it before changing any UI.
- Fonts: Space Grotesk (display) + Inter (UI) via Google Fonts, with system fallbacks.

## Develop

Open `index.html` directly, or serve locally:

```bash
python3 -m http.server 8000
# → http://localhost:8000
```

## Deploy

Any static host works (GitHub Pages, Netlify, Cloudflare Pages). For GitHub Pages, enable Pages
on the default branch — the site is served from the repository root.

## Structure

| File | Purpose |
|------|---------|
| `index.html` | Single-page site: hero, modalities, performance, pipeline, sync, footer |
| `styles.css` | Design tokens + components mapped from `DESIGN.md` |
| `DESIGN.md` | Design reference for coding agents; keep it in sync as the site evolves |

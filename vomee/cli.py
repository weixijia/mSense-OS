"""Vomee command-line entry.

    python -m vomee                       # GUI (camera + RD/RA), like the legacy app
    python -m vomee --trigger             # GUI + pure-Python radar trigger
    python -m vomee --headless --record   # no GUI, record all enabled streams
    python -m vomee --camera-only         # GUI, no radar
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vomee", description="Vomee multimodal mmWave sensing platform")
    ap.add_argument("--trigger", action="store_true", help="trigger the radar from Python (no mmWave Studio)")
    ap.add_argument("--camera-only", action="store_true", help="run without the radar")
    ap.add_argument("--no-camera", action="store_true", help="run without the camera")
    ap.add_argument("--headless", action="store_true", help="run the pipeline without the GUI")
    ap.add_argument("--record", action="store_true", help="(headless) start recording immediately")
    ap.add_argument("--duration", type=float, default=None, help="(headless) seconds to run, then stop")
    ap.add_argument("--pose-backend", default=None, choices=["vitpose"], help="pose backend override")
    ap.add_argument("--keypoint-group", default=None,
                    choices=["body", "body_face", "body_hands", "wholebody"], help="keypoint group override")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.headless:
        from .app import run_headless
        return run_headless(trigger=args.trigger, no_camera=args.no_camera,
                            record=args.record, duration=args.duration)
    from .gui.runner import run_gui
    return run_gui(trigger=args.trigger, camera_only=args.camera_only, no_camera=args.no_camera,
                   pose_backend=args.pose_backend, keypoint_group=args.keypoint_group)


if __name__ == "__main__":
    sys.exit(main())

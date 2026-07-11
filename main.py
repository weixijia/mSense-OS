"""
mSense OS — Multi-Modal Data Capture System

Main application entry point (PySide6 + Qt Quick / QML UI). Integrates a TI
IWR1843 mmWave radar (received live over UDP), a webcam with ViTPose skeleton
overlay, and synchronized recording.

The radar is brought up once by mmWave Studio and then streams autonomously;
this app is RECEIVE-ONLY — it binds the data port and assembles frames, and
never configures or resets the radar.

Usage:
    python main.py
"""

import sys
import time
import argparse
from pathlib import Path

# Apple Silicon: allow any pose-pipeline op unsupported on the MPS backend to fall back
# to CPU. Set before torch is imported. (The mmWave FFT never uses MPS — see mmwave_processor.)
import os
os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtCore import QUrl

import config as _cfg
from config import POSE_PARAMS, CAMERA_PARAMS
from core.pose import (POSE_BACKENDS, POSE_BACKEND_LABELS,
                       KEYPOINT_GROUPS, KEYPOINT_GROUP_LABELS)
from gui.qml_bridge import FrameView, AppController


def parse_args():
    parser = argparse.ArgumentParser(description='mSense OS — Multi-Modal Data Capture System')
    parser.add_argument('--camera-only', action='store_true',
                        help='Run in camera-only mode (no mmWave radar)')
    parser.add_argument('--no-camera', action='store_true',
                        help='Run without camera (mmWave only)')
    parser.add_argument('--recording-dir', type=str, default='./recordings',
                        help='Base directory for recordings (default: ./recordings)')
    parser.add_argument('--camera-device', type=int, default=None,
                        help='Camera device ID (default: from config, usually 0)')
    parser.add_argument('--pose-backend', type=str, default=None,
                        choices=['vitpose'],
                        help='Pose backend (default: vitpose)')
    parser.add_argument('--keypoint-group', type=str, default=None,
                        choices=['body', 'body_face', 'body_hands', 'wholebody'],
                        help='Keypoint group (default: from config, usually body)')
    return parser.parse_args()


def main():
    args = parse_args()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("mSense OS")
    app.setOrganizationName("mSense OS")

    # ── controller + backend objects ────────────────────────────
    from core.mmwave_processor import MmWaveProcessor
    from recording.recorder import Recorder
    from recording.file_writer import FileWriter

    controller = AppController()
    # RD/RA range-axis orientation MUST match the orientation the ML model was trained on.
    # Explicit config flag (verified byte-for-byte against the training data); a wrong value
    # silently corrupts model input. See config.MMWAVE_RD_FLIP_RANGE.
    flip_range = getattr(_cfg, 'MMWAVE_RD_FLIP_RANGE', False)
    controller.set_mmwave_processor(MmWaveProcessor(flip_range=flip_range))
    controller.set_recorder(Recorder(args.recording_dir))

    file_writer = FileWriter()
    file_writer.start()
    controller.set_file_writer(file_writer)

    # mmWave capture (unless camera-only). Prefer the off-GIL C receiver (fpga_udp
    # udp_frame_*): it drains the kernel UDP buffer in a C thread with the GIL released,
    # so recording/FFT/GUI load can't starve it and drop real packets. Falls back to the
    # Python receiver if fpga_udp is not built (e.g. macOS, or Windows without the
    # extension). Neither path fabricates data.
    mmwave_capture = None
    if not args.camera_only:
        try:
            from core.mmwave_capture_c import MmWaveCaptureC
            mmwave_capture = MmWaveCaptureC()
            mmwave_capture.start()
            controller.set_mmwave_capture(mmwave_capture)
            print("mmWave capture initialized (off-GIL C receiver)")
        except Exception as e:
            print(f"[mmWave] C receiver unavailable ({e}); falling back to the Python receiver")
            try:
                from core.mmwave_capture import MmWaveCapture
                mmwave_capture = MmWaveCapture()
                mmwave_capture.start()
                controller.set_mmwave_capture(mmwave_capture)
                print("mmWave capture initialized (Python receiver)")
            except Exception as e2:
                print(f"Warning: Could not initialize mmWave capture: {e2}")

    # camera capture (unless no-camera)
    camera_capture = None
    if not args.no_camera:
        try:
            print("Initializing camera capture...")
            from core.camera_capture import CameraCapture
            camera_capture = CameraCapture(
                device_id=args.camera_device,
                enable_skeleton=True,
                pose_backend=args.pose_backend,
                keypoint_group=args.keypoint_group,
            )
            camera_capture.start()
            controller.set_camera_capture(camera_capture)

            timeout = 5.0
            start = time.time()
            while not camera_capture.is_ready and time.time() - start < timeout:
                time.sleep(0.1)
            print("Camera ready" if camera_capture.is_ready else "Warning: camera not ready in time")
        except Exception as e:
            import traceback
            print(f"Warning: Could not initialize camera: {e}")
            traceback.print_exc()
            camera_capture = None

    # ── QML engine ───────────────────────────────────────────────
    qmlRegisterType(FrameView, "MSense", 1, 0, "FrameView")

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", controller)
    ctx.setContextProperty("POSE_BACKENDS", list(POSE_BACKENDS))
    ctx.setContextProperty("POSE_BACKEND_LABELS", [POSE_BACKEND_LABELS[b] for b in POSE_BACKENDS])
    ctx.setContextProperty("KEYPOINT_GROUPS", list(KEYPOINT_GROUPS))
    ctx.setContextProperty("KEYPOINT_GROUP_LABELS", [KEYPOINT_GROUP_LABELS[g] for g in KEYPOINT_GROUPS])
    ctx.setContextProperty("DEFAULT_BACKEND", args.pose_backend or POSE_PARAMS['backend'])
    ctx.setContextProperty("DEFAULT_GROUP", args.keypoint_group or POSE_PARAMS['keypoint_group'])
    # Native display aspect ratios (width / height) so each view hugs its content.
    ctx.setContextProperty("CAMERA_ASPECT", CAMERA_PARAMS['width'] / CAMERA_PARAMS['height'])
    ctx.setContextProperty("HEATMAP_ASPECT", 1.0)  # RD/RA are ~square (256x256)

    qml_path = Path(__file__).parent / "gui" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        print("Error: failed to load QML UI")
        sys.exit(1)

    # Go live immediately (preview before any Start press).
    controller.start_preview()

    exit_code = app.exec()

    # ── cleanup ──────────────────────────────────────────────────
    print("Shutting down...")
    controller.shutdown()
    # Tear down the QML window/engine while the backend context object is
    # still alive, so trailing binding re-evaluations don't warn about a
    # null `backend` during teardown. deleteLater() posts a DeferredDelete
    # event that must be flushed explicitly (processEvents skips it).
    from PySide6.QtCore import QEvent
    for obj in engine.rootObjects():
        obj.deleteLater()
    engine.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if mmwave_capture:
        mmwave_capture.stop()
    if camera_capture:
        camera_capture.stop()
    if file_writer:
        file_writer.stop()
        file_writer.join(timeout=2.0)
    print("Goodbye!")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

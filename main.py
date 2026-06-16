"""
Vomee Multi-Modal Data Capture System

Main application entry point (PySide6 + Qt Quick / QML UI). Integrates TI IWR1843
mmWave radar, webcam with ViTPose / MediaPipe skeleton overlay, and synchronized
recording.

Usage:
    python main.py
"""

import sys
import time
import argparse
from pathlib import Path

# IMPORTANT: import MediaPipe before heavy GPU libs (torch) to avoid loader clashes.
try:
    import mediapipe
    _ = mediapipe.solutions.pose
    _ = mediapipe.solutions.drawing_utils
    _ = mediapipe.solutions.drawing_styles
    print(f"[Init] MediaPipe {mediapipe.__version__} pre-loaded")
except Exception as e:
    print(f"[Init] MediaPipe preload skipped: {e}")

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtCore import QUrl

from config import POSE_PARAMS, CAMERA_PARAMS
from core.pose import (POSE_BACKENDS, POSE_BACKEND_LABELS,
                       KEYPOINT_GROUPS, KEYPOINT_GROUP_LABELS)
from gui.qml_bridge import FrameView, AppController


def parse_args():
    parser = argparse.ArgumentParser(description='Vomee Multi-Modal Data Capture System')
    parser.add_argument('--camera-only', action='store_true',
                        help='Run in camera-only mode (no mmWave radar)')
    parser.add_argument('--no-camera', action='store_true',
                        help='Run without camera (mmWave only)')
    parser.add_argument('--recording-dir', type=str, default='./recordings',
                        help='Base directory for recordings (default: ./recordings)')
    parser.add_argument('--camera-device', type=int, default=None,
                        help='Camera device ID (default: from config, usually 0)')
    parser.add_argument('--pose-backend', type=str, default=None,
                        choices=['vitpose', 'mediapipe'],
                        help='Pose backend (default: from config, usually vitpose)')
    parser.add_argument('--keypoint-group', type=str, default=None,
                        choices=['body', 'body_face', 'body_hands', 'wholebody'],
                        help='Keypoint group (default: from config, usually body)')
    return parser.parse_args()


def main():
    args = parse_args()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Vomee")
    app.setOrganizationName("Vomee")

    # ── controller + backend objects ────────────────────────────
    from core.mmwave_processor import MmWaveProcessor
    from recording.recorder import Recorder
    from recording.file_writer import FileWriter

    controller = AppController()
    controller.set_mmwave_processor(MmWaveProcessor())
    controller.set_recorder(Recorder(args.recording_dir))

    file_writer = FileWriter()
    file_writer.start()
    controller.set_file_writer(file_writer)

    # mmWave capture (unless camera-only)
    mmwave_capture = None
    if not args.camera_only:
        try:
            from core.mmwave_capture import MmWaveCapture
            mmwave_capture = MmWaveCapture()
            mmwave_capture.start()
            controller.set_mmwave_capture(mmwave_capture)
            print("mmWave capture initialized")
        except Exception as e:
            print(f"Warning: Could not initialize mmWave capture: {e}")

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
    qmlRegisterType(FrameView, "Vomee", 1, 0, "FrameView")

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

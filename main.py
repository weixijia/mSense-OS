"""
Vomee Multi-Modal Data Capture System

Main application entry point (PySide6 + Qt Quick / QML UI). Integrates TI IWR1843
mmWave radar, webcam with ViTPose skeleton overlay, and synchronized
recording.

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
    parser.add_argument('--trigger', action='store_true',
                        help='Trigger the radar from Python (no mmWave Studio). '
                             'Sends the .cfg over UART + configures DCA1000.')
    parser.add_argument('--trigger-cfg', type=str, default=None,
                        help='Radar .cfg for --trigger (default: config MMWAVE_TRIGGER cfg_file)')
    parser.add_argument('--trigger-com', type=str, default=None,
                        help='Radar CLI UART port for --trigger (default: config, e.g. COM4)')
    parser.add_argument('--no-trigger', action='store_true',
                        help='RECEIVE-ONLY: never touch the radar (overrides --trigger and config '
                             'enable). Use when the radar was already started by mmWave Studio and is '
                             'streaming — main.py just receives the live UDP. Avoids resetting/killing '
                             'an in-progress stream.')
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

    # ── pure-Python radar trigger (replaces mmWave Studio) ───────
    # Must run BEFORE MmWaveProcessor()/MmWaveCapture read ADC_PARAMS, so the
    # frame size matches the .cfg (numLoops -> chirps) automatically.
    import config as _cfg
    trig = dict(_cfg.MMWAVE_TRIGGER)
    triggered = False
    if args.no_trigger and (args.trigger or trig.get('enable')):
        print("[trigger] --no-trigger set: skipping radar trigger (RECEIVE-ONLY; will not touch the "
              "radar). Capturing whatever is already streaming to :4098.")
    if (args.trigger or trig.get('enable')) and not args.no_trigger:
        from core import mmwave_trigger
        com = args.trigger_com or trig['com_port']
        baud = trig.get('baud', 921600)
        cfg_file = args.trigger_cfg or trig['cfg_file']
        json_file = trig['json_file']
        print(f"[trigger] starting radar from Python: cfg={cfg_file} com={com}@{baud}")
        try:
            n_loops = mmwave_trigger.trigger(com=com, baud=baud, cfg_file=cfg_file, json_file=json_file)
            if n_loops:
                _cfg.ADC_PARAMS['chirps'] = n_loops  # keep frame size consistent
                print(f"[trigger] ADC_PARAMS['chirps'] set to {n_loops} (from frameCfg)")
            else:
                print(f"[trigger] WARNING: could not parse frameCfg numLoops from {cfg_file}; "
                      f"using ADC_PARAMS['chirps']={_cfg.ADC_PARAMS['chirps']} — frame size may "
                      "mismatch the radar and break the reshape if they differ.")
            triggered = True
        except Exception as e:
            import traceback
            print(f"[trigger] FAILED: {e}")
            traceback.print_exc()

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Vomee")
    app.setOrganizationName("Vomee")

    # ── controller + backend objects ────────────────────────────
    from core.mmwave_processor import MmWaveProcessor
    from recording.recorder import Recorder
    from recording.file_writer import FileWriter

    controller = AppController()
    # RD/RA range orientation. MUST match the orientation the ML model was trained on (mmWave Studio
    # data). mmWave-Studio-sourced frames (received via --no-trigger) are range-mirrored vs the
    # pure-Python capture, but whether to flip depends on what the *training* pipeline produced — so
    # this is an explicit config flag (default False = preserved fft.py orientation), NOT auto-flipped.
    # Confirm against a training-data RD sample before changing. See config.MMWAVE_RD_FLIP_RANGE.
    flip_range = getattr(_cfg, 'MMWAVE_RD_FLIP_RANGE', False)
    controller.set_mmwave_processor(MmWaveProcessor(flip_range=flip_range))
    controller.set_recorder(Recorder(args.recording_dir))

    file_writer = FileWriter()
    file_writer.start()
    controller.set_file_writer(file_writer)

    # mmWave capture (unless camera-only). Prefer the off-GIL C receiver (fpga_udp
    # udp_read_thread): it drains the kernel UDP buffer in a C thread with the GIL released,
    # so recording/FFT/GUI load can't starve it and drop real packets (see ultragoal
    # frame-loss-zero). Falls back to the pure-Python receiver if fpga_udp is unavailable
    # (e.g. macOS without the built extension). Neither path fabricates data.
    mmwave_capture = None
    if not args.camera_only:
        try:
            from core.mmwave_capture_c import MmWaveCaptureC
            mmwave_capture = MmWaveCaptureC()
            mmwave_capture.start()
            controller.set_mmwave_capture(mmwave_capture)
            print("mmWave capture initialized (off-GIL C receiver)")
        except Exception as e:
            print(f"[mmWave] C receiver unavailable ({e}); falling back to pure-Python receiver")
            try:
                from core.mmwave_capture import MmWaveCapture
                mmwave_capture = MmWaveCapture()
                mmwave_capture.start()
                controller.set_mmwave_capture(mmwave_capture)
                print("mmWave capture initialized (pure-Python)")
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
    if triggered and trig.get('stop_on_exit'):
        try:
            from core import mmwave_trigger
            mmwave_trigger.stop_radar(com=args.trigger_com or trig['com_port'],
                                      baud=trig.get('baud', 115200))
            print("[trigger] sensorStop sent")
        except Exception as e:
            print(f"[trigger] stop_radar skipped: {e}")
    if camera_capture:
        camera_capture.stop()
    if file_writer:
        file_writer.stop()
        file_writer.join(timeout=2.0)
    print("Goodbye!")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

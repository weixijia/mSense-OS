"""Run the rebuilt pipeline with the QML GUI (reusing the existing Main.qml).

Composition for the GUI app: build the pipeline (mmWave + camera sources, finalized DSP,
recorder), attach the :class:`BusController`, load the unchanged ``gui/qml/Main.qml``, and
start. The GUI is optional — see :func:`vomee.app.run_headless` for the no-GUI path.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from typing import Optional

from ..config import AppConfig
from ..core.logging import get_logger

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_log = get_logger("gui.runner")


def run_gui(config: Optional[AppConfig] = None, *, trigger: bool = False,
            camera_only: bool = False, no_camera: bool = False,
            pose_backend: Optional[str] = None, keypoint_group: Optional[str] = None) -> int:
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # Apple Silicon pose fallback
    config = config or AppConfig.from_legacy()
    if pose_backend or keypoint_group:
        config = replace(config, pose=replace(
            config.pose,
            backend=pose_backend or config.pose.backend,
            keypoint_group=keypoint_group or config.pose.keypoint_group,
        ))

    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType

    from core.pose import (KEYPOINT_GROUP_LABELS, KEYPOINT_GROUPS,  # noqa: E402
                           POSE_BACKEND_LABELS, POSE_BACKENDS)
    from gui.qml_bridge import FrameView  # reuse the existing FrameView item

    from ..pipeline import Pipeline
    from ..processing.mmwave_dsp import MmWaveDSP
    from ..sinks.recorder import TOPICS, Recorder
    from ..sources.camera import CameraSource
    from ..sources.mmwave import MmWaveSource
    from .controller import BusController

    app = QGuiApplication(sys.argv)
    app.setApplicationName("Vomee")
    app.setOrganizationName("Vomee")

    pipeline = Pipeline(config)
    _log.info("compute: %s", pipeline.compute.describe())

    cam_src = None
    if not camera_only:
        mmw_src = MmWaveSource(config, trigger=(trigger or config.trigger.enable))
        if mmw_src._do_trigger:
            try:
                mmw_src.trigger_now()  # sets ADC chirps BEFORE constructing DSP/capture
            except Exception:
                _log.exception("radar trigger failed; continuing without live radar")
        pipeline.add_processor(MmWaveDSP())
        pipeline.add_source(mmw_src)
    if not no_camera:
        cam_src = CameraSource(config)
        pipeline.add_source(cam_src)

    recorder = Recorder(config, compute=pipeline.compute)
    pipeline.add_sink(recorder, TOPICS)

    controller = BusController(pipeline, recorder=recorder, camera_source=cam_src)

    qmlRegisterType(FrameView, "Vomee", 1, 0, "FrameView")
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    ctx.setContextProperty("backend", controller)
    ctx.setContextProperty("POSE_BACKENDS", list(POSE_BACKENDS))
    ctx.setContextProperty("POSE_BACKEND_LABELS", [POSE_BACKEND_LABELS[b] for b in POSE_BACKENDS])
    ctx.setContextProperty("KEYPOINT_GROUPS", list(KEYPOINT_GROUPS))
    ctx.setContextProperty("KEYPOINT_GROUP_LABELS", [KEYPOINT_GROUP_LABELS[g] for g in KEYPOINT_GROUPS])
    ctx.setContextProperty("DEFAULT_BACKEND", config.pose.backend)
    ctx.setContextProperty("DEFAULT_GROUP", config.pose.keypoint_group)
    ctx.setContextProperty("CAMERA_ASPECT", config.camera.width / config.camera.height)
    ctx.setContextProperty("HEATMAP_ASPECT", 1.0)

    qml_path = os.path.join(_ROOT, "gui", "qml", "Main.qml")
    engine.load(QUrl.fromLocalFile(qml_path))
    if not engine.rootObjects():
        _log.error("failed to load QML UI: %s", qml_path)
        return 1

    pipeline.start()
    controller.start_preview()
    code = app.exec()

    # Tear down the QML window/engine while the backend context object is still alive,
    # so trailing binding re-evaluations don't warn about a null `backend` during teardown
    # (matches the legacy app's shutdown handling).
    from PySide6.QtCore import QEvent
    for obj in engine.rootObjects():
        obj.deleteLater()
    engine.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    pipeline.stop()
    return code

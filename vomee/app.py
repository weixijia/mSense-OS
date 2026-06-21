"""Application composition — build a :class:`Pipeline` from config.

In this scaffold stage the pipeline is created empty (no concrete sources yet);
later rebuild stories register the mmWave/camera sources, DSP/pose processors, the
recorder sink, and feature stubs. Keeping this thin and declarative is deliberate: it is
the one place wiring lives, so adding a capability is a localized change.
"""
from __future__ import annotations

import time
from typing import Optional

from .config import AppConfig
from .core.logging import get_logger
from .pipeline import Pipeline

_log = get_logger("app")


def build_pipeline(config: Optional[AppConfig] = None) -> Pipeline:
    """Construct the pipeline. Uses legacy ``config.py`` values when present so the new
    app matches the old one during migration."""
    config = config or AppConfig.from_legacy()
    pipeline = Pipeline(config)
    # Concrete components are registered in later rebuild stories:
    #   pipeline.add_source(MmWaveSource(config)); pipeline.add_processor(MmWaveDSP(config))
    #   pipeline.add_source(CameraSource(config)); pipeline.add_sink(Recorder(config), [...])
    #   pipeline.add_feature(<heartbeat / action model>)
    return pipeline


def run_headless(config: Optional[AppConfig] = None, *, trigger: bool = False,
                 no_camera: bool = False, record: bool = False,
                 duration: Optional[float] = None) -> int:
    """Run the full capture/processing/recording pipeline with NO GUI.

    Demonstrates that the platform is GUI-optional (the headless data-collection path).
    Runs until ``duration`` seconds elapse (if given) or Ctrl-C.
    """
    config = config or AppConfig.from_legacy()
    from .processing.mmwave_dsp import MmWaveDSP
    from .sinks.recorder import TOPICS, Recorder
    from .sources.camera import CameraSource
    from .sources.mmwave import MmWaveSource

    pipeline = Pipeline(config)
    _log.info("headless | compute: %s", pipeline.compute.describe())

    mmw_src = MmWaveSource(config, trigger=(trigger or config.trigger.enable))
    if mmw_src._do_trigger:
        try:
            mmw_src.trigger_now()  # set ADC chirps before constructing the DSP
        except Exception:
            _log.exception("radar trigger failed")
    pipeline.add_processor(MmWaveDSP())
    pipeline.add_source(mmw_src)
    if not no_camera:
        pipeline.add_source(CameraSource(config))

    recorder = Recorder(config, compute=pipeline.compute)
    pipeline.add_sink(recorder, TOPICS)

    pipeline.start()
    if record:
        recorder.start_session(note="headless")
    try:
        t0 = time.time()
        while duration is None or (time.time() - t0) < duration:
            time.sleep(0.2)
    except KeyboardInterrupt:
        _log.info("interrupted")
    finally:
        pipeline.stop()
    return 0

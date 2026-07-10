"""mmWave radar source — wraps the FINALIZED trigger + DCA1000 capture UNCHANGED.

Optionally runs ``core.mmwave_trigger.trigger()`` (pure-Python radar start over UART +
DCA1000 UDP), then streams raw-ADC frames from ``core.mmwave_capture.MmWaveCapture`` onto
the bus as :data:`Topic.RADAR_RAW`. No protocol/timing/orientation changes — a thin
adapter over the finalized acquisition code.

Ordering note: when triggering, ``core.mmwave_trigger.trigger()`` auto-sets
``config.ADC_PARAMS['chirps']`` from the cfg's frameCfg numLoops (exactly as the legacy
``main.py`` did). The pipeline therefore triggers (via this source) BEFORE constructing
the DSP processor/capture so all of them read a consistent frame size.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Optional

from ..core.bus import FrameBus
from ..core.logging import get_logger
from ..core.types import Frame, Topic
from ..sources.base import Source

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_log = get_logger("source.mmwave")


class MmWaveSource(Source):
    """Publishes raw ADC frames; optionally triggers the radar first."""

    topic = Topic.RADAR_RAW

    def __init__(self, config, trigger: Optional[bool] = None):
        self.config = config
        self._do_trigger = config.trigger.enable if trigger is None else trigger
        self._cap = None
        self._thread = None
        self._running = False
        self._triggered = False
        self.n_loops = None

    def trigger_now(self) -> Optional[int]:
        """Run the finalized pure-Python trigger; returns parsed numLoops (or None).

        Call this BEFORE constructing the DSP/capture so ADC_PARAMS['chirps'] is set."""
        from core import mmwave_trigger  # finalized, unchanged
        import config as _legacy
        t = self.config.trigger
        n = mmwave_trigger.trigger(com=t.com_port, baud=t.baud, cfg_file=t.cfg_file, json_file=t.json_file)
        if n:
            _legacy.ADC_PARAMS['chirps'] = n  # keep frame size consistent (as legacy main.py)
        self._triggered = True
        self.n_loops = n
        return n

    def start(self, bus: FrameBus) -> None:
        if self._do_trigger and not self._triggered:
            self.trigger_now()
        from core.mmwave_capture import MmWaveCapture  # finalized, unchanged
        self._cap = MmWaveCapture()
        self._cap.start()
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=(bus,), daemon=True, name="mmwave-source")
        self._thread.start()
        _log.info("mmWave source started (triggered=%s, numLoops=%s)", self._triggered, self.n_loops)

    def _loop(self, bus: FrameBus) -> None:
        while self._running:
            frame, ts, num, lost = self._cap.get_frame()
            if isinstance(frame, str):  # "wait new frame" / "bufferOverWritten"
                time.sleep(0.005)
                continue
            bus.publish(Frame(Topic.RADAR_RAW, ts, num, frame, {"lost_packets": lost}))

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None:
            try:
                self._cap.stop()
            except Exception:
                _log.exception("capture stop error")
            self._cap = None
        if self._triggered and self.config.trigger.stop_on_exit:
            try:
                from core import mmwave_trigger
                mmwave_trigger.stop_radar(com=self.config.trigger.com_port, baud=self.config.trigger.baud)
            except Exception:
                _log.exception("stop_radar error")
        self._triggered = False

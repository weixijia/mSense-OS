"""Vomee — multimodal mmWave sensing platform (rebuilt, industrial-standard).

Layered, decoupled architecture::

    Sources ──► FrameBus ──► Processing / Sinks / Features ──► (optional) GUI

with a single ``ComputeManager`` (CUDA → MPS → CPU) and a composition-root
``Pipeline``. The finalized pure-Python mmWave workflow (radar trigger + DCA1000
UDP capture + 3D-FFT → RD/RA/DA) is wrapped **unchanged**.

See ``docs/REBUILD_PLAN.md`` for the full design and phased delivery.
"""

from .pipeline import Pipeline
from .app import build_pipeline, run_headless

__version__ = "0.1.0-dev"
__all__ = ["Pipeline", "build_pipeline", "run_headless", "__version__"]

"""Central compute/device manager — the single place that decides where work runs.

Priority: **CUDA → Apple MPS → CPU**. The mmWave FFT has a special policy: ``torch.fft``
is unimplemented on the MPS backend, so the FFT runs on CUDA when available else CPU
(never MPS), with a NumPy fallback if torch is absent. This mirrors the finalized
``core/mmwave_processor`` behavior so the wrapped DSP stays byte-identical.

Every GPU-capable consumer (pose, the action model, the DSP) asks the *same* manager, so
hardware use is maximized from one place. Ubuntu/CUDA first; macOS/MPS best-effort.
"""
from __future__ import annotations

from .logging import get_logger

_log = get_logger("compute")


class ComputeManager:
    def __init__(self, prefer: str | None = None) -> None:
        try:
            import torch  # noqa: F401
            self._torch = torch
        except Exception:
            self._torch = None
        self.device = self._select_device(prefer)
        # FFT follows the SELECTED device, but never MPS (torch.fft is unimplemented there):
        # cuda only if we actually chose cuda; mps/cpu -> cpu.
        self.fft_device = "cuda" if self.device == "cuda" else "cpu"

    # -- backend probing -------------------------------------------------------
    def _cuda(self) -> bool:
        return bool(self._torch and self._torch.cuda.is_available())

    def _mps(self) -> bool:
        t = self._torch
        return bool(t and getattr(t.backends, "mps", None) and t.backends.mps.is_available())

    def _select_device(self, prefer: str | None) -> str:
        if not self._torch:
            if prefer in ("cuda", "mps"):
                _log.warning("requested device %r but torch is unavailable; using cpu", prefer)
            return "cpu"
        if prefer == "cpu":
            return "cpu"
        if prefer == "cuda" and self._cuda():
            return "cuda"
        if prefer == "mps" and self._mps():
            return "mps"
        if prefer in ("cuda", "mps"):
            _log.warning("requested device %r unavailable; falling back to auto-detect", prefer)
        # auto: CUDA -> MPS -> CPU
        if self._cuda():
            return "cuda"
        if self._mps():
            return "mps"
        return "cpu"

    # -- public API ------------------------------------------------------------
    @property
    def has_torch(self) -> bool:
        return self._torch is not None

    def fft_backend(self) -> str:
        """``'torch-cuda'`` | ``'torch-cpu'`` | ``'numpy'`` — used by the mmWave DSP."""
        if not self._torch:
            return "numpy"
        return "torch-cuda" if self.fft_device == "cuda" else "torch-cpu"

    def describe(self) -> str:
        gpu = ""
        if self.device == "cuda":
            try:
                gpu = f" ({self._torch.cuda.get_device_name(0)})"
            except Exception:
                pass
        return f"device={self.device}{gpu} fft={self.fft_backend()} torch={self.has_torch}"

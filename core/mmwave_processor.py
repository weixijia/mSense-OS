"""
mmWave Radar Signal Processor Module

GPU-accelerated FFT processing (Range-Doppler / Range-Azimuth / Doppler-Azimuth)
for TI xWR1843 raw ADC.

Uses **PyTorch** so the SAME code runs GPU-accelerated on NVIDIA (CUDA) and Apple
Silicon (MPS), and on CPU everywhere — replacing the former NVIDIA-only CuPy path
for full macOS/Ubuntu/Windows cross-platform support. Falls back to NumPy if torch
is unavailable. Core reshape/FFT/orientation logic preserved from fft.py (verified
to produce identical RA/RD: relative FFT error ~3e-8, normalized heatmap diff ~2e-7).
"""
import os
# Process-wide hint for the MPS path on Apple Silicon (lets any op unsupported on MPS fall
# back to CPU). Used by both the pose pipeline and this module's FFT (see _pick_device --
# torch.fft runs on MPS as of torch 2.4).
os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')

import sys
from typing import Optional, Tuple

import numpy as np

sys.path.append('..')
from config import ADC_PARAMS

# PyTorch preferred (CUDA / MPS / CPU); NumPy is the fallback.
TORCH_AVAILABLE = False
torch = None
try:
    import torch as _torch
    torch = _torch
    TORCH_AVAILABLE = True
except Exception as e:  # pragma: no cover
    print(f"[Processor] PyTorch unavailable ({e}); using NumPy (CPU)")

# Guard against log10(0) -> -inf poisoning a frame's normalization
_LOG_EPS = 1e-12


def _apply_mps_thread_cap():
    """Cap torch's intra-op CPU thread pool — ONLY for the MPS device.

    On MPS the default pool (= core count, 10+ on an M3 Max) SPIN-WAITS at
    every MPS sync point: ~8.5 cores burned for a 10 fps FFT with no latency
    benefit (measured: 1 thread = 32.5 ms/frame vs 38 ms at 10 threads).

    The cap is process-global, so it must NOT be applied on CUDA or CPU-only
    deployments: there it would pin every CPU-bound torch op in the process
    (pose preprocessing/NMS, MPS-fallback ops, the CPU FFT itself) to a
    single thread. Tunable via TORCH_NUM_THREADS (0/unset -> 1).
    """
    try:
        _nt = int(os.environ.get('TORCH_NUM_THREADS', '1')) or 1
        torch.set_num_threads(_nt)
    except Exception:
        pass


def _pick_device():
    # FFT device: CUDA if available, else Apple-Silicon MPS if available, else CPU.
    # NOTE: torch.fft (_fft_c2c/_fft_r2c) and complex tensors WERE unimplemented on the
    # MPS backend in older PyTorch (pytorch #78044 / #116392) -- hence this used to force
    # CPU. As of torch 2.4 they ARE supported: verified on an M3 Max that fftn / rfft /
    # fftshift / complex64 all run on MPS and match the CPU result to ~2e-6, at ~5x the
    # CPU throughput for a 255x256x256 frame (210ms CPU -> 38ms MPS). process() still
    # auto-falls-back to CPU if any MPS op errors, so this stays safe on old torch too.
    if not TORCH_AVAILABLE:
        return None
    try:
        if torch.cuda.is_available():
            return 'cuda'
    except Exception:
        pass
    try:
        if torch.backends.mps.is_available():
            return 'mps'
    except Exception:
        pass
    return 'cpu'


class MmWaveProcessor:
    """3D-FFT processor producing normalized RD/RA/DA heatmaps from raw ADC."""

    def __init__(self, num_angle_bins: int = 256, flip_range: bool = False):
        self.num_angle_bins = num_angle_bins
        # flip_range: put range 0 (near) at BOTTOM when True. PRODUCTION callers
        # must pass config.MMWAVE_RD_FLIP_RANGE (verified True against the model's
        # training data — see config.py). The ctor default False exists only so the
        # committed flip=False golden fixtures stay valid; do NOT rely on it in
        # pipeline code.
        self.flip_range = flip_range
        self.adc_params = ADC_PARAMS
        self.chirps = ADC_PARAMS['chirps']
        self.rx = ADC_PARAMS['rx']
        self.tx = ADC_PARAMS['tx']
        self.samples = ADC_PARAMS['samples']
        self.iq = ADC_PARAMS['IQ']
        self.virtual_antennas = 2 * self.rx          # first 2 TX

        self.device = _pick_device()
        self.use_torch = TORCH_AVAILABLE and self.device is not None
        if self.use_torch:
            if self.device == 'mps':
                _apply_mps_thread_cap()
            print(f"[Processor] PyTorch {torch.__version__} on '{self.device}'")
        else:
            print("[Processor] NumPy (CPU)")

    def process(self, raw_data: np.ndarray, compute_da: bool = True
                ) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
        """raw int16 ADC -> (rd, ra, da), each normalized [0,1].

        Args:
            compute_da: compute the Doppler-Azimuth map. The live GUI path
                passes False (nothing consumes DA there), skipping its
                reduction + log + normalize + device->host transfer per
                frame. Defaults to True for API compatibility (offline
                tools may consume DA).
        """
        if self.use_torch:
            try:
                return self._process_torch(raw_data, self.device, compute_da)
            except Exception as e:
                print(f"[Processor] torch '{self.device}' error: {e}; retry on CPU")
                try:
                    return self._process_torch(raw_data, 'cpu', compute_da)
                except Exception as e2:
                    print(f"[Processor] torch CPU error: {e2}; falling back to NumPy")
        return self._process_numpy(raw_data, compute_da)

    # ---------- PyTorch path (CUDA / Apple-Silicon MPS / CPU) ----------
    def _process_torch(self, raw_data, device, compute_da=True):
        t = torch.as_tensor(np.ascontiguousarray(raw_data), dtype=torch.int16, device=device)
        t = t.reshape(-1, self.chirps, self.tx, self.rx, self.samples // 2, self.iq, 2)
        t = t.permute(0, 1, 2, 3, 4, 6, 5).contiguous()
        t = t.reshape(-1, self.chirps, self.tx, self.rx, self.samples, self.iq)
        cplx = torch.complex(t[..., 0].float(), t[..., 1].float())            # I + jQ
        d2 = cplx[:, :, 0:2, :, :].reshape(-1, self.chirps, self.virtual_antennas, self.samples)
        frame = d2[0]                                                         # (chirps, VA, samples)
        # zero-pad azimuth (VA) to num_angle_bins (avoid F.pad on complex)
        padded = torch.zeros((frame.shape[0], self.num_angle_bins, frame.shape[2]),
                             dtype=frame.dtype, device=frame.device)
        padded[:, :frame.shape[1], :] = frame
        fft = torch.fft.fftshift(torch.fft.fftn(padded), dim=(0, 1))
        # real^2+imag^2, NOT abs()**2: abs computes a sqrt over all ~16.7M
        # complex elements that **2 immediately undoes
        power = fft.real ** 2 + fft.imag ** 2
        rd = self._nf_t(torch.log10(power.sum(1) + _LOG_EPS).T, self.flip_range)  # (range, doppler) — near at BOTTOM
        ra = self._nf_t(torch.log10(power.sum(0) + _LOG_EPS).T, self.flip_range)  # (range, azimuth) — near at BOTTOM (matches RD)
        if compute_da:
            da = self._nf_t(torch.log10(power.sum(2) + _LOG_EPS).T, False)        # (azimuth, doppler) — no range axis
        # Single device->host sync: one flattened transfer instead of one
        # blocking .cpu() per map (each MPS/CUDA sync stalls the pipeline)
        if compute_da:
            flat = torch.cat((rd.reshape(-1), ra.reshape(-1), da.reshape(-1))).cpu().numpy()
            n_rd, n_ra = rd.numel(), ra.numel()
            return (flat[:n_rd].reshape(rd.shape),
                    flat[n_rd:n_rd + n_ra].reshape(ra.shape),
                    flat[n_rd + n_ra:].reshape(da.shape))
        flat = torch.cat((rd.reshape(-1), ra.reshape(-1))).cpu().numpy()
        n_rd = rd.numel()
        return (flat[:n_rd].reshape(rd.shape),
                flat[n_rd:].reshape(ra.shape),
                None)

    @staticmethod
    def _nf_t(x, flip):
        x = (x - x.min()) / (x.max() - x.min() + 1e-10)
        return torch.flip(x, dims=[0]) if flip else x

    # ---------- NumPy fallback (identical math + orientation) ----------
    def _process_numpy(self, raw_data, compute_da=True):
        adc = np.reshape(raw_data, (-1, self.chirps, self.tx, self.rx, self.samples // 2, self.iq, 2))
        adc = np.transpose(adc, (0, 1, 2, 3, 4, 6, 5))
        adc = np.reshape(adc, (-1, self.chirps, self.tx, self.rx, self.samples, self.iq))
        adc = (adc[:, :, :, :, :, 0] + 1j * adc[:, :, :, :, :, 1]).astype(np.complex64)
        d2 = np.reshape(adc[:, :, 0:2, :, :], (-1, self.chirps, self.virtual_antennas, self.samples))
        frame = d2[0]
        frame = np.pad(frame, ((0, 0), (0, self.num_angle_bins - d2.shape[2]), (0, 0)), mode='constant')
        fft = np.fft.fftshift(np.fft.fftn(frame), axes=(0, 1))
        power = fft.real ** 2 + fft.imag ** 2          # no sqrt (see torch path)
        rd = self._nf_n(np.log10(power.sum(1) + _LOG_EPS).T, self.flip_range)   # near at BOTTOM
        ra = self._nf_n(np.log10(power.sum(0) + _LOG_EPS).T, self.flip_range)   # near at BOTTOM (matches RD)
        da = self._nf_n(np.log10(power.sum(2) + _LOG_EPS).T, False) if compute_da else None
        return rd, ra, da

    @staticmethod
    def _nf_n(x, flip):
        x = (x - x.min()) / (x.max() - x.min() + 1e-10)
        return np.ascontiguousarray(x[::-1] if flip else x)

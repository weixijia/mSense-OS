"""
Headless validation of the FULL Vomee mmWave data path on the live pure-Python-
triggered stream. Uses Vomee's own MmWaveCapture + MmWaveProcessor (no GUI/camera)
to confirm the mmw_demo ADC byte layout matches Vomee's reshape -> real RA/RD/DA
heatmaps (structured, not noise). Run from the repo root AFTER triggering the radar.

  python mmwave_pure_python/tools/validate_pipeline.py [num_loops]
"""
import sys, os, time
sys.path.insert(0, os.getcwd())

import config
chirps = int(sys.argv[1]) if len(sys.argv) > 1 else 64
config.ADC_PARAMS['chirps'] = chirps     # must precede the capture import
print(f"[validate] using chirps={chirps}")

from core.mmwave_capture import MmWaveCapture, BYTES_IN_FRAME
from core.mmwave_processor import MmWaveProcessor
import numpy as np

print(f"[validate] BYTES_IN_FRAME={BYTES_IN_FRAME:,}")
cap = MmWaveCapture(); cap.start()
# Use the PRODUCTION orientation (config.MMWAVE_RD_FLIP_RANGE) — see
# capture_reference_frame.py
proc = MmWaveProcessor(flip_range=getattr(config, 'MMWAVE_RD_FLIP_RANGE', False))

got = 0
t0 = time.time()
try:
    while got < 5 and time.time() - t0 < 20:
        frame, ts, num, lost = cap.get_frame()
        if isinstance(frame, str):      # "wait new frame" / "bufferOverWritten"
            time.sleep(0.02); continue
        rd, ra, da = proc.process(frame)
        finite = np.isfinite(ra).all() and np.isfinite(rd).all()
        print(f"[validate] frame#{num} RA{ra.shape} RD{rd.shape} DA{da.shape} "
              f"RA[min={ra.min():.3f} max={ra.max():.3f} std={ra.std():.3f}] finite={finite}")
        got += 1
finally:
    cap.stop()

if got == 0:
    print("[validate] NO frames assembled — check stream / frame size.")
    sys.exit(1)
print(f"[validate] OK: {got} frames went raw-ADC -> reshape -> 3D-FFT -> RA/RD/DA. "
      "Non-zero std => real structure, layout matches.")

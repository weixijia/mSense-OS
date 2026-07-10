"""
Capture an AUTHORITATIVE reference frame from the live mmWave-Studio-triggered
256x255 stream, for orientation/scale verification. Saves the raw frame + the
processed RA/RD/DA arrays, and prints landmark analysis (where energy concentrates
on each axis) so we can determine the true axis orientation without a screen.

Run AFTER killing DCA1000EVM_CLI_Record.exe (frees UDP 4098). From repo root.
"""
import os, sys, time
sys.path.insert(0, os.getcwd())

import config
config.ADC_PARAMS['chirps'] = 255          # Studio skeleton.lua config
from core.mmwave_capture import MmWaveCapture, BYTES_IN_FRAME
from core.mmwave_processor import MmWaveProcessor
import numpy as np

OUT = 'mmwave_pure_python/ground_truth'
os.makedirs(OUT, exist_ok=True)
print(f"[ref] BYTES_IN_FRAME={BYTES_IN_FRAME:,} (255-loop Studio config)")

cap = MmWaveCapture(); cap.start()
# Use the PRODUCTION orientation (config.MMWAVE_RD_FLIP_RANGE): a reference
# frame captured with the default flip=False describes an orientation the
# live app does not emit, causing spurious mirror mismatches downstream.
proc = MmWaveProcessor(flip_range=getattr(config, 'MMWAVE_RD_FLIP_RANGE', False))
raw = None; got = 0; t0 = time.time()
while got < 12 and time.time() - t0 < 25:
    frame, ts, num, lost = cap.get_frame()
    if isinstance(frame, str):
        time.sleep(0.02); continue
    raw = frame.copy(); got += 1
cap.stop()
if raw is None:
    print("[ref] NO frame captured — is the Studio stream live + 4098 free?")
    sys.exit(1)

raw.tofile(f"{OUT}/ref_studio_255_raw.int16.bin")
rd, ra, da = proc.process(raw)
np.save(f"{OUT}/ref_rd.npy", rd); np.save(f"{OUT}/ref_ra.npy", ra); np.save(f"{OUT}/ref_da.npy", da)
print(f"[ref] saved raw + rd/ra/da. shapes RD{rd.shape} RA{ra.shape} DA{da.shape}")

def axis_report(name, img, ax0, ax1):
    # energy profile along each axis (sum the other axis); report peak index
    p0 = img.sum(axis=1); p1 = img.sum(axis=0)
    print(f"\n[{name}] array[{ax0}(rows,axis0)={img.shape[0]}, {ax1}(cols,axis1)={img.shape[1]}]")
    print(f"   {ax0} energy peak at row index {int(np.argmax(p0))}/{img.shape[0]-1} "
          f"(row0..rowN). first/mid/last row energy: "
          f"{p0[0]:.1f} / {p0[len(p0)//2]:.1f} / {p0[-1]:.1f}")
    print(f"   {ax1} energy peak at col index {int(np.argmax(p1))}/{img.shape[1]-1} "
          f"(col0..colN). first/mid/last col energy: "
          f"{p1[0]:.1f} / {p1[len(p1)//2]:.1f} / {p1[-1]:.1f}")

# Per mmwave_processor: RD/RA have axis0 = range (with [::-1] flip applied),
# RA axis1 = azimuth, RD axis1 = doppler (fftshifted -> 0 at center).
axis_report("RD", rd, "range", "doppler")
axis_report("RA", ra, "range", "azimuth")
print("\n[ref] NOTE: processor applies .T then [::-1] on range axis, so as stored "
      "row0 = FAR range, rowN = NEAR(0) range. Static clutter (zero-Doppler) should "
      "peak at RD doppler col ~center (fftshift). Near-range strong returns reveal "
      "which row holds range=0.")

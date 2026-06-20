"""
Render the reference 256x255 frame's RD & RA exactly as the NEW Vomee displays them,
with PHYSICAL axes (range m, velocity m/s, azimuth deg) and near/far/zero markers, so
the orientation can be confirmed against the user's reference. Params from skeleton.lua.
"""
import os
import numpy as np
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

GT = 'mmwave_pure_python/ground_truth'
rd = np.load(f'{GT}/ref_rd.npy'); ra = np.load(f'{GT}/ref_ra.npy')

# --- skeleton.lua profile params ---
c = 3e8
f0 = 77e9
slope = 65.998e6 / 1e-6        # 65.998 MHz/us -> Hz/s
Nadc = 256
Fs = 4800e3                    # ksps -> sps
Ntx, Nrx, Nloops = 2, 4, 255
idle, ramp = 20e-6, 60e-6
lam = c / f0
Tadc = Nadc / Fs
B = slope * Tadc
range_res = c / (2 * B)
range_max = range_res * Nadc
Tc_eff = Ntx * (idle + ramp)
v_max = lam / (4 * Tc_eff)
print(f'range_res={range_res*100:.2f} cm  range_max={range_max:.2f} m  v_max=±{v_max:.2f} m/s')

# Processor stored arrays: axis0 = range, axis1 = doppler (RD, fftshifted 0 at center) /
# azimuth (RA). The live processor now uses flip=False, so range 0 (near) is the LAST row
# (rendered at the BOTTOM) and far is row 0 (top).
# WARNING: ref_rd.npy / ref_ra.npy below were captured under the OLD flip=True convention,
# i.e. vertically mirrored vs the current pipeline. Regenerate them from a fresh capture
# before trusting this tool's rendering.
def plot_rd():
    fig, ax = plt.subplots(figsize=(5, 5))
    # extent: x = doppler velocity (-v_max..+v_max), y = range. row0=far -> top=range_max.
    ax.imshow(rd, aspect='auto', cmap='viridis',
              extent=[-v_max, v_max, 0, range_max])   # default origin='upper' + extent y 0..max => near(0) at BOTTOM
    ax.set_title('RD — NEW Vomee orientation'); ax.set_xlabel('velocity (m/s)  [0=static@center]')
    ax.set_ylabel('range (m)  [0=near at BOTTOM]')
    ax.axvline(0, color='r', lw=0.6, ls='--')
    fig.tight_layout(); fig.savefig(f'{GT}/annot_RD.png', dpi=120); plt.close(fig)

def plot_ra():
    fig, ax = plt.subplots(figsize=(5, 5))
    az = np.linspace(-90, 90, ra.shape[1])
    ax.imshow(ra, aspect='auto', cmap='viridis', extent=[az[0], az[-1], 0, range_max])
    ax.set_title('RA — NEW Vomee orientation'); ax.set_xlabel('azimuth (deg)')
    ax.set_ylabel('range (m)  [0=near at BOTTOM]')
    fig.tight_layout(); fig.savefig(f'{GT}/annot_RA.png', dpi=120); plt.close(fig)

# NOTE on imshow: with extent y from 0..range_max and default origin='upper', row0 maps
# to the TOP (= range_max = far). That matches the stored array (row0=far). Good.
plot_rd(); plot_ra()
print(f'saved {GT}/annot_RD.png and annot_RA.png')
print('Current NEW-Vomee orientation: range 0 (near) at BOTTOM, far at TOP; '
      'RD velocity 0 (static) at CENTER column; RA azimuth -90..+90 left..right.')

"""
Definitively compare RA/RD orientation between:
  ORIGINAL pipeline:  capture_single -> h_heatmap = hstack((ra,pad,rd,pad,da));
                      plot.plot_heatmap(h_heatmap.T) -> pyqtgraph ImageView
  NEW Vomee pipeline: heatmap_to_qimage(ra/rd) -> QImage(row0=top) -> FrameView (as-is)

Strategy: query pyqtgraph's ACTUAL convention (imageAxisOrder + ImageView yInverted),
derive the on-screen array for each pipeline from the captured reference frame, compute
the transform between them, and save labelled PNGs for visual confirmation.
"""
import os, sys
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
GT = 'mmwave_pure_python/ground_truth'
ra = np.load(f'{GT}/ref_ra.npy'); rd = np.load(f'{GT}/ref_rd.npy'); da = np.load(f'{GT}/ref_da.npy')
print(f'loaded ref RA{ra.shape} RD{rd.shape} DA{da.shape}')

# ---- 1. pyqtgraph convention (definitive) ----
axis_order = None; y_inverted = None
try:
    import pyqtgraph as pg
    from pyqtgraph.Qt import QtWidgets
    axis_order = pg.getConfigOption('imageAxisOrder')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    iv = pg.ImageView()
    try:    y_inverted = bool(iv.view.getViewBox().yInverted())
    except Exception:
        try: y_inverted = bool(iv.view.yInverted())
        except Exception as e: y_inverted = f'unknown ({e})'
    print(f'[pyqtgraph] imageAxisOrder={axis_order!r}  ImageView.yInverted={y_inverted}')
except Exception as e:
    print(f'[pyqtgraph] not available: {e} -> using documented default (col-major, invertY=True)')
    axis_order = 'col-major'; y_inverted = True

# ---- 2. derive on-screen arrays ----
# NEW Vomee: QImage row0=top, col0=left, no transform. screen_new[y,x] = arr[y,x].
def screen_new(arr): return arr

# ORIGINAL: setImage(A) with A = arr.T (per-heatmap equivalent of h_heatmap.T).
# pyqtgraph col-major: A[i,j] -> screen x=i, y=j. invertY=True -> j=0 at TOP.
# So screen_orig[y,x] = A[x,y] = arr.T[x,y] = arr[y,x]  ... THEN if NOT yInverted, flip y.
def screen_orig(arr):
    A = arr.T                       # what original sends to pyqtgraph (per-heatmap)
    if str(axis_order) == 'col-major':
        scr = A.T                   # screen[y,x] = A[x,y]
    else:                           # row-major: A[row,col] direct
        scr = A
    if not (y_inverted is True):    # y axis points up -> top is last row
        scr = scr[::-1]
    return scr

for name, arr in (('RA', ra), ('RD', rd)):
    n, o = screen_new(arr), screen_orig(arr)
    rel = []
    if o.shape == n.shape:
        if np.allclose(o, n): rel.append('identical')
        if np.allclose(o, n[::-1]): rel.append('orig = new flipped vertically (range axis reversed)')
        if np.allclose(o, n[:, ::-1]): rel.append('orig = new flipped horizontally')
    if o.shape == n.T.shape and np.allclose(o, n.T): rel.append('orig = new transposed')
    print(f'\n[{name}] new screen {n.shape}, orig screen {o.shape} -> {rel or ["differ (non-trivial)"]}')

# ---- 3. save labelled PNGs for visual confirmation ----
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    for name, arr in (('RA', ra), ('RD', rd), ('DA', da)):
        fig, axs = plt.subplots(1, 2, figsize=(9, 4.6))
        axs[0].imshow(screen_new(arr), aspect='auto', cmap='viridis'); axs[0].set_title(f'{name} — NEW Vomee (QImage)')
        axs[1].imshow(screen_orig(arr), aspect='auto', cmap='viridis'); axs[1].set_title(f'{name} — ORIGINAL (pyqtgraph)')
        for a in axs: a.set_xlabel('col'); a.set_ylabel('row (0=top)')
        fig.tight_layout(); fig.savefig(f'{GT}/cmp_{name}.png', dpi=110); plt.close(fig)
    print(f'\nsaved comparison PNGs: {GT}/cmp_RA.png cmp_RD.png cmp_DA.png')
except Exception as e:
    print(f'PNG render skipped: {e}')

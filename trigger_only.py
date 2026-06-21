"""
Trigger the radar with the pure-Python method, then EXIT — leaving the radar
chirping and the DCA1000 streaming raw ADC to UDP :4098 (exactly like the old
"mmWave Studio + kill the DCA1000 process" trick, but with zero TI software).

CONTROL-VARIABLE EXPERIMENT
---------------------------
This keeps Vomee's *capture / startup* identical to the pure-Python pipeline, but
lets a DIFFERENT app visualize the same stream — so we can tell whether the RD
"vertical lines" come from the capture/startup or from the visualization.

  # terminal 1 (this repo root):
  python trigger_only.py
  # ...wait for it to print "streaming", then in terminal 2 (the OLD PyQt5 viz):
  cd C:\\Users\\Chuang Yu\\Desktop\\Vomee
  python main.py --no-camera          # heatmaps only (no camera / mediapipe)

The radar keeps streaming after this process exits (hardware state persists).
Stop it later with:
  python trigger_only.py --stop
"""
import sys
import os
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(HERE, p)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--stop', action='store_true',
                    help='Stop chirping + DCA stream and exit (does not start anything)')
    ap.add_argument('--com', default=None, help="radar CLI UART (default: config 'auto')")
    args = ap.parse_args()

    import config as cfg
    from core import mmwave_trigger
    t = dict(cfg.MMWAVE_TRIGGER)
    com = args.com or t['com_port']
    baud = t.get('baud', 921600)

    if args.stop:
        mmwave_trigger.stop_radar(com=com, baud=baud)
        print('[trigger_only] sensorStop + DCA stream_stop sent. Radar idle.')
        return

    n = mmwave_trigger.trigger(com=com, baud=baud,
                               cfg_file=_abs(t['cfg_file']), json_file=_abs(t['json_file']))
    frame_bytes = 255 * 4 * 2 * 2 * 256 * 2
    print(f"\n[trigger_only] DONE — radar chirping + DCA1000 streaming raw ADC to UDP :4098 "
          f"(numLoops={n}, frame={frame_bytes:,} B).")
    print("[trigger_only] This process now EXITS; the hardware keeps streaming.")
    print("[trigger_only] Visualize with the OLD viz to control variables:")
    print("    cd C:\\Users\\Chuang Yu\\Desktop\\Vomee")
    print("    python main.py --no-camera")
    print("[trigger_only] Stop the radar later with:  python trigger_only.py --stop")


if __name__ == '__main__':
    main()

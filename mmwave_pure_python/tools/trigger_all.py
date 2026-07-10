"""
Full pure-Python trigger: bring up IWR1843 + DCA1000 with NO mmWave Studio.

Sequence (mirrors mmWave Studio skeleton.lua, minus the SPI firmware load that
the flashed mmw_demo replaces):
  1. reset radar + FPGA (DCA1000 UDP)
  2. radar RF config over UART (.cfg, withholding sensorStart)
  3. DCA1000 config_fpga + config_record (UDP, from cf.json)
  4. DCA1000 stream_start (UDP)
  5. radar sensorStart (UART)  -> raw ADC streams over LVDS->DCA1000->UDP:4098

Leaves the radar streaming (frameCfg numFrames=0 = infinite), then releases the
config port so Vomee can bind and receive — exactly like the old Studio workflow.

Usage:
  python trigger_all.py --com COM4 --cfg ../configFiles/vomee_1843.cfg --json ../configFiles/cf.json
"""
import argparse
import time
import sys
from dca1000_control import DCA1000
from radar_uart import RadarUART


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--com', default='COM4', help='radar CLI UART (Linux: /dev/ttyACM0)')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--cfg', default='../configFiles/vomee_1843.cfg')
    ap.add_argument('--json', default='../configFiles/cf.json')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()
    verbose = not args.quiet

    dca = DCA1000()
    radar = None
    try:
        print(f"[trigger] FPGA: {dca.read_fpga_version()}")
        print(f"[trigger] alive: {dca.sys_alive_check()}")

        # 1. reset
        print("[trigger] reset radar + fpga ...")
        dca.reset_radar()
        dca.reset_fpga()
        time.sleep(1.0)

        # 2. radar RF config over UART (withhold sensorStart)
        print(f"[trigger] opening {args.com} and sending {args.cfg} ...")
        radar = RadarUART(args.com, args.baud, verbose=verbose)
        radar.send_config(args.cfg, start=False)

        # 3. DCA1000 config
        print(f"[trigger] config_fpga -> {dca.config_fpga(args.json)}")
        print(f"[trigger] config_record -> {dca.config_record(args.json)}")

        # 4. arm DCA1000
        print(f"[trigger] stream_start -> {dca.stream_start()}")
        time.sleep(0.1)

        # 5. start chirping
        print("[trigger] sensorStart ...")
        radar.start_sensor()

        print("\n[trigger] DONE. Radar is chirping; DCA1000 streaming raw ADC to "
              "192.168.33.30:4098.\n          Releasing config port. Now launch Vomee "
              "(python main.py).")
        return 0
    except Exception as e:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # release config port (4096) so Vomee can bind; leave radar running
        dca.close()
        if radar is not None:
            radar.close()


if __name__ == '__main__':
    sys.exit(main())

"""
Pure-Python IWR1843 control over the CLI UART (replaces mmWave Studio RF config).

Requires the radar running the `xwr18xx_mmw_demo` SDK firmware in functional mode
(SOP[2:0]=001). Sends the .cfg profile line-by-line, then `sensorStart` on demand.
Windows: CLI UART = XDS110 "Application/User UART" (COM4 here).
Linux: typically /dev/ttyACM0.
"""
import time
import serial


class RadarUART:
    def __init__(self, cli_port='COM4', baud=115200, verbose=True):
        self.verbose = verbose
        self.port = serial.Serial(cli_port, baud, timeout=0.3)
        time.sleep(0.2)
        self.port.reset_input_buffer()

    def _send(self, line, settle=0.05):
        self.port.write((line + '\n').encode())
        time.sleep(settle)
        resp = self.port.read(self.port.in_waiting or 1)
        if self.verbose:
            txt = resp.decode(errors='replace').strip().replace('\n', ' | ')
            print(f">>> {line:<40}  {txt}")
        return resp

    def send_config(self, cfg_path, start=False):
        """Send every cfg line. If start=False, stop before `sensorStart`
        so the DCA1000 can be armed first (recommended order)."""
        with open(cfg_path) as f:
            lines = [l.strip() for l in f]
        for line in lines:
            if not line or line.startswith('%'):
                continue
            if line == 'sensorStart' and not start:
                if self.verbose:
                    print("--- config sent (sensorStart withheld until DCA armed) ---")
                return
            # flushCfg / sensorStop need a moment longer
            self._send(line, settle=0.08 if line in ('sensorStop', 'flushCfg') else 0.05)

    def start_sensor(self):
        return self._send('sensorStart', settle=0.1)

    def stop_sensor(self):
        return self._send('sensorStop', settle=0.1)

    def close(self):
        try:
            self.port.close()
        except Exception:
            pass

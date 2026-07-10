"""
Read-only check of the radar CLI UART. Tells us whether the board is running
the xwr18xx_mmw_demo firmware (i.e. functional mode + flashed) and responding.

Run AFTER setting the board to functional mode (SOP0 only) and power-cycling,
with mmWave Studio closed.
"""
import sys
import time
import serial


def main():
    com = sys.argv[1] if len(sys.argv) > 1 else 'COM4'
    print(f"[uart] opening {com} @115200 ...")
    try:
        p = serial.Serial(com, 115200, timeout=0.5)
    except serial.SerialException as e:
        print(f"[uart] OPEN FAILED: {e}")
        return 2
    try:
        time.sleep(0.2)
        p.reset_input_buffer()
        # mmw_demo prints a banner on 'version' and echoes 'Done' on commands
        for cmd in ('', 'version', 'sensorStop'):
            p.write((cmd + '\n').encode())
            time.sleep(0.3)
            resp = p.read(p.in_waiting or 1).decode(errors='replace').strip()
            print(f"[uart] '{cmd}' -> {resp!r}")
        print("\n[uart] If you see a version banner / 'Done' / 'mmwDemo:' prompt above,"
              " mmw_demo is running and we can trigger. If blank, the board is not in"
              " functional mode or mmw_demo is not flashed.")
        return 0
    finally:
        p.close()


if __name__ == '__main__':
    sys.exit(main())

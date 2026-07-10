"""
Non-destructive DCA1000 FPGA probe. Sends ONLY read-only queries
(SYSTEM_CONNECT + READ_FPGA_VERSION). No reset, no reconfig, no start/stop.
Validates the pure-Python control half against the live FPGA.
"""
import sys
from dca1000_control import DCA1000

def main():
    print("[probe] binding 192.168.33.30:4096, target FPGA 192.168.33.180:4096 ...")
    try:
        dca = DCA1000()
    except OSError as e:
        print(f"[probe] BIND FAILED: {e}")
        print("        -> config port 4096 is held by another process "
              "(mmWave Studio / DCA1000 record still running?).")
        return 2
    try:
        alive = dca.sys_alive_check()
        print(f"[probe] SYSTEM_CONNECT -> {alive!r}")
        ver = dca.read_fpga_version()
        print(f"[probe] READ_FPGA_VERSION -> {ver!r}")
        if alive is None and ver is None:
            print("[probe] No response (timeout). FPGA reachable? cable/IP ok? "
                  "Note: a running Studio session may not echo config queries.")
            return 1
        print("[probe] OK: pure-Python DCA1000 control path can talk to the FPGA.")
        return 0
    finally:
        dca.close()

if __name__ == '__main__':
    sys.exit(main())

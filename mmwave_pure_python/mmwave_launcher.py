#!/usr/bin/env python3
"""
Standalone mmWave launcher -- NO mmWave Studio.  Cross-platform: Ubuntu / macOS
(Apple Silicon) / Windows.  Only needs:  pip install pyserial

Controls a TI AWR1843 (running the no-DSP CLI firmware) over the only two links
that matter:
  1) radar config + sensorStart/sensorStop  -> UART  (CLI .cfg, 921600)
  2) DCA1000 capture card config + start     -> Ethernet/UDP (192.168.33.x:4096)

The radar's CLI UART (XDS110 "Application/User UART", USB VID:PID 0451:BEF3) is
auto-detected, so you do not need to know the port name on any OS:
  Linux  -> /dev/ttyACM0     macOS -> /dev/cu.usbmodem*     Windows -> COMx

Start order matters: arm the DCA1000 (stream_start) BEFORE sensorStart, so no
opening frames are lost.

Usage:
    python mmwave_launcher.py <radar.cfg>            # auto-detect the radar UART
    python mmwave_launcher.py <radar.cfg> --com /dev/ttyACM0   # or force a port
    python mmwave_launcher.py --list                # list serial ports and exit
Then:  1 = start radar    2 = stop radar    q = quit   (type the key, then Enter)
"""
import argparse
import codecs
import json as _json
import os
import socket
import struct
import sys
import time

import serial
from serial.tools import list_ports

XDS110_VIDPID = (0x0451, 0xBEF3)   # TI XDS110 (App/User UART = the radar CLI port)


# ---------------- serial port auto-detection (cross-platform) ----------------
def find_radar_port():
    """Return the radar CLI UART device on Linux/macOS/Windows, or None."""
    xds = [p for p in list_ports.comports() if (p.vid, p.pid) == XDS110_VIDPID]

    def is_app_uart(p):
        blob = ' '.join(x for x in (p.description, getattr(p, 'interface', None),
                                    getattr(p, 'product', None)) if x)
        return ('Application' in blob) or ('User UART' in blob)

    cands = [p for p in xds if is_app_uart(p)] or xds
    if not cands:
        return None
    # macOS: prefer the callout device /dev/cu.* over /dev/tty.* ; otherwise lowest name.
    cands.sort(key=lambda p: (0 if str(p.device).startswith('/dev/cu.') else 1, str(p.device)))
    return cands[0].device


def list_serial_ports():
    ports = list(list_ports.comports())
    if not ports:
        print('no serial ports found')
        return
    print('serial ports:')
    for p in ports:
        extra = ' '.join(x for x in (p.description, getattr(p, 'interface', None)) if x)
        vp = f'{p.vid:04x}:{p.pid:04x}' if p.vid else '----:----'
        print(f'  {p.device:<22} [{vp}] {extra}')


# ---------------- DCA1000 control (UDP, config port 4096) ----------------
_HDR, _FTR = '5aa5', 'aaee'
_HDR_NUM, _FTR_NUM = 0xa55a, 0xeeaa
_MAX = 4096
_MAX_BYTES_PER_PACKET = 1470
_CLK_FACTOR, _CLK_PERIOD_NS = 1000, 8
_CMD = {'RESET_FPGA': '0100', 'RESET_AR_DEV': '0200', 'CONFIG_FPGA_GEN': '0300',
        'RECORD_START': '0500', 'RECORD_STOP': '0600', 'CONFIG_PACKET_DATA': '0b00',
        'READ_FPGA_VERSION': '0e00'}


class DCA1000:
    def __init__(self, static_ip='192.168.33.30', adc_ip='192.168.33.180', cfg_port=4096):
        self.dest = (adc_ip, cfg_port)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.bind((static_ip, cfg_port))

    def _cmd(self, cmd, length='0000', body='', timeout=1.0):
        self.s.settimeout(timeout)
        self.s.sendto(codecs.decode(''.join((_HDR, cmd, length, body, _FTR)), 'hex'), self.dest)
        try:
            r, _ = self.s.recvfrom(_MAX)
        except socket.timeout:
            return None
        h, _echo, val, f = struct.unpack('<HHHH', r)
        return val if (h == _HDR_NUM and f == _FTR_NUM) else None

    def config_fpga(self, j):
        log = {'raw': '01', 'multi': '02'}; lvds = {1: '01', 2: '02', '1': '01', '2': '02'}
        xfer = {'LVDSCapture': '01', 'playback': '02'}; cap = {'SDCardStorage': '01', 'ethernetStream': '02'}
        fmt = {1: '01', 2: '02', 3: '03', '1': '01', '2': '02', '3': '03'}
        c = _json.load(open(j))['DCA1000Config']
        p = (log[c['dataLoggingMode']] + lvds[c['lvdsMode']] + xfer[c['dataTransferMode']]
             + cap[c['dataCaptureMode']] + fmt[c['dataFormatMode']] + '1e')
        pl = codecs.encode(struct.pack('<H', len(codecs.decode(p, 'hex'))), 'hex').decode()
        return self._cmd(_CMD['CONFIG_FPGA_GEN'], pl, p)

    def config_record(self, j):
        c = _json.load(open(j))['DCA1000Config']
        bpp = codecs.encode(struct.pack('<H', _MAX_BYTES_PER_PACKET), 'hex').decode()
        delay = codecs.encode(struct.pack('<H', int(c['packetDelay_us'] * _CLK_FACTOR / _CLK_PERIOD_NS)), 'hex').decode()
        p = bpp + delay + '0000'
        pl = codecs.encode(struct.pack('<H', len(codecs.decode(p, 'hex'))), 'hex').decode()
        return self._cmd(_CMD['CONFIG_PACKET_DATA'], pl, p)

    def reset_radar(self): return self._cmd(_CMD['RESET_AR_DEV'])
    def reset_fpga(self):  return self._cmd(_CMD['RESET_FPGA'])
    def stream_start(self): return self._cmd(_CMD['RECORD_START'])
    def stream_stop(self):  return self._cmd(_CMD['RECORD_STOP'])

    def version(self):
        v = self._cmd(_CMD['READ_FPGA_VERSION'])
        return None if v is None else f'{v & 0x7F}.{(v >> 7) & 0x7F}'

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


# ---------------- radar UART helpers ----------------
def _drain(port, timeout=0.8):
    """Read until the CLI prompt returns (or timeout) -- keeps responses aligned."""
    end = time.time() + timeout
    buf = b''
    while time.time() < end:
        buf += port.read(port.in_waiting or 1)
        if b'mmwDemo:/>' in buf:
            break
    return buf.decode(errors='replace').replace('\r', '').replace('\n', ' ').strip()


def send_cfg(port, cfg_path, verbose=True):
    """Send every cfg line EXCEPT sensorStart (issued separately after DCA is armed)."""
    for raw in open(cfg_path):
        line = raw.strip()
        if not line or line[0] in '%#':
            continue
        if line == 'sensorStart':
            continue
        port.reset_input_buffer()
        port.write((line + '\n').encode())
        resp = _drain(port)
        if verbose:
            print(f'  >>> {line:<42} {resp}')


def uart(port, cmd, timeout=0.8):
    port.reset_input_buffer()
    port.write((cmd + '\n').encode())
    return _drain(port, timeout)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description='Standalone mmWave start/stop launcher (no mmWave Studio)')
    ap.add_argument('cfg', nargs='?', help='radar .cfg (no-DSP firmware profile)')
    ap.add_argument('--com', default='auto', help="radar CLI UART; 'auto' (default) detects the XDS110 port")
    ap.add_argument('--baud', type=int, default=921600)
    ap.add_argument('--json', default=os.path.join(here, 'configFiles', 'cf.json'), help='DCA1000 cf.json')
    ap.add_argument('--list', action='store_true', help='list serial ports and exit')
    a = ap.parse_args()

    if a.list:
        list_serial_ports(); return
    if not a.cfg:
        ap.error('a radar .cfg is required (or use --list)')

    com = a.com
    if com == 'auto':
        com = find_radar_port()
        if not com:
            print('[x] could not auto-detect the radar UART (XDS110 0451:BEF3).')
            print('    plug in the radar USB, or pass --com <port>.  Detected ports:')
            list_serial_ports()
            sys.exit(2)
        print(f'[i] auto-detected radar UART: {com}')

    try:
        port = serial.Serial(com, a.baud, timeout=0.3)
    except serial.SerialException as e:
        print(f'[x] cannot open {com}: {e}')
        print('    (Linux: add yourself to the dialout group; macOS: use /dev/cu.usbmodem*)')
        sys.exit(2)
    time.sleep(0.2); port.reset_input_buffer()
    running = {'on': False}

    def start():
        if running['on']:
            print('[!] already running -- press 2 to stop first'); return
        print('--- START: reboot radar, arm DCA1000, configure, sensorStart ---')
        dca = DCA1000()
        print(f'    DCA1000 FPGA version: {dca.version()}')
        # Reboot the radar for a clean RF state -- REQUIRED: after idle / repeated
        # start-stop, sensorStart returns Done but no data streams until a reset.
        dca.reset_radar(); dca.reset_fpga(); time.sleep(2.5)
        port.reset_input_buffer()
        send_cfg(port, a.cfg)
        r1, r2, r3 = dca.config_fpga(a.json), dca.config_record(a.json), dca.stream_start()
        print(f'    config_fpga={r1} config_record={r2} stream_start={r3}  (0 = OK)')
        time.sleep(0.1)
        print(f'    sensorStart -> {uart(port, "sensorStart")}')
        dca.close()
        running['on'] = True
        print('[OK] STARTED -- raw ADC streaming to 192.168.33.30:4098')

    def stop():
        print(f'--- STOP: sensorStop -> {uart(port, "sensorStop")}')
        running['on'] = False
        print('[OK] STOPPED')

    print(f'\nmmWave launcher  |  cfg={a.cfg}  com={com}@{a.baud}')
    print('  press  1 = start radar   2 = stop radar   q = quit   (type the key, then Enter)\n')
    try:
        while True:
            try:
                c = input('cmd> ').lstrip('﻿').strip().lower()
            except EOFError:
                break
            if c == '1':
                start()
            elif c == '2':
                stop()
            elif c in ('q', 'quit', 'exit'):
                if running['on']:
                    stop()
                break
            elif c:
                print('  ? press 1 (start), 2 (stop), or q (quit)')
    finally:
        try:
            port.close()
        except Exception:
            pass
    print('bye')


if __name__ == '__main__':
    main()

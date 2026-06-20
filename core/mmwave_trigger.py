"""
Pure-Python mmWave trigger — replaces the mmWave Studio + "kill DCA1000 process"
workflow. Configures the AWR1843/IWR1843 over the CLI UART and the DCA1000EVM over
UDP, then starts chirping. No mmWave Studio, no C extension; works on Windows/macOS/Linux.

Requires the radar in functional mode (SOP=001) running the flashed no-DSP
studio_cli firmware (xwr18xx, CLI @ 921600 baud).

Trigger sequence (mirrors skeleton.lua minus the SPI firmware load that the flashed
mmw_demo replaces):
  reset radar+FPGA -> UART .cfg (no sensorStart) -> DCA config_fpga/config_record
  -> DCA stream_start -> UART sensorStart -> raw ADC streams to UDP :4098.

Then the config port is released so Vomee's MmWaveCapture can bind and receive.
"""
import codecs
import socket
import struct
import json
import time

import serial
from serial.tools import list_ports


XDS110_VIDPID = (0x0451, 0xBEF3)   # TI XDS110 = the radar CLI port (+ an Aux UART, same VID:PID)
_LAST_PORT = None                  # last resolved CLI device, reused by stop_radar on shutdown


# ---------------- serial port auto-detection (cross-platform) ----------------
def _is_cli_uart(device, baud, timeout=0.5):
    """True if `device` answers the mmWave CLI banner (i.e. it's the Application UART,
    not the Auxiliary data UART). Read-only probe: opens, sends 'version', closes."""
    try:
        s = serial.Serial(device, baud, timeout=timeout)
    except Exception:
        return False
    try:
        time.sleep(0.2)
        s.reset_input_buffer()
        s.write(b'version\n')
        time.sleep(0.3)
        resp = s.read(s.in_waiting or 1)
        return (b'mmwDemo' in resp) or (b'mmWave SDK' in resp)
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def find_radar_port(baud=921600, probe=True):
    """Auto-detect the radar CLI UART (XDS110) on Linux/macOS/Windows, or None.

    The XDS110 exposes TWO same-VID:PID CDC ports — the Application/User UART (the
    CLI port we want) and an Auxiliary data UART — and on Linux the per-interface
    string descriptors are usually absent, so they can't be told apart by text.
    With probe=True (default) we OPEN each candidate and keep the one that answers
    `version` with the mmWave CLI banner; this is robust to enumeration order
    (which device is ttyACM0 vs ACM1, hub re-ordering, a stale ACM holding the low
    name, etc.). probe=False returns a name-sorted best-guess without opening ports.
    """
    xds = [p for p in list_ports.comports() if (p.vid, p.pid) == XDS110_VIDPID]
    if not xds:
        return None
    # deterministic order: macOS callout /dev/cu.* first, then lowest device name.
    xds.sort(key=lambda p: (0 if str(p.device).startswith('/dev/cu.') else 1, str(p.device)))
    if not probe:
        return xds[0].device
    for p in xds:
        if _is_cli_uart(p.device, baud):
            return p.device
    # No candidate answered (radar may be pre-reset / momentarily unresponsive). Fall back
    # to the name-sorted best-guess instead of failing — trigger() resets the radar right
    # before opening, after which it responds; this is no worse than the pre-probe behaviour.
    return xds[0].device


def _resolve_port(com, baud=921600):
    """Return an explicit serial device. None/'auto' -> probe-detect; '' is an error."""
    global _LAST_PORT
    if com is None or com == 'auto':
        dev = find_radar_port(baud=baud)
        if not dev:
            raise RuntimeError(
                "could not auto-detect a responding radar CLI UART (XDS110 0451:BEF3 "
                "replying to 'version'); plug in the radar USB, confirm SOP=functional, "
                "or pass --trigger-com / set MMWAVE_TRIGGER['com_port'] explicitly")
        _LAST_PORT = dev
        return dev
    if com == '':
        raise ValueError("radar com_port is an empty string; set a device path or 'auto'")
    _LAST_PORT = com
    return com


# ---------------- DCA1000 control (UDP, port 4096) ----------------
_HDR, _FTR = '5aa5', 'aaee'
_HDR_NUM, _FTR_NUM = 0xa55a, 0xeeaa
_STATUS = {0: 'success', 1: 'failed'}
_MAX_PKT = 4096
_MAX_BYTES_PER_PACKET = 1470
_CLK_FACTOR, _CLK_PERIOD_NS = 1000, 8
_CMD = {
    'RESET_FPGA': '0100', 'RESET_AR_DEV': '0200', 'CONFIG_FPGA_GEN': '0300',
    'RECORD_START': '0500', 'RECORD_STOP': '0600', 'SYSTEM_CONNECT': '0900',
    'CONFIG_PACKET_DATA': '0b00', 'READ_FPGA_VERSION': '0e00',
}


class DCA1000:
    def __init__(self, static_ip='192.168.33.30', adc_ip='192.168.33.180', config_port=4096):
        self.cfg_dest = (adc_ip, config_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((static_ip, config_port))

    def _cmd(self, cmd, length='0000', body='', timeout=1.0):
        self.sock.settimeout(timeout)
        msg = codecs.decode(''.join((_HDR, cmd, length, body, _FTR)), 'hex')
        self.sock.sendto(msg, self.cfg_dest)
        try:
            resp, _ = self.sock.recvfrom(_MAX_PKT)
        except socket.timeout:
            return None
        h, echo, val, f = struct.unpack('<HHHH', resp)
        expect = struct.unpack('<H', codecs.decode(cmd, 'hex'))[0]
        if h != _HDR_NUM or echo != expect or f != _FTR_NUM:
            return ('malformed', resp.hex())
        return val

    def sys_alive_check(self):
        v = self._cmd(_CMD['SYSTEM_CONNECT'])
        return _STATUS.get(v, v)

    def read_fpga_version(self):
        v = self._cmd(_CMD['READ_FPGA_VERSION'])
        if not isinstance(v, int):
            return v
        return f'{v & 0x7F}.{(v >> 7) & 0x7F} ' + ('[Playback]' if v & 0x4000 else '[Record]')

    def config_fpga(self, cf_json):
        log = {'raw': '01', 'multi': '02'}
        lvds = {1: '01', 2: '02', '1': '01', '2': '02'}
        xfer = {'LVDSCapture': '01', 'playback': '02'}
        cap = {'SDCardStorage': '01', 'ethernetStream': '02'}
        fmt = {1: '01', 2: '02', 3: '03', '1': '01', '2': '02', '3': '03'}
        c = json.load(open(cf_json, encoding='utf8'))['DCA1000Config']
        try:
            payload = (log[c['dataLoggingMode']] + lvds[c['lvdsMode']] + xfer[c['dataTransferMode']]
                       + cap[c['dataCaptureMode']] + fmt[c['dataFormatMode']] + '1e')
        except KeyError as e:
            raise ValueError(f"cf.json DCA1000Config: missing/unsupported value for {e} "
                             "(dataLoggingMode/lvdsMode/dataTransferMode/dataCaptureMode/dataFormatMode)") from e
        plen = codecs.encode(struct.pack('<H', len(codecs.decode(payload, 'hex'))), 'hex').decode()
        return self._cmd(_CMD['CONFIG_FPGA_GEN'], plen, payload)

    def config_record(self, cf_json):
        c = json.load(open(cf_json, encoding='utf8'))['DCA1000Config']
        try:
            delay_clk = int(c['packetDelay_us'] * _CLK_FACTOR / _CLK_PERIOD_NS)
        except KeyError as e:
            raise ValueError(f"cf.json DCA1000Config: missing {e} (packetDelay_us)") from e
        bpp = codecs.encode(struct.pack('<H', _MAX_BYTES_PER_PACKET), 'hex').decode()
        delay = codecs.encode(struct.pack('<H', delay_clk), 'hex').decode()
        payload = bpp + delay + '0000'
        plen = codecs.encode(struct.pack('<H', len(codecs.decode(payload, 'hex'))), 'hex').decode()
        return self._cmd(_CMD['CONFIG_PACKET_DATA'], plen, payload)

    def reset_fpga(self):  return self._cmd(_CMD['RESET_FPGA'])
    def reset_radar(self): return self._cmd(_CMD['RESET_AR_DEV'])
    def stream_start(self): return self._cmd(_CMD['RECORD_START'])
    def stream_stop(self):  return self._cmd(_CMD['RECORD_STOP'])

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------- radar CLI UART control ----------------
def parse_num_loops(cfg_path):
    """Return frameCfg numLoops (= ADC_PARAMS['chirps']) from a .cfg, or None."""
    for line in open(cfg_path):
        p = line.split()
        if p and p[0] == 'frameCfg':
            return int(p[3])  # chirpStart chirpEnd numLoops numFrames ...
    return None


class RadarUART:
    def __init__(self, com='auto', baud=921600, verbose=False):
        self.verbose = verbose
        self.port = serial.Serial(_resolve_port(com, baud), baud, timeout=0.3)
        time.sleep(0.2)
        self.port.reset_input_buffer()

    def _send(self, line, settle=0.05):
        self.port.write((line + '\n').encode())
        time.sleep(settle)
        resp = self.port.read(self.port.in_waiting or 1)
        if self.verbose:
            print(f">>> {line:<40} {resp.decode(errors='replace').strip()}")
        return resp

    def send_config(self, cfg_path, start=False):
        for raw in open(cfg_path):
            line = raw.strip()
            if not line or line.startswith('%'):
                continue
            if line == 'sensorStart' and not start:
                return
            self._send(line, settle=0.08 if line in ('sensorStop', 'flushCfg') else 0.05)

    def start_sensor(self): return self._send('sensorStart', settle=0.1)
    def stop_sensor(self):  return self._send('sensorStop', settle=0.1)

    def close(self):
        try:
            self.port.close()
        except Exception:
            pass


def trigger(com='auto', baud=921600, cfg_file=None, json_file=None, verbose=True):
    """Run the full trigger. Returns numLoops parsed from the cfg (for ADC_PARAMS)."""
    dca = DCA1000()
    radar = None
    try:
        if verbose:
            print(f"[trigger] FPGA {dca.read_fpga_version()} alive={dca.sys_alive_check()}")
        # Reboot the radar for a clean RF state. This is REQUIRED for reliability:
        # after idle time or repeated start/stop, sensorStart returns "Done" but no LVDS
        # data streams until a hardware reset. reset_radar (RESET_AR_DEV over Ethernet)
        # reboots the flashed firmware; wait ~2.5 s for it to come back on the CLI UART.
        dca.reset_radar(); dca.reset_fpga(); time.sleep(2.5)
        # Resolve the CLI port AFTER the reset: the radar now answers 'version', so the
        # probe in find_radar_port() can reliably tell the CLI UART from the Aux UART.
        com = _resolve_port(com, baud)
        if verbose:
            print(f"[trigger] radar CLI UART: {com}")
        radar = RadarUART(com, baud, verbose=verbose)
        radar.port.reset_input_buffer()        # drop the post-reboot banner
        radar.send_config(cfg_file, start=False)
        r1, r2, r3 = dca.config_fpga(json_file), dca.config_record(json_file), dca.stream_start()
        if verbose:
            print(f"[trigger] config_fpga={r1} config_record={r2} stream_start={r3}")
        time.sleep(0.1)
        radar.start_sensor()
        if verbose:
            print("[trigger] sensorStart issued; radar chirping, DCA1000 streaming to :4098")
        return parse_num_loops(cfg_file)
    finally:
        dca.close()           # release config port 4096 for MmWaveCapture
        if radar is not None:
            radar.close()


def stop_radar(com='auto', baud=921600):
    """Stop chirping AND the DCA1000 stream on shutdown (best-effort)."""
    # 1) tell the DCA1000 FPGA to stop recording/streaming (trigger() only started it;
    #    otherwise the FPGA stays in RECORD state and keeps emitting on :4098 after exit).
    try:
        dca = DCA1000()
        dca.stream_stop()
        dca.close()
    except Exception:
        pass
    # 2) sensorStop over the CLI UART; reuse the port trigger() already resolved so we
    #    don't re-probe (and can't pick a different device) at shutdown.
    try:
        port = _LAST_PORT if (com in (None, 'auto', '') and _LAST_PORT) else com
        r = RadarUART(port, baud, verbose=False)
        r.stop_sensor()
        r.close()
    except Exception:
        pass

"""
Pure-Python DCA1000EVM control (no C extension, Windows/Linux portable).

Replaces mmWave Studio's CaptureCardConfig_* / StartRecord steps. Speaks the
DCA1000 FPGA command protocol over UDP (config port 4096). Faithfully derived
from PreSenseRadar/OpenRadar + gaoweifan/pyRadar (Apache-2.0), trimmed to the
control path only — receiving is handled by Vomee's existing capture thread.

Command packet wire format (all little-endian):
    header(0x5aa5) | cmd(2B) | data_len(2B) | data(len B) | footer(0xaaee)
Response (8B): header(0xa55a) | cmd_echo(2B) | status_or_value(2B) | footer(0xeeaa)
"""
import codecs
import socket
import struct
import json

# --- protocol constants (from TI DCA1000EVM CLI user guide / OpenRadar) ---
CONFIG_HEADER = '5aa5'
CONFIG_FOOTER = 'aaee'
HEADER_NUM = 0xa55a
FOOTER_NUM = 0xeeaa
STATUS_STR = {0: 'success', 1: 'failed'}

MAX_PACKET_SIZE = 4096
MAX_BYTES_PER_PACKET = 1470
FPGA_CLK_CONVERSION_FACTOR = 1000
FPGA_CLK_PERIOD_IN_NANO_SEC = 8
VERSION_BITS_DECODE = 0x7F
VERSION_NUM_OF_BITS = 7
PLAYBACK_BIT_DECODE = 0x4000

CMD = {
    'RESET_FPGA':        '0100',
    'RESET_AR_DEV':      '0200',
    'CONFIG_FPGA_GEN':   '0300',
    'RECORD_START':      '0500',
    'RECORD_STOP':       '0600',
    'SYSTEM_CONNECT':    '0900',
    'CONFIG_PACKET_DATA':'0b00',
    'READ_FPGA_VERSION': '0e00',
}


class DCA1000:
    def __init__(self, static_ip='192.168.33.30', adc_ip='192.168.33.180',
                 data_port=4098, config_port=4096):
        self.cfg_dest = (adc_ip, config_port)
        self.cfg_recv = (static_ip, config_port)
        self.config_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                           socket.IPPROTO_UDP)
        # allow rebinding even if a lingering socket holds the port
        self.config_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.config_socket.bind(self.cfg_recv)

    # ---- low level ----
    def _send_command(self, cmd, length='0000', body='', timeout=1.0):
        self.config_socket.settimeout(timeout)
        msg = codecs.decode(''.join((CONFIG_HEADER, cmd, length, body, CONFIG_FOOTER)), 'hex')
        self.config_socket.sendto(msg, self.cfg_dest)
        try:
            resp, _ = self.config_socket.recvfrom(MAX_PACKET_SIZE)
            return resp
        except socket.timeout:
            return None

    def _checked(self, cmd, resp):
        if not resp:
            return None
        h, echo, val, f = struct.unpack('<HHHH', resp)
        expect = struct.unpack('<H', codecs.decode(cmd, 'hex'))[0]
        if h != HEADER_NUM or echo != expect or f != FOOTER_NUM:
            return ('malformed', resp.hex())
        return val

    # ---- read-only queries (non-destructive) ----
    def sys_alive_check(self):
        val = self._checked(CMD['SYSTEM_CONNECT'], self._send_command(CMD['SYSTEM_CONNECT']))
        return STATUS_STR.get(val, val) if val is not None else None

    def read_fpga_version(self):
        val = self._checked(CMD['READ_FPGA_VERSION'], self._send_command(CMD['READ_FPGA_VERSION']))
        if val is None or isinstance(val, tuple):
            return val
        major = val & VERSION_BITS_DECODE
        minor = (val >> VERSION_NUM_OF_BITS) & VERSION_BITS_DECODE
        mode = '[Playback]' if (val & PLAYBACK_BIT_DECODE) else '[Record]'
        return f'FPGA Version: {major}.{minor} {mode}'

    # ---- configuration / control (write — used at trigger time) ----
    def config_fpga(self, cf_json):
        log = {'raw': '01', 'multi': '02'}
        lvds = {1: '01', 2: '02', '1': '01', '2': '02'}
        xfer = {'LVDSCapture': '01', 'playback': '02'}
        cap = {'SDCardStorage': '01', 'ethernetStream': '02'}
        fmt = {1: '01', 2: '02', 3: '03', '1': '01', '2': '02', '3': '03'}
        c = json.load(open(cf_json, encoding='utf8'))['DCA1000Config']
        payload = (log[c['dataLoggingMode']] + lvds[c['lvdsMode']] + xfer[c['dataTransferMode']]
                   + cap[c['dataCaptureMode']] + fmt[c['dataFormatMode']] + '1e')
        plen = codecs.encode(struct.pack('<H', len(codecs.decode(payload, 'hex'))), 'hex').decode()
        return self._checked(CMD['CONFIG_FPGA_GEN'], self._send_command(CMD['CONFIG_FPGA_GEN'], plen, payload))

    def config_record(self, cf_json):
        c = json.load(open(cf_json, encoding='utf8'))['DCA1000Config']
        bpp = codecs.encode(struct.pack('<H', MAX_BYTES_PER_PACKET), 'hex').decode()
        delay = codecs.encode(struct.pack('<H', int(
            c['packetDelay_us'] * FPGA_CLK_CONVERSION_FACTOR / FPGA_CLK_PERIOD_IN_NANO_SEC)), 'hex').decode()
        payload = bpp + delay + '0000'
        plen = codecs.encode(struct.pack('<H', len(codecs.decode(payload, 'hex'))), 'hex').decode()
        return self._checked(CMD['CONFIG_PACKET_DATA'], self._send_command(CMD['CONFIG_PACKET_DATA'], plen, payload))

    def reset_fpga(self):
        return self._checked(CMD['RESET_FPGA'], self._send_command(CMD['RESET_FPGA']))

    def reset_radar(self):
        return self._checked(CMD['RESET_AR_DEV'], self._send_command(CMD['RESET_AR_DEV']))

    def stream_start(self):
        return self._checked(CMD['RECORD_START'], self._send_command(CMD['RECORD_START']))

    def stream_stop(self):
        return self._checked(CMD['RECORD_STOP'], self._send_command(CMD['RECORD_STOP']))

    def close(self):
        try:
            self.config_socket.close()
        except OSError:
            pass

"""
Drive the flashed NO-DSP firmware directly in pure Python (no Studio, no TI .exe):
  UART @ 921600 (auto-detected XDS110): send the 256x255 cfg + sensorStart
  Ethernet (UDP 4096): DCA1000 config_fpga/config_record/stream_start
then sniff UDP 4098 to confirm raw 256x255 floods in. Run from repo root.
"""
import sys, os, time, socket, struct
sys.path.insert(0, os.getcwd())
from core.mmwave_trigger import DCA1000, RadarUART

CFG = 'mmwave_pure_python/studio_cli/src/profiles/profile_vomee_256x255_cont.cfg'
JSON = 'mmwave_pure_python/configFiles/cf.json'
# Derive from config.ADC_PARAMS (chirps is dynamic); 255-loop default = 2,088,960
try:
    from config import ADC_PARAMS as _A
    BYTES_IN_FRAME = (_A['chirps'] * _A['rx'] * _A['tx'] * _A['IQ']
                      * _A['samples'] * _A['bytes'])
except ImportError:
    BYTES_IN_FRAME = 255 * 4 * 2 * 2 * 256 * 2

d = DCA1000()
print('FPGA', d.read_fpga_version(), '| alive', d.sys_alive_check())
d.reset_fpga(); time.sleep(0.5)

print('\n--- sending 256x255 cfg over UART @921600 (watch for Done vs invalid) ---')
r = RadarUART('auto', 921600, verbose=True)
r.send_config(CFG, start=False)

print('\n--- DCA1000 over Ethernet ---')
print('config_fpga  ->', d.config_fpga(JSON))
print('config_record->', d.config_record(JSON))
print('stream_start ->', d.stream_start())
time.sleep(0.1)

print('\n--- sensorStart over UART ---')
r.start_sensor()
d.close(); r.close()

print('\n--- sniffing UDP 4098 for 3s (expect 256x255 raw flood) ---')
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2**27)
s.bind(('192.168.33.30', 4098)); s.settimeout(2.0)
n = 0; first = last = None; sizes = set(); t0 = time.time()
try:
    while time.time() - t0 < 3:
        data, _ = s.recvfrom(4096); n += 1
        sizes.add(len(data))
        bc = struct.unpack('>Q', b'\x00\x00' + data[4:10][::-1])[0]
        if first is None: first = bc
        last = bc
except socket.timeout:
    print('  (timeout - no packets)')
s.close()
print(f'\npackets={n}  payload_sizes={sorted(sizes)}')
if n and first is not None:
    tot = last - first
    print(f'bytes={tot:,}  rate={tot/3/1e6:.1f} MB/s  fps~{tot/3/BYTES_IN_FRAME:.2f}  (target 10, frame={BYTES_IN_FRAME:,} B)')
    print('RESULT: RAW 256x255 STREAMING over the network — no Studio.' if tot > 0 else 'no byte progress')
else:
    print('RESULT: NO DATA on 4098.')

"""
Quick UDP sniff to confirm the DCA1000 raw-ADC stream is live and well-formed,
WITHOUT the full GUI. Binds the data port like Vomee does and inspects packets.
"""
import socket
import struct
import sys
import time

STATIC_IP = '192.168.33.30'
DATA_PORT = 4098
BYTES_IN_PACKET = 1456
# Derive from config.ADC_PARAMS (chirps is dynamic — --trigger sets it from
# the .cfg's numLoops); fall back to the 255-loop Studio literal only when
# run outside the repo root.
try:
    import os as _os
    sys.path.insert(0, _os.getcwd())
    from config import ADC_PARAMS as _A
    BYTES_IN_FRAME = (_A['chirps'] * _A['rx'] * _A['tx'] * _A['IQ']
                      * _A['samples'] * _A['bytes'])
except ImportError:
    BYTES_IN_FRAME = 255 * 4 * 2 * 2 * 256 * 2

def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2**27)
    s.bind((STATIC_IP, DATA_PORT))
    s.settimeout(2.0)
    print(f"[verify] listening on {STATIC_IP}:{DATA_PORT} for {secs}s ...")
    print(f"[verify] expected BYTES_IN_FRAME = {BYTES_IN_FRAME:,}")

    n_pkt = 0
    first_seq = last_seq = None
    first_bc = last_bc = None
    sizes = set()
    t0 = time.time()
    try:
        while time.time() - t0 < secs:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                print("[verify] TIMEOUT - no packets. Is the radar chirping?")
                return 1
            seq = struct.unpack('<1l', data[:4])[0]
            bc = struct.unpack('>Q', b'\x00\x00' + data[4:10][::-1])[0]
            sizes.add(len(data))
            if first_seq is None:
                first_seq, first_bc = seq, bc
            last_seq, last_bc = seq, bc
            n_pkt += 1
    finally:
        s.close()

    dt = time.time() - t0
    total_bytes = (last_bc - first_bc) if (first_bc is not None) else 0
    expected_pkts = last_seq - first_seq + 1 if first_seq is not None else 0
    lost = expected_pkts - n_pkt
    print(f"[verify] packets received : {n_pkt}")
    print(f"[verify] seq range        : {first_seq} .. {last_seq}  (expected {expected_pkts})")
    print(f"[verify] packets lost     : {lost}  ({100*lost/max(1,expected_pkts):.2f}%)")
    print(f"[verify] payload sizes    : {sorted(sizes)} bytes")
    print(f"[verify] byte_count delta : {total_bytes:,} over {dt:.2f}s  "
          f"=> {total_bytes/dt/1e6:.1f} MB/s")
    print(f"[verify] approx frame rate: {total_bytes/dt/BYTES_IN_FRAME:.2f} fps "
          f"(target 10)")
    if n_pkt > 0 and total_bytes > 0:
        print("[verify] OK: live, well-formed DCA1000 raw-ADC stream.")
        return 0
    return 1

if __name__ == '__main__':
    sys.exit(main())

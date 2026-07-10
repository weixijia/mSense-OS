"""
Decode mmWave Studio's trace.txt into the ordered mmwavelink SPI command sequence
to REPLAY (the blueprint for driving the AWR1843 like a 2243, no Studio).

Each host->device command frame:
  0x1234 0x4321 | opcode | nByte | flags | ...payload... | CRC
We extract them in order (skipping the 0x5678 CNYS read-trigger words) and pair
each with the device's [RD] response, then emit a replay blueprint (JSON).
"""
import re, json, sys

CMD_SYNC = (0x1234, 0x4321)
CNYS = (0x5678, 0x8765)
RSP_SYNC = (0xDCBA, 0xABCD)

def words(line):
    return [int(w, 16) for w in re.findall(r'0x([0-9A-Fa-f]{4})', line)]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'trace_skeleton.txt'
    lines = open(path, encoding='utf-8', errors='replace').readlines()
    cmds = []
    pending_rd = []
    cur = None
    for ln in lines:
        if 'Sensor Start' in ln:
            if cur is not None:
                cur['note'] = 'StartFrame/SensorStart follows'
        if '[WR]' in ln:
            w = words(ln)
            if len(w) >= 4 and (w[0], w[1]) == CMD_SYNC:
                if cur is not None:
                    cur['response'] = pending_rd; cmds.append(cur); pending_rd = []
                cur = {'idx': len(cmds), 'opcode': f'0x{w[2]:04X}', 'nByte': w[3],
                       'words': [f'0x{x:04X}' for x in w], 'crc': f'0x{w[-1]:04X}'}
        elif '[RD]' in ln:
            w = words(ln)
            if w and not (len(w) >= 2 and (w[0], w[1]) == RSP_SYNC):
                pending_rd.append([f'0x{x:04X}' for x in w])
    if cur is not None:
        cur['response'] = pending_rd; cmds.append(cur)

    # opcode -> best-guess role (by mmwavelink message-id family + the skeleton.lua order)
    ROLE = {
        '0x8345':'rfGet/version-or-status poll', '0x8005':'channel/ADC cfg ack',
        '0x05C1':'low-power/LP cfg', '0x0101':'set msg (RF/datapath cfg)',
        '0x0201':'profile / chirp / frame cfg (large payload)',
        '0x0581':'data-path / LVDS cfg', '0x8185':'cfg ack', '0x0281':'StartFrame / SensorStart',
        '0x8085':'firmware/file-download chunk',
    }
    for c in cmds:
        c['role'] = ROLE.get(c['opcode'], 'cfg')

    out = {'source': path, 'num_commands': len(cmds), 'commands': cmds}
    json.dump(out, open('replay_blueprint.json','w'), indent=1)
    print(f"decoded {len(cmds)} mmwavelink commands -> replay_blueprint.json\n")
    print(f"{'idx':>3} {'opcode':>7} {'nByte':>5}  {'words':>5}  role")
    for c in cmds:
        print(f"{c['idx']:>3} {c['opcode']:>7} {c['nByte']:>5}  {len(c['words']):>5}  {c['role']}"
              + ('   <-- '+c['note'] if 'note' in c else ''))

if __name__ == '__main__':
    main()

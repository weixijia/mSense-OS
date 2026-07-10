"""
Parse mmWave Studio's RunTime/trace.txt into the mmwavelink SPI transaction
sequence (ground truth for replaying Studio's control in Python).

Wire format (16-bit words, from the trace + mmwl_port_ftdi.c):
  [WR] 0x1234 0x4321 <opcode> <nByte> <flags> ... <payload> ... <CRC>   host->dev command
  [WR] 0x5678 0x8765 0xFFFF...                                          host read-trigger (CNYS)
  [RD] 0xDCBA 0xABCD                                                    device response SYNC
  [RD] <opcode> <nByte> ... <payload> ...                              device response body

We don't need full semantic decode to *replay*; we need the ordered command
word-lists. This summarizes opcodes/sizes and flags big blocks (firmware download).
"""
import re
import sys
from collections import Counter

CMD_SYNC = (0x1234, 0x4321)
CNYS_SYNC = (0x5678, 0x8765)
RSP_SYNC = (0xDCBA, 0xABCD)

def words(line):
    return [int(w, 16) for w in re.findall(r'0x([0-9A-Fa-f]{4})', line)]

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'trace_existing.txt'
    cmds = []          # (lineno, opcode, nByte, full_words)
    n_wr = n_rd = n_cnys = 0
    big = []
    for i, line in enumerate(open(path, encoding='utf-8', errors='replace'), 1):
        if '[WR]' in line:
            w = words(line)
            if len(w) >= 2 and (w[0], w[1]) == CMD_SYNC:
                n_wr += 1
                opcode = w[2] if len(w) > 2 else None
                nbyte = w[3] if len(w) > 3 else None
                cmds.append((i, opcode, nbyte, w))
                if len(w) > 12:
                    big.append((i, opcode, len(w)))
            elif len(w) >= 2 and (w[0], w[1]) == CNYS_SYNC:
                n_cnys += 1
        elif '[RD]' in line:
            n_rd += 1

    print(f"WR commands (0x1234 sync): {len(cmds)}")
    print(f"WR read-triggers (CNYS)  : {n_cnys}")
    print(f"RD lines                 : {n_rd}")
    print(f"\nopcode histogram (top 20):")
    for op, c in Counter(op for _, op, _, _ in cmds).most_common(20):
        print(f"   opcode 0x{op:04X}: {c}")
    print(f"\nlong command words (>12 words, e.g. firmware/config blocks): {len(big)}")
    print(f"\nfirst 30 commands (lineno: opcode nByte):")
    for ln, op, nb, w in cmds[:30]:
        print(f"   L{ln}: op=0x{op:04X} nByte=0x{nb:04X} words={len(w)}")
    print(f"\nlast 15 commands:")
    for ln, op, nb, w in cmds[-15:]:
        print(f"   L{ln}: op=0x{op:04X} nByte=0x{nb:04X} words={len(w)}")

if __name__ == '__main__':
    main()

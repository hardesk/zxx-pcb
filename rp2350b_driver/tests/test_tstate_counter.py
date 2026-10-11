#!/usr/bin/env python3
"""Execute assembled counter PIO against generated CLK/WAIT/RD/WR waveforms.

Checks refresh exclusion, read/write qualification and seamless window reload
at both the production clock ratio and the minimum supported ratio.
"""
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
build = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'derived/drv_rel'
header = (build / 'z80_tstate_counter.pio.h').read_text()
body = header.split('z80_tstate_counter_program_instructions[] = {')[1].split('};')[0]
code = [int(x, 16) for x in re.findall(r'0x([0-9a-f]+),', body)]
assert len(code) == 16 and '.origin = 0' in header

# (WAIT asserted, RD asserted, WR asserted). Includes refresh, read, write,
# both strobes, and transfers without WAIT. Controls change on falling CLK.
mixed = [(True, False, False), (True, True, False), (True, False, True),
         (True, True, True), (False, True, False), (False, False, True),
         (False, True, True), (False, False, False)]

def execute(period, pattern, clocks=1003, windows=4):
    mask = 0xffffffff
    pc, x, y, osr, isr = 4, clocks - 1, mask, 0, 0
    result = []
    for tick in range((clocks * windows + 2) * period):
        clk = tick % period >= period // 2
        # CLK bypasses its synchronizer; the other inputs retain two stages.
        wait, rd, wr = pattern[max(0, tick - 2) // period % len(pattern)]
        pins = mask & ~(int(rd) << 2) & ~(int(wr) << 3)
        word = code[pc]
        op, arg, value = word >> 13, (word >> 5) & 7, word & 31
        next_pc = 4 if pc == 15 else pc + 1
        if op == 0:  # JMP
            if arg == 0:
                next_pc = value
            elif arg == 2:
                if x: next_pc = value
                x = (x - 1) & mask
            elif arg == 4:
                if y: next_pc = value
                y = (y - 1) & mask
            elif arg == 6:
                if not wait: next_pc = value
            else: raise AssertionError(hex(word))
        elif op == 1:  # WAIT GPIO: SDK relocates GPIO24 to local input8.
            assert arg & 3 == 0 and value == 24
            if clk != bool(word & 0x80): next_pc = pc
        elif op == 3:  # OUT, right shift.
            bits = osr & ((1 << value) - 1)
            osr >>= value
            if arg == 5: next_pc = bits
            else: assert arg == 3
        elif op == 4:  # PUSH/PULL, DMA always ready.
            if word & 0x80: osr = clocks - 1
            else:
                result.append(isr)
                if len(result) == windows: break
        elif op == 5:  # MOV
            source = {0: pins, 3: 0, 2: y, 7: osr}[value & 7]
            if value & 8: source = (~source) & mask
            if arg == 7: osr = source
            elif arg == 6: isr = source
            elif arg == 1: x = source
            elif arg == 2: y = source
            else: raise AssertionError(hex(word))
        else: raise AssertionError(hex(word))
        pc = next_pc
    expected = [sum(w and (r or s) for w, r, s in
                    (pattern[i % len(pattern)] for i in range(j * clocks, (j + 1) * clocks)))
                for j in range(windows)]
    assert result == expected, (period, pattern, result, expected)

for period in (30, 16):
    for pattern in (mixed, [(True, False, False)], [(True, True, False)],
                    [(True, False, True)], [(False, True, False)]):
        execute(period, pattern)
execute(30, mixed, clocks=100000, windows=2)
print('PASS: assembled PIO qualifies RD/WR, excludes refresh, counts exact consecutive windows and reloads without losing edges')

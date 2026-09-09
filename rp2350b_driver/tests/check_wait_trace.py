#!/usr/bin/env python3
"""Check every request against wait_bus_stress.asm, including data and M1.

Usage: python3 tests/check_wait_trace.py BUILD/wait_bus_stress.bin TRACE.log
The trace must start at reset. A partial final log line is ignored.
"""
import argparse
import re
from pathlib import Path


def expected_requests(program):
    memory = bytearray(65536)
    memory[:3] = bytes([0xc3, 0, 1])
    memory[0x100:0x100 + len(program)] = program
    pc, a, bc, zero = 0, 0, 0, False

    def read(addr, m1=False):
        return (addr, int(m1), 1, 0, 1, 0, memory[addr])

    while True:
        op = memory[pc]
        yield read(pc, True)
        pc += 1
        if op in (0x3e, 0xfe):
            value = memory[pc]
            yield read(pc)
            pc += 1
            if op == 0x3e:
                a = value
            else:
                zero = a == value
        elif op in (0x01, 0x32, 0x3a, 0xc2, 0xc3):
            addr = int.from_bytes(memory[pc:pc + 2], 'little')
            yield read(pc)
            yield read(pc + 1)
            pc += 2
            if op == 0x01:
                bc = addr
            elif op == 0x32:
                yield (addr, 0, 1, 0, 0, 1, a)
                memory[addr] = a
            elif op == 0x3a:
                yield read(addr)
                a = memory[addr]
            elif op == 0xc3 or not zero:
                pc = addr
        elif op == 0xed:
            ext = memory[pc]
            yield read(pc, True)
            pc += 1
            if ext == 0x79:
                yield (bc, 0, 0, 1, 0, 1, a)
            elif ext == 0x78:
                yield (bc, 0, 0, 1, 1, 0, None)
                a = 0xff if bc & 1 else 0xbf
            else:
                raise AssertionError(f'unsupported ED opcode {ext:02x}')
        else:
            raise AssertionError(f'unexpected opcode {op:02x} at {pc - 1:04x}')


PATTERN = re.compile(
    r'busreq ([0-9a-f]{4}) ([0-9a-f]{2}) m1 ([01]) mreq ([01]) '
    r'ioreq ([01]) rd ([01]) wr ([01]) mem ([0-9a-f]{2})')


def check(program, trace):
    expected = expected_requests(program)
    count = loops = 0
    for line in trace.splitlines(keepends=True):
        if not line.endswith(('\n', '\r')):
            continue
        match = PATTERN.search(line)
        if not match:
            if 'busreq ' in line:
                raise AssertionError(f'malformed trace line: {line!r}')
            continue
        addr, data, m1, mreq, iorq, rd, wr, mem = match.groups()
        actual = (int(addr, 16), int(m1), int(mreq), int(iorq), int(rd), int(wr),
                  int(data if wr == '1' else mem, 16))
        want = next(expected)
        count += 1
        if actual[:6] != want[:6] or (want[6] is not None and actual[6] != want[6]):
            raise AssertionError(f'request {count}: expected {want}, got {actual}\n{line.strip()}')
        loops += actual[0] == 0x100 and actual[1] == 1
    if loops < 2:
        raise AssertionError(f'insufficient trace: {count} requests, {loops} loop starts')
    return count, loops - 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('program', type=Path)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args()
    count, loops = check(args.program.read_bytes(), args.trace.read_text())
    print(f'PASS: {count} requests, {loops} complete loops; exact address/control/data sequence')

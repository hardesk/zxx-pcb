#!/usr/bin/env python3
"""Instruction-level handshake regression using the actual .pio source.

This is a digital protocol model, not an FPGA timing or metastability model.
Hardware trace tests remain necessary. Run: python3 tests/test_wait_pio.py
"""
import re
import unittest
from pathlib import Path

MASK = 0xffffffff
CLK, RESET, WAIT = 24, 25, 26
MREQ, IORQ, RD, WR = 28, 29, 30, 31


class Machine:
    def __init__(self, delay, phase):
        source = (Path(__file__).resolve().parents[1] / 'z80_bus_wait.pio').read_text()
        source = source.split('.program z80_wait_bus', 1)[1]
        self.code, self.labels, self.defines = [], {}, {}
        for line in source.splitlines():
            line = line.split(';')[0].strip()
            if line.startswith('.define public'):
                _, _, name, value = line.split()
                self.defines[name] = int(value)
            elif line.endswith(':'):
                self.labels[line[:-1]] = len(self.code)
            elif line and not line.startswith('.'):
                self.code.append(line)
        assert len(self.code) <= 32
        self.pc = self.tick = self.pause = 0
        self.x = self.y = self.isr = self.osr = 0
        self.wait = self.oe = self.data = 0
        self.delay, self.phase = delay, phase
        self.requests, self.releases = [], []
        self.reply = None
        self.stage, self.start, self.end = 0, 200, None
        self.last_drive = 0

    def pins(self):
        if self.end is not None and self.tick >= self.end + 32:
            self.stage += 1
            self.start, self.end = self.tick, None
        clk = ((self.tick + self.phase) % 42) < 21
        pins = 0xfa000000 | (int(clk) << CLK) | (self.wait << WAIT)
        if self.tick < 80:
            pins &= ~(1 << RESET)
        # Refresh is not a transfer and must never reach the FIFO.
        if 100 <= self.tick < 165:
            pins &= ~(1 << MREQ)
        active = (self.stage < 4 and self.tick >= self.start and
                  (self.end is None or self.tick < self.end))
        if active:
            # read -> write -> read of the SAME address -> I/O read
            pins |= 0x4000 << 8
            pins &= ~(1 << (IORQ if self.stage == 3 else MREQ))
            if self.stage == 1:
                pins |= 0xa5
                # Tang's /WR may pulse in Tw; MREQ must keep the cycle owned.
                if not clk:
                    pins &= ~(1 << WR)
            else:
                pins &= ~(1 << RD)
            if self.end is not None:
                # Short all-inactive glitch after release, before true end.
                # A single sample or sequential WAIT instructions are unsafe.
                if self.end - 60 <= self.tick < self.end - 58:
                    pins |= 0xf0000000
                # Longer MREQ-only glitch with RD still asserted.
                if self.stage != 1 and self.end - 40 <= self.tick < self.end - 30:
                    pins |= 1 << MREQ
        if self.oe:
            assert self.stage != 1 or not active, 'read driver contends with write'
            pins = (pins & ~255) | self.data
        return pins

    def step(self):
        pins = self.pins()
        if self.pause:
            self.pause -= 1
            self.tick += 1
            return
        line = self.code[self.pc]
        delay = re.search(r'\[(\d+)\]', line)
        line = re.sub(r'\s*\[\d+\]', '', line)
        parts = line.replace(',', '').split()
        op, args = parts[0], parts[1:]
        next_pc = self.pc + 1
        if op == 'wait':
            polarity, _, pin = args
            if bool(pins & (1 << self.defines[pin])) != bool(int(polarity)):
                self.tick += 1
                return
        elif op == 'mov':
            dest, src = args
            invert = src.startswith('~')
            src = src.lstrip('~')
            value = pins if src == 'pins' else 0 if src == 'null' else getattr(self, src)
            value = value ^ MASK if invert else value
            if dest == 'pindirs':
                self.oe = value & 255
            else:
                setattr(self, dest, value)
        elif op == 'out':
            dest, bits = args[0], int(args[1])
            value = self.osr & ((1 << bits) - 1)
            self.osr >>= bits
            if dest == 'pins':
                self.data = value
            elif dest == 'pindirs':
                self.oe, self.last_drive = value, self.tick
            elif dest != 'null':
                setattr(self, dest, value)
        elif op == 'set':
            dest, value = args[0], int(args[1])
            if dest == 'pins':
                if value:
                    assert not self.wait and self.end is None
                    assert self.tick - self.last_drive >= 16, 'data setup too short'
                    self.end = self.tick + 84
                    self.releases.append(self.tick)
                else:
                    assert self.end is not None and self.tick >= self.end, 'early re-arm'
                self.wait = value
            else:
                setattr(self, dest, value)
        elif op == 'jmp':
            take = True
            if len(args) == 2:
                condition = args[0]
                if condition == 'pin':
                    take = bool(pins & (1 << RESET))
                elif condition.startswith('!'):
                    take = getattr(self, condition[1:]) == 0
                elif condition.endswith('--'):
                    reg = condition[:-2]
                    take = getattr(self, reg) != 0
                    setattr(self, reg, (getattr(self, reg) - 1) & MASK)
                else:
                    raise AssertionError(condition)
            if take:
                next_pc = self.labels[args[-1]]
        elif op == 'push':
            assert self.reply is None and len(self.requests) == self.stage, 'duplicate request'
            assert not self.wait
            assert (self.isr >> 8) & 0xffff == 0x4000
            write = self.stage == 1
            assert not (self.isr & (1 << (WR if write else RD)))
            if write:
                assert self.isr & 255 == 0xa5
            self.requests.append(self.isr)
            self.reply = (self.tick + self.delay, 0 if write else 0xff55)
        elif op == 'pull':
            assert self.reply is not None
            ready, value = self.reply
            if self.tick < ready:
                self.tick += 1
                return
            self.osr, self.reply = value, None
        else:
            raise AssertionError(line)
        self.pc = next_pc
        self.pause = int(delay[1]) if delay else 0
        self.tick += 1


class WaitProtocolTest(unittest.TestCase):
    def test_reply_phase_delay_and_glitches(self):
        for delay in (0, 1, 7, 21, 41, 42, 103, 10000):
            for phase in range(42):
                with self.subTest(delay=delay, phase=phase):
                    machine = Machine(delay, phase)
                    while machine.stage < 4 and machine.tick < 45000:
                        machine.step()
                    self.assertEqual(len(machine.requests), 4)
                    self.assertEqual(len(machine.releases), 4)
                    self.assertEqual(machine.wait, 0)
                    self.assertEqual(machine.oe, 0)


if __name__ == '__main__':
    unittest.main()

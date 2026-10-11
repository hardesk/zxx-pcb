#!/usr/bin/env python3
"""Digital model of the asynchronous detector/service/WAIT PIO source.

Checks IRQ consumption, delayed replies, duplicate suppression, data and bus
turnaround. Does not model FPGA timing, electrical setup/hold or metastability.
"""
import re
import unittest
from pathlib import Path

MASK = 0xffffffff
CLK, WAIT = 24, 26
M1, IORQ, MREQ, RD, WR = range(27, 32)
CLOCK_HALF_TICKS = 48


class SM:
    def __init__(self, source, name, block, status_irq=None, in_base=0):
        self.code, self.labels = [], {}
        self.block = block
        self.status_irq = status_irq
        self.in_base = in_base
        section = source.split('.program ' + name, 1)[1].split('.program', 1)[0]
        for line in section.splitlines():
            line = line.split(';')[0].strip()
            if line == '.wrap_target':
                self.wrap = len(self.code)
            elif line.endswith(':'):
                self.labels[line[:-1]] = len(self.code)
            elif line and not line.startswith('.'):
                self.code.append(line)
        self.pc = self.delay = self.x = self.isr = self.osr = 0

    def step(self, bus):
        if self.delay:
            self.delay -= 1
            return
        line = self.code[self.pc]
        delay = re.search(r'\[(\d+)\]', line)
        sideset = re.search(r'\bside\s+([01])', line)
        if sideset:
            bus.debug = int(sideset[1])
        line = re.sub(r'\s+side\s+[01]', '', line)
        args = re.sub(r'\s*\[\d+\]', '', line).replace(',', '').split()
        op, a = args[0], args[1:]
        pc = (self.pc + 1) if self.pc + 1 < len(self.code) else self.wrap
        if op == 'jmp':
            take = True
            if len(a) == 2:
                if a[0] == 'pin':
                    take = bool(bus.pins & (1 << 25))
                elif a[0] == '!x':
                    take = self.x == 0
                elif a[0] == 'x--':
                    take = self.x != 0
                    self.x = (self.x - 1) & MASK
                elif a[0] == 'x!=y':
                    take = self.x != self.y
                else:
                    raise AssertionError(a)
            if take:
                pc = self.labels[a[-1]]
        elif op == 'mov':
            dest, src = a
            invert = src.startswith('~')
            src = src.lstrip('~')
            if src == 'pins':
                v = ((bus.pins >> self.in_base) |
                     (bus.pins << (32 - self.in_base))) & MASK if self.in_base else bus.pins
            elif src == 'null':
                v = 0
            elif src == 'status':
                v = MASK if (self.block, self.status_irq) in bus.flags else 0
            else:
                v = getattr(self, src)
            v = v ^ MASK if invert else v
            if dest == 'pindirs':
                bus.oe = v & 255
            else:
                setattr(self, dest, v)
        elif op == 'out':
            dest, n = a[0], int(a[1])
            v = self.osr & ((1 << n) - 1)
            self.osr >>= n
            if dest == 'pins':
                bus.data = v
            elif dest == 'pindirs':
                bus.oe = v
                bus.drive_tick = bus.tick
            elif dest != 'null':
                setattr(self, dest, v)
        elif op == 'set':
            dest, value = a[0], int(a[1])
            if dest == 'pins':
                bus.wait = value
            else:
                setattr(self, dest, value)
        elif op == 'irq':
            # RP2350 allows NEXT/PREV before SET/CLEAR, including remote clear.
            target = self.block
            if a[0] in ('next', 'prev'):
                target += -1 if a.pop(0) == 'prev' else 1
            clear = a[0] == 'clear'
            if a[0] in ('clear', 'set'):
                a.pop(0)
            key = (target, int(a[0]))
            if clear:
                bus.flags.discard(key)
            else:
                bus.flags.add(key)
        elif op == 'wait':
            polarity, source, index = int(a[0]), a[1], int(a[2])
            if source == 'irq':
                key = (self.block, index)
                if (key in bus.flags) != bool(polarity):
                    return
                if polarity:
                    bus.flags.remove(key)
            elif source == 'gpio':
                if bool(bus.pins & (1 << index)) != bool(polarity):
                    return
            else:
                raise AssertionError(a)
        elif op == 'push':
            bus.requests.append(self.isr)
        elif op == 'pull':
            if bus.reply is None:
                return
            self.osr, bus.reply = bus.reply, None
        else:
            raise AssertionError(line)
        self.pc = pc
        self.delay = int(delay[1]) if delay else 0


class Bus:
    def __init__(self, source=None, wait_initial=1, wait_in_base=28):
        if source is None:
            source = (Path(__file__).resolve().parents[1] / 'z80_bus_async.pio').read_text()
        self.detector = SM(source, 'z80_async_detector', 0)
        self.service = SM(source, 'z80_async_bus', 0)
        self.wait_sm = SM(source, 'z80_async_guard', 1, status_irq=3, in_base=wait_in_base)
        self.debug_sm = SM(source, 'z80_async_debug', 1)
        assert len(self.detector.code) + len(self.service.code) <= 32
        self.tick = 0
        self.pins = 0xfa000000
        self.flags = set()
        self.wait, self.data, self.oe, self.debug = wait_initial, 0, 0, 0
        self.requests, self.reply = [], None
        self.drive_tick = 0

    def step(self, pins):
        clock = (self.tick // CLOCK_HALF_TICKS) & 1
        self.pins = ((pins & ~((1 << CLK) | (1 << WAIT))) |
                     (clock << CLK) | (self.wait << WAIT))
        self.service.step(self)
        self.wait_sm.step(self)
        self.debug_sm.step(self)
        self.detector.step(self)
        self.tick += 1


class AsyncWaitTest(unittest.TestCase):
    def test_wait_asserted_on_request_before_write_strobe(self):
        bus = Bus()
        setup = 0xfa400055 & ~(1 << MREQ)
        for _ in range(100):
            bus.step(setup)
            if bus.tick >= 8:
                self.assertEqual(bus.wait, 0)
            self.assertFalse(bus.requests)
        for _ in range(30):
            bus.step(setup & ~(1 << WR))
        self.assertEqual(bus.wait, 0)
        self.assertEqual(len(bus.requests), 1)

    def test_detector_publishes_accepted_snapshot(self):
        bus = Bus()
        raw = 0xfa4000a5 & ~((1 << MREQ) | (1 << WR))
        for _ in range(50):
            bus.step(raw)
            if bus.detector.pc == bus.detector.labels['request']:
                break
        else:
            self.fail('detector did not accept the write')
        # Change both address and WR after acceptance, before publication.
        changed = (raw | (1 << WR)) ^ (1 << 8)
        for _ in range(20):
            bus.step(changed)
        mask = MASK & ~((1 << CLK) | (1 << WAIT))
        self.assertEqual(len(bus.requests), 1)
        self.assertEqual(bus.requests[0] & mask, raw & mask)

    def test_debug_marker_irq_window(self):
        bus = Bus()
        self.assertEqual(bus.debug, 0)
        bus.flags.add((1, 6))
        bus.debug_sm.step(bus)
        bus.debug_sm.step(bus)
        self.assertEqual(bus.debug, 1)
        bus.flags.add((1, 7))
        bus.debug_sm.step(bus)
        bus.debug_sm.step(bus)
        self.assertEqual(bus.debug, 0)
        self.assertFalse(bus.flags)

    def test_late_reply_asserts_wait_without_duplicate_request(self):
        # Let the PIO publish a request but withhold the M33 reply. The WAIT
        # guard asserts early; detector must not issue duplicates.
        bus = Bus()
        pins = 0xfa400000 & ~((1 << MREQ) | (1 << RD))
        for _ in range(100):
            bus.step(pins)
            if bus.requests and not bus.wait:
                break
        else:
            self.fail('request did not assert WAIT')
        self.assertEqual(bus.wait, 0)
        self.assertEqual(len(bus.requests), 1)
        for _ in range(100):
            bus.step(pins)
        self.assertEqual(bus.wait, 0)
        self.assertEqual(len(bus.requests), 1)

    def test_fast_reply_releases_wait_after_data_setup(self):
        bus = Bus()
        pins = 0xfa400000 & ~((1 << MREQ) | (1 << RD))
        saw_wait = False
        replied = False
        for _ in range(100):
            bus.step(pins)
            if bus.requests and not replied:
                bus.reply = 0xff55
                replied = True
            saw_wait |= not bus.wait
            if (replied and bus.reply is None and bus.data == 0x55 and
                    bus.wait and bus.tick - bus.drive_tick >= 9):
                break
        self.assertEqual(len(bus.requests), 1)
        self.assertTrue(saw_wait)
        self.assertEqual(bus.wait, 1)
        self.assertEqual(bus.data, 0x55)

    def test_control_truth_table_and_reset(self):
        for bits in range(32):
            m1, io, mem, rd, wr = [bool(bits & (1 << n)) for n in range(5)]
            expected = ((mem or io) and (rd or wr)) or (io and m1)
            for reset in (False, True):
                bus = Bus()
                pins = 0xfa000000 & ~(bits << 27)
                if reset:
                    pins &= ~(1 << 25)
                for _ in range(150):
                    bus.step(pins)
                self.assertEqual(len(bus.requests), int(expected and not reset), (bits, reset))
                self.assertEqual(bus.wait, int(not (mem or io)))

    def test_transactions_delays_and_turnaround(self):
        cycles = [(MREQ, RD), (MREQ, WR), (MREQ, RD),
                  (IORQ, WR), (IORQ, RD), (IORQ, M1), (MREQ, RD)]
        for phase in range(2 * CLOCK_HALF_TICKS):
            for latency in (0, 1, 37, 10000):
                bus = Bus()
                for _ in range(phase):
                    bus.step(0xfa000000)
                for index, signals in enumerate(cycles):
                    raw = 0xfa4000a5
                    for pin in signals:
                        raw &= ~(1 << pin)
                    start = bus.tick
                    while len(bus.requests) <= index and bus.tick - start < 50:
                        bus.step(raw)
                    self.assertEqual(len(bus.requests), index + 1)
                    # The detector may publish before the helper's delayed
                    # acceptance marker rises. IRQ7 ends it after reply setup.
                    for _ in range(2):
                        bus.step(raw)
                    self.assertEqual(bus.debug, 1)
                    sample_mask = ~((1 << CLK) | (1 << WAIT)) & MASK
                    self.assertEqual(bus.requests[-1] & sample_mask, raw & sample_mask)
                    self.assertLessEqual(bus.tick - start, 40)
                    for n in range(latency):
                        # WR may pulse during Tw; request strobe retains ownership.
                        pins = raw | (1 << WR) if WR in signals and n % 5 == 0 else raw
                        bus.step(pins)
                        self.assertEqual(len(bus.requests), index + 1)
                    value = (phase * 13 + index) & 255
                    reply_tick = bus.tick
                    bus.reply = 0 if WR in signals else 0xff00 | value
                    for _ in range(100):
                        bus.step(raw)
                        if (bus.reply is None and bus.wait and
                                bus.drive_tick >= reply_tick and
                                bus.tick - bus.drive_tick >= 9 and
                                (1, 3) not in bus.flags):
                            break
                    else:
                        self.fail('reply did not settle and release WAIT')
                    # The IRQ7 marker may still be propagating through the
                    # helper SM here. Check that it falls before bus release.
                    self.assertEqual(bus.wait, 1)
                    self.assertGreaterEqual(bus.tick - bus.drive_tick, 5)
                    for _ in range(25):
                        bus.step(raw)
                        self.assertEqual(len(bus.requests), index + 1)
                        self.assertEqual(bus.wait, 1)
                        self.assertEqual(bus.oe, 0 if WR in signals else 255)
                        if WR not in signals:
                            self.assertEqual(bus.data, value)
                    # Give the asynchronous end detector time to rearm.
                    for _ in range(48):
                        bus.step(0xfa000000)
                    self.assertEqual(bus.oe, 0)
                    self.assertEqual(bus.wait, 1)
                    self.assertEqual(bus.debug, 0)
                    self.assertFalse(bus.flags)


if __name__ == '__main__':
    unittest.main()

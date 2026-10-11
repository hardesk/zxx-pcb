#!/usr/bin/env python3
"""Digital tests of the production high-idle PIO (override via HIGH_WAIT_PIO).

Models instruction execution, not input synchronizers or FPGA/electrical timing.
"""
import os
from pathlib import Path
import unittest
from test_wait_manual_pio import Bus, MREQ, IORQ, RD, WR, M1


class HighWaitTest(unittest.TestCase):
    def bus(self):
        source = Path(os.environ.get('HIGH_WAIT_PIO', str(Path(__file__).resolve().parents[1] / 'z80_bus_async.pio'))).read_text()
        return Bus(source, wait_initial=1, wait_in_base=int(os.environ.get('HIGH_WAIT_IN_BASE', '28')))

    def test_startup_and_idle_high(self):
        bus = self.bus()
        for pins in (0xf8000000, 0xfa000000):  # reset low, then released
            for _ in range(100):
                bus.step(pins)
                self.assertEqual(bus.wait, 1)
                self.assertFalse(bus.requests)

    def test_refresh_does_not_deadlock_or_leave_irq(self):
        for phase in range(16):
            for length in range(1, 81):
                bus = self.bus()
                for _ in range(phase):
                    bus.step(0xfa000000)
                for _ in range(length):
                    bus.step(0xfa000000 & ~(1 << MREQ))
                for _ in range(30):
                    bus.step(0xfa000000)
                self.assertEqual(bus.wait, 1, (phase, length))
                self.assertFalse(bus.requests)
                self.assertFalse(bus.flags)

    def test_reads_writes_io_intack_delays_and_refresh(self):
        cycles = [(MREQ, RD), (MREQ, WR), (IORQ, RD),
                  (IORQ, WR), (IORQ, M1), (MREQ, RD)]
        for phase in range(16):
            for delay in (0, 1, 37, 1000):
                bus = self.bus()
                for _ in range(phase):
                    bus.step(0xfa000000)
                for index, (request, transfer) in enumerate(cycles):
                    setup = 0xfa4000a5 & ~(1 << request)
                    for _ in range(12):
                        bus.step(setup)
                    self.assertEqual(bus.wait, 0)
                    raw = setup & ~(1 << transfer)
                    for _ in range(40):
                        bus.step(raw)
                    self.assertEqual(len(bus.requests), index + 1)
                    for _ in range(delay):
                        bus.step(raw)
                        self.assertEqual(bus.wait, 0)
                    bus.reply = 0 if transfer == WR else 0xff55
                    for _ in range(100):
                        bus.step(raw)
                        if bus.wait:
                            break
                    self.assertEqual(bus.wait, 1)
                    self.assertGreaterEqual(bus.tick - bus.drive_tick, 9)
                    for _ in range(20):
                        bus.step(raw)
                        self.assertEqual(bus.wait, 1)
                    # All strobes return high, then a refresh-only pulse.
                    for pins in (0xfa000000, 0xfa000000 & ~(1 << MREQ), 0xfa000000):
                        for _ in range(40):
                            bus.step(pins)
                    self.assertEqual(bus.wait, 1)
                    self.assertEqual(bus.oe, 0)
                    self.assertEqual(len(bus.requests), index + 1)
                    self.assertFalse(bus.flags)

    def test_reset_aborts_pending_reply_without_releasing_next_fetch(self):
        # RESET makes the FPGA drop its strobes while a reply is outstanding.
        # The old reply still must be drained, but its DATA_READY cannot belong
        # to the first post-reset read. Cover read/write/INTACK and every guard
        # scan phase, with replies before, during and long after bus abortion.
        idle = 0xfa000000
        reset_idle = idle & ~(1 << 25)
        fetch = idle & ~((1 << M1) | (1 << MREQ) | (1 << RD))
        for request, transfer in ((MREQ, RD), (MREQ, WR), (IORQ, WR), (IORQ, M1)):
            for phase in range(16):
                for reply_at in (0, 1, 4, 8, 16, 40, 100):
                    with self.subTest(request=request, transfer=transfer,
                                      phase=phase, reply_at=reply_at):
                        bus = self.bus()
                        for _ in range(phase):
                            bus.step(idle)
                        old = idle & ~((1 << request) | (1 << transfer))
                        for _ in range(60):
                            bus.step(old)
                        self.assertEqual(len(bus.requests), 1)
                        self.assertEqual(bus.wait, 0)
                        # A software reply may arrive after RESET aborted its
                        # physical transfer. The driver drains it during reset.
                        for tick in range(200):
                            if tick == reply_at:
                                bus.reply = 0 if transfer == WR else 0xff77
                            bus.step(reset_idle)
                        self.assertEqual(bus.oe, 0)
                        self.assertNotIn((1, 3), bus.flags, 'aborted reply left DATA_READY set')
                        for _ in range(phase + 20):
                            bus.step(idle)
                        for tick in range(300):
                            bus.step(fetch)
                            if tick >= 8:
                                self.assertEqual(bus.wait, 0, 'old reply released the new fetch')
                        self.assertEqual(len(bus.requests), 2)
                        bus.reply = 0xffc3
                        for _ in range(100):
                            bus.step(fetch)
                            if bus.wait:
                                break
                        self.assertEqual(bus.wait, 1)
                        self.assertEqual(bus.data, 0xc3)
                        self.assertEqual(bus.oe, 0xff)
                        for _ in range(50):
                            bus.step(idle)
                        self.assertEqual(bus.oe, 0)
                        self.assertFalse(bus.flags)

    @unittest.skipUnless(os.environ.get('HIGH_WAIT_IN_BASE', '28') == '28',
                         'Transfer-strobe retention is added in the shorter guard')
    def test_request_gap_with_transfer_still_active(self):
        for transfer in (RD, WR):
            bus = self.bus()
            raw = 0xfa4000a5 & ~((1 << MREQ) | (1 << transfer))
            for _ in range(40):
                bus.step(raw)
            for _ in range(100):
                bus.step(raw | (1 << MREQ))
                self.assertEqual(bus.wait, 0)
                self.assertEqual(len(bus.requests), 1)


if __name__ == '__main__':
    unittest.main()

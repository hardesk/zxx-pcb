# Posted memory writes — 2026-10-15

RZ80 is now the Tang Primer 25K FPGA core (z80-from-schematics), 5 MHz CLK,
RP2350 at 300 MHz, LCD active, no buffered tape. `run_bus_benchmarks.py
--extended`; every case byte-verified.

## Why writes were slow

The guard asserted WAIT on MREQ. A memory write is only recognisable once WR
falls at T2's falling edge, the same edge where the CPU samples WAIT, so the
RP's work started a clock later than for a read: **2 wait states per write**
against 1 per read. Elapsed-time accounting on the baseline: ram_read 3.0
waits/op (3 transfers), ram_write 4.0 (same loop with the write).

## Change

- Guard (PIO1): WAIT only for RD (`jmp pin`, JMP_PIN=RD) or IORQ. MREQ alone
  — memory write or refresh — never stalls the CPU. Reads assert as early as
  before (RD falls with MREQ); the scan loop is one PIO cycle longer (3→4).
- Detector (PIO0): a snapshot with exactly MREQ+WR (M1/IORQ/RD inactive) is
  pushed with no reply; it then waits for MREQ to rise. A WR tail after MREQ
  is not a request. Everything else is unchanged and synchronous.
- Service: starts on `pull` (the detector's IRQ4 start signal is gone; the
  M33 replies only to synchronous requests).
- M33: no reply for posted writes (`BusRequest::posted_write()` mirrors the
  detector's test). A requested reset services posted writes and resets on
  the next synchronous request, keeping it transaction-safe.
- Ordering: writes share the RX FIFO with requests, so read-after-write is
  in bus order. No back-pressure is needed: no Z80 instruction issues more
  than two memory writes before its next read (PUSH, CALL, INTA/NMI), and
  that read waits for the FIFO to drain.
- PIO0 is now exactly full (detector 21 + service 11 = 32); the GPIO39
  marker program and its IRQ6/7 were removed. `build_bus_latency.py` relies
  on that marker and no longer applies to this firmware.

## Results (effective MHz, completed work)

| Case | Before | Posted writes | Change |
| --- | ---: | ---: | ---: |
| fetch | 3.997 | 3.995 | — |
| ram_read | 3.928 | 3.923 | — |
| **ram_write** | 3.665 | **4.225** | **+15.3%** |
| io_read_fe | 3.669 | 3.664 | — |
| io_write_fe | 3.664 | 3.668 | — |
| io_read_ff | 3.926 | 3.927 | — |
| rom_read | 4.027 | 4.024 | — |
| rom_ram_read | 4.057 | 4.060 | — |
| **push_fill** (new) | 3.443 | **4.564** | **+32.6%** |
| **frame_work** T/frame | 76,657 | **82,140** | **+7.2%** |

push_fill is an unrolled `PUSH HL` blit (11 T: M1 + two writes), the shape of
stack-based screen fills. Before, it delivered 68.9k T per 20 ms — below
Pentagon's 71,680 — and now 91.3k. Baseline push_fill was measured on the
previous firmware (`before.elf`) with the same runner.

A wait-state model — waits = 1 per read/M1, 2 per write before, 0 after —
predicted 82,140 T/frame for frame_work (measured 82,140) and 4.58 MHz for
push_fill (measured 4.564).

Data: `derived/fpga_bench_20261015/` — `fpga.json` (before), `posted.json`,
`before_push.json`, `before.elf`.

## Tests

`make test-async-pio`: 14 model tests, including posted writes (no WAIT, no
reply, no data drive), WR tail after MREQ, write-write-read ordering, and a
posted write then RESET then fetch. Host ROM, tape, fast-tape, keyboard and
frame-interrupt suites pass.

## Not changed

I/O writes (`OUT FE`, `OUT 7FFD`) remain synchronous: 1 wait plus the
automatic I/O wait.

## Addendum: Z80 CLK 6 MHz (posted writes)

`make build Z80_CLOCK_HZ=6000000`, same benchmarks (`posted_6mhz.json`), all
byte-verified PASS. Every case scales by ~20% (one read wait is kept):

| Case | 5 MHz | 6 MHz | T/frame at 6 MHz |
|---|---|---|---|
| fetch | 3.995 | 4.797 | 95.9k |
| ram_read | 3.923 | 4.708 | 94.2k |
| ram_write | 4.225 | 5.068 | 101.4k |
| push_fill | 4.564 | 5.500 | 110.0k |
| frame_work | 4.107 | 4.928 | 98.6k |
| io_write_fe | 3.668 | 4.333 | 86.7k |
| io_read_fe | 3.664 | 4.360 | 87.2k |

The default stays 5 MHz until 6 MHz is qualified with tape loading and demos.

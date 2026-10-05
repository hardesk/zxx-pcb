# Real-board retest after FPGA fix — 2026-10-04, 19:11 session

## Result

The earlier all-four-strobes-inactive snapshot symptom was absent from all
332,620 complete request records in this retest. The bus implementation is
still not stable in the no-injected-delay tests. A 30-second 1 MHz run with
varying reply delays passed; both 3.5 MHz runs failed at request 10.

This is a fresh retest, separate from the 18:35 session interrupted by an
approval-service usage limit. The attached FPGA was used as programmed by the
user; its bitstream identity was not independently read back.

## Setup

- RP2350 system clock: 150 MHz; Debug build.
- Current `z80_pio_bus_wait-manual.pio` and matching driver, unchanged.
- GPIO39 rising/falling markers still denote detector acceptance/service snapshot.
- PIO0 instruction counts: detector 17, service 15.
- Detector/service ignore CLK; WAIT guard still observes CLK.
- `tests/wait_bus_stress.asm` at 0100h, reset vector JP 0100h.
- Blocking RTT request logging before each reply, polling every 1 ms.
- No-DMA stress runs pause RTT polling for 500 ms every two seconds.
- Delayed runs add pseudorandom 0–50 us before replying, in addition to logging.
- Every hardware run starts with a verified flash/reset.

The working CMake now selects `z80full.asm`, uses sjasm, and defaults to 3.5 MHz.
Tests used isolated copies under `/tmp/z80-fpga-fixed-20261004-191136`. The copied
CMake was explicitly changed to assemble the stress program with sjasmplus;
the resulting binary exactly matches the earlier workload. The existing
`build_snapshot_timing.py` alone does not select the stress workload correctly
with the current commented-out test.asm selection, so this explicit adjustment
was necessary. No working-tree firmware or test-script source was modified.

## Test matrix

| Test | Recording window | Complete records | First sequence error / result |
|---|---:|---:|---|
| 1 MHz, dual DMA timing capture | 8 s | 13,913 | FAIL at 703: expected operand read 012A=82; got memory-write record FF80=BF |
| 1 MHz, no DMA, no injected delay | 60 s | 106,769 | FAIL at 646: duplicate I/O read FF82 instead of opcode fetch 0130 |
| 3.5 MHz, no DMA, no injected delay | 60 s | 108,605 | FAIL at 10: opcode fetch 0106 instead of 0105 |
| 1 MHz, no DMA, varying 0–50 us reply delay | 30 s | 51,651 | PASS: 794 complete loops |
| 3.5 MHz, no DMA, varying 0–50 us reply delay | 30 s | 51,682 | FAIL at 10: opcode fetch 0106 instead of 0105 |

All five traces contain zero records with MREQ, IORQ, RD and WR simultaneously
inactive. This is a check for that particular symptom, not a declaration that
all logged transactions are correct. Records after a first mismatch are not
validated transfers. A final incomplete log line is excluded from the counts.

`tests/test_wait_manual_pio.py`: all five tests PASS, 57.762 seconds. This digital
model does not reproduce the physical FPGA/bus timing and cannot override the
hardware failures.

## Concrete remaining failures

In the 1 MHz no-DMA run:

```text
645: IO read FF82
646: IO read FF82 again       <-- unexpected; next should be opcode fetch 0130
647: opcode fetch 0130
```

This is a duplicated transaction record, even though its controls form a valid
I/O-read combination.

In both 3.5 MHz runs, the last correct request is the memory write 4000=55.
The next expected instruction is opcode 3A at 0105. The next published opcode
fetch is instead at 0106 (whose byte is 00). This is a sequence failure; the
log alone does not establish which physical timing mechanism caused it.

The different outcome with injected reply delays at 1 MHz suggests a remaining
timing-sensitive problem. It does not prove a specific completion or WAIT race,
nor justify an arbitrary delay as a permanent fix. A 30-second pass with logging
is not long-duration or full-protocol validation. Interrupt acknowledgement,
reset mid-transaction, and operation without request logging were not tested.

## Timing capture integrity

The capture stopped at the request-1000 fallback, not the invalid-controls
trigger. Published snapshot: 96011001 (memory read at 0110).
Both recorders produced 44,879,334 samples, with 8,192 retained; no RX FIFO
stalls and zero GPIO16..31 overlap mismatches. Offline reconstruction independently
checked counts, endpoints and every overlapping pin sample.

At retained sample 7974 GPIO39 rises; at 7975 it falls. Both samples show
96011001: MREQ and RD are already active, unlike the earlier all-inactive-marker
captures. This particular transaction occurs after the first sequence error
at request 703 and is not a capture of that first failure. Marker-path delay
remains uncalibrated; exact snapshot instants are not inferred from pin edges.

## Artifacts and restored state

`derived/fpga_fixed_retest_20261004_191136/` contains all logs, per-run checker
outputs, verified flash reports, four stress ELFs plus the capture ELF, the
stress binary, isolated main/CMake copies, source hashes, model results,
`capture_validation.json` and `results.json`.

All source hashes saved at the start still match. The user's current normal
application was rebuilt in a separate build directory, flashed, verified and
reset: z80full at 8000h, 3.5 MHz, logging off, DMA capture off, no injected reply
delay, GPIO39 markers retained. The short restoration log confirms startup;
it does not establish completion or correctness of the z80full suite.
OpenOCD was closed after restoration, freeing the probe for VS Code.

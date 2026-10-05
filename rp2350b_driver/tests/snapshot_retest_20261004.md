# Real-board retest after scope inspection — 2026-10-04

User reported /MREQ and /RD appeared correctly positioned on the oscilloscope.
Retested the attached board; no wiring changes were made by the agent and no
analog waveform was acquired by the agent. Current source hashes exactly match
the preceding snapshot-marker tests. No firmware source changes in this retest.

Setup: Debug, current asynchronous detector/service PIO with GPIO39 markers,
150 MHz system clock, 1 MHz external clock, stress assembly at 0100h, blocking
request logging before each reply, no injected reply delay. Both flashes verified.

| Run | Conditions | First sequence mismatch | Result |
|---|---|---|---|
| Timing capture | 8 seconds, RTT polling every 1 ms, synchronized dual DMA recorder | Request 642: expected IO write FF82=BF, published IORQ active but RD/WR inactive | FAIL |
| No DMA recording | 15 seconds, RTT polling every 1 ms, 500 ms polling pauses every 2 seconds | Request 173: expected IO write FF80=AA, published IORQ active but RD/WR inactive | FAIL |

The independent checker validates all requests from reset up to the first
mismatch. Its normalized controls use 1=asserted, unlike the physical GPIO
waveform. The read-data field in a malformed write record is not evidence of
wrong data: the decisive error is absent WR. Both malformed requests also have
M1 inactive, so they are not valid interrupt acknowledgements.

The capture run contains 13,744 complete request records, including 39 with all
four strobes inactive; the no-recorder run contains 27,856, including 105 with
all four inactive. Records after the first mismatch are not validated transfers.
Different first-failure indices are not a reliability ranking.

## Captured memory-cycle failure

The recorder triggers on an all-four-inactive request, not every possible
sequence error. It therefore stopped at request 733, after the first mismatch
at 642. Published raw snapshot: F7010B55 (address 010B, data 55, M1 active,
MREQ/IORQ/RD/WR all inactive).

- Sample 7971: address becomes 010B and M1 asserts.
- Sample 7974: detector-accept GPIO39 marker rises.
- Sample 7975: service-snapshot marker falls.
- Sample 7976: WAIT asserts.
- Sample 7990: sustained MREQ/RD assertion begins.

Both marker edges precede sustained MREQ/RD assertion, matching the previous
capture pattern. Actual snapshots precede their markers; helper/pad latency is
not calibrated. This recording does not expose the detector ISR value.

Both recorders produced 37,391,917 samples; 8,192 retained. Zero RX FIFO stalls,
zero overlapping GPIO16..31 disagreements. Sample interval 4 system clocks =
26.666667 ns. This validates the digital recording, not analog signal integrity.

## Interpretation and next measurement

The implementation still fails with and without DMA recording. A normal-looking
MREQ/RD trace cannot rule out the first failure here because it is an I/O write:
probe IORQ and WR at the RP pins with GPIO39 rising as trigger and pre-trigger
history. Capture the failing transaction, since ordinary accepted cycles also
produce GPIO39 pulses. The present data does not distinguish a brief electrical
excursion from output-logic timing or prove that the wiring is responsible.

## Artifacts and board state

Artifacts are in `derived/snapshot_retest_20261004/`: capture/stress logs,
checker outputs, verified flash logs, source hashes, both diagnostic ELFs, and
`waveforms/failure_timing.png`, SVG, sample text and marker text.

After the tests, rebuilt normal firmware was flashed, verified and reset:
original test.asm at 8000h, logging off, DMA capture off, 1 MHz, current GPIO39
markers retained. OpenOCD was then shut down.

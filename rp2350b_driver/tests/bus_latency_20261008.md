# Bus service latency — 2026-10-08

Measured on the attached RP2350/RZ80, 150 MHz RP clock and 5 MHz RZ80 clock,
with the LCD active and no uploaded tape. Both temporary builds ran the same
128K ROMs and unchanged production PIO bus programs. Production firmware was
restored and verified after the measurements; the temporary OpenOCD was stopped.

| Captured ROM reads | Before | After |
| --- | ---: | ---: |
| Complete measured transfers | 107 | 146 |
| Median detector-to-reply GPIO39 marker interval | 853 ns | 373 ns |
| 95th percentile marker interval | 880 ns | 400 ns |
| Median /WAIT low width | 933 ns | 453 ns |
| 95th percentile /WAIT low width | 960 ns | 507 ns |
| Largest /WAIT low width in this capture | 2,453 ns | 613 ns |

Median WAIT width decreased approximately 51%. These are startup ROM reads in
one 218-us window per build, not a worst-case bound for uploads, active tape,
I/O, RAM writes, interrupts or every program. No RAM reads/writes occurred in
these windows. GPIO39 includes the existing PIO/helper latency and is not a
pure C++ execution timer. The unchanged marker path makes the comparison useful.

PIO1's spare state machine sampled GPIO16..47 every four system clocks
(26.667 ns) into a finite 8,192-word DMA buffer. It changed no pin muxes or
clock/WAIT/detector/service programs. Capture started after transaction 1024;
only complete marker and WAIT transitions were included. Address-high pins
confirmed that all captured reads were below 0x4000. Timestamp precision is one
sample; printed values are rounded here.

Changes:

- A 564-byte request/reply loop resides in SRAM, with inline PIO FIFO access.
- Four cached read pointers are updated on ROM/RAM mapping changes. The existing
  ROM page mask still suppresses writes; registered ROM and RAM tables remain.
- Tape state handling is outlined and entered only around the loader or its
  outgoing fetch; ordinary reads skip it. Fast and normal tape modes remain.
- Host protocol parsing and button timing run after replies, every 256 transfers.
  This reduces frequent stalls but does not eliminate longer waits when core0
  handles uploads/controls. Their state remains owned by core0.
- F10 and tape `reset` use the same transaction-safe reset as GPIO38. Physical
  checks passed for both, tape retention, repeated held-F10 suppression, and a
  new F10 press. The temporary test tape was removed afterward.

Raw GPIO samples, per-transfer measurements and summaries are in
`derived/bus_latency_20261008/` (`before.json`, `after.json`,
`before-measurements.json`, `after-measurements.json`, `summary.json`).

The isolated capture builder is `tests/build_bus_latency.py`:

```sh
python3 tests/build_bus_latency.py /tmp/z80-latency-after --hz 5000000
```

The pre-change source snapshot used for this run is `/tmp/z80-bus-before-opt`.
The builder never flashes. It exposes `bus_latency_samples` and
`bus_latency_dma` for SWD extraction after DMA completion. Firmware restoration
is required after running a capture build.

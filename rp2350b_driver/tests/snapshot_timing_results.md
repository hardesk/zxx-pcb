# Detector/service timestamp markers — 2026-10-04

Implemented and tested on the attached RP2350/Z80 board at 150 MHz system clock
and 1 MHz Z80 clock. This is diagnostic instrumentation, not a stability fix.

## PIO changes

`z80_pio_bus_wait-manual.pio` now raises cross-PIO IRQ6 from the detector,
immediately before REQUEST (IRQ4). Service raises IRQ7 immediately after its
`mov isr, pins`. The existing PIO1 debug helper converts these into GPIO39 rising
and falling edges. GPIO39 therefore no longer describes data-drive duration or
transaction completion.

Detector uses 17 instructions; service uses 15: PIO0 still fits exactly 32.
No extra PIO0 instructions are available for a per-transaction numeric timer.
Instead, the independent recorder timestamps the GPIO39 marker against the
same sample clock as the bus.

For an accepted RD/WR request, detector IRQ6 executes 7 system clocks after
its snapshot (46.667 ns). For the INTACK branch, it executes 12 clocks after
(80 ns). Service IRQ7 executes 1 clock after its snapshot (6.667 ns). Both
recorded GPIO39 edges additionally include IRQ/helper/output/input-path delay.
That additional delay was not calibrated: the plots deliberately label the
**measured marker edges**, not exact snapshot instruction times. The one-sample
pulse width is not the detector-to-service snapshot interval.

Compared with the original instrumentation, the detector inserts one instruction
before REQUEST, service inserts one after its snapshot, and two later debug
instructions are removed. This perturbs transaction timing; these are fresh
instrumented captures, not timestamps retroactively added to the earlier trace.

## Capture implementation

`tests/snapshot_timing_capture.hpp` uses the spare PIO1 SM to sample GPIO16..47,
and a PIO2 SM to sample GPIO0..31. Each executes `in pins, 32` every four clocks
with RX autopush and a separate DMA ring. GPIO39 is bit 23 of the high record.
Both SMs start with synchronized clock dividers and stop in one cross-PIO
control operation. Neither changes pin muxes or output directions.

Both rings are 8,192 words; a short record before the first wrap is supported.
DMA transfer counts are read before abort, after stopping sampling and draining
RX FIFOs. Each exported pair uses the same absolute sample index. All 16 shared
GPIO16..31 bits are compared; counts and FIFO-stall flags are recorded. The plot
script refuses recordings with unequal counts, stalls, or overlap disagreement.

Sampling period is 26.666667 ns. If an edge is first seen at sample N, its
sampled-input transition is bracketed by samples N-1 and N. This does not resolve
sub-sample bus transients or establish analog glitch width.

## Real-board results

| Run | First all-inactive request | Published snapshot | Retained samples | Rising marker | Falling marker | Sustained MREQ/RD low |
|---|---:|---|---:|---:|---:|---:|
| First | 4 | F7010001 | 7,272 | 7054 | 7055 | 7070 |
| Reproducible builder / wrapped ring | 44 | F70122AA | 8,192 | 7975 | 7976 | 7991 |

Both runs have equal recorder counts, zero RX FIFO stalls and zero overlapping
pin mismatches. In the second run, 25,249,173 samples were collected by each
recorder; retained sample zero corresponds to absolute sample 25,240,981.

In the first capture, address 0100 and M1 appear at 7051. The measured markers
are at 7054/7055, WAIT asserts at 7056, and sustained MREQ/RD assertion starts
at 7070. Thus **both measured marker edges are inside the setup region**. The
service published all four request/transfer controls inactive. Detector sampling
occurs earlier than its rising marker; without calibrating the additional
marker-path delay, its precise position relative to the setup region's left
edge remains unproven. This run does not export detector ISR contents.

Five digital-model protocol tests pass (55.070 seconds), including delayed
replies and turnaround. Their IRQ timing is simplified; they do not calibrate
the physical marker latency. Normal and diagnostic firmware builds succeed.
The reproducible builder itself was used for the second hardware run.

Artifacts: `derived/snapshot_timing_20261004/`. Each capture has raw logs,
flash verification, PNG/SVG detail, all samples in tab-separated text and an
edge timestamp table. The first image is `waveforms/failure_timing.png`.

## Reproduce

```sh
python3 tests/build_snapshot_timing.py /tmp/z80-snapshot-timing-build
# Start OpenOCD using the existing rtt.cfg, then:
python3 tests/capture_wait_trace.py /tmp/z80-snapshot-timing-build/build/rp2350_driver.elf /tmp/snapshot-timing.log --seconds 8 --poll-ms 1
python3.11 tests/plot_snapshot_timing.py /tmp/snapshot-timing.log --output-dir /tmp/snapshot-timing-plots
```

The builder copies current sources to an isolated directory, selects the stress
program at 0100h, enables request logging, and adds the recorder. It does not
flash. Recording stops on the first all-inactive published request or request
1000. Capture transfer count is finite (about 7.16 seconds at 150 MHz); longer
runs require a different DMA transfer setup. A missing capture is not a pass.

The normal working-tree firmware was rebuilt, flashed, verified and reset after
testing: original test.asm at 8000h, 1 MHz, logging off, capture off, **new GPIO39
snapshot markers enabled**. No driver C++, main.cpp, CMake or pin mapping changes
were needed in the working tree for this task.

SDK reference for cross-PIO synchronized start/stop:
https://www.raspberrypi.com/documentation/pico-sdk/hardware.html
PIO instruction and input synchronization reference:
https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf

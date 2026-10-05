# Current asynchronous WAIT stability results — 2026-09-28

The current `z80_pio_bus_wait-manual.pio` fails hardware regression. Four fresh
flash/reset runs all publish a request with MREQ, IORQ, RD and WR inactive where
the independent checker expects an opcode fetch. Slowing to 100 kHz and adding
reply delays do not eliminate the failure. These are observed request-stream
failures; the exact preceding electrical waveform has not been captured here.

## Tested source and setup

- PIO SHA-256: `5c9c439db310efdb3864fc643beb4d636b84a53b593f88bee3dca02a78f077f1`.
- PIO, C++ bus driver, pin mapping and driver header were copied byte-for-byte
  from the working tree. Their snapshots and hashes are saved in
  `derived/current_wait_stability/`.
- Attached RP2350/CMSIS-DAP board, existing FPGA bitstream, 150 MHz system clock,
  Debug WAIT firmware. No FPGA programming or PIO changes.
- Isolated test sources/build: `/tmp/z80-current-wait-stability/`.
- Test-only changes there: select `tests/wait_bus_stress.asm`, load at `0100h`,
  and enable blocking `request.dump()` before every reply.
- Each run programs and verifies its ELF, resets the CPU, and checks the trace
  from the reset vector. No failing prefix is discarded.
- RTT polling every 1 ms, stopped for 500 ms every two seconds. GPIO/DMA capture
  disabled. Logging changes reply latency, so these are instrumented bus tests.

## Hardware results

| Clock | Injected reply delay | Capture duration | First bad request | Address | Trace |
|---|---|---|---|---|---|
| 1 MHz | None | 45 s | 18 | `010B` | `debug_1mhz.log` |
| 100 kHz | None | 15 s | 38 | `011D` | `debug_100khz.log` |
| 1 MHz | Varying 0–10 ms | 15 s | 179 | `0126` | `debug_1mhz_delay10ms.log` |
| 1 MHz, repeat | None | 15 s | 25 | `0112` | `debug_1mhz_repeat.log` |

Every first mismatch has M1 asserted and all four request/transfer strobes
inactive. For example, the first 1 MHz run reports:

```text
busreq 010b 55 m1 1 mreq 0 ioreq 0 rd 0 wr 0 mem fe
```

The expected request is an opcode fetch of `FE` at `010B`, with MREQ and RD
asserted. This is not an IRQ7/debug-marker assertion failure.

Raw traces, verified test ELFs, checker output, flash output, source snapshots,
the stress-program binary and `summary.json` are in
`derived/current_wait_stability/`. Captured records after the first mismatch
are diagnostic material, not successfully validated transfers.

## Simulation

All five tests pass in 56.873 seconds after correcting the debug-marker
expectation. IRQ7 intentionally marks the whole transaction ending. The test
now waits for reply installation/WAIT release independently, checks GPIO39
remains high while the transaction is active, and checks it falls after idle.

The transaction sweep was expanded from 20 to all 96 phases of the model's
clock, with four reply latencies and seven transactions per combination:
384 phase/delay combinations and 2,688 transactions. The suite also checks
the control truth table/reset, fast replies, held replies and the marker.

The model holds the main request strobes stable through servicing and does not
model FPGA propagation or electrical setup/hold. Its pass does not validate
the hardware behavior that failed above.

## Interpretation

The new clock-aware WAIT guard has not resolved the invalid published-snapshot
symptom seen in the earlier asynchronous driver. The detector validates one
snapshot, and the service publishes another without requalification. That is
a candidate mechanism consistent with these results, not a waveform-proven
root cause. Further work should capture CLK, WAIT, MREQ, RD and GPIO39 around
an invalid opcode-fetch request before choosing a fix.

## Restoration

Rebuilt, flashed and verified the normal working-tree firmware from
`derived/drv_dbg/rp2350_driver.elf`: Debug WAIT, 1 MHz, original `test.asm` at
`8000h`, request logging disabled, no injected delay or GPIO capture. Its
eight-second startup capture is `normal_restored.log`; it also shows garbled
and repeated test-program text. Flash restoration succeeded, but normal program
execution is not stable. The original PIO and application sources remain
unchanged.

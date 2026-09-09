# Board results — 2026-09-08

Tests used the attached RP2350/CMSIS-DAP board, the existing FPGA configuration,
150 MHz RP2350 system clock, WAIT backend, and blocking `request.dump()` before
every reply. The FPGA was not reprogrammed. Raw traces and test ELFs are in
`derived/wait_stress/` (build artifacts, not source-controlled).

The starting PIO failed at request 2 in `baseline.log`:

```text
busreq 0000 55 m1 1 mreq 1 ioreq 0 rd 1 wr 0 mem c3
busreq 0000 c3 m1 0 mreq 1 ioreq 0 rd 1 wr 0 mem c3
```

The second request should have been the operand at `0001`. Adding a second
qualification sample alone also failed (request 208, `settle.log`). A version
that sampled cycle completion once per clock skipped transfers; the DMA trace
in `aligned_capture.log` shows WAIT remaining high through the `0001` read
after the reset opcode reply. That experiment was rejected.

The final program uses continuous, coherent, twice-confirmed idle detection
and keeps the extra qualification sample and clock-aligned reply release.
The trace checker passed these runs with no extra/missing requests, incorrect
controls, or incorrect memory/write data:

| Build / Z80 clock | Host delay | Checked requests | Complete loops | Trace |
|---|---|---:|---:|---|
| Release / 3.5 MHz | RTT pauses of 250 ms | 3,734 | 57 | `continuous_end.log` |
| Release / 3.5 MHz | RTT pauses of 500 ms, 45 s run | 73,721 | 1,134 | `final_3500k.log` |
| Release / 3.5 MHz | Varying 0–10 ms per reply + 500 ms RTT pauses | 4,888 | 75 | `final_delay10ms.log` |
| Release / 100 kHz | RTT pauses of 500 ms | 34,529 | 531 | `final_100k.log` |
| Debug / 3.75 MHz | RTT pauses of 500 ms | 41,314 | 635 | `final_3750k_debug.log` |

Total: **158,186 checked requests, 2,432 complete loops**. Each trace starts
from a fresh verified firmware flash/reset; no trace prefix was discarded.

The source-interpreting PIO regression also passed all 336 reply-delay/clock-
phase combinations. It is a digital handshake test, not an electrical model.

Finally, `derived/drv_dbg/rp2350_driver.elf` was rebuilt, flashed and verified
with the original ZEXALL image, Debug, 3.5 MHz, zero injected reply delay and
GPIO capture disabled. Its generated PIO instructions match the stress-tested
program. `normal_zexall.log` records 20,762 requests, the correct reset-vector
sequence, and the ZEXALL startup banner. The main-loop dump was enabled for
that recorded run.

These tests validate memory fetch/read/write and I/O read/write under delayed
replies. They do not constitute a complete ZEXALL run or an interrupt-acknowledge,
physical BUSRQ/DMA, or reset-during-transaction qualification.

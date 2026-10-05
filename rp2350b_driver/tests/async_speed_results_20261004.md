# Async bus speed diagnosis, 2026-10-04

Real RP2350 + currently programmed TANG FPGA, 150 MHz RP system clock. User production sources were preserved. Test images were built in isolated copies and flashed/verified through CMSIS-DAP/OpenOCD. The normal current firmware was restored at its hardcoded 2 MHz after the tests; the restore log includes `000 SELF TEST OK` and `001 SCF`. OpenOCD was stopped and the debug probe released.

## Outcome

The current driver is not reliably stable at 2 MHz under the deterministic mixed memory/I/O workload. Without request logging it failed at request 448, repeating an FF82 I/O transaction instead of fetching opcode 012E. The 2.5 MHz run diverged at request 69; 3.5 MHz at request 10. Short baseline runs at 1 and 1.5 MHz passed more than 2 million checked requests each.

An isolated candidate combining prearmed WAIT, a single coherent detector snapshot, and WAIT release immediately after a fresh falling CLK edge passed:

| Clock | Capture window | Checked requests (last progress report) | Complete loops |
|---|---:|---:|---:|
| 3.5 MHz | 60 seconds | 29,895,865 | 459,936 |
| 5 MHz | 20 seconds | 11,081,690 | 170,487 |
| 6 MHz | 20 seconds | 11,797,143 | 181,494 |
| 3.5 MHz, random 0–50 µs reply delay | 20 seconds | 704,753 | 10,842 |

The candidate failed at request 2 at 8 MHz. This is a passing range for this workload and board, not a proved maximum frequency or full CPU/peripheral qualification. No interrupt or external BUSRQ arbitration exercise was included. The checker adds host-side service overhead; slow service, fast service, and logging are distinct timing conditions.

## What fails and where

### 1. WAIT assertion arrives too late for a write

The detector requires RD or WR before accepting a normal transaction. For writes, MREQ is active earlier than WR. Qualifying WR, handing off to service, and then signaling the WAIT guard spends the remaining timing margin. Making the guard immediate helped, but cannot recover a WAIT deadline already missed.

The earlier-assertion + low-phase-release comparison capture has no DMA stalls or shared-pin disagreement. At 3.5 MHz:

- Sample 2285: MREQ low, address 4000, data 55.
- Sample 2296: WR first low.
- Sample 2301: WAIT first low (5 samples / approximately 133 ns later; each edge has up to one sample of uncertainty).
- Sample 2306: WR and MREQ go high despite WAIT still low.
- Sample 2317: the next opcode fetch at 0105 has RD and MREQ low. GPIO39 remains high: the write reply is still pending.
- GPIO39 falls at 2493; WAIT releases at 2496. DATA remains 55. A write reply enables no RP data drivers, so it does not provide the required opcode 3A for the new read.
- The next published request is operand read 0106. The checker expected the missing opcode fetch 0105.

This is transaction overlap caused by missing the write's WAIT acceptance window. It is not merely slow M33 service: a properly accepted WAIT must let the host take arbitrarily longer before replying.

![Write escapes](../derived/async_speed_20261004/write_escape/waveform.png)

### 2. The second snapshot can lose WR

With WAIT prearmed and release tied to a fresh falling CLK edge, the service still failed on the first write: expected raw control/address 58400000 (write 4000), but published DB400055 (MREQ low, both RD and WR high).

The corresponding capture shows MREQ continuously low and address/data held at 4000/55, while WR repeatedly pulses low and high during WAIT. The detector can accept a low WR; the service's later MOV ISR,PINS can sample its high phase. Host service then sees neither read nor write and does not update RAM.

The current FPGA timing source explains the pulsing: `z80_timing.v` asserts memory WR for T2.N or T3.P, while `z80_core.v` handles a stalled T2.N by returning to T2.P without advancing T. This repeats the WR deassert/assert phases in each wait state. Registered control outputs fixed the earlier combinational spikes but do not remove this WAIT-state behavior.

Publishing the accepted detector ISR directly through the detector's RX FIFO fixes this particular software sampling race. The service then only consumes replies and controls data/OE. Its C++ read_request must read detector_sm_, while write_reply still uses bus_sm_.

![Write snapshot race](../derived/async_speed_20261004/write_snapshot/waveform.png)

### 3. Asynchronous WAIT release is independently sensitive

Prearmed WAIT plus the coherent snapshot, with immediate asynchronous release, still failed at request 13 at 3.5 MHz. Adding release at a fresh falling edge made the combined candidate pass tens of millions of transactions.

Release controlled by `wait 0 gpio 24` alone did not suffice: if CLK is already low, that instruction proceeds at an arbitrary point in the low phase. The successful experiment uses `wait 1 gpio 24`, then `wait 0 gpio 24`, then raises WAIT.

The FPGA top synchronizes external CLK through a 3-bit pipeline into its 30 MHz sampling domain, but connects z80_wait_n directly to core.wait_n. Core stall feeds combinational next-state logic. The comparison demonstrates release-phase sensitivity; it does not prove whether the microscopic cause is setup/hold violation, metastability, or another FPGA next-state path. The FPGA's external WAIT timing deserves review rather than assuming raw WAIT is safe whenever CLK is synchronized.

The Z80 samples WAIT at defined clock edges; assertion must meet that deadline. See the [Zilog Z80 CPU User Manual](https://www.zilog.com/docs/z80/um0080.pdf), Timing, pp. 7–10. The exact loaded FPGA input-to-state timing additionally includes its own synchronizer and core phase conventions.

## Recommended change

For this board, use the tested candidate's three changes together:

1. Assert WAIT between transactions. IRQ2 now signals the end of the current cycle, so the guard can rearm before the next request rather than after detecting WR.
2. Publish the detector's accepted snapshot; remove the service's second snapshot and push. Consume requests from detector RX, replies through service TX. Combined PIO0 instruction use is 31 words.
3. Release WAIT after data/OE setup at a fresh falling CLK edge. Detector and service remain asynchronous; the WAIT guard observes CLK.

The candidate is saved as `derived/async_speed_20261004/candidate.patch`, with readable `candidate.pio` and `candidate.cpp`. It has not been applied to production sources. Comments were corrected in the candidate; the experimental instruction stream is unchanged.

If the WAIT guard must also remain entirely independent of CLK, review/fix the FPGA's WAIT input sampling and the preservation of WR during inserted wait states first, then rerun the pure asynchronous cases. Neither faster assertion alone nor coherent snapshots alone passed above 2 MHz in these comparisons.

## Test method and reproduction

The isolated firmware loads `tests/wait_bus_stress.asm` at 0100h with JP 0100h at reset. An independently generated expected sequence checks every address and control snapshot, memory read value, and memory/I/O write data. The repeating program also compares RAM reads against 55/AA and I/O reads against BF. The initial reset has 3 requests; each complete loop has 65 requests. Per-request logging is disabled in the primary runs; one progress line per second records the conservative checked count. The first mismatch stops further servicing and asserts reset after recording.

Paired PIO1/PIO2 samplers capture GPIO0..31 and GPIO16..47 every 4 system clocks (26.667 ns). GPIO39 now marks detector acceptance through reply-data/OE setup, not the old service-snapshot window. Capture clocks/counts and FIFO stalls are validated. Two diagnostic captures had one disagreeing shared-pin sample at a transition; those are retained and flagged in TSV, not treated as exact simultaneous multi-pin measurements. Both illustrated write captures have zero disagreements.

The current main.cpp hardcodes 2 MHz despite Z80_CLOCK_HZ. The isolated builder explicitly replaces this with the macro; every captured boot banner confirms the intended clock. It also selects the stress assembly and assembler rather than accidentally retaining z80full.asm.

Build an isolated image (does not flash):

```sh
python3 tests/build_async_speed.py /tmp/z80-speed-test --hz 3500000 --variant prearm-coherent-fall
```

Run it through an existing OpenOCD with Tcl 6666 and RTT 9090 (flashes the board):

```sh
python3 tests/capture_wait_trace.py /tmp/z80-speed-test/build/rp2350_driver.elf /tmp/z80-speed.log --seconds 60 --poll-ms 1
```

Use `--variant base` to reproduce the current driver's failures. Add `--capture` to the builder to freeze paired GPIO rings on the first mismatch. A pass-only run does not dump a waveform. Use `--delay-us 50` to vary reply delay from 0 to 50 µs.

The image and text exporter is `tests/plot_async_speed.py`; sample tables and metadata are under the two illustrated artifact directories. Raw logs, exact test PIO files, ELFs, source hashes, expected request table, and JSON results are saved in `derived/async_speed_20261004/`.

## All runs

Checked counts below are the last progress report, not the final exact count at TCP capture termination.

| Experiment | MHz | Outcome | Checked requests or first failure |
|---|---:|---|---|
| baseline_1MHz | 1 | PASS | 2004383 |
| baseline_1p5MHz | 1.5 | PASS | 2353427 |
| baseline_2MHz | 2 | FAIL | Logged trace checker: request 632 expected opcode fetch 0124, got duplicate FF80 I/O read |
| baseline_3p5MHz | 3.5 | FAIL | FAIL request=10 index=9 expected=90010500 value=3a observed=97010655 value=00 |
| baseline_fall_2MHz | 2 | PASS | 2559980 |
| baseline_fall_3p5MHz | 3.5 | FAIL | FAIL request=10 index=9 expected=90010500 value=3a observed=97010655 value=00 |
| capture_2MHz | 2 | FAIL | FAIL request=1734 index=43 expected=90012200 value=ed observed=6eff80aa value=aa |
| capture_3p5MHz | 3.5 | FAIL | FAIL request=7 index=6 expected=98010300 value=00 observed=9f010232 value=32 |
| capture_early_low_3p5MHz | 3.5 | FAIL | FAIL request=10 index=9 expected=90010500 value=3a observed=97010655 value=00 |
| capture_prearm_3p5MHz | 3.5 | FAIL | FAIL request=36 index=35 expected=98011b00 value=38 observed=9b011ac2 value=c2 |
| capture_prearm_coherent_fall_3p5MHz | 3.5 | PASS | 3969842 |
| capture_prearm_fall_3p5MHz | 3.5 | FAIL | FAIL request=9 index=8 expected=58400000 value=55 observed=db400055 value=00 |
| checker_2MHz | 2 | FAIL | FAIL request=448 index=57 expected=90012e00 value=ed observed=6eff82bf value=bf |
| checker_2p5MHz | 2.5 | FAIL | FAIL request=69 index=3 expected=90010000 value=3e observed=97010801 value=3a |
| coherent_3p5MHz | 3.5 | FAIL | FAIL request=29 index=28 expected=90011500 value=3a observed=960116aa value=00 |
| early_assert_3p5MHz | 3.5 | FAIL | FAIL request=10 index=9 expected=90010500 value=3a observed=97010655 value=00 |
| early_release_low_3p5MHz | 3.5 | FAIL | FAIL request=29 index=28 expected=90011500 value=3a observed=970116aa value=00 |
| prearm_3p5MHz | 3.5 | FAIL | FAIL request=28 index=27 expected=58400000 value=aa observed=db4000aa value=55 |
| prearm_5MHz | 5 | FAIL | FAIL request=28 index=27 expected=58400000 value=aa observed=da4000aa value=55 |
| prearm_coherent_3p5MHz | 3.5 | FAIL | FAIL request=13 index=12 expected=98400000 value=55 observed=9a400840 value=00 |
| prearm_coherent_5MHz | 5 | FAIL | FAIL request=80 index=14 expected=98010900 value=00 observed=9b01083a value=3a |
| prearm_coherent_fall_3p5MHz | 3.5 | PASS | 5573811 |
| prearm_fall_3p5MHz | 3.5 | FAIL | FAIL request=9 index=8 expected=58400000 value=55 observed=db400055 value=00 |
| qualified_3p5MHz_60s | 3.5 | PASS | 29895865 |
| qualified_3p5MHz_delayed | 3.5 | PASS | 704753 |
| qualified_5MHz_20s | 5 | PASS | 11081690 |
| qualified_6MHz_20s | 6 | PASS | 11797143 |
| qualified_8MHz_12s | 8 | FAIL | FAIL request=2 index=1 expected=98000100 value=00 observed=9a0000c3 value=c3 |
| release_low_3p5MHz | 3.5 | FAIL | FAIL request=10 index=9 expected=90010500 value=3a observed=97010655 value=00 |

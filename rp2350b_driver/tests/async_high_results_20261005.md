# High-start / high-idle WAIT tests — 2026-10-05

WAIT does not need to start or idle low. A separate asynchronous guard asserting WAIT on **MREQ or IORQ, before waiting for RD/WR classification**, passed the exercised workload through **5 MHz**. The tested implementations are not reliable at 6 MHz or above. Merely changing the old service-triggered guard to start high still fails at 1 MHz.

These are actual RP2350/Tang board tests, not only simulations. Across passing runs, the last reported counters total **242,339,874 checked requests**, including 20 successful restarts. Counters are lower bounds at capture termination, not exact totals.

## Implementations and review

- `high-service`: WAIT initially high; assert only after the detector/service accepts a full transfer. Deliberately reproduces the late-WR problem.
- `high-request`: WAIT initially high and high between cycles. A guard scans MREQ/IORQ, asserts WAIT immediately on a request, releases after DATA_READY, and waits for cycle end. Refresh has no host reply, so request deassertion releases its WAIT pulse without waiting for DATA_READY.
- `high-request-fast`: input base moved to GPIO28 (IORQ), removing a shift instruction from each polling loop. The pending-reply path checks all four request/transfer strobes before treating a cycle as ended, so a MREQ gap while RD/WR remains active cannot prematurely release WAIT. Detector/service remain unchanged except removal of the unused CYCLE_END IRQ2 emission.
- Final initialization keeps SIO driving WAIT high until the PIO output latch and output enable are ready; only then switches the pin mux. Earlier test builds switched the mux sooner, temporarily leaving WAIT undriven during initialization. Runtime guard behavior is unchanged by the final handover fix.
- Data/output-enable setup still precedes DATA_READY; the service retains data ownership until all four strobes are inactive. Detector RX carries the accepted snapshot unchanged; service TX carries replies. Debug remains IRQ6/7.
- Final instruction use: PIO0 detector 18 + service 12 = 30 words. PIO1 clock 2 + debug 2 + guard 16 = 20 words. Detector, service and guard do not inspect CLK.
- Instruction model: idle request-to-WAIT takes 5–8 modeled steps for the first guard and 4–6 for the shorter guard. These exclude GPIO synchronization, output pipelines, wiring, and FPGA input sampling.

## Endurance and delayed replies

The initial early-request guard passed every row below. Fast runs use the CPU-side sequence checker without per-request logging or DMA. Delayed runs add deterministic pseudorandom 0–50 µs latency before **every** reply.

| Clock | 60-second fast run: requests | 30-second delayed run: requests | Result |
|---|---:|---:|---|
| 1 MHz | 13,224,163 | 985,034 | PASS |
| 2 MHz | 21,558,983 | 1,060,916 | PASS |
| 3.5 MHz | 28,171,663 | 1,074,720 | PASS |
| 4 MHz | 31,220,631 | 1,082,104 | PASS |
| 5 MHz | 33,306,909 | 1,094,017 | PASS |

The shorter guard additionally passed:

| Test at 5 MHz | Checked requests | Result |
|---|---:|---|
| 60 seconds, fast replies, before handover adjustment | 34,095,880 | PASS |
| 30 seconds, 0–50 µs replies | 1,093,816 | PASS |
| 15 seconds, 0–500 µs replies | 55,500 | PASS |
| 60 seconds, final high-preserving initialization | 34,107,579 | PASS |
| 20 resets, 2.5-second capture each, final initialization | 23,121,775 total | 20/20 PASS |
| Initialization DMA capture followed by workload | 2,309,853 | PASS |

Each restart required a fresh boot banner, checked-request progress, and no failure. These are RP resets/driver restarts, not power cycles.

## WAIT during startup and writes

The final startup capture starts before `bus.init()`, while SIO is driving WAIT high, and stops after the PIO takeover. It recorded **6,441 samples at 26.667 ns/sample**, approximately **171.8 µs**: zero WAIT-low samples, zero RESET-high samples, zero active transfer strobes, and no sampler stall or buffer exhaustion. This verifies firmware handover at that resolution; it does not measure power-on before firmware configures GPIO or exclude sub-sample analog transients.

The first memory-write reply was withheld for 50 µs. The CPU held address 4000, DATA=55 and MREQ low until WAIT release, with no observed WR-high pulses, at 1, 2, 3.5, 4, 5 and 6 MHz (the last three include the shorter guard). **The single write passing at 6 MHz did not make the complete workload pass.**

For the shorter guard at 5 MHz: MREQ asserted at sample 2264, WAIT at 2266, WR at 2272; WAIT released at 4328 and MREQ ended at 4342. Thus WAIT followed MREQ by about 53.3 ns and preceded WR by 160 ns. The write remained held for 54.83 µs through the delayed reply. The two recorders agreed on shared pins with no FIFO stalls.

![5 MHz assertion before WR](../derived/async_high_20261005/pass_5MHz/waveform.png)

## Failures and timing interpretation

| Guard | Clock | Failure |
|---|---:|---|
| Service-triggered, starts high | 1 MHz | Request 10: expected fetch 0105 / 3A; observed read 0106. WAIT fell 160 ns after WR; the write ended about 54 µs before WAIT release. |
| Early-request | 6 MHz | Request 62: expected read 0131 / BF; observed 0132 / C2. |
| Shorter early-request | 6 MHz | Request 3,096: expected fetch 0120 / ED; observed write at 5554. |
| Either early-request guard tested | 8 MHz | Request 2: first fetch had already escaped. |
| Initial early-request guard | 10 and 12 MHz | Request 2. |

The 8 MHz capture shows MREQ/RD falling at sample 668, the next CLK falling at 669, and WAIT falling at 671. RD/MREQ then deassert at 675 while the reply has not yet arrived; DATA remains FF. This is a missed stall followed by execution of incorrect data, not merely a disagreement between detector and service snapshots.

![8 MHz missed initial stall](../derived/async_high_20261005/failure_8MHz/waveform.png)

The local Tang top-level source samples external CLK with a 30 MHz sampler and delays WAIT alongside it using `z80_wait_sync[1]`. That explains why the visible interval from FPGA-generated MREQ to the relevant external clock edge can be much shorter than a nominal Z80 cycle. This interpretation is consistent with the capture. Exact remaining setup margin and every 6 MHz failure were not measured: the write-probe captures stop after the first write, before those later sequence failures. No FPGA source or bitstream was changed by these tests; local source hashes are recorded, not asserted as a read-back identity of the programmed bitstream.

## Models, limits and recommendation

The existing production PIO model passed all 7 tests in 56.280 seconds. The initial high-idle model passed its 3 tests; the final shorter-guard model passed all 4, including a request-strobe gap while RD/WR remains active. Tests cover idle/reset levels, refresh lengths/phases, memory reads/writes, I/O, interrupt acknowledgements, delayed replies, data setup and ownership. Python compilation, normal firmware build and `git diff --check` also passed.

Use the **shorter early-request guard** if adopting high-idle WAIT. **5 MHz is the highest frequency that passed these runs; 4 MHz leaves more timing margin.** Do not use the service-triggered guard for this FPGA, and do not treat 6 MHz as stable. Faster operation needs more assertion margin, for example earlier FPGA request outputs or faster FPGA external-bus sampling, followed by another measurement.

The hardware workload checks the expected sequence/address/control/data for repeated memory writes/reads and I/O, with CPU-side value checks and refresh naturally exercised by opcode fetches. It is not a full Z80 instruction-suite, hardware interrupt, external BUSRQ/BUSACK, voltage/temperature, electrical-signal-integrity or power-cycle qualification.

## Reproduction and artifacts

```sh
/opt/openocd-master/bin/openocd -f interface/cmsis-dap.cfg -f target/rp2350.cfg -f rtt.cfg
# In another terminal:
python3 tests/build_async_speed.py /tmp/high-wait --hz 5000000 --variant high-request-fast
python3 tests/capture_wait_trace.py /tmp/high-wait/build/rp2350_driver.elf /tmp/high-wait.log --seconds 60 --poll-ms 1
```

Builder options: `--write-hold-us 50` for the held-write waveform, `--delay-us 50` or `500` for reply delays, or `--init-capture` for the initialization capture. Initialization and transaction capture cannot be combined. `tests/run_high_wait_tests.py` reproduces the saved test phases; `tests/repeat_wait_startup.py` resets the already-flashed checker. These tools leave test firmware installed; restore normal firmware explicitly afterward.

Exact ELFs, logs, source snapshots, hashes, JSON metrics, PNG/SVG waveforms and GPIO TSV data are under `derived/async_high_20261005/`. The candidate remains an **isolated test variant**; production `z80_bus_async.pio` and `.cpp` were not modified during this turn.

After testing, the original normal **2 MHz prearmed-WAIT firmware** was restored
and flash-verified. Its boot printed `000 SELF TEST OK` and started `001 SCF`;
the full instruction suite was not run to completion. OpenOCD was stopped to
release the probe. Adopting high-idle WAIT in production remains a separate change.

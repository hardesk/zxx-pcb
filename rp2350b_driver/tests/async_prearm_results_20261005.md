# Production asynchronous prearmed-WAIT driver — 2026-10-05

## Implemented behavior

WAIT is asserted before the first request and between transactions. DATA_READY (PIO1 IRQ3) releases WAIT after data and output enables settle. The service releases its data drivers after MREQ, IORQ, RD and WR are all inactive, then sends CYCLE_END (PIO1 IRQ2) to rearm WAIT before sending DONE (PIO0 IRQ5) to the detector. This removes the late-write assertion path entirely.

The detector still publishes its accepted snapshot through detector RX, and the host sends replies through service TX. Detector, service and WAIT guard do not inspect CLK. PIO0 instruction use remains 18 + 13 = 31 words. PIO1 uses 2 clock + 2 debug + 4 guard = 8 words.

## Consistency review

- Renamed the C++ IRQ2 constant from WaitStart to CycleEnd and retained initialization clearing of IRQ2/3/6/7.
- Removed unused MOV STATUS configuration and obsolete commented T2 phase logic.
- Initialized the PIO WAIT output latch low before enabling its output direction and before starting CLK. The common environment asserts RESET before driver initialization.
- Confirmed data output enables are installed before DATA_READY, held until all request/transfer strobes end, and released before CYCLE_END.
- Confirmed one outstanding request: detector PUSH/IRQ4 precede its wait for DONE, and service consumes exactly one reply. Early host replies can safely wait in the service TX FIFO.
- Corrected marker/guard comments and the active test documentation. Historical snapshot-marker tools/results are explicitly identified as historical.
- Removed main.cpp's hardcoded 2 MHz clock override. Z80_CLOCK_HZ now controls the actual clock; Make/CMake still default to 1 MHz. Normal firmware for this test was explicitly configured at 2 MHz.
- Made the isolated builder's prearm/coherent variants idempotent for the new production source; corrected the optional diagnostic release-phase transformation to handle instruction comments.
- Updated model expectations for WAIT low at idle/reset and rearmed after cycle completion, added pre-WR setup coverage, and retained the coherent-snapshot regression.

No additional handshake inconsistency was found in this review. Initialization, idle/refresh filtering, host reply ordering and end-of-cycle IRQ ordering were checked. `git diff --check` and normal firmware compilation passed.

## Tests

All **7 PIO model tests passed in 54.456 seconds**. They cover the actual PIO source, control combinations/reset, preserved detector snapshots, WAIT preassertion, fast and delayed replies, debug IRQ handling, repeated addresses, data ownership, and rearming after complete cycle end. Electrical timing and finite FIFO capacity are outside the model.

All hardware cases below used `--variant base`: the actual production PIO, not an additional prearm or clock-phase patch. The attached FPGA is the version with latched WAIT and WR retained during stalls.

| Test | MHz | RTT capture seconds | Checked requests | Complete loops | Result |
|---|---:|---:|---:|---:|---|
| write_1MHz | 1 | 8 | 1,635,434 | 25,160 | PASS |
| write_3p5MHz | 3.5 | 12 | 5,348,365 | 82,282 | PASS |
| stress_3p5MHz | 3.5 | 60 | 29,808,675 | 458,594 | PASS |
| delayed_3p5MHz | 3.5 | 20 | 704,826 | 10,843 | PASS |
| stress_6MHz | 6 | 20 | 11,860,502 | 182,469 | PASS |

The write tests withhold the first write reply for 50 µs and include paired PIO/DMA capture. `delayed_3p5MHz` applies deterministic randomized 0–50 µs delay before every reply. Stress cases have neither per-request logging nor DMA sampling. Counts are the last progress report, not exact totals at host capture termination; elapsed windows include startup and waveform logging where applicable.

The 1 MHz failure at request 10 from the previous current-guard test is fixed. The first write remained at address 4000 with DATA=55 and MREQ low until WAIT release at both 1 and 3.5 MHz. WR stayed continuously low with **zero extra pulses**. Both waveform captures have equal recorder counts, no FIFO stalls and no shared-pin disagreement.

- 1 MHz: first WR low sample 2882; WAIT release 4950; MREQ end 5019. Write hold to WAIT release: 55.147 µs.
- 3.5 MHz: first WR low sample 2299; WAIT release 4356; MREQ end 4377. Write hold to WAIT release: 54.853 µs.

Sampling resolution is four 150 MHz system clocks, 26.667 ns. GPIO39 rises after acceptance and falls after reply data/OE setup; it is not a bus ownership marker.

![1 MHz write now held](../derived/async_prearm_20261005/write_1MHz_waveform/waveform.png)

## Reproduction

```sh
python3 tests/build_async_speed.py /tmp/z80-async-test --hz 3500000 --variant base
python3 tests/capture_wait_trace.py /tmp/z80-async-test/build/rp2350_driver.elf /tmp/z80-async-test.log --seconds 60 --poll-ms 1
```

Add `--write-hold-us 50` to the builder for the first-write capture, or `--delay-us 50` for randomized reply delays. Run `tests/check_write_wait_capture.py` against the resulting write log. See `tests/README.md` for OpenOCD and plotting instructions.

Logs, exact test ELFs, source hashes, metrics, samples, plots and JSON results are saved under `derived/async_prearm_20261005/`.

These results qualify the exercised memory/I/O workload on this board at the listed frequencies. They do not establish an absolute maximum clock or constitute a complete Z80 instruction, interrupt or external BUSRQ arbitration qualification.

After the tests, the normal firmware was loaded and verified with the implemented driver at 2 MHz. The boot log confirmed 2000 kHz, printed `000 SELF TEST OK`, and started `001 SCF`; this was a startup check, not completion of the full instruction suite. OpenOCD was stopped to release the debug probe.

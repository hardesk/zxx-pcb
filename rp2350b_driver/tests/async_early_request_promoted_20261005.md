# Early-request async driver promoted — 2026-10-05

Production `z80_bus_async.pio` now uses the qualified shorter early-request guard.
WAIT starts and idles high, asserts on MREQ/IORQ without waiting for detector or
service classification, and releases on DATA_READY after reply setup. Refresh
ends without a reply; RD/WR retention prevents an early release during a request
strobe gap. Guard input base is GPIO28; all bus processing remains independent
of CLK. PIO0 uses 30 words and PIO1 uses 20 words.

The WAIT latch and output enable are set high before switching the pin from SIO
to PIO. Removed the obsolete CYCLE_END IRQ2 emission, constant and clearing.
Make/CMake defaults and the normal build are now 5 MHz. Existing CMake caches
still require an explicit clock update. Production PIO instructions match the
qualified `high-request-fast` variant exactly; prior extensive qualification is
in `async_high_results_20261005.md`. Six MHz remains unqualified/failing.

Validation after promotion:

- All 7 production instruction-model tests passed (59.122 seconds).
- All 4 high-idle/refresh/retention model tests passed (2.427 seconds).
- `--variant base` real-board checker at 5 MHz: 10,692,384 checked requests,
  164,498 complete loops, no sequence failure in a 20-second capture.
- First write reply withheld for 50 microseconds: WAIT asserted 53.3 ns after
  MREQ and 160 ns before WR. Address/data/MREQ held until WAIT release; WR stayed
  continuously low. Hold lasted 54.53 microseconds. Both samplers agreed, with
  no FIFO stalls (26.667 ns/sample).
- Normal firmware compiled; Python syntax checks and `git diff --check` passed.

Logs and waveform metrics: `derived/async_promoted_20261005/`.

Normal 5 MHz firmware was flash-verified and left installed. Its startup check
printed `000 SELF TEST OK`, `001 SCF OK`, and started `002 CCF`; the full Z80
instruction suite was not completed. OpenOCD was stopped to release the probe.

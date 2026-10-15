# Brief: POWER_UP.TAP hang on RP2350 + RZ80, then bus-speed assessment

You are running locally on the Mac in `rp2350b_driver`. The WeAct CMSIS-DAP probe
(RP2350 SWD) and the Tang FPGA running RZ80 are on USB. Use the project's own
tooling: `make openocd`, `tools/zx_media.py`, `tools/zx_keyboard.py`, `tests/*.py`,
and the docs in `tests/` (`README.md`, `SPECTRUM128.md`, `vibrate_hang_20261008.md`,
`frame_budget_20261008.md`, `bus_benchmarks_20261008.md`, `bus_latency_20261008.md`).

## Ground rules
- Do NOT modify, reorder or "fix" `taps/POWER_UP.TAP`. The goal is to find why
  the real RP2350+RZ80 hangs on it, not to make the TAP load differently.
- Ask me before flashing anything. If you need a temporary diagnostic build
  (as was done for VIBRATE), build it separately, say what it changes, and
  restore + verify production firmware afterwards. Stop any OpenOCD you start.
- The RZ80+RP uses WAIT states (slow RAM emulation). That is known and intended.

## Task 1 — reproduce and diagnose the hang
Symptom: POWER_UP.TAP hangs/crashes "quite at the very start, maybe 4–5 s in".
1. Ask me (if not already stated) for: tape mode (fast/normal), how I load it
   (128 menu "Tape Loader" vs `LOAD ""` in 48 BASIC), and what the hang looks like.
2. Reproduce on hardware: upload with `zx_media.py`, boot it the same way, note the
   time and the screen/RTT output when it hangs.
3. Capture state at the hang without changing production code paths if possible:
   - Is core0 still servicing requests (RTT responsive, keyboard ack)?
   - Where is the Z80? Sample the address of the request core0 is serving by
     briefly halting core0 repeatedly (holds the Z80 in WAIT, harmless) and
     building a PC histogram; or reuse the temporary SRAM request-ring approach
     from `derived/vibrate_debug/` (see `tests/vibrate_hang_20261008.md`).
   - Dump all eight 128K RAM banks, paging register, tape state.
4. Decide what the code is waiting for / whether code or stack got corrupted,
   and why that differs from a real Pentagon/128K. Report root cause with evidence.

## What is already known (from a reference software emulator, real ROMs, unmodified TAP)
- TAP: BASIC loader "Power_UP" (autostart line 5: CLEAR 24999; POKE 23739,111),
  then "PUP-TEST" CODE 25000 (packed, self-depacks via B800 using SP as a data
  pointer with DI), then 1_RAM-00..07 into banks via `OUT 32765`, 1_BASE, LDIR,
  2_RAM-xx, 2_BASE, LDIR, EPILOGa.
- PUP-TEST = the joke "Quick System Test" screen ending with
  "USING COLOURFUL TV-DRIVE (Y/N)?". In emulation it uses IM1, ROM BEEPER (03B5),
  KEY-SCAN, AY probe (OUT/IN FFFD; RP returns 0xFF which is fine), and a 128K
  bank test (bank0 vs bank1 at C000; failure prints "U DON'T HAVE 128K OF FREE
  MEMORY" and waits). It does NOT move SP with interrupts enabled.
- With 60k–66k T/frame and jitter the first ~10+ s ran fine in emulation, so
  the 4–5 s hang is probably not the VIBRATE frame-budget mechanism. Suspect an
  RP/RZ80-specific difference (bus/tape overlay/CPU core) — verify on hardware.
- Demo notes (in `taps/PowerUpV2.0.tap.zip` INFO): requires Pentagon 128 timing,
  71,680 T per INT, 3.5+ MHz, no waits ("on wait computers some parts look bad").
  Part 1's IM2 handler (I=0x5F, vector 0x6060) uses ~68.5k T per frame with DI.
- Observation only (do not change the file): in tape order 1_BASE precedes LDIR,
  but BASIC loads "LDIR" (line 2030) before "1_BASE" (line 50).

## Task 2 — after Task 1: assess faster/stable bus request handling
I see ~80k T per 20 ms on the LCD counter at 5 MHz (note: `bus_benchmarks_20261008.md`
says that counter overstates; completed-work timing gave ~66.7k for fetches).
Goal: real ~70–80k T/frame AND stable frame-to-frame. Review `main.cpp`
(`run_z80_bus`, `service_pio_request`, `handle_io_in/out`), `z80_bus_async.pio`,
`z80_bus_async.cpp`. Measure with `make test-bus-benchmarks` before/after.
Candidate directions to evaluate (measure, don't assume):
- ROM images live in flash (XIP): copy 128-0/128-1 into SRAM to avoid cache-miss jitter.
- `select_rom()` memcmp's 175 bytes on every 0x7FFD write; precompute per ROM.
- Housekeeping every 256 transfers (RTT/keyboard/tape/button) causes long
  stalls; move it to core1 or make it time-bounded and lock-free.
- Pure-PIO/DMA service for plain RAM/ROM reads and writes (address -> SRAM
  lookup without the CPU), CPU only for I/O, paging and tape.
- Tie the 50 Hz INT to delivered T-states (e.g. count from the PIO T-state
  counter) instead of wall-clock, for stable T/frame regardless of WAIT jitter.
- Shorter PIO handshakes (detector->service IRQ chain, WAIT guard latency).
Write results to `tests/` like the existing reports.

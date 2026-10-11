# Asynchronous bus regression

The ASYNC backend uses `z80_bus_async.pio` and `AsyncBusDriver`.

- The PIO0 detector (18 instructions) classifies one coherent GPIO snapshot,
  pushes it to its RX FIFO, signals REQUEST on PIO0 IRQ4, and waits for DONE
  on PIO0 IRQ5. C++ reads detector RX and writes replies to service TX.
- The PIO0 service (12 instructions) installs reply data/output enables, waits
  eight extra clocks for setup, then signals DATA_READY on PIO1 IRQ3.
- The PIO1 WAIT guard (16 instructions) starts and idles high. It asserts
  WAIT on MREQ/IORQ independently of transfer classification, then releases
  on DATA_READY. Refresh ends without a reply; all four request/transfer
  strobes must be inactive to release a pending refresh or finish a cycle.
- Detector, service and WAIT guard do not inspect CLK. A separate PIO1 state
  machine generates CLK. PIO0 uses 30 of its 32 instruction words.
- GPIO39 rises after detector acceptance and falls after reply data/OE setup.
  Neither marker is an exact snapshot timestamp or the full data-drive window.
- Reset must be asserted during initialization. WAIT stays high during initialization and idle; its latch and output enable
  are set before switching from SIO to PIO. Reset with a pending request still requires the host
  to supply its reply before releasing reset, as documented by the driver API.

`main.cpp` uses `Z80_CLOCK_HZ`; Make/CMake default to 5 MHz. Set
`Z80_CLOCK_HZ=2000000` with Make or `-DZ80_CLOCK_HZ=2000000` with CMake to select
2 MHz. A direct CMake build retains an existing cached value. The previous
hardcoded 2 MHz override in main has been removed.

## Instruction-level regression

```sh
make test-async-pio
```

The model interprets the active PIO source and tests coherent request
publication, early-request WAIT, all control combinations and reset, delayed
replies, repeated addresses, turnaround, data/OE setup and IRQ consumption.
It also tolerates WR pulses during a held request, as a regression against the
older FPGA behavior. The model does not simulate electrical setup/hold,
metastability or finite FIFO capacity; real-board validation is separate.

## Isolated real-board sequence checker

These commands build an isolated copy without changing the normal program or
flashing automatically. `base` always uses the current production PIO.

```sh
python3 tests/build_async_speed.py /tmp/z80-bus-check --hz 3500000 --variant base
```

The firmware runs `wait_bus_stress.asm` at 0100h and checks every request against
an independent expected sequence: address, M1, memory/I/O controls and data.
The CPU also compares memory and I/O read results. It reports progress once a
second and stops on the first mismatch. Each complete loop has 65 requests.
Per-request RTT logging is disabled; progress counts are conservative totals
from the last report.

Launch OpenOCD with the connected CMSIS-DAP probe available:

```sh
/opt/openocd-master/bin/openocd -f interface/cmsis-dap.cfg -f target/rp2350.cfg -f rtt.cfg
```

The next command **flashes and verifies the attached RP2350**, resets it and
records RTT via Tcl port 6666 / RTT port 9090. It does not program the FPGA.

```sh
python3 tests/capture_wait_trace.py /tmp/z80-bus-check/build/rp2350_driver.elf /tmp/z80-bus-check.log --seconds 60 --poll-ms 1
```

Use `--delay-us 50` on the builder for randomized 0–50 µs reply delays.
The older fully logged test uses `request.dump()` before replying and
`check_wait_trace.py`; its RTT blocking behavior changes host service timing.
Stopping RTT polling only stretches replies if the firmware fills its blocking
RTT buffer, so that test is different from the lightweight checker above.

## Delayed-write waveform

```sh
python3 tests/build_async_speed.py /tmp/z80-write-check --hz 3500000 --variant base --write-hold-us 50
python3 tests/capture_wait_trace.py /tmp/z80-write-check/build/rp2350_driver.elf /tmp/z80-write-check.log --seconds 12 --poll-ms 1
python3 tests/check_write_wait_capture.py /tmp/z80-write-check.log
python3 tests/plot_async_speed.py /tmp/z80-write-check.log --output /tmp/z80-write-plot
```

The first memory-write reply is withheld for 50 µs. Two PIO/DMA recorders sample
GPIO0..31 and GPIO16..47 every four system clocks, including GPIO39. The checker
reports both cycle retention until WAIT release and WR continuity. The plotter
exports every sample as text with ADDR/DATA grouped. Add `--capture` instead to
freeze a waveform only on a sequence mismatch. Capture changes host timing;
use a non-capture run as well for stress validation.

The coherent variant preserves accepted detector snapshots. Prearm variants
are historical comparisons that deliberately assert WAIT at idle. `fall` and `low` are isolated
CLK-observing release experiments, not the production guard.

After testing, rebuild/reflash the normal firmware with the intended clock and
release OpenOCD's probe. Early-request qualification is in `async_high_results_20261005.md`; production
promotion and its verification are in `async_early_request_promoted_20261005.md`.
Earlier result documents describe their archived firmware versions, not the
current driver. In particular, `build_snapshot_timing.py` and
`plot_snapshot_timing.py` are historical tools for the former service-snapshot
marker; use the current builder and plotter above for GPIO39's present meaning.

## High-start / high-idle WAIT experiments

See `async_high_results_20261005.md` for the real-board speed sweep, delayed
replies, initialization capture and restart results. These are isolated test
variants. The shorter early-request guard is now the production implementation.

Use `--variant high-request-fast` to assert WAIT on MREQ/IORQ before transfer
classification, starting and idling high. `high-request` is the earlier polling
version; `high-service` reproduces the late service-triggered assertion.
Add `--init-capture` to sample WAIT throughout `bus.init()` with PIO2. This cannot
be combined with `--capture` or `--write-hold-us`, which also need PIO2.

```sh
python3 tests/build_async_speed.py /tmp/high-wait --hz 5000000 --variant high-request-fast
HIGH_WAIT_PIO=/tmp/high-wait/z80_bus_async.pio HIGH_WAIT_IN_BASE=28 python3 tests/test_high_wait_pio.py
python3 tests/capture_wait_trace.py /tmp/high-wait/build/rp2350_driver.elf /tmp/high-wait.log --seconds 60 --poll-ms 1
# Resets the already-flashed checker; requires a fresh boot and PASS progress:
python3 tests/repeat_wait_startup.py /tmp/high-wait-restarts --count 20
```


## LCD strip renderer

After building the firmware, run `python3 tests/test_zxdisplay.py` (an optional
argument selects another build directory). This executes the assembled pixel
and command PIO instructions, then uses a sanitizer-enabled host test to check
all Spectrum bitmap/attribute addresses, BRIGHT/FLASH, and the 592 DMA segments
forming the 272x208 image plus an eight-pixel border. It also prepares the next
strip before consuming the current one to check that the two buffers are independent.

`ZxDisplay::render(screen, flash)` owns an entire frame on core1. Two eight-line
pixel buffers alternate: conversion fills one while data/control DMA channels
stream the other. The final descriptor of each strip stops chaining and sets a
raw completion flag; core1 starts another strip only once it is prepared. No
per-pixel CPU FIFO writes or DMA NVIC interrupts are used for pixel streaming.

`set_border(rgb444)` and `set_border_line(row, left, right)` are display-core-only
APIs, called between frames. Border row numbers cover all 208 output rows;
top/bottom rows use the left colour across the full 272 pixels. No Z80 port
interception is installed. The outer LCD margins are cleared black at startup.

For on-device timing, inspect `main::display.m_last_frame_us`, `m_max_frame_us`
and `m_frames` without halting the target. Debugger halts contaminate frame
latency measurements. The host checks do not validate electrical timing or DMA
hardware handshakes.

On-device check (2026-10-06, RP2350 at 150 MHz): the two-channel renderer
completed 504 frames in 10.078 seconds without debugger halts. Latest frame
work was 19,249 us; the recorded maximum was 19,309 us. Live screen RAM matched
all 6912 source bytes for Rambo, GameOver and RoboCop2 during the three-second
slideshow. These timings describe this tested workload, not a worst-case bound.

## ROM and RAM banking

Run `python3 tests/test_rom.py` to test the production environment classes with
host GPIO stubs and address/undefined-behaviour sanitizers. It checks all four
ROM slots and CPU pages, ignored ROM writes, bus fetches, eight independent RAM
banks, fixed-bank aliases, and host loads crossing a page boundary.

`add_rom(data, size, bank)` registers an exactly 16 KiB borrowed image in ROM
slot 0..3; `select_rom(bank)` maps it at 0x0000. The optional second argument
selects another CPU page (0..3). `unmap_rom(page)` exposes its underlying RAM.
A four-bit mask controls ROM protection, with direct per-page pointer lookup.
Call mapping APIs on core0; registered images must remain alive.

RAM banks 5 and 2 are fixed at 0x4000 and 0x8000. `select_ram_bank(bank)` maps
bank 0..7 at 0xC000, removing any ROM overlay there. Bank 0 is the default.
Selecting bank 5 or 2 aliases the fixed slot, including the LCD's live bank-5
screen memory at `m_ram + 0x4000`. Allocation is 128 KiB of banked RAM plus
16 KiB of legacy RAM underneath the low ROM slot. Host `load`/`fill` target
mapped backing RAM, even underneath a ROM overlay. The 128K machine now drives these APIs from port 0x7FFD, including its
paging lock and bank-7 shadow display. See `SPECTRUM128.md`.

Bus service latency measurements and SRAM-loop changes: [2026-10-08 results](bus_latency_20261008.md).
Use `python3 tests/test_tape_cli.py` for filename completion/history and
`python3 tests/test_tape_fast.py` for ROM fast-load regression tests.

## VIBRATE demo hang

See [vibrate_hang_20261008.md](vibrate_hang_20261008.md) for the captured IM2
interrupt overwriting a stack-based drawing table, and the 25 Hz timing
experiment that isolates the frame-budget failure.

POWER_UP.TAP stops after its RAM blocks because the TAP's block order does
not match its BASIC load order (TR-DOS origin); see
[power_up_hang_20261008.md](power_up_hang_20261008.md).

Passive CLK/WAIT measurements over 500 consecutive 20 ms windows:
[frame_budget_20261008.md](frame_budget_20261008.md). The reusable capture tool
is `measure_frame_budget.py`; it uses spare PIO/DMA resources without flashing
or adding work to the bus-service loop.

## Runtime T-state label

The normal LCD firmware now runs `Z80TstateCounter` continuously. One PIO2
state machine counts transfer-qualified WAIT at rising CLK edges in 20 ms
windows. Two endless DMA channels reload the window and store a 64-entry
ring; there are no measurement interrupts or bus-loop calls. Core1 polls
the ring between rendered frames and averages its latest 50 samples once
per second. The outer-border label now shows, for example, ` 67022 T`, at
the same x=24, y=1 position. It shows a placeholder until samples are ready.

This is an estimate of nominal T-states per 20 ms, including HALT/refresh,
not an instruction counter. WAIT assertions without RD/WR are excluded.
The CLK synchronization setting matches the calibrated capture described
above; the other control inputs keep their synchronizers.

Run `python3 tests/test_tstate_counter.py derived/drv_rel` after building
to execute the assembled counter against generated waveforms, including
refresh, read/write waits, no-wait transfers and consecutive window reloads.
`test_zxdisplay.py` also checks the new label, including its last character
and pixel-buffer guards.

Hardware verification on 2026-10-08: flash verified; the menu averaged about
70,475 T-states, while VIBRATE's drawing workload produced rolling averages
around 65,000–68,000. RX/TX DMA remained in endless mode through multiple
ring wraps with no counter FIFO stalls. The bus-service function remains
564 bytes. Samples and text-buffer checks are retained in
`derived/frame_budget_20261008/runtime-counter.json`. The board was restored
to the 50 Hz menu with VIBRATE buffered, rewound and in fast mode.

The earlier SWD capture tool requires the runtime counter to be absent:
its existing resource checks reject a running counter safely rather than
overwriting the counter's state machine, DMA or instruction memory.

Subsequent finite device benchmarks exposed a substantial bias in the LCD
estimate after shortening the reply path. Use completed-work timings for
quantitative performance comparisons; see the counter limitation in
[bus_benchmarks_20261008.md](bus_benchmarks_20261008.md).

## Heavy RAM and I/O device benchmarks

With local OpenOCD running and the matching production ELF already flashed:

```sh
make test-bus-benchmarks BENCHMARK_OUTPUT=derived/bus_benchmarks/run.json
python3 tests/compare_bus_benchmarks.py before.json after.json
```

The runner verifies the ELF matches running code, executes real RZ80 workloads
with LCD activity, checks their results/FIFO flags, and restores RAM and the
menu. Each RAM/I/O workload performs over a million operations. It resets
RZ80 and stops tape playback while retaining the buffered file; stop keyboard
and tape clients before running it. `--case` selects individual workloads.
See [bus_benchmarks_20261008.md](bus_benchmarks_20261008.md) for methods,
limitations and the FIFO/memory optimization comparison.

`--extended` adds byte-verified flash-ROM and RAM sweeps (`rom_read`,
`rom_ram_read`) and `frame_work`, which records completed work in every
50 Hz IM1 frame (true T per frame and its jitter). The 300 MHz RP clock
option (`RP_SYS_CLOCK_KHZ=300000`) and the hot-path changes are assessed in
[bus_speed_20261008.md](bus_speed_20261008.md).

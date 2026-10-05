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

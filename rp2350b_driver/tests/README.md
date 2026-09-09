# WAIT bus regression

The hardware trace test requires `request.dump()` enabled in the main loop,
before `write_reply()`. Normal firmware may leave that call commented out.
RTT uses blocking mode, so a stopped debugger can hold a request indefinitely.
The bus PIO must keep WAIT asserted and issue exactly one request per transfer.

The revised 32-word PIO program:

- Qualifies `(MREQ || IORQ) && (RD || WR)` from one GPIO image, testing
  MREQ/IORQ first. A second qualified sample after another clock supplies the
  request, with WAIT asserted throughout.
- Sets read data and direction before releasing WAIT at a settled falling
  clock phase. The independent clock SM keeps running during logging.
- Checks MREQ, IORQ, RD and WR together, continuously, until **two consecutive
  samples** show all four inactive. It then releases data and re-arms WAIT.
  A single strobe transition, including WR pulses during Tw, cannot end a cycle.

Do not replace completion detection with one sample per clock: the inactive
gap around refresh can last only half a clock. The GPIO/DMA capture caught
that approach missing the gap, leaving WAIT high through the next operand read.
Do not deduplicate by address: two legitimate reads may use the same address.

The `[15]` delays assume the board's 150 MHz system clock and allow the Tang
external-clock synchronizer to settle. The driver requires at least 40 PIO
ticks per Z80 clock (up to 3.75 MHz at 150 MHz). This is a board timing budget,
not a claim of compatibility with every external Z80 implementation.

## Instruction-level regression

```sh
make test-wait-pio
```

The test interprets the actual PIO source. It checks 42 clock phases and eight
reply delays, with startup reset, refresh rejection, short strobe glitches,
WR pulses during waits, read/write turnaround, I/O, and repeated-address reads.
It checks request count, data direction, data setup, and WAIT re-arming.
This digital model does not model FPGA propagation delay or metastability.

## Hardware regression

Before building the hardware test, enable `request.dump()` in `main.cpp`, set
`prog_org` to `0x100`, and select the stress program in `CMakeLists.txt`:

```cmake
set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/tests/wait_bus_stress.asm)
```

Replace the existing active `DATA_ASM` selection for this test. An unconditional
`set(DATA_ASM ...)` overrides a command-line `-DDATA_ASM=...` cache value.
Keep these test-only source changes out of the normal firmware commit, and use
a separate build directory:

```sh
cmake -S . -B derived/wait_regression \
  -DPICO_SDK_PATH=/Users/orl/Projects/pico-sdk \
  -DCMAKE_BUILD_TYPE=Release -DZ80_BUS_MODE=WAIT \
  -DZ80_CLOCK_HZ=3500000 -DZ80_REPLY_DELAY_US=0
cmake --build derived/wait_regression --parallel
```

Run `make openocd` in another terminal. The following command **flashes the
attached RP2350**, verifies it, resets it, and captures RTT. No FPGA bitstream
is changed.

```sh
python3 tests/capture_wait_trace.py \
  derived/wait_regression/rp2350_driver.elf \
  derived/wait_regression/trace.log \
  --seconds 45 --pause-every 2 --pause-seconds 0.5 --poll-ms 1
python3 tests/check_wait_trace.py \
  derived/wait_regression/wait_bus_stress.bin \
  derived/wait_regression/trace.log
```

Pauses stop **OpenOCD RTT polling**, rather than just TCP reads, so socket
buffers cannot hide the intended blocking-printf stall. All complete trace
lines are checked from the reset vector onwards. The checker compares address,
M1, request/transfer controls, memory contents and write data with an independent
execution of the small stress program. Conditional branches also check that the
CPU actually received the read data. Each loop has 65 bus requests and includes
two reads of the same memory location, memory writes and I/O reads/writes.

Set `-DZ80_REPLY_DELAY_US=10000` to add a deterministic varying 0–10 ms delay
before every reply. Use `-DZ80_WAIT_CAPTURE=ON` to capture GPIO0..31 with PIO2
and DMA around the first eight replies; `sample` indices are four system-clock
ticks apart (26.67 ns at 150 MHz). Captures perturb host reply timing and are
diagnostics, not the final stress qualification. Capture records are ignored
by the bus-trace checker.

Restore the normal program selection, load address and logging setting, then
rebuild and reflash the normal firmware after testing. See `wait_results.md` for the
recorded board results and remaining validation limits.

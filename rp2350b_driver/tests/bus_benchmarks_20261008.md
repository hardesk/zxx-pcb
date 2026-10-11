# FIFO/memory-read optimization and device benchmarks — 2026-10-08

The three requested changes are flashed and verified on the RP2350. Completed
workload throughput improved about **3.3% for RAM writes**, **1.9% for IN FE**,
**3.7% for OUT FE**, and **6.1% for unmapped IN FF**. Fetch-only and RAM-read
changes are below 1% and are not conclusive given host polling uncertainty.

| Workload | Before operations/s | After operations/s | Throughput gain | Before / after seconds |
| --- | ---: | ---: | ---: | ---: |
| Fetch / NOP | 808,572 | 815,325 | +0.84% | 3.890 / 3.858 |
| RAM read | 290,441 | 291,849 | +0.48% | 3.610 / 3.593 |
| RAM write | 266,716 | 275,647 | +3.35% | 3.931 / 3.804 |
| IN FE | 258,213 | 263,071 | +1.88% | 4.061 / 3.986 |
| OUT FE | 265,414 | 275,335 | +3.74% | 3.951 / 3.808 |
| IN FF | 273,838 | 290,609 | +6.12% | 3.829 / 3.608 |

The table uses the optimized repeat; the first optimized run agreed within
0.3% for every workload. The baseline was measured once. Each RAM/I/O case
performs 1,048,576 target operations; fetch performs 3,145,728 NOPs. Rates
include opcode fetches and loop overhead, not isolated memory bandwidth.

## Implementation

- `AsyncBusDriver::init` caches RX/TX FIFO addresses, the status-register
  address and the RX-empty mask. The SRAM owner loop copies this immutable
  access descriptor once, keeping it across handler calls. Assembly confirms
  that SM-number loads and mask calculations are outside the request loop.
- Replies use a direct TX register write. The detector publishes one request,
  then waits for IRQ5. The service state machine pulls its reply, completes
  the bus cycle, releases the data pins and signals IRQ5 before another
  request is accepted. Thus every accepted request has space for its one
  reply. The transaction-safe reset also writes only that final reply before
  resetting the machine. No detector, guard, clock or service PIO code changed.
- `ZxTape::observes_cpu()` is now one cached boolean, maintained at upload,
  commit, rewind, stop/reset, loader-fetch and block-finish transitions.
  Ordinary memory reads test it first. Detailed loader-range and active-call
  checks remain when needed, including operand overlays and the first fetch
  leaving the loader. This keeps normal/fast tape semantics intact.

The whole SRAM bus function is 580 bytes versus 564 before; this includes
initialization and cold reset branches, so byte size alone is not a latency
metric. The compiled reply path contains no TX-full polling.

## Device workload runner

`run_bus_benchmarks.py` uses the running production ELF's DWARF to locate
state and verifies that its SRAM bus-function bytes match the actual device
before writing memory. It does not flash, halt RP cores, or add calls to the
CPU bus-service loop. It temporarily holds RZ80 RESET, puts a cloned standard
ROM with `JP 8000` in the existing RAM underneath ROM, and substitutes its
read pointer. The ROM write-protection mask remains intact; the standard
loader profile is preserved for representative ordinary-memory checks.

The code at 8000 executes finite loops with start/end markers in RAM. RAM
reads/writes cycle through C000..C0FF, using the selected upper RAM bank;
other cases exercise FE input/output and unmapped FF input. The LCD, its DMA,
the runtime counter and 50 Hz INT remain active. Test programs execute DI so
interrupts cannot alter the workload. Read results, all 256 written bytes,
keyboard input bits, unmapped input values and PIO TX overflow flags are checked.

The runner restores all three affected RAM pages and the original mapping,
then boots/resets the normal menu. It stops tape playback but preserves the
buffered file. It uses RP2350 SET/CLR aliases, which differ from RP2040.
Keyboard/tape clients should be stopped during a run.

With the matching build already flashed and local OpenOCD running:

```sh
make test-bus-benchmarks BENCHMARK_OUTPUT=derived/bus_benchmarks/before.json
# After changing, building and flashing firmware, restart OpenOCD:
make test-bus-benchmarks BENCHMARK_OUTPUT=derived/bus_benchmarks/after.json
python3 tests/compare_bus_benchmarks.py \
    derived/bus_benchmarks/before.json derived/bus_benchmarks/after.json
```

For a subset, use `python3 tests/run_bus_benchmarks.py output.json --case ram_read
--case ram_write`. The comparator rejects different CPU clocks, LCD activity,
tape-presence conditions or workload sizes. Buffered tape can change the FE
input path even when stopped; keep that condition the same across comparisons.
JSON includes ELF hashes, elapsed times, polling intervals, operation rates
and passive WAIT estimates. The measured runs had no buffered tape.

Host SWD polling brackets the marker writes. Maximum observed polling gaps
were about 9–26 ms for optimized runs and 12–17 ms for the baseline, against
3.6–4.1 second workloads. Treat small differences accordingly. Standard Z80
instruction timings also provide a nominal MHz estimate; completed-operation
rates are the primary metric for comparing these identical programs.

## LCD counter limitation exposed by these tests

The qualified-WAIT counter overstates the optimized workload's throughput.
For example, fetch reports about 82,535 T per 20 ms while its known nominal
instruction count divided by elapsed time gives about 66,695 T per 20 ms.
The increase in LCD text therefore must not be interpreted as the measured
execution speedup. RD/WR-qualified WAIT observation does not decode internal
T2, and observing GPIOs near a sampling boundary is phase-sensitive.

A passive trace confirmed RD transitions near rising CLK, so merely changing
the assumed CPU edge is not established as a fix. The exact counting bias has
not been isolated. Use completed-work timing for optimization comparisons;
the current LCD value remains an estimate, not an exact runtime T-state counter.

## Validation and retained artifacts

- Release firmware programmed and verified; baseline and two optimized device
  suites completed with data checks and no TX overflow or counter FIFO stalls.
- Host ROM/banking/ULA tests passed with sanitizers, including non-M1 fast-load
  operands, the outgoing fetch, final block, and cached-observer transitions.
- Normal tape pulse/protocol tests and real-ROM fast-loader tests passed.
- Both async PIO simulation suites passed (12 tests).
- Actual VIBRATE loading completed all four fast blocks, and its outgoing fetch
  cleared observation. F10 reset worked with no TX overflow and retained the
  tape; rewind reenabled observation. These checks do not certify the demo's
  separately diagnosed interrupt/stack issue as fixed.

Data and matching firmware snapshots are retained in
`derived/bus_benchmarks_20261008/`: `before.json`, `after.json`,
`after-repeat.json`, `comparison.md`, `before.elf`, `after.elf`,
`edge-phase.json` and `regression.json`.

The final board state is the normal 50 Hz menu, with VIBRATE buffered and
rewound in fast mode. The temporary OpenOCD instance was stopped.

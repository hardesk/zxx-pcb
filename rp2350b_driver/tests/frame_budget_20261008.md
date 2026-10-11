# VIBRATE frame budget, 2026-10-08

Later [finite device benchmarks](bus_benchmarks_20261008.md) showed that the
qualified-WAIT estimate can substantially overstate execution throughput after
shortening the reply path. Treat the figures here as GPIO estimates, not an
exact count of CPU progress; use completed-work timings to compare optimizations.

The running production setup at 5 MHz delivered an estimated **67,022 nominal
T-states per 20 ms** in the first 500 measured windows after VIBRATE entered
its drawing code. A repeat delivered **68,543**. That is approximately
**3.35–3.43 MHz** after transfer wait extensions, with the LCD active.

| Capture | Mean estimated T-states / 20 ms | Minimum | Maximum | Equivalent MHz |
| --- | ---: | ---: | ---: | ---: |
| 50 Hz INT, first run | 67,021.564 | 63,074 | 71,026 | 3.351 |
| 50 Hz INT, repeat | 68,542.614 | 63,413 | 74,874 | 3.427 |
| 25 Hz INT, control | 67,663.146 | 64,440 | 71,999 | 3.383 |

Each capture contains 500 windows of exactly 100,000 physical CLK edges:
20 ms at 5 MHz, or ten seconds total. The control also uses 20 ms windows;
only its interrupt frequency changes. The repeated 50 Hz means differ by
2.27%, so the result should be treated as roughly 67–69 thousand rather than
a fixed instruction budget.

## What was counted

Unused PIO2 SM1/2/3 observed CLK, `/WAIT`, `/RD`, `/WR` and `/HALT`.
DMA2..7 collected counts and supplied window reload values. Nothing was added
to the CPU bus-service loop, no firmware was flashed, and neither RP core was
halted. Count-none, count-all and GPIO-decoding calibrations passed before each
capture. The count-all result was exactly 100,000 for every counter.

The RZ80's TV80 state machine samples `/WAIT` on the **rising** CLK edge:
see the positive-edge state machine and its `tstate[2] && wait_n == 0`
hold condition in
[tv80_core.v](/Users/orl/Projects/electronics/ci2406-rej-pommedeterrible-tholin/verilog/rtl/Z80/tv80_core.v:1263).
The counter uses that edge. CLK's PIO input synchronizer was bypassed to
compensate for the edge-detection/JMP latency; WAIT and control synchronization
was retained. This is a GPIO observation, not an internal TV80 state trace.

For the first 50 Hz run:

| Quantity, mean per window | CLK edges |
| --- | ---: |
| Total | 100,000 |
| `/WAIT` low at the sampling edge | 42,799.736 |
| Raw `CLK minus WAIT-low` | 57,200.264 |
| `/WAIT` low with `/RD` or `/WR` asserted | 32,978.436 |
| Estimated nominal T-states, subtracting transfer-qualified WAIT | 67,021.564 |

The raw subtraction gives **2.86 MHz**, but it subtracts assertions during
refresh and other intervals where the CPU does not extend a transfer. The
qualified estimate excludes these assertions, recovering about 9,821 clocks
per window in this run. Approximately **33%** of physical clocks were spent
in transfer-qualified WAIT.

Qualification by RD/WR is an approximation: it does not decode the internal
T2 state or every interrupt-acknowledge phase. The estimate includes nominal
refresh and HALT cycles and is not a count of retired instructions or useful
non-HALT execution. `/HALT` was low for 14.11% of physical clocks in the first
run and 13.67% in the repeat; the 25 Hz control spent 34.88% in HALT.

## Capture limits and retained data

Capture started when the loader's unpacked drawing-entry and IM2 signatures
appeared in RAM, polled every 10 ms. This is an approximation to the first
visible effect, not an optical trigger on the LCD.

Both 50 Hz captures ended with eight invalid drawing-table words, consistent
with the [previously captured interrupt/stack corruption](vibrate_hang_20261008.md).
Entry-code polling did not detect a change, but that does not establish that
all 500 windows were healthy. The 25 Hz control ended with no invalid table
entries. The 50 Hz results therefore describe the actual workload, including
any corruption during the capture; they are not a benchmark of 500 verified
correct demo frames.

JSON and per-window CSV are in
`derived/frame_budget_20261008/50hz-rz80-rising.{json,csv}`,
`50hz-rz80-rising-repeat.{json,csv}` and
`25hz-rz80-rising.{json,csv}`. Earlier falling-edge cross-checks are retained
separately and are not used for the results above. `discarded-input-base.json`
is explicitly invalid and must not be used.

## Repeating the measurement

The capture below requires firmware without the subsequent permanent runtime
counter, and VIBRATE.TAP already buffered. The diagnostic's resource checks
reject the current runtime counter safely. For continuous measurement in
current firmware, use the LCD T-state label described in [README.md](README.md).
For the earlier firmware, run:

```sh
make openocd
# In another terminal:
python3 tests/measure_frame_budget.py derived/frame_budget_20261008/new-50hz.json
# Optional control:
python3 tests/measure_frame_budget.py derived/frame_budget_20261008/new-25hz.json --interrupt-hz 25
```

The tool resets/replays the retained tape. It depends on this firmware's
memory layout and checks the required free PIO state machines, instruction
space, DMA channels and capture-buffer separation from the tape allocation.
It restores its borrowed resources, resets to the menu at 50 Hz, and rewinds
the tape afterwards. It is a diagnostic tool, not permanent firmware telemetry.

After these captures, LCD SM0 remained enabled, SM1/2/3 and DMA2..7 were
disabled, CLK synchronization was restored, and INT was restored to 50 Hz.
VIBRATE remains buffered and rewound in fast mode. The measurement's OpenOCD
instance was stopped.

# POWER_UP.TAP "hang" — 2026-10-08

## Diagnosis

The stop about 4–5 s after the Y/N prompt is a **tape-order deadlock in the
TAP**. It is not an RP/PIO stall, a CPU-core fault or memory corruption. The
BASIC loader asks for `LDIR` before `1_BASE`, but the TAP stores `1_BASE`
first. The standard ROM loader's search for `LDIR` reads and discards the
`1_BASE` header and data. Line 50's `LOAD "1_BASE"` then searches the rest of
the tape, reaches its end, and waits indefinitely in LD-EDGE. A real 128K or
Pentagon playing this TAP from a tape deck would do the same: the name
comparison and block skipping are done by the unmodified ROM.

The demo was a TR-DOS release (archive `INFO/POWER_UP.TXT`: "TR-DOS v5.03+",
Pentagon 128). On disk the files are loaded by name in any order. The 1998
TAP conversion (`taps/POWER_UP.TAP` is byte-identical to the zip's copy) put
the blocks in tape order without matching the BASIC load order. The TAP was
not modified for this investigation.

## Setup

Production firmware `derived/drv_rel/rp2350_driver.elf` (SHA-256
`a31fa1d3…a5a2`; SRAM bus loop verified against the device). The RZ80 ran at
5 MHz, the RP2350 at 150 MHz, the LCD was active, and INT was 50 Hz. Tape mode
was fast, loaded from the 128 menu's "Tape Loader", as reported. Nothing was
flashed, no RP core was halted, and no SRAM code was patched.

Observation was passive. OpenOCD Tcl reads of SIO `GPIO_IN`/`GPIO_HI_IN`
(~2,000 samples/s) gave M1 fetch-address histograms, and the RP's own state
was read over SWD: paging register, mapped pointers, `ZxTape` fields, screen
and all eight RAM banks. The RTT tape-status replies on channel 2 show core0
servicing its 256-transfer housekeeping throughout.

## Timeline (from Tape Loader selection)

| Time | Tape | Paging | Z80 activity |
| ---: | --- | --- | --- |
| 0.0–0.5 s | blocks 0–3 (BASIC, PUP-TEST) fast-loaded | 0x10 | ROM loader, then PUP-TEST self-depacker at B800 |
| 0.6–6.0 s | idle | 0x10 | PUP-TEST: beeper loop 03D6 / caller 648E–6491 |
| ≥ 6.2 s | idle | 0x10 | 6302–630A: `XOR A; IN A,(FE); CPL; AND 1F; JR NZ` — waits for any key under "USING COLOURFUL TV-DRIVE (Y/N)?" |
| after Y | blocks 4–15: 1_RAM-00…07 | 0x10→0x17 | Each block followed by `RANDOMIZE USR 49152` depacker (BFxx) |
| +4.8 s | block 16 | 0x17 | 1_RAM-07 depack done; BASIC line 2030 `LOAD "LDIR"` |
| +5.2 s | **finished, 38/38** | 0x17 | ROM LD-EDGE loop 05ED–05F8 indefinitely |

The PUP-TEST key wait is the first "freeze". It is intended, and Y/N (any
key) continues it. The second freeze, the static "Light Dreams… / megacode"
screen, is the reported hang. At that point BASIC's `PPC` is **50** with
`ERR_NR` 0xFF. The BASIC program in RAM matches the TAP byte for byte; only
the variables area after it differs. Tape positions jump from block 16 to 38
within ~0.4 s: `LOAD "LDIR"` skips blocks 16/17 and loads 18/19, then
`LOAD "1_BASE"` scans blocks 20–37 without a match.

## BASIC loader (decoded)

```text
 15 LOAD "PUP-TEST" CODE 25000        16 RANDOMIZE USR 25000
 20 GO SUB 2000
 50 LOAD "1_BASE" CODE 32768          60 RANDOMIZE USR 30000
120 GO SUB 2000
150 LOAD "2_BASE" CODE 32768         160 CLS: RANDOMIZE USR 30000
200 POKE 23388,17: OUT 32765,17: LOAD "EPILOGa" CODE 25000
2000 FOR f=1 TO 6: READ ba: POKE 23388,ba: OUT 32765,ba: READ n$: LOAD n$ CODE 49152
2010 RANDOMIZE USR 49152
2020 NEXT f
2030 LOAD "LDIR" CODE 30000
2040 RETURN
```

Tape order: … 1_RAM-07, **1_BASE, LDIR**, 2_RAM-00 … 2_RAM-07, **2_BASE,
LDIR**, EPILOGa. The same inversion occurs again at line 150 (`2_BASE`).

## Confirmation without changing the TAP

While BASIC waited at line 50, the buffered tape was rewound with the normal
`zx_tape.py rewind` control, equivalent to rewinding a cassette. The ROM
skipped blocks 0–15, loaded `1_BASE` (blocks 16/17) and stopped at block 18.
Line 60's `RANDOMIZE USR 30000` then started Part 1. Over the following 40 s
it ran HALT-paced frames (about 45% of samples in HALT) with screen-bank
flipping (0x17/0x1F) and drew the MEGACODE logo, the POWER UP picture and
the "EYES!!!" text sequence (`derived/power_up_debug/run1_rewind/montage.png`).
This passes the reported failure point. It does not certify the rest of Part 1:
the archive notes that WAIT-state machines render some parts badly, and the
VIBRATE frame-budget mechanism may still apply to effects with strict timing.

The same rewind is needed once more at line 150 for `2_BASE`. In practice:
load as normal; when the screen freezes after the first or second set of RAM
blocks, `rewind` the tape.

## Reordered copy

`taps/POWER_UP_fixed.TAP` (created on request; the original is unchanged)
swaps the two `*_BASE`/`LDIR` header+data pairs, so the tape order matches
the BASIC load order: … 1_RAM-07, LDIR, 1_BASE, … 2_RAM-07, LDIR, 2_BASE,
EPILOGa. All block bytes and XOR checksums are unchanged and the file size
is identical. A host simulation of the 19 named loads finds every file in a
single forward pass, ending exactly at the last block. It has not yet been
loaded on hardware.

## Answers to the brief's questions

- Core0 remains responsive at the hang: RTT tape status replies, and the Z80
  is served in the ROM loader loop with no stalled request.
- The Z80 is in ROM1 `LD-EDGE-1`/`LD-SAMPLE` (05ED–05F8). Paging is 0x17:
  ROM1, bank 7 at C000, normal screen 5 unlocked.
- Code and stack were not corrupted. Program bytes are unchanged and the stack
  matches an active `LOAD` from line 50. The paging register was valid at
  every sample.
- The fast tape overlay is not the cause. It retains the ROM's own flag and
  name handling, so normal pulse playback reaches the same state, only more
  slowly.

## Retained data

`derived/power_up_debug/`:

- `run1/`: load and PUP-TEST
- `run1_after_y/`: RAM blocks to the deadlock
- `run1_rewind/`: rewind and Part 1

Each run directory holds `log.jsonl` (per-interval fetch histograms, tape and
paging state) and screens. `dump_yn/` and `dump_end/` are all eight banks plus
mapping metadata at the Y/N prompt and at the line-50 stall. `tools/` holds the
passive monitor, dump script and disassembler wrapper (needs the SkoolKit copy
in `/tmp/vibrate-skoolkit`).

Board state afterwards: production firmware unchanged; POWER_UP.TAP buffered
in fast mode (this replaced the previously buffered 33,679-byte tape).

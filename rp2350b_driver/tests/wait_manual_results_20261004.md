# Real-board asynchronous PIO investigation — 2026-10-03/04

## Result

The current detector/service implementation is not stable on the attached
board. A version with no CLK observation in either bus handling or WAIT control
also fails. Two qualification experiments remove invalid snapshots but still
repeat requests. The older clock-aware implementation passes the same workload.

No production PIO, C++ driver, application, pin mapping or CMake source was
changed. Experiments used isolated source copies under `/tmp`. The normal
working-tree firmware was rebuilt for restoration after testing.

## Setup and identity

- Original file: `z80_pio_bus_wait-manual.pio`.
- SHA-256: `f58389db8b6eddfe1d420fb81e15e35e527c4436dfdee6bb7b11f925835c1409`.
- Detector/service do not observe CLK. The original WAIT guard still contains
  `wait 1 gpio 24`; the explicitly asynchronous comparison removes that line.
- RP2350/CMSIS-DAP, existing FPGA configuration, 150 MHz system clock, Debug.
- `tests/wait_bus_stress.asm` loaded at `0100h`; blocking request logging enabled
  before each reply. No artificial reply delay. Every stress run stops RTT
  polling for 500 ms every two seconds, otherwise polling every 1 ms.
- Every run starts with a verified flash/reset. The independent checker examines
  address, M1, transfer controls, memory contents and write data from reset.
- Normal source snapshots/hashes, diagnostic sources/ELFs, raw logs, flash
  confirmations and checker results are in `derived/wait_stability_20261003/`.

## Hardware tests

| Variant | Clock | Duration | Result |
|---|---|---|---|
| Current file | 1 MHz | 12 s | First mismatch 71: inactive request at `0102` |
| Current file | 100 kHz | 12 s | First mismatch 35: inactive request at `011A` |
| Remove CLK wait from guard | 1 MHz | 12 s | First mismatch 20: inactive request at `010D` |
| Remove CLK wait from guard | 100 kHz | 12 s | First mismatch 38: inactive request at `011D` |
| Two qualified samples, publish accepted snapshot, no CLK wait | 1 MHz | 15 s | First mismatch 559: duplicate opcode fetch at `011D` |
| Above plus four consecutive idle samples before completion | 1 MHz | 15 s | First mismatch 443: repeated operand read at `0129` |
| Historical `z80_bus_wait.pio` with its matching driver | 1 MHz | 45 s | **PASS: 83,773 requests, 1,288 complete loops** |

The first four failures have all MREQ, IORQ, RD and WR inactive. The two filtered
runs contain respectively 27,597 and 27,348 complete records with no such
invalid snapshots, but their request sequences still fail. Records after a
first mismatch are not validated transfers. Failure indices from single runs
are not statistical reliability rankings.

The qualification experiment preserves the detector's accepted ISR and publishes
it through detector RX, while replies still go to service TX. Memory/IO RD/WR
requests require two qualified samples, with an eight-tick sampling instruction.
The existing interrupt-acknowledge branch bypasses this new two-sample filter;
interrupts were not tested. Debug IRQ markers were disabled to fit PIO0.

The completion experiment moves completion polling to the WAIT guard (its input
base is explicitly GPIO16). It requires four consecutive samples with all four
strobes inactive before signaling the service to release OE and notify the
detector. This is still an experimental failed candidate, not a production fix.

## What the on-device capture establishes

An independent PIO2/DMA recorder samples GPIO0..31 every four system clocks,
26.67 ns per sample. An 8,192-word circular buffer is stopped on the first
published request with all four control strobes inactive. The recorded PIO
FIFO-stall flags are zero. Capture adds DMA traffic and changes failure timing;
these are diagnostic runs, separate from the stress matrix above.

`async_ring.log` catches an invalid published request at `0122`, while WAIT
asserts before the sustained MREQ/RD assertion of the next opcode fetch.

A second diagnostic saves the detector ISR to its RX FIFO before raising
REQUEST. This adds one PIO instruction and removes the debug-start IRQ to keep
within the instruction budget. `accepted_ring.log` records:

```text
accepted 97010855 published f7010855
```

| Snapshot | Address | M1 | MREQ | RD | IORQ | WR |
|---|---|---|---|---|---|---|
| Detector accepted | `0108` | active | active | active | inactive | inactive |
| Service published | `0108` | active | inactive | inactive | inactive | inactive |

The circular capture around that event has these sample indices:

| Sample | Observed event |
|---|---|
| 7963 | Previous read at `4000` deasserts MREQ/RD |
| 7978 | CLK rises |
| 7982 | Address becomes `0108`, M1 asserts; MREQ/RD are inactive |
| 7987 | WAIT asserts while MREQ/RD are still inactive |
| 7997 | CLK falls |
| 8001 | Sustained MREQ/RD assertion at `0108` begins |

The detector observed active MREQ/RD during this transition, but the sustained
read does not begin until roughly half a clock later. The 26.67 ns recorder
does not resolve the brief active condition itself, so its exact width and
electrical origin remain unmeasured. The extra detector snapshot establishes
what PIO accepted; it does not establish an analog glitch amplitude or width.

The checked local Tang FPGA source derives external controls combinationally
from several registered timing fields (`z80_core.v` / `z80_timing.v`) and
exports them directly in `fpga/tang-primer-25k/top.v`. Transient decode states
are a plausible source of the observed early qualification. The programmed
bitstream was not identified against that checkout, so this is supporting
source evidence rather than proof of the exact loaded implementation.

## Recommendation

1. **For the tested workload, use the clock-aware `z80_bus_wait.pio` and its
   matching initialization at 1 MHz.** This is the implementation that passed
   today's controlled run. It pre-arms WAIT, qualifies a settled request,
   releases WAIT at a settled clock phase after data/OE setup, and filters
   completion. Its 45-second pass is not universal or long-duration validation;
   interrupt acknowledge and reset during a transaction remain unqualified.
2. **If the RP2350 must ignore CLK, establish a stable transaction interface.**
   Prefer registering/latching address, data/OE and request controls coherently
   in the FPGA, with a request-valid/completion handshake held through servicing.
   Handle response acceptance at the FPGA's actual clock-enable boundary.
   Registering individual signals without preserving their relative timing is
   not sufficient. Alternatively, define and measure a maximum transient width
   and minimum valid/idle interval before designing an asynchronous filter.
3. **Keep qualification and payload together.** Publish the snapshot that was
   actually validated, and sample writes only once their data is valid. This
   fixes a demonstrated gap in the current handoff, but the experiments show
   that it is not enough by itself.
4. **Do not use a single idle sample, an address deduplicator, or arbitrary extra
   delays as the stability fix.** Completion must mean the CPU has finished
   consuming/driving data. Consecutive legitimate accesses may share addresses.
   Four idle samples plus request filtering still failed on this board.

The clock-independent approach is not proven impossible. What is disproven by
these runs is that instantaneous RD/WR/MREQ/IORQ qualification, or these short
fixed filters, are sufficient on the present bus.

Protocol references: [Zilog Z80 CPU manual](https://www.zilog.com/docs/z80/um0080.pdf)
for WAIT sampling and bus timing, and the
[RP2350 datasheet](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)
for PIO input synchronization. Input synchronizers reduce metastability risk;
they do not establish a complete, stable multi-signal bus transaction.

## Final board state

The normal working-tree firmware was rebuilt, flashed, verified and reset:
Debug WAIT at 1 MHz, original `test.asm` at `8000h`, request logging disabled,
no injected delay and no GPIO capture. `normal_restored_flash.txt` records the
successful flash verification. The failed experimental candidates and the
passing reference remain saved as diagnostic artifacts; none was installed as
a production source change.

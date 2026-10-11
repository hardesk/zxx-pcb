# Spectrum 128K and ULA ports

The firmware boots the original 128K editor/menu ROM (`128-0.rom`, ROM slot 0)
and companion BASIC ROM (`128-1.rom`, slot 1). Generated headers retain the exact
16 KiB images; their redistribution notes are in `roms/README.copyright`.
This implements the original 128K memory model, without AY or TR-DOS.

## Port 0xFE

All even I/O addresses select the ULA:

- Writes latch bits 0..4. Bits 0..2 select the normal-intensity border colour;
  bit 3 is the MIC output latch (low is active); bit 4 is the beeper/EAR output.
- Reads return the keyboard matrix in bits 0..4, with bit 6 from
  `ula.set_ear_input(bool)`. Bits 5 and 7 read high. With no tape backend the
  input defaults low. Physical audio/tape I/O and analogue loopback are not
  implemented; output getters retain the state for a future backend.
- Core1 samples the atomic border latch while preparing each eight-line LCD
  strip, so OUT-driven colour changes reach the thin border, including loading
  stripes. This samples live state rather than reproducing precise ULA raster
  timing. The refresh label remains in the separate outer margin.

## Port 0x7FFD

Original 128K partial decoding is `(port & 0x8002) == 0`. An even alias can
write both paging and ULA latches; neither decoder suppresses the other.

| Bit | Effect |
| --- | --- |
| 0..2 | Select RAM bank 0..7 at C000..FFFF |
| 3 | Display bank 5 (0) or bank 7 (1) |
| 4 | ROM 0 (editor/menu) or ROM 1 (BASIC) at 0000..3FFF |
| 5 | Apply this write, then ignore further paging writes until reset |

RAM bank 5 remains at 4000..7FFF and bank 2 at 8000..BFFF. Mapping bank 5 or 2
into the upper slot aliases the same physical memory. Selecting the shadow
screen never changes either fixed RAM slot. The LCD snapshots the selected
bank pointer once per frame using atomic publication, then reads that live bank.

`enable_128k()` requires registered ROM slots 0 and 1. `reset_machine()` restores
ROM 0, upper RAM bank 0, screen bank 5, unlocked paging and reset ULA/keyboard
state, preserving RAM contents. The GPIO38 reset button now calls this with
RZ80 held reset and stops/restarts the frame interrupt around the reset.

Selecting 48 BASIC in the ROM menu uses ROM 1 and its normal paging-lock write;
it does not replace the companion ROM with the standalone `48.rom`.

Unimplemented odd ports read FF, including AY and paging readback. No AY,
TR-DOS, floating-bus emulation, original contention delays, physical EAR/MIC,
or audio synthesis is included. The configured Z80 clock is preserved (the
current development configuration is 1 MHz); IRQ and LCD pacing remain 50 Hz.
This is a functional memory/I/O implementation, not cycle-exact 128K timing.

## Verification

`python3 tests/test_rom.py` checks generated ROM bytes, all eight banks, ROM
protection, screen selection, lock/reset, keyboard/EAR/output bits, PIO I/O
routing, and all 65,536 addresses against the independent partial decoders.
Keyboard, LCD/PIO and interrupt regressions also pass.

On-board validation: the two-ROM firmware boots to the Sinclair 128 menu,
selects RAM bank 7 during ROM initialization, advances FRAMES, and accepts RTT
keyboard snapshots. In 128 BASIC, an RTT-entered `BORDER 2` produced ULA output 0x02 and
RGB444 0xC00 in the LCD border buffer. At the current 1 MHz setting, allow the
ROM menu to finish appearing before sending navigation keys; early keys during
startup can be missed. Physical visual confirmation is separate from these
memory/state checks.

Reference: [Sinclair 128 service manual](https://spectrumforeveryone.com/wp-content/uploads/2017/11/ZX-Spectrum-128-Service-Manual.pdf).

# Tape and TR-DOS disks over RTT

`zx_media.py` (formerly `zx_tape.py`) uses only the Python
standard library. Over channel 2 on TCP port 9092 it uploads a whole TAP file
into RP RAM and arms it for the Spectrum ROM loader, and mounts TRD/SCL disk
images in TR-DOS drives A..D (see [TR-DOS disks](#tr-dos-disks)). The host
connection can close after an upload; the RP plays the tape and serves the
disks locally.

Start the normal OpenOCD/RTT setup with `make openocd`, which now exposes all
three channels. If using an already-running VS Code OpenOCD session with the
current firmware, enter in its Debug Console:

```text
monitor rtt server start 9092 2
```

## Commands

```sh
python3 tools/zx_media.py        # or: make media (aliases: make tape, make rtt2)
```

```text
zx> tape /path/to/game.tap
zx> mode fast
zx> disk /path/to/demo.trd       # drive A
zx> disk /path/to/game.scl B ro  # drive B, read-only
zx> status
zx> quit
```

Up/Down arrows recall command history on macOS/Linux through Python readline.
History is kept for the current tool session. Tab completes commands and filenames
after `tape ` and `disk `, including directories, `~/` paths and filenames containing spaces.

Quote paths containing spaces. Windows paths also work as one-shot arguments;
forward-slash paths work in the interactive prompt on every platform.

```sh
python3 tools/zx_media.py tape "my game.tap"
python3 tools/zx_media.py disk demo.trd
python3 tools/zx_media.py status
make disk DISK_FILE=demo.scl DRIVE=B
```

Use `--host`/`--port` for another RTT endpoint. One tool owns channel 2 at a time.
Keyboard channel 1 can remain connected while uploading or playing tape.

- `tape <file>` validates block lengths locally, uploads in acknowledged 512-byte
  chunks, and commits/arms the whole file after CRC verification on the RP.
  This replaces the previous tape. Files up to **256 KiB** are supported.
- `stop` stops playback and keeps the file. It does not press BREAK on the ZX;
  use the keyboard sender's Escape if you also want to cancel LOAD.
  During an incomplete upload, `stop` aborts it and releases the buffer.
- `rewind` returns to block zero and re-arms the file. It can restart the pilot
  signal if the ROM is already waiting for tape.
- `mode normal` selects original EAR pulse playback (the default).
- `mode fast` bypasses pilot tones and bit decoding for subsequent standard ROM
  loader calls. A temporary ROM read overlay supplies buffered bytes through
  virtual ports, keeping the ROM's LOAD/VERIFY, flag, destination, and checksum
  logic. The ROM images themselves are unchanged. Fast mode has no tape stripes.
  Change modes before issuing LOAD; a change during a loader call is rejected.
  Uploading or rewinding while BASIC waits for tape also enables fast mode,
  at the next safe EAR sampling-loop boundary.
  Upload/rewind during an active fast call is rejected; stop then cancel LOAD.
  Mode persists across tape uploads and RZ80 reset, but RP reset defaults to normal.
- `reset` requests an RZ80 reset through the same bus-safe path as the physical
  reset button. The RP and RTT stay running; keyboard/ULA/paging reset and the
  buffered tape is retained, stopped. Use `rewind` afterward to arm it again.
- `status` reports state, file size, uploaded bytes, tape byte position,
  completed block count, total blocks, capacity and mode. `playback` shows the
  active path; `fast_blocks`/`normal_blocks` count completed blocks since upload
  or rewind, so the requested mode can be distinguished from actual playback. States are `empty`,
  `uploading`, `armed`, `playing`, `stopped`, and `finished`.
- `quit`/closing the host tool leaves the uploaded tape and playback intact.

For a small example, upload `tests/tape_hello.tap`; its BASIC program prints
`TAPE OK` after loading.

Upload the TAP, then issue `LOAD ""` on the Spectrum. Uploading while the ROM is
already waiting also works: committing the file starts a fresh pilot signal on
its next loader instruction. After pressing the RZ80 reset button (GPIO38), the file is retained but
stopped; use `rewind` to arm it again. Resetting/power-cycling the RP discards it.

## TR-DOS disks

The firmware emulates a Beta 128 interface with TR-DOS 5.03 (`roms/trdos.rom`).
The default editor ROM is the Pentagon 128 one (`roms/128p-0.rom`): its menu has
a **TR-DOS** item in place of Tape Tester. From BASIC, `RANDOMIZE USR 15616`
enters TR-DOS as usual (from 48 BASIC, note the menu's 48 BASIC locks 128K
paging, so 128K software should be started from the TR-DOS item or 128 BASIC).
In TR-DOS, `RUN` boots the disk's `boot` file and `LIST` shows the catalog.
Build with `-DZX_PENTAGON_ROM=OFF` for the original Spectrum 128 menu.

- `disk <file> [A|B|C|D] [ro]` mounts a `.trd` or `.scl` image, in drive A unless
  a drive is given. SCL is converted to TRD on the host (files laid out from
  track 1, catalog and disk info sector written as TR-DOS would). The empty tail
  of the image is not sent: the RP reads unwritten sectors as zeros. `ro`
  write-protects the drive.
- `eject [A|B|C|D]` empties a drive (A by default); `disks` lists them; `status`
  shows the tape and the disks.
- `blank [A|B|C|D] [label]` mounts a freshly formatted 80-track double-sided disk.

Images live in the last 4 MiB of the RP's flash, one 1 MiB slot per drive, so
mounts survive an RP reset and reflashing the firmware. Mounting erases and
programs only the 4 KiB flash blocks that differ, holding the Z80 for each
(~50 ms). A full 640 KiB disk uploads in about 18 s, limited by the CMSIS-DAP
probe's RTT bandwidth (~35 KiB/s); remounting the same image costs the transfer
only.

TR-DOS writes (SAVE, FORMAT, MOVE) go to a one-block RAM cache and reach flash
after the drive has been idle for 0.5 s, on a mount change, or at an RZ80
reset; `disks` reports pending writes. Each flash write holds the Z80 for one
block erase. Power loss within that half second loses the last writes.

The WD1793 completes commands at once: DRQ is ready when TR-DOS polls, and disk
rotation appears only as 300 rpm index pulses (TR-DOS uses them to detect a
disk) and as the Write Track timeout. Read/Write Sector (single and multiple),
Read Address, Restore/Seek/Step with verify, Write Track (format) and Force
Interrupt are emulated; Read Track ends immediately with no data. Copy
protection that depends on real track layout or timing will not work.

TR-DOS 5.03 quirk: the first time a drive is used, its drive detection writes
50h into a variable that SAVE has already set, so the first `SAVE ... CODE` to
a fresh drive records its start address 80 too high (the data itself is
right). Touch the drive first, e.g. `CAT "b:"`. The host emulator test
reproduces this with the stock ROM.

## Playback and scope

The receiver is `ZxTapeRtt`; its protocol parser is `ZxTapeProtocol`. The tape
object belongs to `Rp2350ZxEnv`. All transfer/control/playback mutation happens
on core0 between bus requests. Upload/control processing is bounded per poll;
no tape data is streamed in real time from the PC.

Each TAP block contains a little-endian length followed by flag, payload and
checksum. The RP generates 8063 header or 3223 data pilot pulses of 2168 T states,
667/735-T-state sync pulses, and two 855/1710-T-state pulses per zero/one bit.
Data is sent MSB first, including the TAP's original flag/checksum bytes.
The ROM retains responsibility for accepting a flag, writing memory and checking
its XOR checksum; the upload CRC only protects the host-to-RP transfer.

This first version supports the **standard ROM LD-BYTES routine at 0556..0604**
in the supplied 48K ROM and 128K companion BASIC ROM. Firmware verifies all
175 routine bytes before applying its instruction timing profile. Z80 M1 fetches
advance a virtual pulse clock using executed instruction timings and resolved
conditional branches; IN samples partway through its instruction. WAIT time,
RTT pauses and the configured physical clock do not distort that virtual clock.
In normal mode, no memory is loaded directly as a shortcut: the real RZ80 ROM reads EAR bit 6
and decodes the pulses itself, driving the border through normal OUT instructions.

A block begins on loader entry and waits between blocks until the next ROM load
request. This accommodates the slow development CPU and ROM header processing
without racing ahead during BASIC/editor work. Returning early from the loader
skips the rest of the current block. Custom machine-code loaders, TZX, recording,
and physical tape/audio I/O are outside this version's scope.

For fast loading:

```text
tape> mode fast
tape> tape /path/to/game.tap
```

Then issue `LOAD ""` on the Spectrum. `mode normal` restores pulse playback.

## Wire protocol

Every frame: `ZT`, version byte 1, opcode byte, sequence u32 LE, payload length
u16 LE, payload, CRC32 of header+payload (u32 LE). Payload limit is 2052 bytes
(tape chunks use 516).
Responses use opcode OR 80h, the same sequence, and a JSON payload containing
`ok` and status. A rejected command has `ok:false`. The receiver caches the last
response so retransmitting a request does not repeat commit/rewind actions.
Malformed frames resynchronize; partial frames expire after 400 ms. The host
keeps one request outstanding and retries timeouts up to three attempts.

| Opcode | Payload |
| --- | --- |
| 1 BEGIN | total size u32, file CRC32 u32 |
| 2 CHUNK | byte offset u32, 1..512 bytes |
| 3 COMMIT | empty |
| 4 STOP | empty |
| 5 REWIND | empty |
| 6 STATUS | empty |
| 7 MODE | u8: 0 normal, 1 fast |
| 8 RESET | empty; acknowledges a queued RZ80 reset |
| 10h DISK BEGIN | drive u8, flags u8 (bit 0 read-only), size u32, CRC32 u32, name (≤24 bytes) |
| 11h DISK CHUNK | byte offset u32, 1..2048 bytes; short reply |
| 12h DISK COMMIT | empty; mounts after size/CRC check |
| 13h DISK EJECT | drive u8 |
| 14h DISK STATUS | empty |

Disk replies list all four drives. The host keeps up to three disk chunks in
flight (the RP's RTT down buffer is 8 KiB); replies arrive in order, and a lost
one aborts the upload instead of retrying.

The RP rejects invalid sizes, noncontiguous chunks, incomplete or corrupt
uploads, and malformed block lengths. A file is never played while uploading.
If an upload is interrupted, retry `tape <file>` to start a new upload.

Run `python3 tests/test_tape_fast.py` to execute the real ROM byte loop with
the fast overlay for LOAD, VERIFY, bad flags/checksums, short blocks and
consecutive blocks.

Run `python3 tests/test_tape.py` for transfer, pulse, instruction-clock,
resynchronization and control regressions with sanitizers.

Run `python3 tests/test_disk.py` (`make test-disk`) for the disk store and
WD1793, and an end-to-end run of the real 48 and TR-DOS ROMs on z80emu
(`Z80EMU`, default `~/Projects/speccy/z80emu`): `RANDOMIZE USR 15616`, `RUN`
of a `boot` from a converted SCL, and a SAVE checked in the catalog.
`tests/test_rom.py` covers the Beta 128 paging in the production environment.

References: [standard tape pulse specification](https://www.worldofspectrum.net/TZXformat.html)
and [ROM loader disassembly](https://www.skoolkit.ca/disassemblies/rom/hex/asm/0556.html).

On-board checks (2026-10-07, RZ80 at 1 MHz): the actual standard ROM loader
successfully decoded bytes 42h, 19h, A5h and returned carry set from a synthetic
buffered data block. A full 262,144-byte/four-block file uploaded and committed
with matching CRC; stop, rewind and status also passed. Its upload took 51.55 s
with OpenOCD's original 100 ms polling; `rtt.cfg` now requests 10 ms polling.
The normal 128K firmware was restored after the isolated loader test.

Fast late-upload check (2026-10-07, RZ80 at 1 MHz): the real ROM loader
loaded 42h, 19h, A5h with carry set in 1,982 microseconds; status reported
`fast_blocks: 1`, `normal_blocks: 0`. Production firmware with the fix was
restored, and the original 42,957-byte TAP was re-uploaded and armed in fast mode.

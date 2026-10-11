# Buffered TAP over RTT

`zx_tape.py` uses only the Python standard library. Channel 2 on TCP port 9092
uploads a whole TAP file into RP RAM, then arms it for the Spectrum ROM loader.
The host connection can close after the upload; the RP generates EAR locally.

Start the normal OpenOCD/RTT setup with `make openocd`, which now exposes all
three channels. If using an already-running VS Code OpenOCD session with the
current firmware, enter in its Debug Console:

```text
monitor rtt server start 9092 2
```

## Commands

```sh
python3 tools/zx_tape.py
```

```text
tape> tape /path/to/game.tap
tape> mode fast
tape> status
tape> stop
tape> rewind
tape> quit
```

Up/Down arrows recall command history on macOS/Linux through Python readline.
History is kept for the current tool session. Tab completes commands and filenames
after `tape `, including directories, `~/` paths and filenames containing spaces.

Quote paths containing spaces. Windows paths also work as one-shot arguments;
forward-slash paths work in the interactive prompt on every platform.

```sh
python3 tools/zx_tape.py tape "my game.tap"
python3 tools/zx_tape.py status
python3 tools/zx_tape.py stop
python3 tools/zx_tape.py rewind
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
u16 LE, payload, CRC32 of header+payload (u32 LE). Payload limit is 516 bytes.
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

The RP rejects invalid sizes, noncontiguous chunks, incomplete or corrupt
uploads, and malformed block lengths. A file is never played while uploading.
If an upload is interrupted, retry `tape <file>` to start a new upload.

Run `python3 tests/test_tape_fast.py` to execute the real ROM byte loop with
the fast overlay for LOAD, VERIFY, bad flags/checksums, short blocks and
consecutive blocks.

Run `python3 tests/test_tape.py` for transfer, pulse, instruction-clock,
resynchronization and control regressions with sanitizers.

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

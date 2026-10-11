# PC/Mac keyboard over RTT

`tools/zx_keyboard.py` opens a small Tkinter window (Python standard library;
no extra packages) that sends real key-down/key-up state over RTT channel 1.
Keys stay held for as long as you hold them, so games, chords and simultaneous
keys work. Conversion into Spectrum key combinations happens on the RP2350.
Channel 0 remains the console.

## Run

1. Build and load the firmware using the VS Code launch task or `make flash`.
   The 50 Hz interrupt is enabled in `main.cpp` so the Spectrum ROM scans its
   keyboard.
2. With no other debug session owning the probe, `make openocd` uses `rtt.cfg`
   and exposes console port 9090 and keyboard port 9091. It attaches to the
   running board without resetting it. If VS Code's OpenOCD is already running,
   use its Debug Console instead (do not start a second OpenOCD):

   ```text
   monitor rtt server start 9091 1
   ```

   `monitor rtt channels` should list `ZX keyboard` as up/down channel 1.
3. Run `make keyboard` (alias `make rtt1`), or
   `python3 tools/zx_keyboard.py --host 127.0.0.1 --port 9091`.
4. After `RP2350 keyboard acknowledged`, keep the window focused and type.
   If acknowledgement times out, load the latest firmware, resume the debugger
   and check RTT channel 1; a TCP connection alone does not prove delivery.
   Closing the window sends an empty state. Losing focus releases everything.
   If the connection drops, the firmware releases keys after 500 ms.

## Keys

Physical keys are sent unshifted (US layout), so a key keeps one identity while
modifiers change. Host Shift is Caps Shift and host Ctrl is Symbol Shift, as on
a real Spectrum; e.g. Ctrl+P types `"`. Host punctuation keys (`; ' , . / - =`)
are sent as those characters and the RP maps them to Symbol Shift combinations.
The Spectrum ROM still determines the meaning of keys in K/L/E modes.
Cmd, Alt, Caps Lock and unmapped keys are ignored.

| Host key | Meaning |
| --- | --- |
| Shift or F1 | Caps Shift |
| Ctrl or F2 | Symbol Shift |
| Left / Down / Up / Right | Spectrum cursors |
| Backspace or Delete | DELETE |
| Escape | BREAK |
| Tab | Extended mode |
| F10 | Reset the RZ80; buffered tape stays in RP RAM, stopped |

Mac keyboards may need Fn for F1/F2/F10. After a reset, use `rewind` in the
tape tool to arm the retained tape.

Host autorepeat is suppressed. Windows repeats as extra presses, which are
ignored while held; X11 and macOS Tk report each repeat as a release+press
pair, so a release is only sent after a 40 ms grace period with no re-press of
that key.

## Firmware API and transport

`Rp2350ZxEnv::keyboard` owns an eight-row matrix. `keyboard.set_key(row, col,
down)` edits a native key, `clear()` releases everything, and
`set_host_keys(codes, count)` replaces the whole state with converted host keys.
All calls are on core0. An incoming snapshot replaces any manually set state.
Rows are selected by low address bits A8..A15; selected rows are ANDed, columns
0..4 are active-low, odd ports return 0xFF. The existing even-port upper bits
remain 0xA0 (EAR low). Both legacy I/O handling and PIO requests use this matrix.

Packets are 35 bytes: `ZK`, 16 little-endian uint16 host codes (zero-padded), and
an 8-bit sum of the 32 payload bytes. Printable codes are Unicode values;
special host codes are listed in `ZxKeyboard::HostKey`. Snapshots are sent on
changes and every 100 ms. The checksum and sliding decoder recover from broken
frames; the full state prevents stuck synthetic modifiers after dropped releases.
RTT polling is bounded and runs between bus requests on core0, at most once per
2 ms, including before I/O replies. No second-core matrix sharing is needed.
Only one sender should own the keyboard channel.

## Validation

```sh
python3 tests/test_keyboard.py
python3 tests/test_rom.py
```

Tests exercise the real C++ matrix/decoder with sanitizers and packets from the
Python sender, including active-low row selection, overlapping modifiers,
corruption/resynchronization, timeout and timer wrap. They do not test physical
SWD latency or real windowing-system key events.

References: [OpenOCD RTT](https://openocd.org/doc-release/html/General-Commands.html),
and the
[Sinclair keyboard manual](https://worldofspectrum.org/ZXBasicManual/zxmanappc.html).

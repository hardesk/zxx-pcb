# VIBRATE.TAP hang — 2026-10-08

## Diagnosis

The demo misses its frame deadline with the current wait-stretched bus and
wall-clock 50 Hz interrupt. Its renderer uses SP as a graphics source,
destination and address-table pointer with interrupts enabled. An interrupt
during that work writes the interrupt frame into graphics data or the address
table. Corrupted destination addresses then cause the renderer to overwrite
its own code. This is not a stuck RP/PIO transaction or an incomplete TAP.

The retained tape was 34,304 bytes, four blocks, all consumed in fast mode.
The local TAP's four block XOR checksums are valid. Initial live inspection
found both RP cores running, responding to RTT, and an RZ80 executing a BASIC
ROM loop after the failure. The 128K paging register was 0x1D.

## Captured cause

A temporary SRAM ring recorded accepted bus requests without changing the
PIO programs or production flash. The trace froze shortly after the first
write into the drawing table (0x899F–0x8C9E), armed after the renderer's first
HALT at 0x857D. Trace instrumentation adds bus latency; an uninstrumented
50 Hz replay also failed and corrupted the code at 0x8101.

The decisive sequence in `derived/vibrate_debug/table-write-trace.json`
(chronological entries after rotating the ring at `control[0]`, omitting the
four header words):

| Entry | Accepted transfer | Meaning |
| ---: | --- | --- |
| 8056–8058 | Fetch 8622; read 8623 and 8624 | Execute `LD SP,0x8C39` |
| 8059 | M1 + IORQ, address 8625 | Accept IM2 interrupt before `POP HL` |
| 8060–8061 | Write 86 to 8C38; write 25 to 8C37 | Push interrupted PC 0x8625 into the table |
| 8062–8066 | Read BEFF/BF00; fetch BFBF and read its operands | Valid IM2 vector 0xBFBF and `JP 0x81AF` |
| 8067–8090 | Fetch interrupt prologue, writes 8C36 down to 8C29 | Saved registers overwrite more table entries |

An earlier failure capture, decoded in
`derived/vibrate_debug/failure-trace.txt`, showed the renderer reading a
corrupted table entry at 0x8C1B, loading SP with 0x8376, then pushing graphics
words into 0x8375 downwards. That overwrote its interrupt handler. Execution
subsequently reached a corrupted 0xFF opcode at 0x836F (`RST 0x38`) and entered
the ROM. The IM2 acknowledgement itself was decoded correctly.

## Timing experiment

The RP ran at 150 MHz and the RZ80 at 5 MHz with the LCD active. With the
temporary trace removed, the PWM interrupt period was changed from 20,000 us
to 40,000 us (25 Hz), retaining its pulse width, CPU clock, ROMs, TAP and bus
implementation. The same demo passed the known failure window and still ran
with intact entry code after 40 seconds. This is a short confirmation of the
initial failure mechanism, not a complete-demo compatibility certification.

A temporary SkoolKit 128K reference simulation loaded the same local TAP,
unpacked it, and ran the initial effect with its original code intact. No AY
or TR-DOS implementation was added to the board.

## Consequence

5 MHz on CLK does not mean 5 MHz of useful Z80 execution: memory and I/O
transactions insert WAIT cycles. The independent PWM interrupt continues
every 20 ms while software loses time to those waits. Frame-timed software
can therefore be interrupted at a point it never reaches on the original
machine. Fast tape mode only accelerates the ROM loader; it cannot accelerate
the running demo.

25 Hz is a demonstrated temporary workaround and slows animation. A general
fix needs either enough bus throughput to meet Spectrum frame budgets or a
frame clock tied to emulated CPU progress rather than unconditionally to
wall time. Simply changing the vector, keyboard, ROM or tape mode does not
address the captured corruption.

All diagnostic SRAM hooks and the temporary interrupt-rate change were
removed afterward. Production flash was not changed. The retained TAP was
rewound and the normal 50 Hz boot menu restored; the diagnostic OpenOCD was
stopped.

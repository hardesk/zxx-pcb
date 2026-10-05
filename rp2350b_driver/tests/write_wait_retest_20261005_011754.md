# FPGA write-WAIT retest — 2026-10-05, 01:17 Europe/Vilnius

Repeated the previous real-board tests using the identical RP test ELFs. Hash checks confirmed the RP production sources were unchanged. Only the user-updated FPGA changed between the two runs. No FPGA programming or production source edits were performed here.

## Results

| Check | Previous run | This run |
|---|---|---|
| Preasserted WAIT, 3.5 MHz, first memory write reply withheld 50 µs | Write held, but WR pulsed high 193 times | **Write held; WR continuously low; zero pulses** |
| Address 4000, DATA 55, MREQ low, RD high until WAIT releases | Stable | **Stable for 55.04 µs from WR assertion to WAIT release** |
| Mixed memory/I/O stress, 12-second RTT capture | 5,315,744 requests passed | **5,371,000 requests / 82,630 complete loops passed** |
| Current guard, 1 MHz, first write reply withheld 50 µs | Failed at request 10 because WAIT asserted late | **Same failure at request 10** |
| PIO model suite | 6 passed | **6 passed in 54.516 seconds** |

The stress count is the last one-second progress report, not an exact count at capture termination. The passing test uses an isolated prearmed guard and fully asynchronous release, with the production detector-push change. It does not use the earlier CLK-phase release workaround.

## Write hold waveform

At 3.5 MHz, WAIT was already asserted before first WR low at sample 2313. WR remained low, address stayed 4000, DATA stayed 55, MREQ stayed low, and RD stayed high until WAIT release at sample 4377. MREQ ended at sample 4392, about 0.400 µs after WAIT release. There were **zero WR high transitions before release**. Sample interval is 26.667 ns. Both captures have equal recorder counts, zero FIFO stalls and zero shared-pin disagreements.

![WR held low during WAIT](../derived/write_wait_retest_20261005_011754/held_write/waveform.png)

The updated FPGA RTL retains WR when `stall` is true (`if (!stall) wr_n <= next_wr_n`). This addresses the previously captured deassertion when a memory-write wait state revisits T2.P. The hardware result is consistent with that correction.

## Remaining current-guard failure

The current guard at 1 MHz detects WR before requesting WAIT. First WR low is sample 2820; WAIT first goes low at sample 2827, approximately 186.7 ns later. The FPGA ends the write at sample 2858 despite the later low WAIT level; its defined sampling deadline was already missed. WAIT instead stalls the following opcode fetch at 0105. The write reply does not supply that opcode, and the next published request is 0106 instead of the expected opcode fetch 0105.

This is the same late-assertion failure as before. It is distinct from WR continuity, which now passes when WAIT is preasserted. Prearming WAIT between transactions remains the demonstrated solution for this PIO write deadline; that change was not applied to production in this retest.

## Artifacts and restoration

Raw logs, JSON metrics, sample TSV, waveform PNG/SVG and test ELF hashes are in `derived/write_wait_retest_20261005_011754/`. The tests used the previous `base_1MHz.elf` for 8 seconds and `prearm_3p5MHz.elf` for 12 seconds, both with `--poll-ms 1`. `tests/check_write_wait_capture.py` checked the waveform. All six tests in `tests/test_wait_manual_pio.py` passed.

Normal firmware was rebuilt and restored at its existing hardcoded 2 MHz, with the previously applied detector-push change. Flash verification succeeded. OpenOCD was stopped to release the probe. Restoring normal firmware does not qualify the unchanged production guard against delayed writes.

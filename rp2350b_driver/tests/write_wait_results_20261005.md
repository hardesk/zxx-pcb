# FPGA WAIT during writes — 2026-10-05

## Applied change

`z80_async_detector` now pushes its accepted ISR snapshot to its RX FIFO before signaling IRQ4. The service SM no longer samples GPIO or pushes a separate request. `AsyncBusDriver::read_request()` consumes detector RX; replies still go to service TX. PIO0 detector + service use 31 instruction words. The production WAIT guard retains its current assertion/release behavior.

The model includes a regression that changes WR and address after detector acceptance but before publication, and checks that the original write snapshot is published. Its old immediate-marker and fast-reply expectations were adjusted to the actual helper delay and current guard behavior. All six PIO model tests passed in 58.105 seconds. The normal firmware built successfully.

## Real-board test

RP2350 at 150 MHz system clock, attached TANG with the user's updated FPGA bitstream. FPGA source and the latest build now register WAIT at the edge entering T2.N (automatic Tw.N for I/O), rather than continuously deriving stall from raw WAIT. No FPGA source or bitstream was changed by this test.

The independent sequence-checking workload writes 55 to 4000 as request 9. The test withholds that write's reply for 50 µs, then captures WAIT release and the write ending. Paired PIO samplers run every four system clocks, 26.667 ns/sample. Both captures have equal sample counts, zero FIFO stalls, and zero shared-pin disagreement.

| Configuration | Write held until WAIT release? | WR held continuously low? | Sequence result |
|---|---|---|---|
| Current guard + applied detector push, 1 MHz | No: WAIT reaches the FPGA too late for this write | No | First divergence at request 10 |
| Isolated preasserted-WAIT guard + applied detector push, 3.5 MHz | Yes, about 55.07 µs from first WR low to WAIT release | No: 193 WR rising transitions before release | 5,315,744 checked requests / 81,780 complete loops passed during a 12-second capture window |

The checked count is the last progress report, not an exact final count at host capture termination. Printing the waveform stalls host service of a subsequent request, so the second test also resumes correctly after a long host pause.

### Current guard: late assertion

At 1 MHz, first WR low is sample 2830; WAIT goes low at 2836, about 160 ns later. MREQ returns high at 2868, about 1.013 µs after WR first asserts. WAIT remains low until 4876, but by then it is stalling the next opcode fetch at 0105 rather than holding the write at 4000. The write reply supplies no opcode data; execution consumes the lingering 55 instead of opcode 3A. The next request is operand read 0106, while the checker expects opcode fetch 0105.

This does not demonstrate a failure to honor WAIT that met setup time. The new FPGA samples WAIT at a defined edge; the current PIO only starts asserting it after detecting WR, which is already too late for this write. The late assertion overlaps the next transaction instead.

![Late WAIT](../derived/write_wait_20261005/late_detail/waveform.png)

### Preasserted WAIT: cycle retention passes, WR waveform still fails

For the isolated prearmed guard at 3.5 MHz, WAIT is already low before WR asserts. First WR low is sample 2308. Through sample 4372, address remains 4000, data remains 55, MREQ remains low and RD remains high. WAIT rises at 4373; MREQ finally rises at 4398, approximately 0.667 µs later. No next transaction starts before WAIT release. This confirms that the updated FPGA respects an in-time WAIT request during a memory write in this capture.

WR nevertheless alternates low/high each inserted wait state. There are 193 rising transitions before release. The FPGA's memory-write timing expression still asserts WR for T2.N or T3.P, while the stalled core revisits T2.P/T2.N. Registering WAIT fixes the sampling decision but does not keep WR asserted through Tw. The detector's retained snapshot prevents the service from reclassifying the write when it sees WR high, but the external WR pulse train is still present.

![WR pulses during held write](../derived/write_wait_20261005/prearm_detail/waveform.png)

## Implication

The WAIT sampling fix works for the measured write when WAIT is asserted in time. Two distinct issues remain:

- The production PIO guard asserts WAIT too late to stall the tested write. Preasserting WAIT between transactions avoids this, and the isolated test remained fully asynchronous: no CLK waits were added.
- The FPGA still pulses WR during inserted wait states. Holding WR asserted through those states requires a separate FPGA timing correction if a continuous write strobe is intended.

Only the requested detector-push change was applied to production. Prearming WAIT was an isolated test variant, not applied to the production guard. After testing, normal firmware with the new detector-push change was restored at its existing hardcoded 2 MHz; flash was verified. OpenOCD was stopped and the probe released. Restoration is not a claim that the production WAIT guard is stable.

## Reproduction and artifacts

Build the current-guard probe without flashing:

```sh
python3 tests/build_async_speed.py /tmp/z80-write-wait --hz 1000000 --variant base --write-hold-us 50
```

For the in-time WAIT comparison:

```sh
python3 tests/build_async_speed.py /tmp/z80-write-wait --hz 3500000 --variant prearm --write-hold-us 50
```

Flash and capture through existing OpenOCD Tcl 6666 / RTT 9090:

```sh
python3 tests/capture_wait_trace.py /tmp/z80-write-wait/build/rp2350_driver.elf /tmp/z80-write-wait.log --seconds 12 --poll-ms 1
python3 tests/check_write_wait_capture.py /tmp/z80-write-wait.log
```

`check_write_wait_capture.py` distinguishes transaction retention from WR continuity. It exits unsuccessfully if WAIT was not low before WR or the address/data/MREQ/RD window did not remain valid through release, and reports WR pulse count separately.

Raw logs, ELFs, JSON metrics, full sample TSV files and plots are in `derived/write_wait_20261005/`. The previous clock-phase release workaround was not used in the passing prearmed test.

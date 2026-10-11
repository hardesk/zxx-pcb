#!/usr/bin/env python3
"""Run real RZ80 RAM/IO workloads against production firmware, with the LCD active.

Requires `make openocd`; never flashes or halts an RP core. Temporarily resets
RZ80 and substitutes a boot ROM in its existing RAM-under-ROM allocation.
Restores RAM/mapping, boots the normal menu and retains the buffered tape.
Do not run keyboard/tape clients during the benchmark. Results include host
timing uncertainty and passive one-second CLK/WAIT averages during each loop.
"""
import argparse
import json
import hashlib
from pathlib import Path
import re
import subprocess
import statistics
import struct
import time

from measure_frame_budget import Probe, DMA, PIO, ROOT, request, symbol

CASES = ('fetch', 'ram_read', 'ram_write', 'io_read_fe', 'io_write_fe', 'io_read_ff')
# Optional cases, run only when selected with --case or --extended.
# rom_read sweeps the real (flash-backed) ROM 1 after OUT 7FFD; rom_ram_read
# runs the identical sweep over RAM bank 0 for a like-for-like XIP comparison.
# frame_work records completed loop iterations in every 50 Hz IM1 frame.
EXTRA_CASES = ('rom_read', 'rom_ram_read', 'frame_work')
FRAME_HANDLER = 0x8100
FRAMES = 200
FRAME_LOOP_TICKS = 23 # INC DE; LD (HL),A; JP loop.
FRAME_HANDLER_TICKS = 116 # IM1 ack 13, JP 10, handler 93 (excluding the final RET's return).

def sweep_program(case, case_id):
    """Read every byte of one 16 KiB page 64 times: ADC A,(HL); INC HL.

    The carry-chained sum makes any single misread byte change the result."""
    base = 0x0000 if case == 'rom_read' else 0xc000
    code = bytearray((0xf3, 0x31, 0xf0, 0xbf, 0x01, 0xfd, 0x7f, 0x3e, 0x10, 0xed, 0x79)) # DI; SP; OUT (7FFD),10h.
    code += bytes((0x21, base & 255, base >> 8, 0x3e, case_id, 0x32, 0x00, 0xb0))
    outer = 64
    code += bytes((0x0e, outer, 0x06, 64, 0xaf)) # C=sweeps; B=64 blocks of 256 reads; A=0, CF=0.
    body = len(code)
    code += bytes((0x8e, 0x23)) * 256
    djnz = len(code); code += bytes((0x10, 0))
    code += bytes((0x0d, 0x28, 0)) # DEC C; JR Z,done.
    jrz = len(code) - 1
    code += bytes((0x06, 64, 0x21, base & 255, base >> 8))
    repeat = len(code); code += bytes((0xc3, (0x8000+body) & 255, (0x8000+body) >> 8))
    done = len(code)
    code += bytes((0x32, 0x02, 0xb0, 0x3e, 0x80 | case_id, 0x32, 0x00, 0xb0, 0x76))
    code[djnz+1] = (repeat - djnz - 2) & 255
    code[jrz] = done - jrz - 1
    inner = 256 * 13
    nominal = outer * (64 * inner + 63 * 23 + 8) + (outer-1) * (4 + 7 + 7 + 10 + 10) + 4 + 12 + 13 + 7 + 4
    return code, nominal, outer * 64 * 256

def adc_sweep(page, sweeps=64):
    """Host model of the sweep: A=0, CF=0, then ADC A,(HL) over the page."""
    a = carry = 0
    for _ in range(sweeps):
        for value in page:
            total = a + value + carry
            a, carry = total & 255, total >> 8
    return a

def frame_program(case_id):
    """IM1 records DE (loop count) per frame into C000.., FRAMES+1 entries."""
    loop = 0x8000 + 26
    code = bytearray((0xf3, 0x31, 0xf0, 0xbf, 0xed, 0x56, 0xdd, 0x21, 0x00, 0xc0,
                      0x06, FRAMES + 1, 0x21, 0x00, 0x90, 0x3e, case_id, 0x32, 0x00, 0xb0,
                      0x11, 0x00, 0x00, 0xfb, 0x76, 0x00))
    assert len(code) == loop - 0x8000
    code += bytes((0x13, 0x77, 0xc3, loop & 255, loop >> 8))
    code += bytes(FRAME_HANDLER - 0x8000 - len(code))
    code += bytes((0xdd, 0x73, 0x00, 0xdd, 0x72, 0x01, 0xdd, 0x23, 0xdd, 0x23,
                   0x11, 0x00, 0x00, 0x05, 0x28, 0x02, 0xfb, 0xc9,
                   0x3e, 0x80 | case_id, 0x32, 0x00, 0xb0, 0x76))
    assert FRAMES + 1 <= 255
    return code

def check_firmware(probe, elf):
    """Reject a stale ELF before using any debugger-derived layout to write RAM."""
    symbols = subprocess.check_output(['arm-none-eabi-nm', '-S', '-C', str(elf)], text=True)
    entry = next(line.split(maxsplit=3) for line in symbols.splitlines()
                 if len(line.split(maxsplit=3)) == 4 and line.split(maxsplit=3)[3].startswith('run_z80_bus('))
    address, size = int(entry[0], 16), int(entry[1], 16)
    data = elf.read_bytes()
    assert data[:6] == b'\x7fELF\x01\x01', 'Expected little-endian ELF32'
    offset = struct.unpack_from('<I', data, 28)[0]
    stride, count = struct.unpack_from('<HH', data, 42)
    for i in range(count):
        kind, file_offset, virtual, _, file_size, *_ = struct.unpack_from('<8I', data, offset+i*stride)
        if kind == 1 and virtual <= address and address+size <= virtual+file_size:
            expected = data[file_offset+address-virtual:file_offset+address-virtual+size]
            assert bytes(probe.read(address, size, 8)) == expected, 'Running firmware does not match --elf; flash the matching build first'
            return hashlib.sha256(data).hexdigest()
    raise RuntimeError('Bus loop not found in ELF load segments')

def addresses(elf):
    expressions = {
        'screen_offset': '&((Rp2350ZxEnv*)0)->display_screen',
        'read_pages_offset': '&((Rp2350ZxEnv*)0)->m_read_pages',
        'ram_pages_offset': '&((Rp2350ZxEnv*)0)->m_ram_pages',
        'ram_banks_offset': '&((Rp2350ZxEnv*)0)->m_ram_banks',
        'loader_offset': '&((Rp2350ZxEnv*)0)->m_standard_loader_rom',
        'wait_ring': "&'main::display'.m_tstate_counter.m_wait_samples",
        'rx_dma': "&'main::display'.m_tstate_counter.m_rx_dma",
    }
    command = ['arm-none-eabi-gdb', '-batch', str(elf)]
    for expression in expressions.values():
        command += ['-ex', 'p/x (unsigned long)(' + expression + ')']
    output = subprocess.check_output(command, text=True)
    values = re.findall(r'\$\d+ = (0x[0-9a-f]+)', output)
    if len(values) != len(expressions):
        raise RuntimeError('Could not resolve firmware layout from DWARF: ' + output)
    return dict(zip(expressions, (int(v, 16) for v in values)))

def program(case, case_id):
    """256-operation unrolled body, B=256 inner repeats, C outer repeats."""
    if case in ('rom_read', 'rom_ram_read'): return sweep_program(case, case_id)
    code = bytearray(); labels = {}; fixups = []
    def emit(*values): code.extend(values)
    def label(name): labels[name] = len(code)
    def jump(op, target, relative=False):
        emit(op); fixups.append((len(code), target, relative))
        emit(0) if relative else emit(0, 0)
    outer = 48 if case == 'fetch' else 16
    emit(0xf3, 0x31, 0xf0, 0xbf, 0x21, 0x00, 0xc0) # DI; SP=BFF0; HL=C000.
    emit(0x3e, case_id, 0x32, 0x00, 0xb0) # Start marker.
    emit(0x3e, 0xa5, 0x0e, outer, 0x06, 0) # A=A5; C=outer; B=256.
    label('body')
    op, ticks = {
        'fetch': ((0x00,), 4),
        'ram_read': ((0x7e, 0x2c), 11), # LD A,(HL); INC L (256-byte wrap).
        'ram_write': ((0x77, 0x2c), 11), # LD (HL),A; INC L.
        'io_read_fe': ((0xdb, 0xfe), 11),
        'io_write_fe': ((0xd3, 0xfe), 11),
        'io_read_ff': ((0xdb, 0xff), 11),
    }[case]
    for _ in range(256): emit(*op)
    jump(0x10, 'repeat', True) # DJNZ repeat.
    emit(0x0d) # DEC C.
    jump(0x28, 'done', True) # JR Z,done.
    emit(0x06, 0) # LD B,256.
    label('repeat'); jump(0xc3, 'body')
    label('done')
    emit(0x32, 0x02, 0xb0) # Result A.
    emit(0x3e, 0x80 | case_id, 0x32, 0x00, 0xb0, 0x76) # End marker; HALT.
    for offset, target, relative in fixups:
        value = labels[target] - offset - 1 if relative else 0x8000 + labels[target]
        if relative:
            assert -128 <= value <= 127
            code[offset] = value & 255
        else: code[offset:offset+2] = value.to_bytes(2, 'little')
    # Between identical start/end LD (B000),A write phases, standard Z80 timing:
    # body; DJNZ+JP for inner iterations; outer reload; setup/result/end marker.
    nominal = outer * 256 * 256 * ticks + outer * 255 * 23 + (outer-1) * 36 + 24 + 7 + 47
    return code, nominal, outer * 256 * 256

def write_bytes(probe, address, data):
    for offset in range(0, len(data), 1024):
        chunk = data[offset:offset+1024]
        probe.command(f'write_memory {address+offset:#x} 8 {{' + ' '.join(map(str, chunk)) + '}')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--elf', type=Path, default=ROOT/'derived/drv_rel/rp2350_driver.elf')
    parser.add_argument('--case', choices=CASES+EXTRA_CASES, action='append')
    parser.add_argument('--extended', action='store_true', help='Run the standard cases plus ROM and frame-work cases')
    args = parser.parse_args(); layout = addresses(args.elf); probe = Probe()
    elf_hash = check_firmware(probe, args.elf)
    assert probe.read(0x400a80b0)[0] in (19999, 39999), 'Expected 50 Hz INT (1 or 0.5 us PWM ticks)'
    reset_status = request(8); time.sleep(2) # Clear held keys/loader state before starting.
    env = probe.read(symbol(args.elf, '(anonymous namespace)::core1_screen'))[0] - layout['screen_offset']
    ram = probe.read(env + layout['ram_pages_offset'], 4)
    assert all(0x20000000 <= pointer < 0x20080000-16384 for pointer in ram), 'Invalid RAM-page layout'
    read0 = probe.read(env + layout['read_pages_offset'])[0]
    loader = probe.read(env + layout['loader_offset'], 1, 8)[0]
    rx = probe.read(layout['rx_dma'])[0]
    assert 0 <= rx < 16 and probe.read(DMA+rx*64+8) == [0xffffffff]
    assert layout['wait_ring'] & 255 == 0
    assert probe.read(DMA+rx*64+4)[0] & ~255 == layout['wait_ring'], 'Counter ring does not match ELF'
    saved = {}; results = []
    # RP2350 adds high-bank registers between the low-bank aliases. These
    # SET/CLR offsets differ from RP2040; never write GPIO_OUT/HI_OUT directly.
    def reset(level): probe.write(0xd0000018 if level else 0xd0000020, 1 << 25)
    def average():
        next_index = (probe.read(DMA+rx*64+4)[0] & 255) // 4
        values = probe.read(layout['wait_ring'], 64)
        return (5000000//50) - sum(values[(next_index-i)&63] for i in range(1, 51))/50
    try:
        reset(False); time.sleep(.02)
        saved = {page: bytes(probe.read(ram[page], 16384, 8)) for page in (0, 2, 3)}
        boot = bytearray((ROOT/'roms/48.rom').read_bytes())
        assert len(boot) == 16384
        boot[:3] = bytes((0xc3, 0, 0x80))
        boot[0x38:0x3b] = bytes((0xc3, FRAME_HANDLER & 255, FRAME_HANDLER >> 8)) # frame_work IM1.
        write_bytes(probe, ram[0], boot)
        probe.write(env+layout['read_pages_offset'], ram[0])
        # The cloned standard ROM still has its normal loader fingerprint.
        probe.command(f'write_memory {env+layout["loader_offset"]:#x} 8 {{1}}')
        selected = args.case or (CASES + EXTRA_CASES if args.extended else CASES)
        for case_id, case in enumerate(selected, 1):
            reset(False); time.sleep(.02)
            # rom_* cases page the real ROM in with OUT 7FFD; boot each case from the clone.
            probe.write(env+layout['read_pages_offset'], ram[0])
            probe.write(env+layout['read_pages_offset']+12, ram[3])
            probe.write(env+layout['ram_pages_offset']+12, ram[3])
            assert not probe.read(0xd0000004)[0] & (1<<25), 'RZ80 RESET did not assert'
            if case == 'frame_work':
                write_bytes(probe, ram[2], frame_program(case_id))
                write_bytes(probe, ram[2]+0x3000, bytes(3))
                write_bytes(probe, ram[3], bytes(2*(FRAMES+1)))
                reset(True); deadline = time.monotonic()+FRAMES/50+10
                while probe.read(ram[2]+0x3000, 1, 8)[0] != (case_id|0x80):
                    if time.monotonic() > deadline: raise TimeoutError('frame_work did not finish')
                    time.sleep(.05)
                raw = probe.read(ram[3], 2*(FRAMES+1), 8)
                counts = [raw[i] | raw[i+1] << 8 for i in range(2, len(raw), 2)]
                frame_t = [c*FRAME_LOOP_TICKS + FRAME_HANDLER_TICKS for c in counts]
                bus_debug = probe.read(0x50200008)[0]
                assert not bus_debug & 0x000f0000, 'PIO0 TX overflow: unchecked reply invariant failed'
                entry = dict(case=case, frames=len(frame_t), tstates_per_frame=frame_t,
                             mean_tstates_per_frame=statistics.mean(frame_t),
                             stdev_tstates_per_frame=statistics.pstdev(frame_t),
                             min_tstates_per_frame=min(frame_t), max_tstates_per_frame=max(frame_t),
                             p1_tstates_per_frame=sorted(frame_t)[len(frame_t)//100],
                             p99_tstates_per_frame=sorted(frame_t)[len(frame_t)*99//100],
                             effective_mhz=statistics.mean(frame_t)*50/1e6,
                             lcd_counter_tstates_per_20ms=average(), pio0_fdebug=bus_debug)
                results.append(entry)
                print(json.dumps({k: v for k, v in entry.items() if k != 'tstates_per_frame'}), flush=True)
                continue
            code, nominal, operations = program(case, case_id)
            write_bytes(probe, ram[2], code)
            write_bytes(probe, ram[2]+0x3000, bytes(3))
            write_bytes(probe, ram[3], bytes(i ^ 0x5a for i in range(256)))
            start = None; last_poll = time.monotonic(); max_poll = 0; samples = []
            sample_at = 1.25; deadline = time.monotonic()+15
            reset(True)
            while time.monotonic() < deadline:
                marker = probe.read(ram[2]+0x3000, 1, 8)[0]
                now = time.monotonic()
                if marker == case_id and start is None: start = now
                if marker == case_id and start is not None and now-start >= sample_at:
                    samples.append(average()); sample_at += 1
                if marker == (case_id|0x80):
                    assert start is not None and samples, 'Workload completed without steady samples'
                    elapsed = now-start; uncertainty = max_poll
                    break
                if start is None: max_poll = 0
                else: max_poll = max(max_poll, now-last_poll)
                last_poll = now; time.sleep(.005)
            else: raise TimeoutError('RZ80 benchmark did not finish: ' + case)
            result = probe.read(ram[2]+0x3002, 1, 8)[0]
            if case in ('ram_read', 'ram_write'): assert result == 0xa5, result
            if case == 'rom_read': assert result == adc_sweep((ROOT/'roms/128-1.rom').read_bytes()), result
            if case == 'rom_ram_read': # OUT 7FFD,10h mapped physical bank 0 at C000.
                bank0 = probe.read(env + layout['ram_banks_offset'])[0]
                assert result == adc_sweep(bytes(probe.read(bank0, 16384, 8))), result
            if case == 'ram_write': assert probe.read(ram[3], 256, 8) == [0xa5]*256
            if case == 'io_read_fe': assert result & 31 == 31, result
            if case == 'io_read_ff': assert result == 0xff, result
            fdebug = probe.read(PIO+8)[0]
            # SM0 is LCD, SM1 is the counter. No monitor stalls/overflow allowed.
            assert not fdebug & 0x02020202, hex(fdebug)
            bus_debug = probe.read(0x50200008)[0]
            assert not bus_debug & 0x000f0000, 'PIO0 TX overflow: unchecked reply invariant failed'
            entry = dict(case=case, operations=operations, nominal_tstates=nominal,
                         elapsed_seconds=elapsed, max_poll_seconds=uncertainty,
                         effective_mhz=nominal/elapsed/1e6,
                         operations_per_second=operations/elapsed,
                         steady_tstates_per_20ms=samples, mean_tstates_per_20ms=sum(samples)/len(samples),
                         result_byte=result, pio0_fdebug=bus_debug, pio2_fdebug=fdebug)
            results.append(entry); print(json.dumps(entry), flush=True)
    finally:
        reset(False); time.sleep(.02)
        for page, data in saved.items(): write_bytes(probe, ram[page], data)
        probe.write(env+layout['read_pages_offset'], read0)
        probe.command(f'write_memory {env+layout["loader_offset"]:#x} 8 {{{loader}}}')
        reset(True); time.sleep(2); request(8); time.sleep(2)
        probe.sock.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(clock_hz=5000000, rp_clock_hz=150000000,
        lcd_active=True, ram_restored=True, elf_sha256=elf_hash,
        tape_present=bool(reset_status['blocks']),
        metric_note='Completed-work elapsed time is authoritative; RD/WR-qualified WAIT is approximate and phase-sensitive.',
        cases=results), indent=2))
    print('PASS: workload results checked; RAM/mapping restored; normal menu restarted', flush=True)

if __name__ == '__main__': main()

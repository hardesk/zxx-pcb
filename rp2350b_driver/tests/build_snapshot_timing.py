#!/usr/bin/env python3
"""Build an isolated snapshot-timing firmware; never flash automatically.

Usage: python3 tests/build_snapshot_timing.py /tmp/z80-snapshot-timing-build
Uses current PIO/driver, stress program at 0100h, request logging and two DMA
recorders. Stops recording on an all-inactive request, or request 1000.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f'Expected exactly one integration point: {old!r}')
    return source.replace(old, new, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--sdk', default=os.environ.get('PICO_SDK_PATH', '/Users/orl/Projects/pico-sdk'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = args.directory.resolve()
    if target == root or root in target.parents:
        parser.error('Use a separate source directory outside the working tree')
    target.mkdir(parents=True, exist_ok=True)
    for p in root.iterdir():
        if p.is_file() and (p.suffix in ('.cpp', '.hpp', '.pio', '.asm', '.cmake') or p.name == 'CMakeLists.txt'):
            shutil.copy2(p, target / p.name)
    for name in ('tests', 'z80'):
        shutil.copytree(root / name, target / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
    cmake = (target / 'CMakeLists.txt').read_text()
    cmake = replace_once(cmake, 'set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/test.asm)',
                         'set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/tests/wait_bus_stress.asm)')
    (target / 'CMakeLists.txt').write_text(cmake + '\ntarget_link_libraries(rp2350_driver hardware_dma)\n')
    source = (target / 'main.cpp').read_text()
    source = '#include "tests/snapshot_timing_capture.hpp"\n' + source
    source = replace_once(source, 'uint16_t prog_org = 0x8000;', 'uint16_t prog_org = 0x100;')
    source = replace_once(source, '    bus.reset_cpu();', '''    static SnapshotTimingCapture timing;
    timing.start();
    bus.reset_cpu();
    unsigned timing_request = 0;''')
    source = replace_once(source, '        const z80pio::BusRequest request = bus.read_request();', '''        const z80pio::BusRequest request = bus.read_request();
        ++timing_request;
        if ((!request.mreq() && !request.iorq() && !request.rd() && !request.wr()) || timing_request == 1000)
            timing.finish(timing_request, request.raw);''')
    source = replace_once(source, '// request.dump(zx.peek(request.address()));', 'request.dump(zx.peek(request.address()));')
    (target / 'main.cpp').write_text(source)
    subprocess.run(['cmake', '-S', str(target), '-B', str(target/'build'),
                    f'-DPICO_SDK_PATH={args.sdk}', '-DCMAKE_BUILD_TYPE=Debug',
                    '-DZ80_BUS_MODE=ASYNC', '-DZ80_CLOCK_HZ=1000000',
                    '-DZ80_REPLY_DELAY_US=0', '-DZ80_WAIT_CAPTURE=OFF'], check=True)
    subprocess.run(['cmake', '--build', str(target/'build'), '--parallel', '6'], check=True)
    print(target/'build/rp2350_driver.elf')


if __name__ == '__main__':
    main()

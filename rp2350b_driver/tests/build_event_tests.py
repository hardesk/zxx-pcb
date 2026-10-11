#!/usr/bin/env python3
"""Build isolated reset/INT/NMI firmware using the current unmodified async PIO."""
from pathlib import Path
import subprocess,shutil,argparse,hashlib,json
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
r=Path(__file__).resolve().parents[1];d=a.directory.resolve();d.mkdir(parents=True,exist_ok=True)
assert d!=r and r not in d.parents
for name in ('z80_bus_async.cpp','z80_bus_async.pio','z80_pio_bus.hpp','z80_pins.hpp','pico_sdk_import.cmake'):
 shutil.copy2(r/name,d/name)
shutil.copy2(r/'tests/event_test_firmware.cpp',d/'main.cpp')
shutil.copy2(r/'tests/snapshot_timing_capture.hpp',d/'snapshot_timing_capture.hpp')
(d/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.20)
set(PICO_PLATFORM rp2350-arm-s)
set(PICO_BOARD solderparty_rp2350_stamp_xl)
include(pico_sdk_import.cmake)
project(event_tests C CXX ASM)
set(CMAKE_CXX_STANDARD 20)
pico_sdk_init()
add_executable(event_tests main.cpp z80_bus_async.cpp)
pico_generate_pio_header(event_tests ${CMAKE_CURRENT_LIST_DIR}/z80_bus_async.pio)
target_compile_definitions(event_tests PRIVATE Z80_BUS_MODE=1 SEGGER_RTT_MODE_DEFAULT=SEGGER_RTT_MODE_BLOCK_IF_FIFO_FULL)
target_link_libraries(event_tests pico_stdlib hardware_pio hardware_dma hardware_clocks)
pico_enable_stdio_uart(event_tests 0)
pico_enable_stdio_usb(event_tests 0)
pico_enable_stdio_rtt(event_tests 1)
pico_add_extra_outputs(event_tests)
''')
subprocess.run(['cmake','-S',str(d),'-B',str(d/'build'),'-DPICO_SDK_PATH=/Users/orl/Projects/pico-sdk','-DCMAKE_BUILD_TYPE=Debug'],check=True)
subprocess.run(['cmake','--build',str(d/'build'),'--parallel','6'],check=True)
(d/'source_hashes.json').write_text(json.dumps({n:hashlib.sha256((d/n).read_bytes()).hexdigest() for n in ['main.cpp','z80_bus_async.cpp','z80_bus_async.pio']},indent=2))

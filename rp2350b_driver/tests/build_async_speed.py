#!/usr/bin/env python3
"""Build an isolated real-board sequence-checking firmware; does not flash.

Variants are timing experiments, not qualified production replacements.
"""
import argparse,itertools,re,shutil,subprocess
from pathlib import Path
from check_wait_trace import expected_requests
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('directory',type=Path);p.add_argument('--hz',type=int,default=3500000)
p.add_argument('--variant',choices=['base','low','fall','coherent','prearm','prearm-coherent','prearm-fall','prearm-coherent-fall','high-service','high-request','high-request-fast'],default='base')
p.add_argument('--capture',action='store_true');p.add_argument('--delay-us',type=int,default=0)
p.add_argument('--init-capture',action='store_true',help='Capture WAIT across bus.init(), before releasing RESET')
p.add_argument('--write-hold-us',type=int,default=0,
               help='Capture the first memory write with this reply delay, including release')
p.add_argument('--sdk',default='/Users/orl/Projects/pico-sdk');a=p.parse_args()
r=Path(__file__).resolve().parents[1];d=a.directory.resolve()
if a.write_hold_us < 0 or a.write_hold_us > 100:
 p.error('Write hold must be 0..100 microseconds to fit the waveform ring')
if a.write_hold_us:a.capture=True
if a.init_capture and a.capture:p.error('Initialization and paired transaction capture both use PIO2; choose one')
if d==r or r in d.parents:p.error('Use a separate source directory outside the repository')
d.mkdir(parents=True,exist_ok=True)
for f in r.iterdir():
 if f.is_file() and (f.suffix in ('.cpp','.hpp','.pio','.asm','.cmake') or f.name=='CMakeLists.txt'):shutil.copy2(f,d/f.name)
for name in ('tests','z80'):shutil.copytree(r/name,d/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
cm=(d/'CMakeLists.txt').read_text().replace('set(DATA_ASM $ENV{HOME}/Projects/speccy/z80test.git/src/z80full.asm)','set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/tests/wait_bus_stress.asm)').replace('    COMMAND ${SJASM_EXECUTABLE} ${DATA_ASM} ${DATA_BIN}','    COMMAND ${SJASMPLUS_EXECUTABLE} --syntax=aF ${DATA_ASM} --raw=${DATA_BIN}')
cm+='\ntarget_link_libraries(rp2350_driver hardware_dma)\n'
if a.capture:cm+='target_compile_definitions(rp2350_driver PRIVATE SPEED_CAPTURE=1)\n'
(d/'CMakeLists.txt').write_text(cm)
subprocess.run(['sjasmplus','--syntax=aF',str(d/'tests/wait_bus_stress.asm'),f'--raw={d}/stress_expected.bin'],check=True)
e=list(itertools.islice(expected_requests((d/'stress_expected.bin').read_bytes()),134))
assert e[3:68]==e[68:133], 'Expected loop length changed'
header='#include <cstdint>\nstruct ExpectedRequest { uint32_t raw; uint8_t value; bool check; };\nstatic constexpr ExpectedRequest expected[] = {\n'
for addr,m1,mem,io,rd,wr,value in e[:68]:
 raw=(addr<<8)|sum((not v)<<bit for v,bit in zip((m1,io,mem,rd,wr),(27,28,29,30,31)))
 header+=f'{{0x{raw:08x}u, {value or 0}, {str(value is not None).lower()}}},\n'
(d/'tests/expected_speed.hpp').write_text(header+'};\n')
s=(d/'main.cpp').read_text().replace('uint16_t prog_org = 0x8000;','uint16_t prog_org = 0x100;').replace('2000000;//Z80_CLOCK_HZ','Z80_CLOCK_HZ')
s=s.replace('        request.dump(zx.peek(request.address()));','        // request.dump(zx.peek(request.address()));')
s='#include "tests/expected_speed.hpp"\n#ifdef SPEED_CAPTURE\n#include "tests/snapshot_timing_capture.hpp"\n#endif\n'+s
s=s.replace('    bus.reset_cpu();','''#ifdef SPEED_CAPTURE
    static SnapshotTimingCapture timing;
    timing.start();
#endif
    bus.reset_cpu();
    unsigned request_count = 0, expected_index = 0;
    uint64_t report_at = time_us_64() + 1000000;''')
s=s.replace('        const z80pio::BusRequest request = bus.read_request();','''        const z80pio::BusRequest request = bus.read_request();
        ++request_count;
        const auto want = expected[expected_index];
        const uint8_t value = request.wr() ? request.data() : zx.peek(request.address());
        if ((request.raw & 0xf8ffff00u) != want.raw || (want.check && value != want.value)) {
#ifdef SPEED_CAPTURE
            timing.finish(request_count, request.raw);
#endif
            printf("FAIL request=%u index=%u expected=%08lx value=%02x observed=%08lx value=%02x\\n", request_count, expected_index, (unsigned long)want.raw, want.value, (unsigned long)request.raw, value);
            bus.begin_reset();
            while (true) tight_loop_contents();
        }
        if (++expected_index == 68) expected_index = 3;
        if (time_us_64() >= report_at) {
            printf("PASS progress requests=%u loops=%u\\n", request_count, request_count > 3 ? (request_count-3)/65 : 0);
            report_at = time_us_64() + 1000000;
        }''')
if a.write_hold_us:
 s=s.replace('    unsigned request_count = 0, expected_index = 0;',
             '    bool write_probe_done = false;\n    unsigned request_count = 0, expected_index = 0;')
 s=s.replace('        const auto reply = zx.service_pio_request(request);',
             f'''        const bool write_probe = !write_probe_done && request.mreq() && request.wr();
        if (write_probe) busy_wait_us_32({a.write_hold_us});
        const auto reply = zx.service_pio_request(request);''')
 s=s.replace('        bus.write_reply(reply);',f'''        bus.write_reply(reply);
        if (write_probe) {{
            busy_wait_us_32(3); // Include WAIT release and the end of the write.
            timing.finish(request_count, request.raw);
            printf("write probe request=%u raw=%08lx hold_us={a.write_hold_us}\\n", request_count, (unsigned long)request.raw);
            write_probe_done = true;
        }}''')
(d/'main.cpp').write_text(s)
if a.init_capture:
 s='#include "tests/init_wait_capture.hpp"\n'+s
 s=s.replace('    bus.init(kZ80ClockHz);','''    static InitWaitCapture init_capture;
    init_capture.start();
    bus.init(kZ80ClockHz);
    init_capture.finish();''')
 (d/'main.cpp').write_text(s)
s=(d/'z80_bus_async.pio').read_text()
if 'coherent' in a.variant and '    mov isr, pins\n    irq next 2' in s:
 s=s.replace('    irq 4 ; Signal','    push block ; accepted detector snapshot\n    irq 4 ; Signal').replace('    mov isr, pins\n    irq next 2','    irq next 2').replace('    push block\n    pull block','    pull block')
 f=d/'z80_bus_async.cpp';f.write_text(f.read_text().replace('pio_sm_get_blocking(bus_pio_, bus_sm_)','pio_sm_get_blocking(bus_pio_, detector_sm_)'))
service = s.split('.program z80_async_bus', 1)[1]
if 'prearm' in a.variant and ('irq next 2' not in service or service.index('irq next 2') < service.index('pull block')):
 begin=s.index('.program z80_async_guard');end=s.index('.program z80_async_detector')
 s=s[:begin]+'''.program z80_async_guard
.pio_version 1
.wrap_target
    set pins, 0
    wait 1 irq 3
    set pins, 1
    wait 1 irq 2
.wrap

'''+s[end:]
 s=s.replace('    irq next 2\n','').replace('    mov pindirs, null\n','    mov pindirs, null\n    irq next 2 ; cycle ended: rearm WAIT\n')
# Historical prearm variants intentionally restore low-at-idle WAIT.
if 'fall' in a.variant or a.variant == 'low':
 extra = '    wait 1 gpio 24\n    wait 0 gpio 24\n' if 'fall' in a.variant else '    wait 0 gpio 24\n'
 s, replacements = re.subn(r'(    (?:wait 1 irq 3|irq clear 3)[^\n]*\n)(    set pins, 1)',
                           lambda m: m[1]+extra+m[2], s)
 if replacements != 1: raise ValueError('Expected one WAIT release integration point')
(d/'z80_bus_async.pio').write_text(s)
if a.variant.startswith('high-'):
 begin=s.index('.program z80_async_guard');end=s.index('.program z80_async_detector')
 if a.variant == 'high-service':
  guard='''    wait 1 irq 2
    set pins, 0
    wait 1 irq 3
    set pins, 1
'''
  s=s.replace('    irq next 2 ; rearm WAIT before allowing another detector request\n','')
  s=s.replace('    pull block\n','    irq next 2 ; accepted request starts reactive WAIT\n    pull block\n')
 else:
  # GPIOBASE/IN_BASE=16: IORQ/MREQ occupy bits 12/13 of MOV PINS.
  # Refresh has MREQ but no reply: release when request pins deassert.
  guard='''    set pins, 1
scan_request:
    mov osr, ~pins
    out null, 12
    out x, 2
    jmp !x scan_request
    set pins, 0
pending_reply:
    mov x, status
    jmp !x check_request
    irq clear 3
    set pins, 1
wait_end:
    mov osr, ~pins
    out null, 12
    out x, 4
    jmp x-- wait_end
    jmp scan_request
check_request:
    mov osr, ~pins
    out null, 12
    out x, 2
    jmp x-- pending_reply
    ; Refresh ended without DATA_READY. Return to high idle.
'''
  s=s.replace('    irq next 2 ; rearm WAIT before allowing another detector request\n','')
 if a.variant == 'high-request-fast':
  # IN_BASE=IORQ removes one shift from each request/end polling loop.
  guard=guard.replace('    out null, 12\n','')
  # Match service ownership: a brief MREQ/IORQ gap must not release WAIT
  # while RD/WR is still active. Refresh has neither transfer strobe.
  guard=guard.replace('check_request:\n    mov osr, ~pins\n    out x, 2',
                      'check_request:\n    mov osr, ~pins\n    out x, 4')
 # Recompute offsets after service edits.
 begin=s.index('.program z80_async_guard');end=s.index('.program z80_async_detector')
 s=s[:begin]+'.program z80_async_guard\n.pio_version 1\n.wrap_target\n'+guard+'.wrap\n\n'+s[end:]
 s=s[s.index('.program z80_async_clock'):]
 s=('; TEST VARIANT '+a.variant+': WAIT starts high.\n'
    '; Detector RX carries accepted snapshots; service TX carries replies.\n'
    '; DATA_READY is PIO1 IRQ3; debug uses IRQ6/7.\n'+s)
 s=s.replace('Detector+service use 31 words.', 'Detector+service use '+('31' if a.variant == 'high-service' else '30')+' words.')
 (d/'z80_bus_async.pio').write_text(s)
 f=d/'z80_bus_async.cpp';cpp=f.read_text()
 # Replace guard input/status configuration rather than duplicating it.
 cpp=re.sub(r'^    sm_config_set_(?:in_pins|in_pin_count|out_shift|mov_status)\(&guard_config,[^\n]*\n', '', cpp, flags=re.M)
 cpp=re.sub(r'^    pio_gpio_init\(clock_pio_, pWAIT\);[^\n]*\n', '', cpp, flags=re.M)
 cpp=cpp.replace('clock_pio_, wait_sm_, 0, 1ull << pWAIT','clock_pio_, wait_sm_, 1ull << pWAIT, 1ull << pWAIT')
 # Keep the existing high SIO drive until the PIO latch and OE are ready.
 # Selecting PIO earlier would temporarily leave WAIT undriven at init.
 cpp=cpp.replace('    pio_gpio_init(clock_pio, pWAIT);\n', '')
 cpp=cpp.replace('    pio_sm_set_consecutive_pindirs(clock_pio_, wait_sm_, pWAIT, 1, true);',
                 '''    pio_sm_set_consecutive_pindirs(clock_pio_, wait_sm_, pWAIT, 1, true);
    pio_gpio_init(clock_pio_, pWAIT); // High PIO latch/OE before SIO-to-PIO handover.''')
 cpp=cpp.replace('    // WAIT is prearmed. Maximum clock rate still depends on cycle-end\n    // detection/rearming and input timing; qualify it on the connected CPU.',
                 '    // TEST: high-idle WAIT; qualify assertion latency on the connected CPU.')
 cpp=cpp.replace('// Arm WAIT and the marker before requests can arrive, then start the bus.',
                 '// Start the high-idle WAIT guard and marker, then the bus clock.')
 if a.variant in ('high-request', 'high-request-fast'):
  cpp=cpp.replace('    sm_config_set_clkdiv(&guard_config, 1.0f);','''    sm_config_set_clkdiv(&guard_config, 1.0f);
    sm_config_set_in_pins(&guard_config, 16);
    sm_config_set_in_pin_count(&guard_config, 32);
    sm_config_set_out_shift(&guard_config, true, false, 32);
    sm_config_set_mov_status(&guard_config, STATUS_IRQ_SET, 3);''')
  if a.variant == 'high-request-fast':
   cpp=cpp.replace('sm_config_set_in_pins(&guard_config, 16)', 'sm_config_set_in_pins(&guard_config, pIORQ)')
 f.write_text(cpp)
subprocess.run(['cmake','-S',str(d),'-B',str(d/'build'),f'-DPICO_SDK_PATH={a.sdk}','-DCMAKE_BUILD_TYPE=Debug','-DZ80_BUS_MODE=ASYNC',f'-DZ80_CLOCK_HZ={a.hz}',f'-DZ80_REPLY_DELAY_US={a.delay_us}','-DZ80_WAIT_CAPTURE=OFF'],check=True)
subprocess.run(['cmake','--build',str(d/'build'),'--parallel','6'],check=True)
print(d/'build/rp2350_driver.elf')

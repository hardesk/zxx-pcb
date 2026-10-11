#!/usr/bin/env python3
"""Test the production environment classes with host GPIO/PIO type stubs."""
from pathlib import Path
import subprocess
import re
import tempfile

root=Path(__file__).resolve().parents[1]
for bank in (0, 1):
    header = (root / f'roms/128-{bank}.h').read_text().split('{', 1)[1]
    generated = bytes(int(x,16) for x in re.findall(r'0x([0-9a-f]{2})', header))
    assert generated == (root / f'roms/128-{bank}.rom').read_bytes()
main=(root/'main.cpp').read_text()
macros=main[main.index('#define IO_DATA_SHIFT'):main.index('inline uint32_t extract_ctrl')]
classes=main[main.index('template<class DerivedT>'):main.index('inline static uint32_t gpio_get_all_hi')]
source=r'''
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <array>
#include <cassert>
#include <fstream>
#include "zx_keyboard.hpp"
#include "zx_ula.hpp"
#include "zx_tape.hpp"
#include "z80_pins.hpp"
#include "z80_pio_bus.hpp"
using std::size_t;
#define __no_inline_not_in_flash_func(name) __attribute__((noinline)) name
constexpr int GPIO_FUNC_SIO=5;
uint32_t output=0;
void gpio_set_pulls(unsigned,bool,bool) {}
void gpio_set_function_masked64(uint64_t,int) {}
void gpio_put_all64(uint64_t) {}
void gpio_set_dir_all_bits64(uint64_t) {}
void gpio_set_dir_masked(uint32_t,uint32_t) {}
void gpio_put_masked(uint32_t,uint32_t value) { output=value; }
'''+macros+classes+r'''
z80pio::BusRequest request(uint16_t address, uint8_t value, uint32_t asserted) {
    return {(0xff000000u & ~asserted) | (uint32_t(address)<<8) | value};
}
int main(int argc,char** argv) {
    assert(argc==2);
    using namespace z80pio;
    // Exercise the optimized memory-read gate with the real standard ROM.
    std::array<uint8_t,0x4000> standard_rom{};
    std::ifstream romfile(argv[1],std::ios::binary);
    romfile.read(reinterpret_cast<char*>(standard_rom.data()),standard_rom.size());
    assert(romfile.gcount()==standard_rom.size());
    Rp2350ZxEnv tape_machine;
    assert(tape_machine.add_rom(standard_rom.data(),standard_rom.size(),0));
    assert(tape_machine.select_rom(0));
    const uint8_t test_tap[]={3,0,255,0x42,0xbd};
    assert(tape_machine.tape.set_mode(ZxTape::Mode::Fast));
    assert(tape_machine.tape.begin(sizeof(test_tap),tape_crc(test_tap,sizeof(test_tap))));
    assert(tape_machine.tape.chunk(0,test_tap,sizeof(test_tap)) && tape_machine.tape.commit());
    assert(tape_machine.tape.observes_cpu());
    assert(tape_machine.service_pio_request(request(0x0556,0,kRawMreq|kRawRd|kRawM1))==read_reply(0x14));
    assert(tape_machine.service_pio_request(request(0x0562,0,kRawMreq|kRawRd))==read_reply(0x0e));
    assert(tape_machine.handle_io_in(0xfd)==1 && tape_machine.handle_io_in(0xfb)==255);
    tape_machine.write_memory(0x8000,0x76);
    assert(tape_machine.service_pio_request(request(0x8000,0,kRawMreq|kRawRd|kRawM1))==read_reply(0x76));
    assert(!tape_machine.tape.loader_call_active() && tape_machine.tape.fast_blocks()==1);
    assert(tape_machine.service_pio_request(request(0x0562,0,kRawMreq|kRawRd))==read_reply(standard_rom[0x0562]));
    // Consume the remaining fast bytes, and keep interception until M1 leaves.
    assert(tape_machine.tape.rewind());
    assert(tape_machine.service_pio_request(request(0x0556,0,kRawMreq|kRawRd|kRawM1))==read_reply(0x14));
    assert(tape_machine.handle_io_in(0xfb)==255);
    assert(tape_machine.handle_io_in(0xfb)==0x42);
    assert(tape_machine.handle_io_in(0xfb)==0xbd);
    assert(tape_machine.tape.observes_cpu());
    assert(tape_machine.service_pio_request(request(0x8000,0,kRawMreq|kRawRd|kRawM1))==read_reply(0x76));
    assert(!tape_machine.tape.observes_cpu());
    assert(tape_machine.service_pio_request(request(0x0562,0,kRawMreq|kRawRd))==read_reply(standard_rom[0x0562]));

    Rp2350ZxEnv env;
    const uint16_t quote_key[] = {'"'};
    env.keyboard.set_host_keys(quote_key,1);
    assert(env.service_pio_request(request(0xdffe,0,kRawIorq|kRawRd))==read_reply(0xbe));
    assert(env.service_pio_request(request(0x7ffe,0,kRawIorq|kRawRd))==read_reply(0xbd));
    assert(env.service_pio_request(request(0x7fff,0,kRawIorq|kRawRd))==read_reply(0xff));
    env.keyboard.clear();

    std::array<std::array<unsigned char,0x4000>,4> roms{};
    assert(!env.select_rom(0));
    assert(!env.add_rom(nullptr,0x4000,0));
    assert(!env.add_rom(roms[0].data(),0x3fff,0));
    assert(!env.add_rom(roms[0].data(),0x4001,0));
    assert(!env.add_rom(roms[0].data(),0x4000,4));
    for(unsigned bank=0;bank<4;++bank) {
        for(unsigned i=0;i<0x4000;++i) roms[bank][i]=(bank*53+i*7)&255;
        assert(env.add_rom(roms[bank].data(),roms[bank].size(),bank));
        assert(!env.add_rom(roms[bank].data(),roms[bank].size(),bank));
    }
    env.write_memory(0x1234,0x17);
    assert(env.peek(0x1234)==0x17); // Registration does not change mapping.
    for(unsigned page=0;page<4;++page) {
        for(unsigned bank=0;bank<4;++bank) {
            assert(env.select_rom(bank,page));
            for(unsigned offset : {0u,0x1234u,0x3fffu}) {
                const uint16_t a=page*0x4000+offset;
                const auto expected=roms[bank][offset];
                assert(env.peek(a)==expected);
                assert(env.service_pio_request(request(a,0,kRawMreq|kRawRd))==read_reply(expected));
                assert(env.service_pio_request(request(a,0,kRawMreq|kRawRd|kRawM1))==read_reply(expected));
                assert(env.service_pio_request(request(a,0x99,kRawMreq|kRawWr))==write_reply());
                assert(env.peek(a)==expected);
            }
        }
    }
    assert(env.m_ram[0x1234]==0x17);
    assert(!env.select_rom(4));
    assert(!env.select_rom(0,4));
    assert(!env.unmap_rom(4));
    assert(!env.select_ram_bank(8));
    assert(env.peek(0x1234)==roms[3][0x1234]);
    assert(env.peek(0xffff)==roms[3].back());
    assert(env.service_pio_request(request(0x1234,0,kRawIorq|kRawRd))==read_reply(0xbf));
    assert(env.service_pio_request(request(0x1234,0,kRawIorq|kRawM1))==read_reply(0xff));
    const unsigned char patch[]={0xff};
    env.load(patch,1,0x1234);
    assert(env.peek(0x1234)==roms[3][0x1234]);
    env.react(0x1fff ^ (1<<5) ^ (1<<7), (0x1234<<8)|0x22);
    assert(static_cast<unsigned char>(env.m_ram[0x1234])==0xff);
    env.react(0x1fff,0);
    env.react(0x1fff ^ (1<<5) ^ (1<<6), 0x1234<<8);
    assert(output==roms[3][0x1234]);
    for(unsigned page=0;page<4;++page) assert(env.unmap_rom(page));
    assert(env.peek(0x1234)==0xff);
    // All eight physical banks retain independent contents.
    for(unsigned bank=0;bank<8;++bank) {
        assert(env.select_ram_bank(bank));
        env.write_memory(0xc123,0x80+bank);
        env.service_pio_request(request(0xffff,0x40+bank,kRawMreq|kRawWr));
    }
    for(unsigned bank=0;bank<8;++bank) {
        assert(env.select_ram_bank(bank));
        assert(env.peek(0xc123)==0x80+bank);
        assert(env.peek(0xffff)==0x40+bank);
    }
    assert(env.peek(0x4123)==0x85);
    assert(env.peek(0x8123)==0x82);
    assert(static_cast<unsigned char>(env.m_ram[0x4123])==0x85);
    assert(env.select_ram_bank(5));
    env.write_memory(0x4123,0x55);
    assert(env.peek(0xc123)==0x55);
    assert(env.select_ram_bank(2));
    env.write_memory(0xc123,0x22);
    assert(env.peek(0x8123)==0x22);
    assert(env.select_rom(1,3));
    assert(env.unmap_rom(3));
    assert(env.peek(0xc123)==0x22); // Overlay preserves RAM selection.
    assert(env.select_rom(1,3));
    assert(env.select_ram_bank(6)); // RAM selection removes top-page ROM.
    assert(env.peek(0xc123)==0x86);
    const unsigned char crossing[]={0x12,0x34,0x56};
    env.load(crossing,sizeof(crossing),0xbfff);
    assert(env.peek(0xbfff)==0x12);
    assert(env.peek(0xc000)==0x34);
    assert(env.peek(0xc001)==0x56);
    env.fill(0xbfff,3,0xab,0xcd);
    assert(env.peek(0xbfff)==0xab);
    assert(env.peek(0xc000)==0xcd);
    assert(env.peek(0xc001)==0xab);
    env.fill(0xc000,0,0xff);
    assert(env.peek(0xc000)==0xcd);
    env.load(crossing,sizeof(crossing),0xffff); // Reject address overflow.
    assert(env.peek(0xffff)==0x46);
    assert(env.select_ram_bank(0));
    assert(env.peek(0xc000)==0);
    assert(env.select_ram_bank(6));
    assert(env.peek(0xc000)==0xcd);

    // 128K port decode, ROM switching, shadow screen and paging lock.
    Rp2350ZxEnv machine;
    assert(!machine.enable_128k());
    assert(machine.add_rom(roms[0].data(),0x4000,0));
    assert(machine.add_rom(roms[1].data(),0x4000,1));
    assert(machine.enable_128k());
    const auto* normal_screen = machine.display_screen.load();
    assert(normal_screen == reinterpret_cast<const volatile uint8_t*>(machine.m_ram+0x4000));
    for (unsigned bank=0;bank<8;++bank) {
        machine.handle_io_out(0x7ffd,bank);
        machine.write_memory(0xc100,0x30+bank);
    }
    for (unsigned bank=0;bank<8;++bank) {
        machine.handle_io_out(0x7ffd,bank);
        assert(machine.peek(0xc100)==0x30+bank);
    }
    assert(machine.peek(0x4100)==0x35 && machine.peek(0x8100)==0x32);
    machine.handle_io_out(0x7ffd,0x1f);
    assert(machine.peek(0x1234)==roms[1][0x1234]);
    assert(machine.display_screen.load()!=normal_screen);
    machine.write_memory(0xc000,0xd7);
    assert(machine.display_screen.load()[0]==0xd7);
    assert(machine.peek(0x4000)==0); // Shadow selection does not map bank 7 at 4000.
    machine.handle_io_out(0x7ffd,0x3f); // Apply this selection, then lock.
    machine.handle_io_out(0x7ffd,0);
    assert(machine.paging_register()==0x3f && machine.peek(0xc100)==0x37);
    machine.handle_io_out(0x0000,2); // Paging locked, but ULA alias still writes.
    assert(machine.paging_register()==0x3f && machine.ula.border()==2);
    machine.reset_machine();
    assert(machine.paging_register()==0);
    assert(machine.peek(0xc100)==0x30 && machine.peek(0x1234)==roms[0][0x1234]);
    assert(machine.display_screen.load()==normal_screen);
    // Exhaustively test original 128K partial decoding (A15=A1=0), including
    // even aliases that hit BOTH decoders. Avoid legacy debug-output ports.
    for (unsigned port=0;port<65536;++port) {
        if (port==0xff81 || port==0xff83) continue;
        machine.reset_machine();
        machine.handle_io_out(port,0x1b);
        assert(machine.paging_register()==((port & 0x8002) ? 0 : 0x1b));
        assert(machine.ula.output()==((port & 1) ? 0 : 0x1b));
    }
    machine.reset_machine();
    const uint16_t a_key[]={'a'};
    machine.keyboard.set_host_keys(a_key,1);
    assert(machine.handle_io_in(0xfdfe)==0xbe);
    machine.ula.set_ear_input(true);
    assert(machine.handle_io_in(0xfdfe)==0xfe);
    assert(machine.handle_io_in(0xfffd)==0xff); // No AY or paging readback.
    machine.ula.set_ear_input(false);
    machine.service_pio_request(request(0xfffe,0xf5,kRawIorq|kRawWr));
    assert(machine.ula.border()==5 && machine.ula.beeper() && machine.ula.mic_active());
    assert(machine.ula.output()==0x15); // Unused high output bits ignored.
    machine.service_pio_request(request(0x7ffd,0x11,kRawIorq|kRawWr));
    assert(machine.paging_register()==0x11 && machine.peek(0xc100)==0x31);
    assert(machine.peek(0x1234)==roms[1][0x1234]);
    machine.reset_machine();
    assert(machine.handle_io_in(0xfdfe)==0xbf && machine.ula.output()==0);

}
'''
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);(p/'hardware').mkdir()
    (p/'hardware/pio.h').write_text('#pragma once\nusing uint=unsigned; using PIO=void*; inline PIO pio0=nullptr,pio1=nullptr;\ninline uint32_t pio_sm_get_blocking(PIO,uint) { return 0; }\ninline void pio_sm_put_blocking(PIO,uint,uint32_t) {}\n')
    (p/'test.cpp').write_text(source)
    subprocess.run(['c++','-std=c++20','-Wno-format','-fsanitize=address,undefined',
                    '-I',tmp,'-I',str(root),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test'),str(root/'roms/48.rom')],check=True)
print('PASS: four ROM slots, page masks, bus reads/writes, eight RAM banks, aliases, mapped loading, ULA and 128K paging/aliases/reset')

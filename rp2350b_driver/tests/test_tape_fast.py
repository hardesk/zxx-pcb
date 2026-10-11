#!/usr/bin/env python3
"""Execute the real 48K ROM byte loop with the production fast-load overlay.

This deliberately small Z80 interpreter implements only instructions reached by
LD-BYTES in fast mode; an unexpected instruction fails instead of being ignored.
"""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
source = r'''
#include "zx_tape.hpp"
#include <array>
#include <cassert>
#include <fstream>
#include <vector>
#include <algorithm>
struct Cpu {
    ZxTape tape;
    std::array<uint8_t,65536> mem{};
    uint8_t a=0,f=1,aa=0,ff=0,b=0,c=0,d=0,e=0,h=0,l=0;
    uint16_t pc=0x0556,ix=0x8000,sp=0xff00;
    static constexpr uint8_t C=1,Z=64;
    uint8_t read() { auto address=pc++;return tape.rom_byte(address,mem[address]); }
    uint16_t word() { auto lo=read();return lo | (uint16_t(read())<<8); }
    void flags(uint8_t value,bool carry=false) { f=(value==0?Z:0)|(carry?C:0); }
    void push(uint16_t value) { mem[--sp]=value>>8;mem[--sp]=value; }
    void ret() { pc=mem[sp] | (uint16_t(mem[uint16_t(sp+1)])<<8);sp+=2; }
    void relative(bool taken) { int8_t disp=read();if(taken) pc+=disp; }
    void run(unsigned waiting=0) {
        push(0x9000);
        if (waiting) {
            // State after the original loader's prologue, before its EAR loop.
            push(0x053f);push(0x056f);if(waiting==2) push(0x05e6);aa=a;ff=f&1;a=0;f=64;pc=0x05ed;
            tape.observe_fetch(0x05f1,0xdb,true); // Upload first noticed mid-sampling.
            assert(tape.rom_byte(0x0562,0xdb)==0xdb);
        }
        for(unsigned steps=0;steps<100000;++steps) {
            if(pc==0x053f) { tape.observe_fetch(pc,mem[pc],true);return; }
            tape.observe_fetch(pc,mem[pc],true);
            const auto op=read();
            switch(op) {
            case 0x14: ++d; f=(f&C)|(d==0?Z:0);break;
            case 0x15: --d; f=(f&C)|(d==0?Z:0);break;
            case 0x08: std::swap(a,aa);std::swap(f,ff);break;
            case 0xf3: break;
            case 0x3e: a=read();break;
            case 0xd3: read();break;
            case 0x21: { auto v=word();h=v>>8;l=v;break; }
            case 0xe1: l=mem[sp++];h=mem[sp++];break;
            case 0x7d: a=l;break;
            case 0xe5: push((uint16_t(h)<<8)|l);break;
            case 0x0e: c=read();break;
            case 0xc3: pc=word();break;
            case 0x79: a=c;break;
            case 0xee: a^=read();flags(a);break;
            case 0x4f: c=a;break;
            case 0x26: h=read();break;
            case 0x06: b=read();break;
            case 0x18: relative(true);break;
            case 0xdb: { auto port=read();uint8_t v;assert(tape.fast_io((uint16_t(a)<<8)|port,v));a=v;break; }
            case 0xb7: flags(a);break;
            case 0xc8: if(f&Z) ret();break;
            case 0x6f: l=a;break;
            case 0x7c: a=h;break;
            case 0xad: a^=l;flags(a);break;
            case 0x67: h=a;break;
            case 0x7a: a=d;break;
            case 0xb3: a|=e;flags(a);break;
            case 0x20: relative(!(f&Z));break;
            case 0x30: relative(!(f&C));break;
            case 0xc0: if(!(f&Z)) ret();break;
            case 0xdd: {
                auto next=read();
                if(next==0x75) { auto disp=int8_t(read());if(uint16_t(ix+disp)>=0x4000) mem[uint16_t(ix+disp)]=l; }
                else if(next==0x7e) { auto disp=int8_t(read());a=mem[uint16_t(ix+disp)]; }
                else { assert(next==0x23);++ix; }
                break;
            }
            case 0xcb: { assert(read()==0x11);auto old=c;c=(c<<1)|(f&C);flags(c,old&0x80);break; }
            case 0x1f: { auto old=a;a=(a>>1)|((f&C)<<7);f=(f&Z)|(old&1);break; }
            case 0x13: { uint16_t v=((uint16_t(d)<<8)|e)+1;d=v>>8;e=v;break; }
            case 0x1b: { uint16_t v=((uint16_t(d)<<8)|e)-1;d=v>>8;e=v;break; }
            case 0xfe: { auto v=read();flags(uint8_t(a-v),a<v);break; }
            case 0xc9: ret();break;
            default: assert(!"unexpected Z80 opcode");
            }
        }
        assert(!"loader did not return");
    }
    void upload(std::vector<uint8_t> bytes) {
        assert(tape.begin(bytes.size(),tape_crc(bytes.data(),bytes.size())));
        assert(tape.chunk(0,bytes.data(),bytes.size()));assert(tape.commit());
        assert(tape.set_mode(ZxTape::Mode::Fast));
    }
};
int main(int argc,char** argv) {
    assert(argc==2);
    std::array<uint8_t,16384> rom{};
    std::ifstream file(argv[1],std::ios::binary);file.read((char*)rom.data(),rom.size());assert(file.gcount()==rom.size());
    auto init=[&](Cpu& cpu,uint8_t flag,uint16_t count,bool load) {
        std::copy(rom.begin(),rom.end(),cpu.mem.begin());cpu.a=flag;cpu.f=load?1:0;cpu.d=count>>8;cpu.e=count;
    };
    const std::vector<uint8_t> tap={5,0,255,0x42,0x19,0xa5,0x01}; // FF^42^19^A5 = 01
    { Cpu cpu;init(cpu,255,3,true);cpu.upload(tap);cpu.run();
      assert(cpu.f&1);assert(cpu.ix==0x8003 && cpu.d==0 && cpu.e==0);
      assert(cpu.mem[0x8000]==0x42 && cpu.mem[0x8001]==0x19 && cpu.mem[0x8002]==0xa5);
      assert(cpu.tape.block()==1 && std::string(cpu.tape.state_name())=="finished"); }
    { Cpu cpu;init(cpu,255,3,true);cpu.upload(tap);cpu.run(true);
      assert(cpu.f&1);assert(cpu.ix==0x8003 && cpu.mem[0x8002]==0xa5);
      assert(cpu.tape.fast_blocks()==1 && cpu.tape.normal_blocks()==0); }
    { Cpu cpu;init(cpu,255,3,true);cpu.upload(tap);cpu.run(2);
      assert(cpu.f&1);assert(cpu.ix==0x8003 && cpu.mem[0x8002]==0xa5);
      assert(cpu.tape.fast_blocks()==1 && cpu.tape.normal_blocks()==0); }
    { Cpu cpu;init(cpu,255,3,false);cpu.upload(tap);cpu.mem[0x8000]=0x42;cpu.mem[0x8001]=0x19;cpu.mem[0x8002]=0xa5;
      cpu.run();assert(cpu.f&1);assert(cpu.ix==0x8003); }
    { Cpu cpu;init(cpu,255,3,false);cpu.upload(tap);cpu.mem[0x8000]=0x43;
      cpu.run();assert(!(cpu.f&1));assert(cpu.mem[0x8000]==0x43 && cpu.ix==0x8000); }
    { Cpu cpu;init(cpu,0,3,true);cpu.upload(tap);cpu.run();assert(!(cpu.f&1));assert(cpu.ix==0x8000 && cpu.mem[0x8000]==0); }
    { Cpu cpu;init(cpu,255,3,true);auto bad=tap;bad.back()^=1;cpu.upload(bad);cpu.run();assert(!(cpu.f&1)); }
    { Cpu cpu;init(cpu,255,4,true);cpu.upload(tap);cpu.run();assert(!(cpu.f&1)); } // Missing checksum byte.
    { Cpu cpu;init(cpu,0,17,true);std::vector<uint8_t> header={19,0,0};header.resize(21,0);cpu.upload(header);
      cpu.run();assert(cpu.f&1);assert(cpu.ix==0x8011); }
    { Cpu cpu;init(cpu,255,3,true);auto two=tap;two.insert(two.end(),tap.begin(),tap.end());cpu.upload(two);
      cpu.run();assert(cpu.f&1);assert(cpu.tape.block()==1 && std::string(cpu.tape.state_name())=="armed");
      cpu.pc=0x0556;cpu.a=255;cpu.f=1;cpu.d=0;cpu.e=3;cpu.run();assert(cpu.f&1);assert(cpu.tape.block()==2); }
}
'''
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)
    (path/'test.cpp').write_text(source)
    subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined','-I',str(root),str(path/'test.cpp'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test'),str(root/'roms/48.rom')],check=True)
print('PASS: real ROM fast loop: LOAD, VERIFY, flag/checksum errors, truncated block, header and consecutive blocks')

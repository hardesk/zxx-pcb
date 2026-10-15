#!/usr/bin/env python3
"""Cross-language transfer integrity, control semantics, and TAP pulse checks."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import zlib
sys.dont_write_bytecode = True
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('zx_media',root/'tools/zx_media.py')
sender=importlib.util.module_from_spec(spec);spec.loader.exec_module(sender)
def block(data): return len(data).to_bytes(2,'little')+data
tap=block(bytes([0,0x80,0x80]))+block(bytes([255,0x42,0xbd]))
assert sender.validate_tap(tap)==2
for bad in (b'',b'\x01',b'\x01\x00\x00',b'\x03\x00\x00\x00'):
    try: sender.validate_tap(bad);raise AssertionError('accepted malformed TAP')
    except ValueError: pass
frames=[sender.frame(1,1,len(tap).to_bytes(4,'little')+zlib.crc32(tap).to_bytes(4,'little')),
        sender.frame(2,2,(0).to_bytes(4,'little')+tap),sender.frame(3,3)]
source=r'''
#include "zx_tape_protocol.hpp"
#include <cassert>
#include <string>
#include <vector>
std::vector<uint8_t> response;
void reply(const uint8_t* p,unsigned n,void*) { response.assign(p,p+n); }
int main() {
    const uint8_t tap[]={TAP};
    const uint8_t begin[]={BEGIN}, chunk[]={CHUNK}, commit[]={COMMIT};
    ZxTape t; ZxTapeProtocol protocol;
    assert(!t.observes_cpu());
    auto feed=[&](const uint8_t* bytes,unsigned n,unsigned now=1) {
        for(unsigned i=0;i<n;++i) protocol.feed(bytes[i],now,t,reply,nullptr);
        assert(response.size()>=14 && response[0]=='Z' && response[1]=='T');
        uint32_t crc=0;for(unsigned i=0;i<4;++i) crc|=uint32_t(response[response.size()-4+i])<<(i*8);
        assert(tape_crc(response.data(),response.size()-4)==crc);
    };
    assert(!t.begin(3,0) && !t.begin(ZxTape::capacity+1,0));
    feed(begin,sizeof(begin));assert(t.size()==sizeof(tap) && t.received()==0);
    assert(!t.observes_cpu());
    feed(chunk,sizeof(chunk));assert(t.received()==sizeof(tap));
    feed(chunk,sizeof(chunk));assert(t.received()==sizeof(tap)); // ACK retry is idempotent.
    feed(commit,sizeof(commit));assert(std::string(t.state_name())=="armed" && t.blocks()==2);
    assert(!t.chunk(0,tap,1));
    t.observe_fetch(0x0556,0x14,false);assert(std::string(t.state_name())=="armed");
    t.observe_fetch(0x0556,0x14,true);assert(std::string(t.state_name())=="playing");
    feed(commit,sizeof(commit));assert(std::string(t.state_name())=="playing"); // Duplicate commit cannot rewind.
    bool level=false;
    auto pulse=[&](unsigned duration) {
        const bool before=t.ear();
        t.advance(duration-1);assert(t.ear()==before);
        t.advance(1);level=!level;assert(t.ear()==level);
    };
    for(unsigned i=0;i<8063;++i) pulse(2168);
    pulse(667);pulse(735);
    for(unsigned i=2;i<5;++i) for(unsigned bit=0;bit<8;++bit) {
        unsigned duration=tap[i]&(0x80>>bit) ? 1710 : 855;
        pulse(duration);pulse(duration);
    }
    assert(std::string(t.state_name())=="armed" && t.position()==5 && t.block()==1);
    t.observe_fetch(0x05e2,0xc9,true); // Still in loader: must not start next block.
    assert(std::string(t.state_name())=="armed");
    assert(t.observes_cpu()); // Finished pulse train still needs the outgoing fetch.
    t.observe_fetch(0x053f,0xf5,true);assert(!t.ear());
    t.observe_fetch(0x0556,0x14,true);
    level=false;
    for(unsigned i=0;i<3223;++i) pulse(2168);
    pulse(667);pulse(735);
    for(unsigned i=7;i<10;++i) for(unsigned bit=0;bit<8;++bit) {
        unsigned duration=tap[i]&(0x80>>bit) ? 1710 : 855;
        pulse(duration);pulse(duration);
    }
    assert(std::string(t.state_name())=="finished" && t.position()==sizeof(tap));
    assert(t.observes_cpu());
    t.observe_fetch(0x053f,0xf5,true);assert(!t.ear() && !t.observes_cpu());
    assert(t.rewind());t.stop();assert(std::string(t.state_name())=="stopped");
    assert(!t.observes_cpu());
    t.observe_fetch(0x0556,0x14,true);assert(std::string(t.state_name())=="stopped");
    assert(t.rewind());t.observe_fetch(0x0556,0x14,true);
    t.observe_fetch(0x8000,0,true);assert(t.position()==5); // Skip rejected block on loader exit.
    t.reset();assert(std::string(t.state_name())=="stopped" && t.has_tape());
    assert(!t.observes_cpu());
    assert(t.begin(4,0));t.stop();assert(std::string(t.state_name())=="empty" && t.size()==0);
    assert(!t.observes_cpu());
    // Streaming upload CRC and structure are independently checked on commit.
    assert(t.begin(sizeof(tap),123));assert(t.chunk(0,tap,sizeof(tap)));assert(!t.commit());
    uint8_t broken[]={4,0,0,0};
    assert(t.begin(4,tape_crc(broken,4)));assert(t.chunk(0,broken,4));assert(!t.commit());
    assert(t.begin(sizeof(tap),tape_crc(tap,sizeof(tap))));
    assert(!t.chunk(1,tap,1));assert(t.chunk(0,tap,4));assert(!t.chunk(4,tap,100));
    assert(t.chunk(4,tap+4,sizeof(tap)-4));assert(t.commit());
    // Exhaustive standard ROM loop cycle accounting, including IN partial time.
    // 36 complete no-edge sampling loops consume 36*59=2124 T states.
    assert(t.rewind());
    t.observe_fetch(0x05ed,0x04,true);
    auto loop=[&]() {
        t.observe_fetch(0x05ee,0xc8,true);t.observe_fetch(0x05ef,0x3e,true);
        t.observe_fetch(0x05f1,0xdb,true);t.read_ear();t.read_ear();
        t.observe_fetch(0x05f3,0x1f,true);t.observe_fetch(0x05f4,0xd0,true);
        t.observe_fetch(0x05f5,0xa9,true);t.observe_fetch(0x05f6,0xe6,true);
        t.observe_fetch(0x05f8,0x28,true);t.observe_fetch(0x05ed,0x04,true);
    };
    for(unsigned i=0;i<36;++i) loop();
    assert(!t.ear());t.advance(43);assert(!t.ear());t.advance(1);assert(t.ear());
    // Fast overlay supplies complete bytes, retaining the ROM's byte processing.
    t.observe_fetch(0x8000,0,true);
    assert(t.set_mode(ZxTape::Mode::Fast));assert(t.rewind());
    t.observe_fetch(0x0556,0x14,false);assert(t.rom_byte(0x0562,0xdb)==0xdb);
    t.observe_fetch(0x0556,0x14,true);
    assert(t.rom_byte(0x0562,0xdb)==0x0e && t.rom_byte(0x0564,0x1f)==0xc3);
    assert(t.rom_byte(0x05c8,0x2e)==0xdb && t.rom_byte(0x05c9,1)==0xfd);
    assert(t.rom_byte(0x05a9,0x08)==0x08); // Existing LOAD/VERIFY loop is unchanged.
    assert(!t.set_mode(ZxTape::Mode::Normal));
    uint8_t v=0;
    for(unsigned i=2;i<5;++i) {
        assert(t.fast_io(0x12fd,v) && v==1);
        assert(t.fast_io(0xabfb,v) && v==tap[i]);
    }
    assert(t.fast_io(0xfd,v) && v==0); // Short block causes RET Z, carry clear.
    assert(!t.fast_io(0xfe,v));
    t.observe_fetch(0x053f,0xf5,true);
    assert(t.block()==1 && std::string(t.state_name())=="armed");
    assert(!t.fast_io(0xfb,v));assert(t.rom_byte(0x0562,0xdb)==0xdb);
    t.observe_fetch(0x0556,0x14,true);
    assert(t.fast_io(0xfb,v) && v==255);
    t.observe_fetch(0x053f,0xf5,true); // Rejected flag/VERIFY failure skips the rest.
    assert(t.block()==2 && std::string(t.state_name())=="finished");
    assert(t.rewind());t.observe_fetch(0x0556,0x14,true);t.stop();
    assert(t.fast_io(0xfd,v) && v==0); // Stop keeps overlay until safe error return.
    assert(t.rom_byte(0x05c8,0x2e)==0xdb);
    t.observe_fetch(0x053f,0xf5,true);assert(t.set_mode(ZxTape::Mode::Normal));
    // Upload or rewind after LOAD is already waiting must still enter fast mode.
    assert(t.set_mode(ZxTape::Mode::Fast));assert(t.rewind());
    t.observe_fetch(0x05f1,0xdb,true); // First observed fetch is in the EAR sampling loop.
    assert(!t.fast_io(0xfd,v)); // Cannot replace an instruction in mid-loop.
    t.observe_fetch(0x05ed,0x04,true); // Safe start of the sampling loop.
    assert(t.fast_io(0xfd,v) && v==1);
    assert(t.rom_byte(0x05ed,0x04)==0xe1); // Jump back to initialization after PUSH.
    assert(t.rom_byte(0x05ee,0xc8)==0x7d && t.rom_byte(0x05f4,0xa9)==0xc3);
    t.observe_fetch(0x053f,0xf5,true);
    // Mode wire command and invalid payloads.
    const uint8_t fast_mode[]={FASTMODE}, bad_mode[]={BADMODE};
    feed(fast_mode,sizeof(fast_mode),900);assert(std::string(t.mode_name())=="fast");
    assert(std::string(response.begin()+10,response.end()-4).find("\"mode\":\"fast\"")!=std::string::npos);
    feed(bad_mode,sizeof(bad_mode),901);assert(std::string(t.mode_name())=="fast");
    assert(std::string(response.begin()+10,response.end()-4).find("\"ok\":false")!=std::string::npos);
    const uint8_t reset[]={RESETFRAME}, bad_reset[]={BADRESETFRAME};
    assert(t.rewind());
    feed(bad_reset,sizeof(bad_reset),902);assert(!protocol.take_reset_request());
    feed(reset,sizeof(reset),903);assert(protocol.take_reset_request());
    assert(!protocol.take_reset_request());assert(t.has_tape());
    assert(std::string(t.state_name())=="stopped" && std::string(t.mode_name())=="fast");
    feed(reset,sizeof(reset),904);assert(!protocol.take_reset_request()); // ACK retry must not reset twice.
    // Corrupt packet, noise, and truncated header resynchronize before a status.
    ZxTapeProtocol p2;response.clear();
    auto corrupt=std::vector<uint8_t>(begin,begin+sizeof(begin));corrupt.back()^=1;
    for(auto b:corrupt) p2.feed(b,2,t,reply,nullptr);
    assert(response.empty());
    for(unsigned i=0;i<5;++i) p2.feed(begin[i],3,t,reply,nullptr);
    const uint8_t status[]={STATUS};
    for(auto b:status) p2.feed(b,1000,t,reply,nullptr);
    assert(!response.empty() && response[3]==0x86);
}
'''
for key,data in [('TAP',tap),('BEGIN',frames[0]),('CHUNK',frames[1]),('COMMIT',frames[2]),('STATUS',sender.frame(6,4)),('FASTMODE',sender.frame(7,5,b'\x01')),('BADMODE',sender.frame(7,6,b'\x02')),('BADRESETFRAME',sender.frame(8,8,b'\x00')),('RESETFRAME',sender.frame(8,7))]:
    source=source.replace(key,','.join(str(x) for x in data))
with tempfile.TemporaryDirectory() as temp:
    p=Path(temp);(p/'test.cpp').write_text(source)
    subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined','-I',str(root),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
print('PASS: buffered TAP, Python/C++ framing and CRC, retries, pulses, ROM clock, controls and corruption')

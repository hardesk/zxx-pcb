#pragma once
#include "zx_tape.hpp"
#include "zx_disk.hpp"
#include <cstring>
#include <cstdio>
#include <algorithm>

// ZT, version=1, opcode, sequence:u32, length:u16, payload, CRC32(header+payload).
// Responses use opcode|0x80 and a JSON payload. One request is outstanding.
// Opcodes 1..8 control the tape, 0x10..0x14 the TR-DOS disk store.
class ZxTapeProtocol {
public:
    // Tape chunks carry 512 data bytes, disk chunks up to 2048.
    static constexpr unsigned max_payload=2052, max_frame=10+max_payload+4, max_reply=900;
    using Reply=void(*)(const uint8_t*,unsigned,void*);
    bool take_reset_request() {
        const bool requested=reset_requested_; reset_requested_=false; return requested;
    }
    void feed(uint8_t byte, uint32_t now, ZxTape& tape, Reply reply, void* context,
              ZxDiskStore* disks=nullptr) {
        if (used_ && uint32_t(now-last_byte_)>400) used_=0;
        last_byte_=now;
        input_[used_++]=byte;
        while (used_>=2) {
            if (input_[0]!='Z' || input_[1]!='T') { discard(1); continue; }
            if (used_<10) return;
            const unsigned n=u16(input_+8);
            if (input_[2]!=1 || n>max_payload) { discard(1); continue; }
            const unsigned total=14+n;
            if (used_<total) return;
            if (tape_crc(input_,total-4)!=u32(input_+total-4)) { discard(1); continue; }
            const uint32_t seq=u32(input_+4);
            if (cached_ && seq==last_seq_ && input_[3]==last_op_ &&
                u32(input_+total-4)==last_crc_) {
                reply(output_,output_size_,context);
            } else {
                handle(tape,disks,seq,input_[3],input_+10,n,reply,context);
                last_seq_=seq; last_op_=input_[3]; last_crc_=u32(input_+total-4); cached_=true;
            }
            discard(total);
        }
    }
private:
    uint8_t input_[max_frame]{}, output_[max_reply]{};
    unsigned used_=0, output_size_=0;
    uint32_t last_byte_=0,last_seq_=0,last_crc_=0;
    uint8_t last_op_=0;
    bool cached_=false;
    bool reset_requested_=false;
    static unsigned u16(const uint8_t* p) { return p[0] | (unsigned(p[1])<<8); }
    static uint32_t u32(const uint8_t* p) { return u16(p) | (uint32_t(u16(p+2))<<16); }
    static void put32(uint8_t* p,uint32_t v) { for(unsigned i=0;i<4;++i) p[i]=v>>(i*8); }
    void discard(unsigned n) { used_-=n; memmove(input_,input_+n,used_); }
    void handle(ZxTape& tape,ZxDiskStore* disks,uint32_t seq,uint8_t op,const uint8_t* p,unsigned n,Reply reply,void* context) {
        if (op>=0x10 && op<=0x14) { handle_disk(disks,seq,op,p,n,reply,context); return; }
        bool ok=false;
        switch(op) {
        case 1: ok=n==8 && tape.begin(u32(p),u32(p+4)); break;
        case 2: ok=n>4 && tape.chunk(u32(p),p+4,n-4); break;
        case 3: ok=n==0 && tape.commit(); break;
        case 4: if(n==0) { tape.stop(); ok=true; } break;
        case 5: ok=n==0 && tape.rewind(); break;
        case 6: ok=n==0; break;
        case 7: ok=n==1 && p[0]<=1 && tape.set_mode(p[0] ? ZxTape::Mode::Fast : ZxTape::Mode::Normal); break;
        case 8: if(n==0) { tape.reset(); reset_requested_=true; ok=true; } break;
        default: break;
        }
        const int length=snprintf(reinterpret_cast<char*>(output_+10),sizeof(output_)-14,
            "{\"ok\":%s,\"state\":\"%s\",\"size\":%lu,\"received\":%lu,\"position\":%lu,\"block\":%u,\"blocks\":%u,\"capacity\":%lu,\"mode\":\"%s\",\"playback\":\"%s\",\"fast_blocks\":%u,\"normal_blocks\":%u}",
            ok?"true":"false",tape.state_name(),(unsigned long)tape.size(),(unsigned long)tape.received(),
            (unsigned long)tape.position(),tape.block(),tape.blocks(),(unsigned long)ZxTape::capacity,tape.mode_name(),tape.playback_name(),tape.fast_blocks(),tape.normal_blocks());
        send(seq,op,length,reply,context);
    }
    // 10 BEGIN drive u8, flags u8 (bit 0 write protect), size u32, CRC32 u32, name
    // 11 CHUNK offset u32, 1..512 bytes   12 COMMIT   13 EJECT drive u8   14 STATUS
    void handle_disk(ZxDiskStore* disks,uint32_t seq,uint8_t op,const uint8_t* p,unsigned n,Reply reply,void* context) {
        bool ok=false;
        if (disks) switch(op) {
        case 0x10: ok=n>=10 && disks->begin(p[0],u32(p+2),u32(p+6),p[1]&1,reinterpret_cast<const char*>(p+10),n-10); break;
        case 0x11: ok=n>4 && disks->chunk(u32(p),p+4,n-4); break;
        case 0x12: ok=n==0 && disks->commit(); break;
        case 0x13: ok=n==1 && disks->eject(p[0]); break;
        case 0x14: ok=n==0; break;
        }
        char* out=reinterpret_cast<char*>(output_+10);
        const unsigned room=sizeof(output_)-14;
        int length=snprintf(out,room,"{\"ok\":%s,\"disk\":%s",ok?"true":"false",disks?"true":"false");
        if (disks && op==0x11) { // Chunks: keep the per-chunk reply short.
            length+=snprintf(out+length,room-length,",\"received\":%lu",(unsigned long)disks->received());
        } else if (disks) {
            length+=snprintf(out+length,room-length,",\"uploading\":%d,\"received\":%lu,\"programmed_blocks\":%u,\"capacity\":%lu,\"drives\":[",
                disks->upload_drive(),(unsigned long)disks->received(),disks->programmed_blocks(),(unsigned long)ZxDiskStore::max_image);
            for (unsigned d=0;d<ZxDiskStore::drives;++d) {
                const ZxDiskStore::Info& info=disks->info(d);
                length+=snprintf(out+length,room-length,"%s{\"drive\":\"%c\",\"present\":%s,\"name\":\"%s\",\"size\":%lu,\"write_protect\":%s}",
                    d?",":"",'A'+d,info.present?"true":"false",info.name,(unsigned long)info.size,info.write_protect?"true":"false");
            }
            length+=snprintf(out+length,room-length,"],\"dirty\":%s",disks->dirty()?"true":"false");
        }
        length+=snprintf(out+length,room-length,"}");
        send(seq,op,length,reply,context);
    }
    void send(uint32_t seq,uint8_t op,int length,Reply reply,void* context) {
        const unsigned len=length>0 ? std::min<unsigned>(unsigned(length),sizeof(output_)-15) : 0;
        output_[0]='Z';output_[1]='T';output_[2]=1;output_[3]=op|0x80;
        put32(output_+4,seq);output_[8]=len;output_[9]=len>>8;
        put32(output_+10+len,tape_crc(output_,10+len));output_size_=14+len;
        reply(output_,output_size_,context);
    }
};

#pragma once
#include "zx_tape_protocol.hpp"
#include "SEGGER_RTT.h"
#include <pico/time.h>

class ZxTapeRtt {
public:
    bool take_reset_request() { return protocol_.take_reset_request(); }
    void init() {
        hard_assert(SEGGER_RTT_ConfigUpBuffer(2,"ZX tape",up_,sizeof(up_),SEGGER_RTT_MODE_NO_BLOCK_SKIP)==0);
        hard_assert(SEGGER_RTT_ConfigDownBuffer(2,"ZX tape",down_,sizeof(down_),SEGGER_RTT_MODE_NO_BLOCK_SKIP)==0);
    }
    void poll(ZxTape& tape, ZxDiskStore* disks=nullptr) {
        const uint32_t now=to_ms_since_boot(get_absolute_time());
        if (uint32_t(now-last_poll_)<2) return;
        last_poll_=now;
        // A whole disk chunk per poll; static, since core0's stack is small.
        static uint8_t bytes[ZxTapeProtocol::max_frame];
        const unsigned count=SEGGER_RTT_Read(2,bytes,sizeof(bytes));
        for(unsigned i=0;i<count;++i) protocol_.feed(bytes[i],now,tape,reply,nullptr,disks);
    }
private:
    // The up buffer holds a whole reply (disk status is the largest).
    char up_[1024]{},down_[8192]{};
    uint32_t last_poll_=0;
    ZxTapeProtocol protocol_;
    static void reply(const uint8_t* data,unsigned size,void*) { SEGGER_RTT_Write(2,data,size); }
};

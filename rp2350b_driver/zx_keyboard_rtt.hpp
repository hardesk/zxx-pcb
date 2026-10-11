#pragma once
#include "zx_keyboard.hpp"
#include "SEGGER_RTT.h"
#include <pico/time.h>

class ZxKeyboardRtt {
public:
    bool take_reset_request() { return receiver_.take_reset_request(); }
    void init() {
        // Channel 0 remains stdio. OpenOCD needs an up-buffer for this server too.
        hard_assert(SEGGER_RTT_ConfigUpBuffer(1, "ZX keyboard", up_, sizeof(up_), SEGGER_RTT_MODE_NO_BLOCK_SKIP) == 0);
        hard_assert(SEGGER_RTT_ConfigDownBuffer(1, "ZX keyboard", down_, sizeof(down_), SEGGER_RTT_MODE_NO_BLOCK_SKIP) == 0);
    }
    void poll(ZxKeyboard& keyboard) {
        const uint32_t now = to_ms_since_boot(get_absolute_time());
        if (uint32_t(now-last_poll_) < 2) return;
        last_poll_ = now;
        uint8_t bytes[128]; // Bound work between bus transactions.
        const unsigned count = SEGGER_RTT_Read(1, bytes, sizeof(bytes));
        for (unsigned i=0; i<count; ++i)
            if (receiver_.feed(bytes[i], now, keyboard))
                SEGGER_RTT_Write(1, "K", 1); // Confirms a validated, applied snapshot.
        receiver_.expire(now, keyboard);
    }
private:
    char up_[16]{}, down_[1024]{};
    uint32_t last_poll_ = 0;
    ZxKeyboardReceiver receiver_;
};

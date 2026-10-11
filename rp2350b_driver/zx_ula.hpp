#pragma once
#include <atomic>
#include <cstdint>
#include "zx_keyboard.hpp"

// Digital ULA port state. Core0 writes; the LCD core samples output atomically.
// Physical tape/audio pins and analogue EAR/MIC coupling are separate backends.
class ZxUla {
public:
    void reset() { output_.store(0, std::memory_order_relaxed); ear_input_ = false; }
    void write(uint8_t value) { output_.store(value & 0x1f, std::memory_order_relaxed); }
    uint8_t output() const { return output_.load(std::memory_order_relaxed); }
    unsigned border() const { return output() & 7; }
    bool beeper() const { return (output() & 0x10) != 0; }
    bool mic_active() const { return (output() & 8) == 0; }
    void set_ear_input(bool high) { ear_input_ = high; }
    uint8_t read(const ZxKeyboard& keyboard, uint16_t port) const {
        return uint8_t(keyboard.read(port) | (ear_input_ ? 0x40 : 0));
    }
private:
    std::atomic<uint8_t> output_{0};
    bool ear_input_ = false;
};

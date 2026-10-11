#pragma once

#include <cstdint>

// Owns PWM slice 8 on RP2350B (GPIO32 / INT). GPIO33 (NMI) and the
// GPIO40/41 aliases remain SIO/PIO and are not switched to PWM.
// No DMA, PIO state machine, or RP2350 timer interrupt is required.
class Z80FrameInterrupt {
public:
    static constexpr uint32_t frequency_hz = 50;
    static constexpr uint32_t period_us = 1'000'000 / frequency_hz;

    // 1 us resolution, rounded up so the pulse is never shorter than requested.
    static constexpr uint32_t pulse_width_us(uint32_t z80_hz, uint32_t tstates = 32) {
        return z80_hz ? static_cast<uint32_t>((uint64_t(tstates) * 1'000'000 + z80_hz - 1) / z80_hz) : 0;
    }

    Z80FrameInterrupt() = default;
    ~Z80FrameInterrupt() { stop(); }
    Z80FrameInterrupt(const Z80FrameInterrupt&) = delete;
    Z80FrameInterrupt& operator=(const Z80FrameInterrupt&) = delete;

    // Start after bus initialization/reset. First pulse is one frame later.
    // Requires an integer-MHz system clock; above 255 MHz it must divide evenly
    // into 1/2 or 1/3 us PWM ticks (e.g. 300 MHz uses 0.5 us ticks).
    // INT returns high after the pulse, even if the Z80 did not acknowledge it.
    void start(uint32_t z80_hz, uint32_t tstates = 32);
    void stop(); // Restore inactive-high SIO GPIO; safe when already stopped.

private:
    bool m_running = false;
};

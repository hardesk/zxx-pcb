#include "z80_pio_bus.hpp"

#include <hardware/gpio.h>
#include <pico/time.h>

#include "z80_pins.hpp"

namespace z80pio {

namespace {

constexpr bool active_low(uint32_t sample, uint32_t mask)
{
    return !(sample & mask);
}

} // namespace

void ManualBusDriver::init(uint32_t z80_hz)
{
    // This backend deliberately preserves the old unpaced software loop.
    // z80_hz is meaningful only to the hardware-clocked PIO backends.
    (void)z80_hz;

    gpio_set_function(pCLK, GPIO_FUNC_SIO);
    gpio_set_dir(pCLK, true);
    gpio_put(pCLK, false);
    gpio_set_dir_masked(kZ80DataMask, 0);

    previous_raw_ = gpio_get_all();
    next_clock_high_ = true;
}

void ManualBusDriver::begin_reset()
{
    gpio_put(pRESET, false);
}

void ManualBusDriver::end_reset()
{
    // RESET needs at least three complete clocks. Eight deliberately slow
    // clocks leave ample margin and finish with CLK low.
    for (uint i = 0; i < 8; ++i) {
        gpio_put(pCLK, true);
        busy_wait_us_32(1);
        gpio_put(pCLK, false);
        busy_wait_us_32(1);
    }

    gpio_set_dir_masked(kZ80DataMask, 0);
    gpio_put(pRESET, true);
    previous_raw_ = gpio_get_all();
    next_clock_high_ = true;
}

BusRequest ManualBusDriver::read_request()
{
    while (true) {
        gpio_put(pCLK, next_clock_high_);
        next_clock_high_ = !next_clock_high_;

        const uint32_t raw = gpio_get_all();
        const uint32_t changed = raw ^ previous_raw_;
        previous_raw_ = raw;

        // The original loop stopped driving read data when either bus cycle
        // ended. Do this before looking for a new request on the same sample.
        if (((raw & kRawMreq) && (changed & kRawMreq)) ||
            ((raw & kRawIorq) && (changed & kRawIorq))) {
            gpio_set_dir_masked(kZ80DataMask, 0);
        }

        const bool mreq = active_low(raw, kRawMreq);
        const bool iorq = active_low(raw, kRawIorq);
        const bool rd = active_low(raw, kRawRd);
        const bool wr = active_low(raw, kRawWr);

        // As in the old react() loop, capture normal requests on the falling
        // edge of RD or WR.
        if (mreq && ((rd && (changed & kRawRd)) ||
                     (wr && (changed & kRawWr)))) {
            return {raw};
        }

        if (iorq && ((rd && (changed & kRawRd)) ||
                     (wr && (changed & kRawWr)))) {
            return {raw};
        }

        // An interrupt acknowledge has IORQ and M1 low without RD or WR.
        if (iorq && active_low(raw, kRawM1) &&
            (changed & (kRawIorq | kRawM1))) {
            return {raw};
        }
    }
}

void ManualBusDriver::write_reply(uint32_t reply)
{
    if (reply & kReplyDriveData) {
        gpio_put_masked(kZ80DataMask, reply & kZ80DataMask);
        gpio_set_dir_masked(kZ80DataMask, kZ80DataMask);
    }
}

} // namespace z80pio

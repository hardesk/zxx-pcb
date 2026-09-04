#include "z80_pio_bus.hpp"

#include <algorithm>

#include <hardware/clocks.h>
#include <hardware/pio.h>
#include <pico/stdlib.h>

#include "z80_bus_wait.pio.h"
#include "z80_pins.hpp"

namespace z80pio {

namespace {

void assign_wait_bus_pins(PIO pio)
{
    for (uint pin = pD0; pin <= pCLK; ++pin) {
        pio_gpio_init(pio, pin);
    }
    for (uint pin = pWAIT; pin <= pWR; ++pin) {
        pio_gpio_init(pio, pin);
    }
}

} // namespace

void WaitStateBusDriver::init(uint32_t z80_hz)
{
    hard_assert(z80_hz != 0);
    pio_set_gpio_base(pio_, 0);
    reset_hold_us_ = std::max<uint32_t>(
        10,
        static_cast<uint32_t>((8'000'000ull + z80_hz - 1) / z80_hz));

    clock_sm_ = pio_claim_unused_sm(pio_, true);
    bus_sm_ = pio_claim_unused_sm(pio_, true);

    const uint clock_offset = pio_add_program(pio_, &z80_wait_clock_program);
    const uint bus_offset = pio_add_program(pio_, &z80_wait_bus_program);

    assign_wait_bus_pins(pio_);

    pio_sm_config clock_config = z80_wait_clock_program_get_default_config(clock_offset);
    sm_config_set_sideset_pins(&clock_config, pCLK);
    const float clock_divider =
        static_cast<float>(clock_get_hz(clk_sys)) /
        (2.0f * static_cast<float>(z80_hz));
    sm_config_set_clkdiv(&clock_config, std::max(1.0f, clock_divider));

    pio_sm_config bus_config = z80_wait_bus_program_get_default_config(bus_offset);
    sm_config_set_in_pins(&bus_config, pD0);
    sm_config_set_in_pin_count(&bus_config, 32);
    sm_config_set_out_pins(&bus_config, pD0, 8);
    sm_config_set_set_pins(&bus_config, pWAIT, 1);
    sm_config_set_jmp_pin(&bus_config, pRESET);
    sm_config_set_out_shift(&bus_config, true, false, 32);
    sm_config_set_clkdiv(&bus_config, 1.0f);

    pio_sm_init(pio_, clock_sm_, clock_offset, &clock_config);
    pio_sm_init(pio_, bus_sm_, bus_offset, &bus_config);

    pio_sm_set_pins_with_mask(pio_, clock_sm_, 0, 1u << pCLK);
    pio_sm_set_pins_with_mask(pio_, bus_sm_, 1u << pWAIT, 1u << pWAIT);

    pio_sm_set_consecutive_pindirs(pio_, bus_sm_, pD0, 8, false);
    pio_sm_set_consecutive_pindirs(pio_, bus_sm_, pWAIT, 1, true);
    pio_sm_set_consecutive_pindirs(pio_, clock_sm_, pCLK, 1, true);

    // Let the bus state machine reach its first edge wait before CLK starts.
    pio_sm_set_enabled(pio_, bus_sm_, true);
    pio_sm_set_enabled(pio_, clock_sm_, true);
}

void WaitStateBusDriver::begin_reset()
{
    gpio_put(pRESET, false);
}

void WaitStateBusDriver::end_reset()
{
    // Hold for at least eight clocks (and at least 10 us). The Z80 requires
    // three complete clocks, so this leaves margin at any configured rate.
    busy_wait_us_32(reset_hold_us_);

    // Deassert during the low phase, comfortably before the next rising edge.
    while (!gpio_get(pCLK))
        tight_loop_contents();
    while (gpio_get(pCLK))
        tight_loop_contents();
    gpio_put(pRESET, true);
}

BusRequest WaitStateBusDriver::read_request()
{
    return {pio_sm_get_blocking(pio_, bus_sm_)};
}

void WaitStateBusDriver::write_reply(uint32_t reply)
{
    pio_sm_put_blocking(pio_, bus_sm_, reply);
}

} // namespace z80pio

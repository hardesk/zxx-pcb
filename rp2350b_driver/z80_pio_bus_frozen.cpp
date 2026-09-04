#include "z80_pio_bus.hpp"

#include <algorithm>

#include <hardware/clocks.h>
#include <hardware/pio.h>
#include <pico/stdlib.h>

#include "z80_bus_frozen.pio.h"
#include "z80_pins.hpp"

namespace z80pio {

namespace {

constexpr float kFrozenClockCyclesPerPeriod = 40.0f;

void assign_frozen_bus_pins(PIO bus_pio, PIO clock_pio)
{
    for (uint pin = pD0; pin <= pA15; ++pin) {
        pio_gpio_init(bus_pio, pin);
    }
    for (uint pin = pM1; pin <= pWR; ++pin) {
        pio_gpio_init(bus_pio, pin);
    }
    pio_gpio_init(clock_pio, pCLK);
}

} // namespace

void FrozenClockBusDriver::init(uint32_t z80_hz)
{
    hard_assert(z80_hz != 0);
    // The PIO assembly uses NEXT/PREV IRQ addressing and therefore relies on
    // this exact adjacency: bus=PIO0, clock=PIO1.
    pio_set_gpio_base(bus_pio_, 0);
    pio_set_gpio_base(clock_pio_, 0);
    reset_hold_us_ = std::max<uint32_t>(
        10,
        static_cast<uint32_t>((8'000'000ull + z80_hz - 1) / z80_hz));

    bus_sm_ = pio_claim_unused_sm(bus_pio_, true);
    clock_sm_ = pio_claim_unused_sm(clock_pio_, true);

    const uint bus_offset =
        pio_add_program(bus_pio_, &z80_frozen_bus_program);
    const uint clock_offset =
        pio_add_program(clock_pio_, &z80_frozen_clock_program);

    assign_frozen_bus_pins(bus_pio_, clock_pio_);

    pio_sm_config bus_config =
        z80_frozen_bus_program_get_default_config(bus_offset);
    sm_config_set_in_pins(&bus_config, pA0);
    sm_config_set_in_pin_count(&bus_config, 32);
    sm_config_set_out_pins(&bus_config, pD0, 8);
    sm_config_set_jmp_pin(&bus_config, pRESET);
    sm_config_set_out_shift(&bus_config, true, false, 32);
    sm_config_set_clkdiv(&bus_config, 1.0f);

    pio_sm_config clock_config =
        z80_frozen_clock_program_get_default_config(clock_offset);
    sm_config_set_sideset_pins(&clock_config, pCLK);
    sm_config_set_mov_status(&clock_config, STATUS_IRQ_SET, 1);
    const float clock_divider =
        static_cast<float>(clock_get_hz(clk_sys)) /
        (kFrozenClockCyclesPerPeriod * static_cast<float>(z80_hz));
    sm_config_set_clkdiv(&clock_config, std::max(1.0f, clock_divider));

    pio_sm_init(bus_pio_, bus_sm_, bus_offset, &bus_config);
    pio_sm_init(clock_pio_, clock_sm_, clock_offset, &clock_config);

    pio_interrupt_clear(bus_pio_, 0);
    pio_interrupt_clear(clock_pio_, 1);

    pio_sm_set_pins_with_mask(clock_pio_, clock_sm_, 0, 1u << pCLK);
    pio_sm_set_consecutive_pindirs(bus_pio_, bus_sm_, pD0, 8, false);
    pio_sm_set_consecutive_pindirs(clock_pio_, clock_sm_, pCLK, 1, true);

    // PIO0 waits for PIO1's first sample IRQ before PIO1 starts CLK.
    pio_sm_set_enabled(bus_pio_, bus_sm_, true);
    pio_sm_set_enabled(clock_pio_, clock_sm_, true);
}

void FrozenClockBusDriver::begin_reset()
{
    gpio_put(pRESET, false);
}

void FrozenClockBusDriver::end_reset()
{
    // While RESET is low the bus SM rejects all accesses and clears each
    // SAMPLE_IRQ, so the clock SM cannot remain frozen.
    busy_wait_us_32(reset_hold_us_);

    // Deassert during the low phase, comfortably before the next rising edge.
    while (!gpio_get(pCLK))
        tight_loop_contents();
    while (gpio_get(pCLK))
        tight_loop_contents();
    gpio_put(pRESET, true);
}

BusRequest FrozenClockBusDriver::read_request()
{
    return {pio_sm_get_blocking(bus_pio_, bus_sm_)};
}

void FrozenClockBusDriver::write_reply(uint32_t reply)
{
    pio_sm_put_blocking(bus_pio_, bus_sm_, reply);
}

} // namespace z80pio

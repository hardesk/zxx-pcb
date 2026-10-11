#include "z80_pio_bus.hpp"

#include <algorithm>

#include <hardware/clocks.h>
#include <hardware/pio.h>
#include <pico/stdlib.h>

#include "z80_bus_async.pio.h"
#include "z80_pins.hpp"

namespace z80pio {

namespace {

constexpr uint kDataReadyIrq = 3;
constexpr uint kDebugStartIrq = 6;
constexpr uint kDebugEndIrq = 7;

void assign_async_bus_pins(PIO bus_pio, PIO clock_pio)
{
    for (uint pin = pD0; pin <= pCLK; ++pin) {
        pio_gpio_init(bus_pio, pin);
    }
    for (uint pin = pM1; pin <= pWR; ++pin) {
        pio_gpio_init(bus_pio, pin);
    }
    pio_gpio_init(clock_pio, pCLK);
    pio_gpio_init(clock_pio, pPIO_DEBUG);
}

} // namespace

void AsyncBusDriver::init(uint32_t z80_hz)
{
    hard_assert(z80_hz != 0);
    // Early MREQ/IORQ assertion, qualified through 5 MHz on the attached FPGA.
    // Higher clocks require more assertion margin and board qualification.

    // Detector and service share PIO0. PIO1 generates CLK and owns WAIT.
    pio_set_gpio_base(bus_pio_, 0);
    // PIO1's relocated 16..47 window reaches CLK24, WAIT26 and GPIO39.
    // PIO0 remains at 0 for the native GPIO0..31 bus snapshot.
    pio_set_gpio_base(clock_pio_, 16);
    reset_hold_us_ = std::max<uint32_t>(
        10,
        static_cast<uint32_t>((8'000'000ull + z80_hz - 1) / z80_hz));

    bus_sm_ = pio_claim_unused_sm(bus_pio_, true);
    clock_sm_ = pio_claim_unused_sm(clock_pio_, true);
    wait_sm_ = pio_claim_unused_sm(clock_pio_, true);
    debug_sm_ = pio_claim_unused_sm(clock_pio_, true);
    detector_sm_ = pio_claim_unused_sm(bus_pio_, true);
    fifo_access_ = {&bus_pio_->fstat, &bus_pio_->rxf[detector_sm_],
                   &bus_pio_->txf[bus_sm_], 1u << (PIO_FSTAT_RXEMPTY_LSB + detector_sm_)};

    const uint bus_offset = pio_add_program(bus_pio_, &z80_async_bus_program);
    const uint clock_offset = pio_add_program(clock_pio_, &z80_async_clock_program);
    const uint guard_offset = pio_add_program(clock_pio_, &z80_async_guard_program);
    const uint debug_offset = pio_add_program(clock_pio_, &z80_async_debug_program);
    const uint detector_offset = pio_add_program(bus_pio_, &z80_async_detector_program);

    assign_async_bus_pins(bus_pio_, clock_pio_);

    pio_sm_config clock_config = z80_async_clock_program_get_default_config(clock_offset);
    sm_config_set_sideset_pins(&clock_config, pCLK);
    const float clock_divider =
        static_cast<float>(clock_get_hz(clk_sys)) /
        (2.0f * static_cast<float>(z80_hz));
    hard_assert(clock_divider >= 1.0f && clock_divider < 65536.0f);
    sm_config_set_clkdiv(&clock_config, clock_divider);

    pio_sm_config guard_config = z80_async_guard_program_get_default_config(guard_offset);
    sm_config_set_set_pins(&guard_config, pWAIT, 1);
    sm_config_set_clkdiv(&guard_config, 1.0f);
    sm_config_set_in_pins(&guard_config, pIORQ);
    sm_config_set_in_pin_count(&guard_config, 32);
    sm_config_set_out_shift(&guard_config, true, false, 32);
    sm_config_set_mov_status(&guard_config, STATUS_IRQ_SET, kDataReadyIrq);

    pio_sm_config debug_config = z80_async_debug_program_get_default_config(debug_offset);
    sm_config_set_sideset_pins(&debug_config, pPIO_DEBUG);
    sm_config_set_clkdiv(&debug_config, 1.0f);

    pio_sm_config detector_config = z80_async_detector_program_get_default_config(detector_offset);
    sm_config_set_in_pins(&detector_config, pD0);
    sm_config_set_in_pin_count(&detector_config, 32);
    sm_config_set_out_shift(&detector_config, true, false, 32);
    sm_config_set_jmp_pin(&detector_config, pRESET);
    sm_config_set_clkdiv(&detector_config, 1.0f);

    pio_sm_config bus_config = z80_async_bus_program_get_default_config(bus_offset);
    sm_config_set_in_pins(&bus_config, pD0);
    sm_config_set_in_pin_count(&bus_config, 32);
    sm_config_set_out_pins(&bus_config, pD0, 8);
    sm_config_set_out_shift(&bus_config, true, false, 32);
    sm_config_set_clkdiv(&bus_config, 1.0f);

    pio_interrupt_clear(bus_pio_, 4);
    pio_interrupt_clear(bus_pio_, 5);
    pio_interrupt_clear(clock_pio_, kDataReadyIrq);
    pio_interrupt_clear(clock_pio_, kDebugStartIrq);
    pio_interrupt_clear(clock_pio_, kDebugEndIrq);
    pio_sm_init(bus_pio_, detector_sm_, detector_offset, &detector_config);
    pio_sm_init(bus_pio_, bus_sm_, bus_offset, &bus_config);
    pio_sm_init(clock_pio_, clock_sm_, clock_offset, &clock_config);
    pio_sm_init(clock_pio_, wait_sm_, guard_offset, &guard_config);
    pio_sm_init(clock_pio_, debug_sm_, debug_offset, &debug_config);

    pio_sm_set_pins_with_mask(clock_pio_, clock_sm_, 0, 1u << pCLK);
    pio_sm_set_pins_with_mask64(clock_pio_, wait_sm_, 1ull << pWAIT, 1ull << pWAIT);
    pio_sm_set_pins_with_mask64(clock_pio_, debug_sm_, 0, 1ull << pPIO_DEBUG);

    pio_sm_set_consecutive_pindirs(bus_pio_, bus_sm_, pD0, 8, false);
    pio_sm_set_consecutive_pindirs(clock_pio_, clock_sm_, pCLK, 1, true);
    pio_sm_set_consecutive_pindirs(clock_pio_, wait_sm_, pWAIT, 1, true);
    pio_gpio_init(clock_pio_, pWAIT); // High PIO latch/OE before SIO-to-PIO handover.
    pio_sm_set_consecutive_pindirs(clock_pio_, debug_sm_, pPIO_DEBUG, 1, true);

    // Start the high-idle WAIT guard and marker, then the bus clock.
    pio_sm_set_enabled(clock_pio_, wait_sm_, true);
    pio_sm_set_enabled(clock_pio_, debug_sm_, true);
    pio_sm_set_enabled(bus_pio_, bus_sm_, true);
    pio_sm_set_enabled(bus_pio_, detector_sm_, true);
    pio_sm_set_enabled(clock_pio_, clock_sm_, true);
}

void AsyncBusDriver::begin_reset()
{
    gpio_put(pRESET, false);
}

void AsyncBusDriver::end_reset()
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

} // namespace z80pio

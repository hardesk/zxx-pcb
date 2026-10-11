#include "z80_frame_interrupt.hpp"
#include "z80_pins.hpp"

#include <hardware/clocks.h>
#include <hardware/gpio.h>
#include <hardware/pwm.h>
#include <pico/stdlib.h>

void Z80FrameInterrupt::start(uint32_t z80_hz, uint32_t tstates) {
    const uint32_t width_us = pulse_width_us(z80_hz, tstates);
    const uint32_t sys_hz = clock_get_hz(clk_sys);
    hard_assert(z80_hz && tstates && width_us && width_us < period_us);
    hard_assert(sys_hz % 1'000'000 == 0);
    // The integer divider is at most 255: count 1/ticks_per_us steps above 255 MHz.
    const uint32_t sys_mhz = sys_hz / 1'000'000;
    const uint32_t ticks_per_us = (sys_mhz + 254) / 255;
    hard_assert(sys_mhz % ticks_per_us == 0);
    const uint32_t divider = sys_mhz / ticks_per_us;
    const uint32_t width = width_us * ticks_per_us;
    hard_assert(divider >= 1 && divider <= 255 && period_us * ticks_per_us <= 65536);
    stop();

    const uint slice = pwm_gpio_to_slice_num(pINT);
    const uint channel = pwm_gpio_to_channel(pINT);
    auto config = pwm_get_default_config();
    pwm_config_set_clkdiv_int(&config, divider);
    pwm_config_set_wrap(&config, period_us * ticks_per_us - 1);
    // Invert the selected channel: low while counter < pulse width.
    pwm_config_set_output_polarity(&config, channel == PWM_CHAN_A,
                                  channel == PWM_CHAN_B);
    pwm_init(slice, &config, false);
    pwm_set_chan_level(slice, channel, width);
    // Prime the inverted output high while disconnected from the pin. Let one
    // PWM tick elapse to latch the output; wrapping is ~20 ms away.
    pwm_set_counter(slice, width);
    pwm_set_enabled(slice, true);
    busy_wait_us_32(2);
    gpio_set_function(pINT, GPIO_FUNC_PWM);
    m_running = true;
}

void Z80FrameInterrupt::stop() {
    if (!m_running) return;
    // Preload SIO high before changing mux, so stopping cannot assert INT.
    gpio_put(pINT, true);
    gpio_set_dir(pINT, GPIO_OUT);
    gpio_set_function(pINT, GPIO_FUNC_SIO);
    pwm_set_enabled(pwm_gpio_to_slice_num(pINT), false);
    m_running = false;
}

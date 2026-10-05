#pragma once
// Observe the SIO-to-PIO handover while RESET is still held low.
// PIO2 samples GPIO0..31 every four system clocks; no pin ownership changes.
#include <cstdio>
#include <hardware/pio.h>
#include <hardware/dma.h>
#include <pico/stdlib.h>

class InitWaitCapture {
    static constexpr unsigned capacity = 8192;
    uint32_t samples[capacity];
    uint sm;
    int dma;
public:
    void start() {
        pio_set_gpio_base(pio2, 0);
        sm = pio_claim_unused_sm(pio2, true);
        const uint16_t code[] = {static_cast<uint16_t>(pio_encode_in(pio_pins, 32))};
        const pio_program program = {code, 1, -1, 1, 0};
        uint offset = pio_add_program(pio2, &program);
        auto c = pio_get_default_sm_config();
        sm_config_set_wrap(&c, offset, offset);
        sm_config_set_in_pins(&c, 0);
        sm_config_set_in_pin_count(&c, 32);
        sm_config_set_in_shift(&c, true, true, 32);
        sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
        sm_config_set_clkdiv(&c, 4.0f);
        pio_sm_init(pio2, sm, offset, &c);
        dma = dma_claim_unused_channel(true);
        auto dc = dma_channel_get_default_config(dma);
        channel_config_set_read_increment(&dc, false);
        channel_config_set_write_increment(&dc, true);
        channel_config_set_dreq(&dc, pio_get_dreq(pio2, sm, false));
        pio2->fdebug = (1u << sm) << PIO_FDEBUG_RXSTALL_LSB;
        dma_channel_configure(dma, &dc, samples, &pio2->rxf[sm], capacity, true);
        pio_sm_set_enabled(pio2, sm, true);
        busy_wait_us_32(2); // Include stable SIO high before bus.init().
    }
    void finish() {
        busy_wait_us_32(2); // Include stable PIO high after bus.init().
        pio_sm_set_enabled(pio2, sm, false);
        busy_wait_us_32(2);
        unsigned n = capacity - dma_channel_hw_addr(dma)->transfer_count;
        bool stall = pio2->fdebug & ((1u << sm) << PIO_FDEBUG_RXSTALL_LSB);
        dma_channel_abort(dma);
        unsigned low = 0, reset_high = 0, active = 0;
        for (unsigned i = 0; i < n; ++i) {
            low += !(samples[i] & (1u << 26));
            reset_high += !!(samples[i] & (1u << 25));
            active += (samples[i] & 0xf0000000u) != 0xf0000000u;
        }
        printf("init capture samples=%u capacity=%u clocks=4 WAIT_low_samples=%u RESET_high_samples=%u active_strobe_samples=%u stall=%u\n",
               n, capacity, low, reset_high, active, unsigned(stall));
        printf("init capture %s\n", n > 0 && n < capacity && !stall && !low && !reset_high && !active ? "PASS" : "FAIL");
        // Keep the disabled test SM/DMA claimed for this short firmware run.
    }
};

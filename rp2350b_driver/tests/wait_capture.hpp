#pragma once

// Optional on-device logic capture: GPIO0..31 every four clk_sys ticks, PIO2.
// Call start() before a reply and finish() afterwards, while the next request
// is held in WAIT. No CPU polling is involved in the sampled signal timing.
#include <hardware/dma.h>
#include <hardware/pio.h>

class WaitCapture {
    static constexpr unsigned count = 1024;
    uint32_t samples[count];
    uint sm;
    int dma;
public:
    WaitCapture() {
        sm = pio_claim_unused_sm(pio2, true);
        const uint16_t instructions[] = {pio_encode_in(pio_pins, 32)};
        const pio_program program = {instructions, 1, -1, 1, 0};
        const auto offset = pio_add_program(pio2, &program);
        auto config = pio_get_default_sm_config();
        sm_config_set_wrap(&config, offset, offset);
        sm_config_set_in_pins(&config, 0);
        sm_config_set_in_pin_count(&config, 32);
        sm_config_set_in_shift(&config, true, true, 32);
        sm_config_set_fifo_join(&config, PIO_FIFO_JOIN_RX);
        sm_config_set_clkdiv(&config, 4.0f);
        pio_sm_init(pio2, sm, offset, &config);
        dma = dma_claim_unused_channel(true);
        auto d = dma_channel_get_default_config(dma);
        channel_config_set_read_increment(&d, false);
        channel_config_set_write_increment(&d, true);
        channel_config_set_dreq(&d, pio_get_dreq(pio2, sm, false));
        dma_channel_configure(dma, &d, samples, &pio2->rxf[sm], count, false);
    }
    void start() {
        pio_sm_clear_fifos(pio2, sm);
        dma_channel_set_write_addr(dma, samples, false);
        dma_channel_set_trans_count(dma, count, true);
        pio_sm_set_enabled(pio2, sm, true);
    }
    void finish(unsigned request) {
        dma_channel_wait_for_finish_blocking(dma);
        pio_sm_set_enabled(pio2, sm, false);
        printf("capture %u begin\n", request);
        for (unsigned i = 0; i < count; ++i) {
            if (i == 0 || samples[i] != samples[i - 1])
                printf("sample %u %08lx\n", i, (unsigned long)samples[i]);
        }
        printf("capture %u end\n", request);
    }
};

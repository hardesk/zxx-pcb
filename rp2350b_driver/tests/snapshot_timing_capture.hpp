#pragma once
// Diagnostic recorder. Construct after bus.init(), before reset_cpu().
// PIO1's spare SM reads GPIO16..47; PIO2 reads GPIO0..31 in lockstep.
// No pin muxes/directions are changed. Shared GPIO16..31 verify alignment.
#include <cstdio>
#include <hardware/pio.h>
#include <hardware/dma.h>
#include <hardware/clocks.h>
#include <pico/stdlib.h>

class SnapshotTimingCapture {
    static constexpr unsigned count = 8192, transfers = 0x0fffffffu;
    alignas(32768) uint32_t low[count];
    alignas(32768) uint32_t high[count];
    uint low_sm, high_sm;
    int low_dma, high_dma;
    bool finished = false;

    static uint sampler(PIO pio, uint base) {
        uint sm = pio_claim_unused_sm(pio, true);
        const uint16_t code[] = {static_cast<uint16_t>(pio_encode_in(pio_pins, 32))};
        const pio_program program = {code, 1, -1, 1, 0};
        uint offset = pio_add_program(pio, &program);
        auto c = pio_get_default_sm_config();
        sm_config_set_wrap(&c, offset, offset);
        sm_config_set_in_pins(&c, base);
        sm_config_set_in_pin_count(&c, 32);
        sm_config_set_in_shift(&c, true, true, 32);
        sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_RX);
        sm_config_set_clkdiv(&c, 4.0f);
        pio_sm_init(pio, sm, offset, &c);
        return sm;
    }
    static int recorder(PIO pio, uint sm, uint32_t *buffer) {
        int channel = dma_claim_unused_channel(true);
        auto c = dma_channel_get_default_config(channel);
        channel_config_set_read_increment(&c, false);
        channel_config_set_write_increment(&c, true);
        channel_config_set_ring(&c, true, 15);
        channel_config_set_dreq(&c, pio_get_dreq(pio, sm, false));
        dma_channel_configure(channel, &c, buffer, &pio->rxf[sm], transfers, false);
        return channel;
    }
public:
    SnapshotTimingCapture() {
        // The bus already uses PIO1 GPIOBASE=16. Do not reconfigure it here.
        hard_assert(pio_get_gpio_base(pio1) == 16);
        pio_set_gpio_base(pio2, 0);
        high_sm = sampler(pio1, 16);
        low_sm = sampler(pio2, 0);
        high_dma = recorder(pio1, high_sm, high);
        low_dma = recorder(pio2, low_sm, low);
    }
    void start() {
        pio1->fdebug = (1u << high_sm) << PIO_FDEBUG_RXSTALL_LSB;
        pio2->fdebug = (1u << low_sm) << PIO_FDEBUG_RXSTALL_LSB;
        dma_start_channel_mask((1u << low_dma) | (1u << high_dma));
        pio_enable_sm_multi_mask_in_sync(pio1, 0, 1u << high_sm, 1u << low_sm);
    }
    void finish(unsigned request, uint32_t raw) {
        if (finished) return;
        finished = true;
        pio_set_sm_multi_mask_enabled(pio1, 0, 1u << high_sm, 1u << low_sm, false);
        busy_wait_us_32(2); // Drain the now frozen RX FIFOs into their rings.
        const uint32_t nlow = transfers - dma_channel_hw_addr(low_dma)->transfer_count;
        const uint32_t nhigh = transfers - dma_channel_hw_addr(high_dma)->transfer_count;
        const uint32_t low_stall = pio2->fdebug & ((1u << low_sm) << PIO_FDEBUG_RXSTALL_LSB);
        const uint32_t high_stall = pio1->fdebug & ((1u << high_sm) << PIO_FDEBUG_RXSTALL_LSB);
        dma_channel_abort(low_dma);
        dma_channel_abort(high_dma);
        const unsigned n = nlow < nhigh ? nlow : nhigh;
        const unsigned kept = n < count ? n : count;
        unsigned mismatch = 0;
        for (unsigned i=n-kept; i<n; ++i)
            mismatch += (low[i%count] >> 16) != (high[i%count] & 0xffffu);
        printf("timing begin request=%u raw=%08lx hz=%lu clocks=4 first=%u count=%u nlow=%lu nhigh=%lu low_stall=%lu high_stall=%lu overlap_mismatch=%u\n",
            request, (unsigned long)raw, (unsigned long)clock_get_hz(clk_sys), n-kept, kept,
            (unsigned long)nlow, (unsigned long)nhigh, (unsigned long)low_stall,
            (unsigned long)high_stall, mismatch);
        uint32_t prev_low=0, prev_high=0;
        for (unsigned j=0; j<kept; ++j) {
            const unsigned i=(n-kept+j)%count;
            if (!j || j==kept-1 || low[i]!=prev_low || high[i]!=prev_high)
                printf("timing %u %08lx %08lx\n", j, (unsigned long)low[i], (unsigned long)high[i]);
            prev_low=low[i]; prev_high=high[i];
        }
        printf("timing end\n");
    }
};

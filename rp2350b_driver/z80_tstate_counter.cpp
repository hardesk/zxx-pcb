#include "z80_tstate_counter.hpp"
#include "z80_pins.hpp"
#include "z80_tstate_counter.pio.h"

#include <algorithm>
#include <hardware/clocks.h>
#include <hardware/dma.h>
#include <hardware/pio.h>
#include <hardware/sync.h>
#include <pico/stdlib.h>

void Z80TstateCounter::start(uint32_t clock_hz) {
    if (m_sm >= 0) return;
    // An integral number of clocks represents precisely 20 ms. At least
    // sixteen system clocks/CPU clock leave room for sample and reload paths.
    hard_assert(clock_hz && clock_hz % 50 == 0);
    hard_assert(clock_get_hz(clk_sys) >= uint64_t(clock_hz) * 16);
    hard_assert(pio_get_gpio_base(pio2) == 16);
    hard_assert(pio_can_add_program_at_offset(pio2, &z80_tstate_counter_program, 0));
    m_sm = pio_claim_unused_sm(pio2, true);
    pio_add_program_at_offset(pio2, &z80_tstate_counter_program, 0);
    m_rx_dma = dma_claim_unused_channel(true);
    m_tx_dma = dma_claim_unused_channel(true);
    m_reload = clock_hz / 50 - 1;
    m_index = m_available = 0;

    auto c = z80_tstate_counter_program_get_default_config(0);
    sm_config_set_in_pins(&c, pIORQ);
    sm_config_set_in_pin_count(&c, 32);
    sm_config_set_jmp_pin(&c, pWAIT);
    sm_config_set_out_shift(&c, true, false, 32);
    sm_config_set_clkdiv(&c, 1.0f);
    hard_assert(pio_sm_init(pio2, m_sm, z80_tstate_counter_wrap_target, &c) == PICO_OK);
    // Read existing pin inputs only: no mux, pad or pin-direction changes.
    // CLK bypass compensates edge-detection/JMP latency; control inputs keep
    // their synchronizers, matching the calibrated external measurement.
    m_clock_sync_original = pio2->input_sync_bypass & (1u << (pCLK - 16));
    pio_set_input_sync_bypass_with_mask64(pio2, 1ull << pCLK, 1ull << pCLK);
    pio_sm_put_blocking(pio2, m_sm, m_reload);
    pio_sm_exec(pio2, m_sm, pio_encode_pull(false, true));
    pio_sm_exec(pio2, m_sm, pio_encode_mov(pio_x, pio_osr));
    pio_sm_exec(pio2, m_sm, pio_encode_mov_not(pio_y, pio_null));

    auto rx = dma_channel_get_default_config(m_rx_dma);
    channel_config_set_transfer_data_size(&rx, DMA_SIZE_32);
    channel_config_set_read_increment(&rx, false);
    channel_config_set_write_increment(&rx, true);
    channel_config_set_ring(&rx, true, 8);
    channel_config_set_dreq(&rx, pio_get_dreq(pio2, m_sm, false));
    channel_config_set_irq_quiet(&rx, true);
    dma_channel_configure(m_rx_dma, &rx, m_wait_samples, &pio2->rxf[m_sm],
                          dma_encode_endless_transfer_count(), false);
    auto tx = dma_channel_get_default_config(m_tx_dma);
    channel_config_set_transfer_data_size(&tx, DMA_SIZE_32);
    channel_config_set_read_increment(&tx, false);
    channel_config_set_write_increment(&tx, false);
    channel_config_set_dreq(&tx, pio_get_dreq(pio2, m_sm, true));
    channel_config_set_irq_quiet(&tx, true);
    dma_channel_configure(m_tx_dma, &tx, &pio2->txf[m_sm], &m_reload,
                          dma_encode_endless_transfer_count(), false);
    dma_start_channel_mask((1u << m_rx_dma) | (1u << m_tx_dma));
    pio_sm_set_enabled(pio2, m_sm, true);
}

void Z80TstateCounter::poll() {
    if (m_sm < 0) return;
    const unsigned next = (dma_channel_hw_addr(m_rx_dma)->write_addr & 255u) / 4;
    m_available = std::min(sample_count, m_available + ((next - m_index) & (sample_count - 1)));
    m_index = next;
}

bool Z80TstateCounter::average(uint32_t& tstates) const {
    if (m_available < average_windows) return false;
    // DMA completes the write before advancing WRITE_ADDR. Poll's saved index
    // points past completed samples; fourteen ring slots leave 280 ms before
    // these fifty samples could be overwritten (this read takes microseconds).
    __dmb();
    uint64_t waits = 0;
    for (unsigned i = 1; i <= average_windows; ++i)
        waits += m_wait_samples[(m_index - i) & (sample_count - 1)];
    const uint64_t nominal = uint64_t(m_reload + 1) * average_windows - waits;
    tstates = uint32_t((nominal + average_windows / 2) / average_windows);
    return true;
}

void Z80TstateCounter::stop() {
    if (m_sm < 0) return;
    pio_sm_set_enabled(pio2, m_sm, false);
    dma_channel_abort(m_rx_dma);
    dma_channel_abort(m_tx_dma);
    dma_channel_unclaim(m_rx_dma);
    dma_channel_unclaim(m_tx_dma);
    pio_set_input_sync_bypass_with_mask64(pio2,
        uint64_t(m_clock_sync_original) << 16, 1ull << pCLK);
    pio_sm_unclaim(pio2, m_sm);
    pio_remove_program(pio2, &z80_tstate_counter_program, 0);
    m_sm = m_rx_dma = m_tx_dma = -1;
    m_available = 0;
}

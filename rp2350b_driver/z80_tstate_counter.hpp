#pragma once

#include <cstdint>

// Passive GPIO estimate, including nominal refresh/HALT cycles. This does not
// decode the CPU's internal T2 state or count retired instructions.
class Z80TstateCounter {
public:
    static constexpr unsigned sample_count = 64;
    static constexpr unsigned average_windows = 50;
    void start(uint32_t clock_hz); // After LCD and bus PIO initialization.
    void stop();
    ~Z80TstateCounter() { stop(); }
    Z80TstateCounter() = default;
    Z80TstateCounter(const Z80TstateCounter&) = delete;
    Z80TstateCounter& operator=(const Z80TstateCounter&) = delete;
    // Display core only, once per rendered frame. Never call in the bus loop.
    void poll();
    bool average(uint32_t& tstates) const;

private:
    // DMA's 256-byte write ring requires matching address alignment.
    alignas(256) volatile uint32_t m_wait_samples[sample_count]{};
    uint32_t m_reload = 0;
    unsigned m_index = 0, m_available = 0;
    int m_sm = -1, m_rx_dma = -1, m_tx_dma = -1;
    uint32_t m_clock_sync_original = 0;
};

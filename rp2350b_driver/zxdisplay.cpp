#include "zxdisplay.hpp"
#include <initializer_list>
#include <cstdio>

#include <hardware/clocks.h>
#include <hardware/dma.h>
#include <hardware/gpio.h>
#include <hardware/pio.h>
#include <hardware/sync.h>
#include <pico/stdlib.h>

#include "zxdisplay.pio.h"

ZxDisplay::~ZxDisplay() {
    m_tstate_counter.stop();
    if (m_sm >= 0) {
        wait_batch();
        drain();
        pio_sm_set_enabled(pio2, m_sm, false);
        dma_channel_unclaim(m_dma);
        dma_channel_unclaim(m_control_dma);
        pio_sm_unclaim(pio2, m_sm);
        pio_remove_program(pio2, &zxdisplay_program, m_offset);
        pio_remove_program(pio2, &zxdisplay_command_program, m_command_offset);
        gpio_put(pinBLK, false);
    }
}

void ZxDisplay::init() {
    if (m_sm >= 0) return;
#ifdef Z80_WAIT_CAPTURE
    panic("ZxDisplay and Z80_WAIT_CAPTURE require incompatible PIO2 GPIO bases");
#endif
    // GPIO base is shared by all four SMs. Never remap an active PIO2 user.
    for (uint sm = 0; sm < NUM_PIO_STATE_MACHINES; ++sm)
        if (pio_sm_is_claimed(pio2, sm)) panic("ZxDisplay requires unused PIO2");
    hard_assert(pio_set_gpio_base(pio2, 16) == PICO_OK);
    m_sm = pio_claim_unused_sm(pio2, true);
    m_offset = pio_add_program(pio2, &zxdisplay_program);
    m_command_offset = pio_add_program(pio2, &zxdisplay_command_program);

    for (uint pin : {pinRES, pinDC, pinCS, pinBLK}) {
        gpio_init(pin);
        gpio_put(pin, pin != pinBLK); // Reset inactive, data mode, CS inactive.
        gpio_set_dir(pin, GPIO_OUT);
    }
    pio_gpio_init(pio2, pinSCL);
    pio_gpio_init(pio2, pinSDA);
    auto c = zxdisplay_program_get_default_config(m_offset);
    sm_config_set_out_pins(&c, pinSDA, 1);
    sm_config_set_sideset_pins(&c, pinSCL);
    sm_config_set_out_shift(&c, false, false, 32); // MSB first, explicit pull.
    sm_config_set_fifo_join(&c, PIO_FIFO_JOIN_TX);
    // Two system cycles per clock half-period at 150 MHz: 37.5 MHz SCL.
    // Integer divider avoids short pulses from fractional clock division.
    const uint32_t div = (clock_get_hz(clk_sys) + 149999999u) / 150000000u;
    sm_config_set_clkdiv_int_frac(&c, div, 0);
    hard_assert(pio_sm_init(pio2, m_sm, m_offset, &c) == PICO_OK);
    pio_sm_set_pins_with_mask64(pio2, m_sm, 0,
                              (1ull << pinSCL) | (1ull << pinSDA));
    pio_sm_set_consecutive_pindirs(pio2, m_sm, pinSCL, 2, true);

    m_dma = dma_claim_unused_channel(true);
    m_control_dma = dma_claim_unused_channel(true);
    auto d = dma_channel_get_default_config(m_dma);
    channel_config_set_transfer_data_size(&d, DMA_SIZE_16);
    channel_config_set_read_increment(&d, true);
    channel_config_set_write_increment(&d, false);
    channel_config_set_dreq(&d, pio_get_dreq(pio2, m_sm, true));
    channel_config_set_chain_to(&d, m_control_dma);
    channel_config_set_irq_quiet(&d, true);
    m_data_control = channel_config_get_ctrl_value(&d);
    channel_config_set_read_increment(&d, false);
    m_fill_control = channel_config_get_ctrl_value(&d);

    // Each completion loads exactly one four-word descriptor. Wrapping the
    // destination revisits the data channel's AL3 registers, with trigger last.
    static_assert(sizeof(DmaBlock) == 16);
    auto c_dma = dma_channel_get_default_config(m_control_dma);
    channel_config_set_transfer_data_size(&c_dma, DMA_SIZE_32);
    channel_config_set_read_increment(&c_dma, true);
    channel_config_set_write_increment(&c_dma, true);
    channel_config_set_ring(&c_dma, true, 4);
    channel_config_set_irq_quiet(&c_dma, true);
    dma_channel_configure(m_control_dma, &c_dma,
                          &dma_channel_hw_addr(m_dma)->al3_ctrl,
                          nullptr, 4, false);
    pio_sm_set_enabled(pio2, m_sm, true);
}

void ZxDisplay::set_border(uint16_t colour) {
    for (auto& row : m_border) row[0] = row[1] = colour & 0xfff;
}

void ZxDisplay::set_border_line(unsigned row, uint16_t left, uint16_t right) {
    hard_assert(row < frame_height);
    m_border[row][0] = left & 0xfff;
    m_border[row][1] = right & 0xfff;
}

void ZxDisplay::prepare_strip(unsigned slot, const volatile uint8_t* screen,
                              unsigned row, bool flash) {
    // Sample live ULA colour per strip so rapid OUT FE changes can produce
    // loading stripes. This LCD scan is not cycle-accurate to the original ULA.
    if (m_live_ula) {
        const uint16_t colour = zx_rgb444[m_live_ula->border()];
        for (unsigned i = row; i < row + ZxDisplayStrip::lines; ++i)
            m_border[i][0] = m_border[i][1] = colour;
    }
    auto& strip = m_strips[slot];
    strip.prepare(screen, row, m_border, flash);
    for (unsigned i = 0; i < strip.segment_count; ++i) {
        const auto& segment = strip.segments[i];
        auto control = segment.increment ? m_data_control : m_fill_control;
        if (i + 1 == strip.segment_count) {
            // Only the final segment raises the raw completion flag. It does
            // not chain, so DMA cannot consume an unprepared next strip.
            control &= ~(DMA_CH0_CTRL_TRIG_CHAIN_TO_BITS | DMA_CH0_CTRL_TRIG_IRQ_QUIET_BITS);
            control |= static_cast<uint32_t>(m_dma) << DMA_CH0_CTRL_TRIG_CHAIN_TO_LSB;
        }
        m_blocks[slot][i] = {control, reinterpret_cast<uint32_t>(&pio2->txf[m_sm]),
                            segment.count, reinterpret_cast<uint32_t>(segment.source)};
    }
}

void ZxDisplay::start_strip(unsigned slot) {
    hard_assert(!m_batch_active);
    dma_hw->intr = 1u << m_dma;
    __dmb(); // Publish completed pixels/descriptors before starting DMA.
    m_batch_active = true;
    dma_channel_set_read_addr(m_control_dma, m_blocks[slot], false);
    dma_channel_set_trans_count(m_control_dma, 4, true);
}

void ZxDisplay::wait_batch() {
    if (!m_batch_active) return;
    // BUSY alone is insufficient: it drops between chained segments.
    // No NVIC DMA interrupt is enabled; core1 polls the final raw flag.
    while (!(dma_hw->intr & (1u << m_dma))) tight_loop_contents();
    dma_channel_wait_for_finish_blocking(m_control_dma);
    dma_channel_wait_for_finish_blocking(m_dma);
    dma_hw->intr = 1u << m_dma;
    m_batch_active = false;
}

void ZxDisplay::begin_pixels(unsigned x, unsigned y, unsigned w, unsigned h) {
    set_command_mode(true);
    set_window(x, y, w, h);
    command(0x2c, {}, true);
    set_command_mode(false);
}

void ZxDisplay::render(const volatile uint8_t* screen, bool flash, const ZxUla* live_ula) {
    m_live_ula = live_ula;
    hard_assert(m_lcd_ready && screen);
    const uint64_t started = time_us_64();
    if (!m_refresh_epoch_us) m_refresh_epoch_us = started;
    prepare_strip(0, screen, 0, flash);
    // A single RAMWR stream covers the inner frame, leaving the outer label intact.
    begin_pixels((280 - frame_width) / 2, (240 - frame_height) / 2,
                 frame_width, frame_height);
    unsigned slot = 0;
    start_strip(slot);
    for (unsigned row = ZxDisplayStrip::lines; row < frame_height; row += ZxDisplayStrip::lines) {
        const unsigned next = slot ^ 1;
        prepare_strip(next, screen, row, flash); // While previous strip transmits.
        wait_batch(); // The old buffer is now reusable (PIO may still be draining).
        start_strip(next);
        slot = next;
    }
    wait_batch();
    drain(); // Last DMA write is not the final serial clock.
    gpio_put(pinCS, true);
    m_last_frame_us = static_cast<uint32_t>(time_us_64() - started);
    if (m_last_frame_us > m_max_frame_us) m_max_frame_us = m_last_frame_us;
    m_frames = m_frames + 1;
    // Sampling is entirely PIO/DMA. Only core1 polls the ring and formats its
    // latest one-second average; core0's bus service does no measurement work.
    m_tstate_counter.poll();
    const uint64_t elapsed = time_us_64() - m_refresh_epoch_us;
    if (elapsed >= 1000000) {
        uint32_t average;
        if (m_tstate_counter.average(average)) {
            m_average_tstates = average;
            snprintf(m_refresh_text, sizeof(m_refresh_text), "%6lu T",
                     static_cast<unsigned long>(average));
        }
        m_refresh_epoch_us += elapsed;
        update_refresh_label();
    } else if (m_frames == 1) {
        update_refresh_label();
    }
}

void ZxDisplay::update_refresh_label() {
    // The frame has fully drained. Reuse its idle strip storage and DMA channel
    // for a separate window; the next frame restores its own window/descriptors.
    static_assert(ZxRefreshLabel::width * ZxRefreshLabel::height <=
                  ZxDisplayStrip::lines * ZxDisplayStrip::width);
    static_assert(ZxRefreshLabel::y + ZxRefreshLabel::height <= (240 - frame_height) / 2);
    auto* pixels = reinterpret_cast<uint16_t*>(m_strips[0].pixels);
    ZxRefreshLabel::draw(pixels, m_refresh_text);
    begin_pixels(ZxRefreshLabel::x, ZxRefreshLabel::y,
                 ZxRefreshLabel::width, ZxRefreshLabel::height);
    auto control = m_data_control & ~(DMA_CH0_CTRL_TRIG_CHAIN_TO_BITS | DMA_CH0_CTRL_TRIG_IRQ_QUIET_BITS);
    control |= static_cast<uint32_t>(m_dma) << DMA_CH0_CTRL_TRIG_CHAIN_TO_LSB;
    m_blocks[0][0] = {control, reinterpret_cast<uint32_t>(&pio2->txf[m_sm]),
                     ZxRefreshLabel::width * ZxRefreshLabel::height,
                     reinterpret_cast<uint32_t>(pixels)};
    start_strip(0);
    wait_batch();
    drain();
    gpio_put(pinCS, true);
}

void ZxDisplay::drain() {
    while (!pio_sm_is_tx_fifo_empty(pio2, m_sm)) tight_loop_contents();
    const uint32_t stalled = 1u << (PIO_FDEBUG_TXSTALL_LSB + m_sm);
    pio2->fdebug = stalled;
    while (!(pio2->fdebug & stalled)) tight_loop_contents();
}

void ZxDisplay::set_command_mode(bool commands) {
    // Only switch after the previous stream has fully drained.
    drain();
    pio_sm_set_enabled(pio2, m_sm, false);
    pio_sm_restart(pio2, m_sm);
    const uint offset = commands ? m_command_offset : m_offset;
    const uint wrap_start = commands ? zxdisplay_command_wrap_target : zxdisplay_wrap_target;
    const uint wrap_end = commands ? zxdisplay_command_wrap : zxdisplay_wrap;
    pio_sm_set_wrap(pio2, m_sm, offset + wrap_start, offset + wrap_end);
    pio_sm_exec(pio2, m_sm, pio_encode_jmp(offset + wrap_start));
    pio_sm_set_enabled(pio2, m_sm, true);
}

void ZxDisplay::command(uint8_t opcode, std::initializer_list<uint8_t> data,
                        bool keep_selected) {
    gpio_put(pinDC, false);
    gpio_put(pinCS, false);
    pio_sm_put_blocking(pio2, m_sm, opcode);
    drain(); // DC must not change until the eighth clock has finished.
    gpio_put(pinDC, true);
    for (uint8_t byte : data) pio_sm_put_blocking(pio2, m_sm, byte);
    drain();
    if (!keep_selected) gpio_put(pinCS, true);
}

void ZxDisplay::set_window(unsigned x, unsigned y, unsigned w, unsigned h) {
    hard_assert(w && h && x + w <= 280 && y + h <= 240);
    // Landscape swaps axes, moving the native 20-row panel offset to X.
    x += 20;
    const unsigned xe = x + w - 1, ye = y + h - 1;
    command(0x2a, {uint8_t(x >> 8), uint8_t(x), uint8_t(xe >> 8), uint8_t(xe)});
    command(0x2b, {uint8_t(y >> 8), uint8_t(y), uint8_t(ye >> 8), uint8_t(ye)});
}

void ZxDisplay::init_lcd() {
    init();
    wait_batch();
    m_lcd_ready = false;
    gpio_put(pinBLK, false);
    gpio_put(pinCS, true);
    gpio_put(pinRES, false);
    sleep_ms(10);
    gpio_put(pinRES, true);
    sleep_ms(120);
    set_command_mode(true);
    command(0x11); // SLPOUT; hardware reset has restored register defaults.
    sleep_ms(120);
    command(0x28); // DISPOFF while preparing the initial frame.
    command(0x3a, {0x03}); // COLMOD: 12-bit/pixel MCU interface, packed RGB444.
    command(0x36, {0x60}); // MADCTL: MX|MV, RGB order, landscape.
    command(0x21); // INVON: the module uses an IPS panel.
    command(0x13); // NORON: normal display, no partial/scroll mode.
    sleep_ms(10);
    // Clear the entire visible panel once; later frames update only 272x208.
    begin_pixels(0, 0, 280, 240);
    auto clear_config = dma_channel_get_default_config(m_dma);
    channel_config_set_transfer_data_size(&clear_config, DMA_SIZE_16);
    channel_config_set_read_increment(&clear_config, false);
    channel_config_set_write_increment(&clear_config, false);
    channel_config_set_dreq(&clear_config, pio_get_dreq(pio2, m_sm, true));
    dma_hw->intr = 1u << m_dma;
    m_batch_active = true;
    dma_channel_configure(m_dma, &clear_config, &pio2->txf[m_sm], &m_black,
                          280 * 240, true);
    wait_batch();
    drain();
    gpio_put(pinCS, true);
    m_lcd_ready = true;
    set_command_mode(true);
    command(0x29); // DISPON
    sleep_ms(20);
    gpio_put(pinBLK, true);
}

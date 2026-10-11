#pragma once

#include <cstdint>
#include <initializer_list>
#include "zxdisplay_stream.hpp"
#include "zx_ula.hpp"
#include "z80_tstate_counter.hpp"

struct ZxDisplay {
    static constexpr unsigned width = ZxDisplayStrip::width;
    static constexpr unsigned height = ZxDisplayStrip::height;
    static constexpr unsigned border = ZxDisplayStrip::border;
    static constexpr unsigned frame_width = ZxDisplayStrip::frame_width;
    static constexpr unsigned frame_height = ZxDisplayStrip::frame_height;
    enum { pinSCL = 40, pinSDA = 41, pinRES = 42,
           pinDC = 43, pinCS = 44, pinBLK = 45 };

    ZxDisplay() = default;
    ~ZxDisplay();
    ZxDisplay(const ZxDisplay&) = delete;
    ZxDisplay& operator=(const ZxDisplay&) = delete;
    void init();
    // Initializes landscape RGB444, clears the whole LCD black, enables BLK.
    void init_lcd();
    void start_tstate_counter(uint32_t clock_hz) { m_tstate_counter.start(clock_hz); }
    // Core1 owns this object after initialization. Blocking for a frame, but
    // CPU conversion and DMA transmission overlap using two eight-line strips.
    void render(const volatile uint8_t* screen, bool flash_phase = false,
                const ZxUla* live_ula = nullptr);
    // Call on the display-owning core between frames; no CPU-port interception.
    void set_border(uint16_t rgb444);
    // Rows 0..207 include top/bottom border. Top/bottom rows use left only.
    void set_border_line(unsigned row, uint16_t left, uint16_t right);

private:
    // RP2350 AL3 register order: CTRL, WRITE_ADDR, TRANS_COUNT, READ_ADDR_TRIG.
    struct DmaBlock {
        uint32_t control, destination, count, source;
    };
    ZxDisplayStrip m_strips[2]{};
    DmaBlock m_blocks[2][ZxDisplayStrip::max_segments]{};
    uint16_t m_border[frame_height][2]{};
    uint16_t m_black = 0;
    const ZxUla* m_live_ula = nullptr;
    // Debugger-readable measurements, written only by the display owner.
    volatile uint32_t m_last_frame_us = 0, m_max_frame_us = 0, m_frames = 0;
    uint64_t m_refresh_epoch_us = 0;
    volatile uint32_t m_average_tstates = 0;
    char m_refresh_text[9] = "------ T";
    Z80TstateCounter m_tstate_counter;
    int m_sm = -1, m_dma = -1, m_control_dma = -1;
    unsigned m_offset = 0, m_command_offset = 0;
    bool m_lcd_ready = false, m_batch_active = false;
    uint32_t m_data_control = 0, m_fill_control = 0;

    void prepare_strip(unsigned slot, const volatile uint8_t* screen,
                       unsigned row, bool flash);
    void update_refresh_label();
    void start_strip(unsigned slot);
    void wait_batch();
    void set_command_mode(bool commands);
    void drain();
    void command(uint8_t opcode, std::initializer_list<uint8_t> data = {},
                 bool keep_selected = false);
    // Coordinates relative to visible 280x240 landscape panel.
    void set_window(unsigned x, unsigned y, unsigned w, unsigned h);
    void begin_pixels(unsigned x, unsigned y, unsigned w, unsigned h);
};

#pragma once
#include <cstdint>

static constexpr uint16_t zx_rgb444[16] = {
    // normal
    0x000, // black
    0x00C, // blue
    0xC00, // red
    0xC0C, // magenta
    0x0C0, // green
    0x0CC, // cyan
    0xCC0, // yellow
    0xCCC, // white

    // bright
    0x000, // black
    0x00F, // blue
    0xF00, // red
    0xF0F, // magenta
    0x0F0, // green
    0x0FF, // cyan
    0xFF0, // yellow
    0xFFF, // white
};

// An eight-line staging buffer. Segments describe reads, not copied borders.
struct ZxDisplayStrip {
    static constexpr unsigned width = 256, height = 192, border = 8;
    static constexpr unsigned frame_width = width + 2 * border;
    static constexpr unsigned frame_height = height + 2 * border;
    static constexpr unsigned lines = 8, max_segments = 3 * lines;
    static_assert(frame_height % lines == 0);
    struct Segment {
        const uint16_t* source;
        unsigned count;
        bool increment;
    };
    uint16_t pixels[lines][width];
    uint16_t colours[lines][2];
    Segment segments[max_segments];
    unsigned segment_count = 0;

    // first_row is in the 272x208 output window, including the thin border.
    // All source reads are directly from the live Spectrum screen RAM.
    void prepare(const volatile uint8_t* screen, unsigned first_row,
                 const uint16_t (&border_colours)[frame_height][2], bool flash) {
        segment_count = 0;
        for (unsigned line = 0; line < lines; ++line) {
            const unsigned row = first_row + line;
            colours[line][0] = border_colours[row][0] & 0xfff;
            colours[line][1] = border_colours[row][1] & 0xfff;
            if (row < border || row >= border + height) {
                append(&colours[line][0], frame_width, false);
                continue;
            }
            const unsigned y = row - border;
            const volatile uint8_t* bitmap = screen + ((y & 7) << 8)
                + ((y & 0x38) << 2) + ((y & 0xc0) << 5);
            const volatile uint8_t* attributes = screen + 6144 + (y >> 3) * 32;
            uint16_t* out = pixels[line];
            for (unsigned x = 0; x < 32; ++x) {
                const uint8_t attr = attributes[x];
                uint8_t bits = bitmap[x];
                const unsigned bright = (attr & 64) >> 3;
                const uint16_t ink = zx_rgb444[(attr & 7) | bright];
                const uint16_t paper = zx_rgb444[((attr >> 3) & 7) | bright];
                if ((attr & 128) && flash) bits ^= 0xff;
                for (unsigned bit = 0; bit < 8; ++bit) {
                    *out++ = bits & 128 ? ink : paper;
                    bits <<= 1;
                }
            }
            append(&colours[line][0], border, false);
            append(pixels[line], width, true);
            append(&colours[line][1], border, false);
        }
    }
private:
    void append(const uint16_t* source, unsigned count, bool increment) {
        segments[segment_count++] = {source, count, increment};
    }
};

// Separate LCD window in the 16-pixel outer top margin, outside the frame.
struct ZxRefreshLabel {
    static constexpr unsigned x = 24;
    static constexpr unsigned y = 1, width = 72, height = 14;
    static void draw(uint16_t* pixels, const char* text) {
        for (unsigned i = 0; i < width * height; ++i) pixels[i] = 0;
        for (unsigned c = 0; c < 8 && text[c]; ++c) {
            for (unsigned row = 0; row < 5; ++row) {
                const unsigned bits = glyph(text[c]) >> ((4 - row) * 3);
                for (unsigned col = 0; col < 3; ++col) {
                    if (!(bits & (4u >> col))) continue;
                    for (unsigned dy = 0; dy < 2; ++dy)
                        for (unsigned dx = 0; dx < 2; ++dx)
                            pixels[(2 + row * 2 + dy) * width + 2 + c * 8 + col * 2 + dx] = 0xfff;
                }
            }
        }
    }
private:
    // Five rows of three bits, most significant row first.
    static constexpr unsigned glyph(char c) {
        constexpr unsigned digits[] = {
            0b111101101101111, 0b010110010010111,
            0b111001111100111, 0b111001111001111,
            0b101101111001001, 0b111100111001111,
            0b111100111101111, 0b111001010010010,
            0b111101111101111, 0b111101111001111
        };
        if (c >= '0' && c <= '9') return digits[c - '0'];
        if (c == '.') return 0b000000000000010;
        if (c == '-') return 0b000000111000000;
        if (c == 'T') return 0b111010010010010;
        return 0;
    }
};

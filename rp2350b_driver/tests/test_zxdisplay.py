#!/usr/bin/env python3
"""Host conversion checks and execution of assembled PIO words (not electrical tests).

Build firmware first, then run: python3 tests/test_zxdisplay.py [build-directory]
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
build = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'derived/drv_dbg'
header = (build / 'zxdisplay.pio.h').read_text()
body = header.split('zxdisplay_program_instructions[] = {')[1].split('};')[0]
code = [int(x, 16) for x in re.findall(r'0x([0-9a-f]+),', body)]
# Every RGB444 value, including dirty high nibbles to verify they are discarded.
pixels = [0xa000 | i for i in range(4096)] * 12
def simulate(code, pixels, replicate):
    pc = osr = x = data = clock = consumed = ticks = 0
    bits = []
    while True:
        word = code[pc]
        side = (word >> 12) & 1
        if side and not clock:
            bits.append(data)
        clock = side
        op, arg, value = word >> 13, (word >> 5) & 7, word & 31
        ticks += 1 + ((word >> 8) & 15)
        next_pc = (pc + 1) % len(code)
        if op == 4:  # pull block
            assert word & 0xff == 0xa0
            if consumed == len(pixels):
                break
            p = pixels[consumed]
            osr = (p | (p << 16)) if replicate else p  # RP2350 narrow peripheral writes replicate.
            consumed += 1
        elif op == 3:  # out
            count = value or 32
            shifted = osr >> (32 - count)
            osr = (osr << count) & 0xffffffff
            if arg == 0:
                assert count == 1
                data = shifted
            else:
                assert arg == 3  # null
        elif op == 7:
            assert arg == 1
            x = value
        elif op == 0:
            assert arg == 2  # x--
            if x:
                next_pc = value
            x = (x - 1) & 0xffffffff
        else:
            raise AssertionError(hex(word))
        pc = next_pc
    assert clock == 0 and pc == 0
    return "".join(map(str, bits)), ticks - 1

stream, cycles = simulate(code, pixels, True)
expected = ''.join(f'{p & 0xfff:012b}' for p in pixels)
assert stream == expected
assert len(stream) == 256 * 192 * 12
assert cycles == 51 * len(pixels)
assert int(stream[:24], 2).to_bytes(3, 'big') == bytes([0, 0, 1])
# Commands must clock eight bits, including zero and high-bit opcodes/parameters.
body = header.split('zxdisplay_command_program_instructions[] = {')[1].split('};')[0]
command_code = [int(x, 16) for x in re.findall(r'0x([0-9a-f]+),', body)]
stream, cycles = simulate(command_code, list(range(256)), False)
assert stream == ''.join(f'{byte:08b}' for byte in range(256))
assert cycles == 35 * 256

# Exercise production strip conversion and segment planning on the host.
source = r'''
#include "zxdisplay_stream.hpp"
#include <cassert>
#include <array>
#include <vector>
int main() {
    std::array<uint8_t, 6912> screen{};
    ZxDisplayStrip strips[2];
    uint16_t borders[208][2];
    for (unsigned y = 0; y < 208; ++y) {
        borders[y][0] = (y * 17) & 0xfff;
        borders[y][1] = (y * 31) & 0xfff;
    }
    for (unsigned i = 0; i < screen.size(); ++i)
        screen[i] = (i * 37 + i / 17) & 255;
    for (bool flash : {false, true}) {
        std::vector<uint16_t> expected_image(256 * 192);
        for (unsigned address = 0; address < 6144; ++address) {
            unsigned y = ((address >> 8) & 7) + ((address >> 5) & 7) * 8
                       + (address >> 11) * 64;
            unsigned col = address & 31;
            auto attr = screen[6144 + (y / 8) * 32 + col];
            for (unsigned bit = 0; bit < 8; ++bit) {
                bool ink = (screen[address] & (128 >> bit)) != 0;
                if (flash && (attr & 128)) ink = !ink;
                unsigned color = ink ? attr & 7 : (attr >> 3) & 7;
                unsigned intensity = (attr & 64) ? 15 : 12;
                expected_image[y * 256 + col * 8 + bit] =
                    ((color & 2) ? intensity << 8 : 0)
                    | ((color & 4) ? intensity << 4 : 0)
                    | ((color & 1) ? intensity : 0);
            }
        }
        std::vector<uint16_t> actual;
        unsigned segments = 0;
        strips[0].prepare(screen.data(), 0, borders, flash);
        for (unsigned row = 0; row < 208; row += 8) {
            unsigned slot = (row / 8) & 1;
            // Preparing the other buffer must not corrupt the in-flight strip.
            if (row + 8 < 208)
                strips[slot ^ 1].prepare(screen.data(), row + 8, borders, flash);
            auto& strip = strips[slot];
            unsigned pixels = 0;
            for (unsigned i = 0; i < strip.segment_count; ++i) {
                auto& seg = strip.segments[i];
                assert(seg.count % 2 == 0); // RGB444 byte-aligned boundaries.
                for (unsigned j = 0; j < seg.count; ++j)
                    actual.push_back(seg.source[seg.increment ? j : 0]);
                pixels += seg.count;
                ++segments;
            }
            assert(pixels == 8 * 272);
        }
        assert(segments == 592);
        assert(actual.size() == 272 * 208);
        for (unsigned y = 0; y < 208; ++y) {
            for (unsigned x = 0; x < 272; ++x) {
                uint16_t expected;
                if (y < 8 || y >= 200 || x < 8) expected = borders[y][0];
                else if (x >= 264) expected = borders[y][1];
                else expected = expected_image[(y - 8) * 256 + x - 8];
                assert(actual[y * 272 + x] == expected);
            }
        }
    }

    // Label window is entirely above the DMA frame and uses doubled pixels.
    static_assert(ZxRefreshLabel::y + ZxRefreshLabel::height <= 16);
    std::array<uint16_t, ZxRefreshLabel::width * ZxRefreshLabel::height + 2> label{};
    label.front() = label.back() = 0x1234;
    ZxRefreshLabel::draw(label.data() + 1, " 67022 T");
    assert(label.front() == 0x1234 && label.back() == 0x1234);
    auto pixel = [&](unsigned x, unsigned y) { return label[1 + y * ZxRefreshLabel::width + x]; };
    assert(pixel(2,2) == 0); // Leading space for a five-digit measurement.
    assert(pixel(10,2) == 0xfff && pixel(15,3) == 0xfff); // Six.
    assert(pixel(10,4) == 0xfff && pixel(14,4) == 0);
    assert(pixel(58,2) == 0xfff && pixel(62,2) == 0xfff); // Last character T.
    assert(pixel(58,4) == 0 && pixel(60,4) == 0xfff);
    ZxRefreshLabel::draw(label.data() + 1, "        ");
    for (unsigned i = 1; i + 1 < label.size(); ++i) assert(label[i] == 0);

}
'''
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 'convert.cpp'
    exe = Path(tmp) / 'convert'
    src.write_text(source)
    subprocess.run(['c++', '-std=c++20', '-fsanitize=address,undefined',
                    '-I', str(root), str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: full-frame RGB444 and 8-bit command streams, idle clock, cycle counts; ping-pong strips, border segmentation, BRIGHT/FLASH with sanitizers')

#!/usr/bin/env python3
"""TR-DOS disk support: image store, WD1793/Beta 128 emulation, SCL conversion.

1. C++ unit checks of ZxDiskStore (upload, CRC, persistence, write-back cache,
   growth, eject) and ZxBetaDisk (seek, read/write, sides, RNF, protection,
   Read Address, Force Interrupt, index pulses, Write Track) with sanitizers.
2. End to end: the real 48 ROM and TR-DOS 5.03 on z80emu (Z80EMU, default
   ~/Projects/speccy/z80emu; skipped if absent). BASIC runs
   RANDOMIZE USR 15616, TR-DOS runs a "boot" from an SCL converted by
   zx_media.py, and boot SAVEs a file through a REM command.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zlib

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zx_media', root/'tools/zx_media.py')
media = importlib.util.module_from_spec(spec); spec.loader.exec_module(media)
CXX = os.environ.get('CXX', 'c++')

UNIT = r'''
#include "zx_disk.hpp"
#include <cassert>
#include <cstdio>
#include <vector>
struct RamBackend : ZxDiskBackend {
    std::vector<uint8_t> flash = std::vector<uint8_t>(ZxDiskStore::drives*ZxDiskStore::slot_blocks*block_size, 0xff);
    unsigned programs = 0;
    const uint8_t* block(unsigned d, unsigned i) const override { return flash.data() + (d*ZxDiskStore::slot_blocks+i)*block_size; }
    bool program(unsigned d, unsigned i, const uint8_t* data) override {
        assert(d < ZxDiskStore::drives && i < ZxDiskStore::slot_blocks);
        memcpy(flash.data() + (d*ZxDiskStore::slot_blocks+i)*block_size, data, block_size); ++programs; return true;
    }
};
static std::vector<uint8_t> image(uint32_t size) {
    std::vector<uint8_t> v(size);
    for (uint32_t i = 0; i < size; ++i) v[i] = uint8_t(i * 7 + (i >> 8) * 13 + 1);
    return v;
}
static bool upload(ZxDiskStore& s, unsigned d, const std::vector<uint8_t>& v, bool wp=false, uint32_t crc_xor=0) {
    if (!s.begin(d, v.size(), tape_crc(v.data(), v.size()) ^ crc_xor, wp, "game \"x\".trd", 12)) return false;
    for (uint32_t o = 0; o < v.size(); o += 512)
        if (!s.chunk(o, v.data()+o, std::min<uint32_t>(512, v.size()-o))) return false;
    return s.commit();
}
// Port helpers: 1F command/status, 3F track, 5F sector, 7F data, FF system.
struct Fdc {
    ZxBetaDisk& b; uint32_t now = 10000; // Outside the index pulse.
    uint8_t in(uint8_t p) { return b.read(p, now); }
    void out(uint8_t p, uint8_t v) { b.write(p, v, now); }
    void select(unsigned drive, unsigned side) { out(0xff, uint8_t(0x0c | drive | (side ? 0 : 0x10))); }
    void seek(uint8_t cyl) { out(0x7f, cyl); out(0x1f, 0x18); assert(in(0xff) & 0x80); in(0x1f); }
    bool read(uint8_t track, uint8_t sector, uint8_t* out256) {
        out(0x3f, track); out(0x5f, sector); out(0x1f, 0x80);
        if (!(in(0xff) & 0x40)) return false;
        for (unsigned i = 0; i < 256; ++i) { assert(in(0xff) & 0x40); out256[i] = in(0x7f); }
        assert((in(0xff) & 0xc0) == 0x80);
        return (in(0x1f) & 0x1d) == 0;
    }
    uint8_t write(uint8_t track, uint8_t sector, const uint8_t* data) {
        out(0x3f, track); out(0x5f, sector); out(0x1f, 0xa0);
        if (in(0xff) & 0x40) for (unsigned i = 0; i < 256; ++i) out(0x7f, data[i]);
        assert(in(0xff) & 0x80);
        return in(0x1f);
    }
};
int main() {
    RamBackend flash;
    ZxDiskStore store(flash);
    store.load();
    for (unsigned d = 0; d < 4; ++d) assert(!store.present(d));
    const uint8_t name[] = "x";
    assert(!store.begin(0, 0, 0, false, (const char*)name, 1));
    assert(!store.begin(0, 300, 0, false, (const char*)name, 1));
    assert(!store.begin(0, ZxDiskStore::max_image + 256, 0, false, (const char*)name, 1));
    assert(!store.begin(4, 256, 0, false, (const char*)name, 1));

    const auto img = image(0x5100); // 20.25 KiB: last block is partial.
    assert(!upload(store, 0, img, false, 1) && !store.present(0)); // CRC mismatch
    assert(upload(store, 0, img) && store.present(0) && store.info(0).size == img.size());
    assert(std::string(store.info(0).name) == "game _x_.trd"); // JSON-safe
    uint8_t s[256];
    store.read_sector(0, 0x5000, s); assert(!memcmp(s, img.data()+0x5000, 256));
    store.read_sector(0, 0x5100, s); for (uint8_t b : s) assert(b == 0);   // Past the end
    store.read_sector(0, 0x9f000, s); for (uint8_t b : s) assert(b == 0);
    // Remounting identical data programs only the two header writes.
    const unsigned before = flash.programs;
    assert(upload(store, 0, img) && flash.programs - before == 2);
    { ZxDiskStore again(flash); again.load(); assert(again.present(0) && again.info(0).size == img.size()); }

    // Out-of-order and oversize chunks are rejected and abort nothing else.
    assert(store.begin(1, 512, 0, false, (const char*)name, 1));
    assert(!store.chunk(256, img.data(), 256) && !store.chunk(0, img.data(), 513));
    store.abort_upload(); assert(!store.present(1) && !store.uploading());

    ZxBetaDisk beta(store); beta.reset();
    Fdc fdc{beta};
    assert(ZxBetaDisk::decodes(0x1f) && ZxBetaDisk::decodes(0x7f) && ZxBetaDisk::decodes(0x00ff));
    assert(!ZxBetaDisk::decodes(0xfe) && !ZxBetaDisk::decodes(0x7ffd) && !ZxBetaDisk::decodes(0xfffd));
    fdc.select(0, 0);
    fdc.out(0x1f, 0x08); // Restore
    assert(fdc.in(0xff) & 0x80);
    uint8_t st = fdc.in(0x1f); assert(st & 0x04 && !(st & 0x80) && !(fdc.in(0xff) & 0x80));
    fdc.now = 1000; assert(fdc.in(0x1f) & 0x02); fdc.now = 10000; assert(!(fdc.in(0x1f) & 0x02));
    // Cylinder 0 side 0 sector 9 is the 9th sector of the image.
    assert(fdc.read(0, 9, s) && !memcmp(s, img.data()+8*256, 256));
    fdc.seek(1);
    assert(beta.cylinder(0) == 1 && !(fdc.in(0x1f) & 0x04));
    assert(fdc.read(1, 3, s) && !memcmp(s, img.data()+((1*2+0)*16+2)*256, 256));
    fdc.select(0, 1);
    assert(fdc.read(1, 16, s) && !memcmp(s, img.data()+((1*2+1)*16+15)*256, 256));
    assert(!fdc.read(1, 17, s) && (fdc.in(0x1f) & 0x10));   // No sector 17
    assert(!fdc.read(5, 1, s) && (fdc.in(0x1f) & 0x10));    // Track register mismatch
    // Seek with verify to a track the image lacks reports a seek error.
    fdc.out(0x3f, 1); fdc.out(0x7f, 82); fdc.out(0x1f, 0x1c); assert(fdc.in(0x1f) & 0x10); fdc.seek(1);
    // Step-in/step-out with track update.
    fdc.out(0x1f, 0x58); assert(beta.cylinder(0) == 2 && fdc.in(0x3f) == 2);
    fdc.out(0x1f, 0x78); assert(beta.cylinder(0) == 1 && fdc.in(0x3f) == 1);
    fdc.out(0x1f, 0x38); assert(beta.cylinder(0) == 0 && fdc.in(0x3f) == 0); // Step repeats out
    fdc.seek(1);

    // Read Address: six ID bytes; the WD copies the track into the sector register.
    fdc.out(0x5f, 9); fdc.out(0x1f, 0xc0);
    uint8_t id[6]; for (auto& b : id) { assert(fdc.in(0xff) & 0x40); b = fdc.in(0x7f); }
    assert(id[0] == 1 && id[1] == 1 && id[2] >= 1 && id[2] <= 16 && id[3] == 1 && fdc.in(0x5f) == 1);
    assert(fdc.in(0xff) & 0x80);

    // Write, read back through the cache, then flush to flash.
    uint8_t w[256]; for (unsigned i = 0; i < 256; ++i) w[i] = uint8_t(0xa5 ^ i);
    assert((fdc.write(1, 4, w) & 0x5d) == 0 && store.dirty());
    assert(fdc.read(1, 4, s) && !memcmp(s, w, 256));
    const uint32_t off = ((1*2+1)*16+3)*256;
    assert(memcmp(flash.block(0, 1 + off/4096) + off%4096, w, 256) != 0);
    assert(store.flush() && !store.dirty());
    assert(!memcmp(flash.block(0, 1 + off/4096) + off%4096, w, 256));
    // Multi-sector read crosses into the next sector and ends with RNF.
    fdc.out(0x3f, 1); fdc.out(0x5f, 15); fdc.out(0x1f, 0x90);
    for (unsigned i = 0; i < 512; ++i) { assert(fdc.in(0xff) & 0x40); fdc.in(0x7f); }
    assert((fdc.in(0xff) & 0xc0) == 0x80 && (fdc.in(0x1f) & 0x10) && fdc.in(0x5f) == 17);

    // A write past the uploaded size grows the image to the end of its block.
    fdc.select(0, 0); fdc.seek(40);
    assert((fdc.write(40, 1, w) & 0x5d) == 0 && store.flush());
    const uint32_t grown = (40*2*16*256 / 4096 + 1) * 4096;
    assert(store.info(0).size == grown && store.info(0).crc == 0);
    { ZxDiskStore again(flash); again.load(); assert(again.info(0).size == grown);
      again.read_sector(0, 40*2*16*256, s); assert(!memcmp(s, w, 256)); }
    fdc.seek(1);

    // Force interrupt: D0 stops quietly, D8 interrupts at once.
    fdc.out(0x3f, 1); fdc.out(0x5f, 1); fdc.out(0x1f, 0x80); assert(fdc.in(0xff) & 0x40);
    fdc.out(0x1f, 0xd0); assert(!(fdc.in(0xff) & 0xc0) && !(fdc.in(0x1f) & 0x01));
    fdc.out(0x1f, 0xd8); assert(fdc.in(0xff) & 0x80);
    fdc.in(0x1f);

    // Drive B is empty: not ready, no index; drive B gets a read-only image.
    fdc.select(1, 0);
    fdc.out(0x1f, 0x08); st = fdc.in(0x1f); assert(st & 0x80);
    fdc.now = 1000; assert(!(fdc.in(0x1f) & 0x02)); fdc.now = 10000;
    assert(!fdc.read(0, 1, s) && (fdc.in(0x1f) & 0x80));
    assert(upload(store, 1, img, true));
    fdc.out(0x1f, 0x08); fdc.in(0x1f);
    assert(fdc.read(0, 1, s) && fdc.write(0, 1, w) == 0x40 && !store.dirty());
    fdc.out(0x1f, 0x08); assert(fdc.in(0x1f) & 0x40);

    // A Write Track with no data ends at the next index pulse: Lost Data.
    fdc.select(0, 0); fdc.out(0x1f, 0xfc); assert(fdc.in(0xff) & 0x40);
    fdc.now = 150000; assert(fdc.in(0xff) & 0x40);
    fdc.now = 210000; assert((fdc.in(0xff) & 0xc0) == 0x80 && (fdc.in(0x1f) & 0x05) == 0x04);
    fdc.now = 10000;

    // Write Track (format) cylinder 2 side 0 of drive A with E5 fill.
    // The WD's track register is shared: restore after changing drives.
    fdc.select(0, 0); fdc.out(0x1f, 0x08); fdc.in(0x1f); fdc.seek(2);
    fdc.out(0x1f, 0xf0);
    unsigned written = 0;
    auto put = [&](uint8_t v, unsigned n = 1) { while (n--) if (fdc.in(0xff) & 0x40) { fdc.out(0x7f, v); ++written; } };
    put(0x4e, 80); put(0, 12); put(0xf6, 3); put(0xfc); put(0x4e, 50);
    for (unsigned sec = 1; sec <= 16; ++sec) {
        put(0, 12); put(0xf5, 3); put(0xfe); put(2); put(0); put(uint8_t(sec)); put(1); put(0xf7);
        put(0x4e, 22); put(0, 12); put(0xf5, 3); put(0xfb); put(0xe5, 256); put(0xf7); put(0x4e, 54);
    }
    put(0x4e, 2000);
    assert(written == 6250 && (fdc.in(0xff) & 0x80) && !(fdc.in(0x1f) & 0x01));
    for (unsigned sec = 1; sec <= 16; ++sec) {
        assert(fdc.read(2, uint8_t(sec), s));
        for (uint8_t b : s) assert(b == 0xe5);
    }
    // Side 1 of cylinder 2 is untouched.
    fdc.select(0, 1); assert(fdc.read(2, 1, s) && !memcmp(s, img.data()+((2*2+1)*16)*256, 256));

    // System register reset aborts a transfer.
    fdc.out(0x3f, 2); fdc.out(0x5f, 1); fdc.out(0x1f, 0x80); assert(fdc.in(0xff) & 0x40);
    fdc.out(0xff, 0x08); assert(!(fdc.in(0xff) & 0xc0)); fdc.select(0, 0);

    // Eject flushes pending writes and clears the header.
    assert((fdc.write(2, 2, w) & 0x5d) == 0 && store.dirty());
    assert(store.eject(0) && !store.present(0) && !store.dirty());
    { ZxDiskStore again(flash); again.load(); assert(!again.present(0) && again.present(1)); }
    assert(store.eject(0)); // Already empty
    printf("unit ok: %u flash programs\n", flash.programs);
}
'''


def basic_line(number, tokens):
    body = tokens + b'\r'
    return number.to_bytes(2, 'big') + len(body).to_bytes(2, 'little') + body


def num(text):
    """ASCII digits plus the hidden 5-byte small-integer form."""
    value = int(text)
    return text.encode() + b'\x0e\x00\x00' + value.to_bytes(2, 'little') + b'\x00'


def make_scl():
    # 10 POKE 32768,42: RANDOMIZE USR 15619: REM :SAVE "out" CODE 32768,300 (no space
    # after the colon: REM text is raw, and TR-DOS wants the token there)
    program = basic_line(10, b'\xf4' + num('32768') + b',' + num('42') + b':\xf9\xc0' + num('15619') +
                         b':\xea:\xf8"out"\xaf32768,300')
    data = program + b'\x80\xaa' + (10).to_bytes(2, 'little')
    sectors = -(-len(data) // 256)
    entry = b'boot    B' + len(program).to_bytes(2, 'little') + len(program).to_bytes(2, 'little') + bytes([sectors])
    body = b'SINCLAIR' + bytes([1]) + entry + data.ljust(sectors * 256, b'\0')
    return body + (sum(body) & 0xffffffff).to_bytes(4, 'little')


ROM_TEST = r'''
#include "zx_disk.hpp"
extern "C" {
#include "z80emu.h"
}
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
struct RamBackend : ZxDiskBackend {
    std::vector<uint8_t> flash = std::vector<uint8_t>(ZxDiskStore::drives*ZxDiskStore::slot_blocks*block_size, 0xff);
    const uint8_t* block(unsigned d, unsigned i) const override { return flash.data() + (d*ZxDiskStore::slot_blocks+i)*block_size; }
    bool program(unsigned d, unsigned i, const uint8_t* data) override {
        memcpy(flash.data() + (d*ZxDiskStore::slot_blocks+i)*block_size, data, block_size); return true;
    }
};
static std::vector<uint8_t> file(const char* path) {
    std::ifstream f(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(f), {}};
}
struct Machine {
    std::vector<uint8_t> rom48, trdos, ram = std::vector<uint8_t>(0xc000);
    bool dos = false; unsigned dos_entries = 0;
    ZxBetaDisk* beta = nullptr;
    uint64_t t = 0;
    uint8_t rows[8] = {0x1f,0x1f,0x1f,0x1f,0x1f,0x1f,0x1f,0x1f};
};
extern "C" {
uint8_t m_read(void* c, uint16_t a) {
    auto* m = static_cast<Machine*>(c);
    return a < 0x4000 ? (m->dos ? m->trdos : m->rom48)[a] : m->ram[a - 0x4000];
}
// Opcode fetches drive the Beta 128 paging, as in Rp2350ZxEnv::beta_fetch.
uint8_t m_fetch(void* c, uint16_t a) {
    auto* m = static_cast<Machine*>(c);
    if (!m->dos && (a & 0xff00) == 0x3d00) { m->dos = true; ++m->dos_entries; }
    else if (m->dos && a >= 0x4000) m->dos = false;
    return m_read(c, a);
}
void m_write(void* c, uint16_t a, uint8_t v) {
    auto* m = static_cast<Machine*>(c);
    if (a >= 0x4000) m->ram[a - 0x4000] = v;
}
uint8_t m_in(void* c, uint16_t p) {
    auto* m = static_cast<Machine*>(c);
    if (m->dos && ZxBetaDisk::decodes(p)) return m->beta->read(p, uint32_t(m->t * 2 / 7));
    if (p & 1) return 0xff;
    uint8_t v = 0x1f;
    for (unsigned r = 0; r < 8; ++r) if (!(p & (0x100 << r))) v &= m->rows[r];
    return v | 0xa0;
}
void m_out(void* c, uint16_t p, uint8_t v) {
    auto* m = static_cast<Machine*>(c);
    if (m->dos && ZxBetaDisk::decodes(p)) m->beta->write(p, v, uint32_t(m->t * 2 / 7));
}
}
// Keys: row (port A8..A15 bit), column bit.
struct Key { unsigned row, bit; };
constexpr Key CAPS{0,0}, SYM{7,1}, ENTER{6,0}, T{2,4}, L{6,1}, R{2,3}, K{6,2};
constexpr Key DIGIT[] = {{4,0},{3,0},{3,1},{3,2},{3,3},{3,4},{4,4},{4,3},{4,2},{4,1}};
int main(int argc, char** argv) {
    Machine m;
    m.rom48 = file(argv[1]); m.trdos = file(argv[2]);
    const auto img = file(argv[3]);
    assert(m.rom48.size() == 16384 && m.trdos.size() == 16384 && !img.empty());
    RamBackend flash; ZxDiskStore store(flash); store.load();
    const uint8_t name[] = "test.scl";
    assert(store.begin(0, img.size(), tape_crc(img.data(), img.size()), false, (const char*)name, 8));
    assert(store.chunk(0, img.data(), img.size()) && store.commit());
    ZxBetaDisk beta(store); beta.reset(); m.beta = &beta;
    Z80_STATE z; Z80Reset(&z);
    auto frames = [&](unsigned n) {
        for (unsigned f = 0; f < n; ++f) {
            for (unsigned used = 0; used < 69888; ) { const int e = Z80Emulate(&z, 224, &m); used += e; m.t += e; }
            Z80Interrupt(&z, 0xff, &m);
        }
    };
    auto press = [&](std::initializer_list<Key> keys) {
        for (Key k : keys) m.rows[k.row] &= uint8_t(~(1u << k.bit));
        frames(6);
        for (Key k : keys) m.rows[k.row] |= uint8_t(1u << k.bit);
        frames(6);
    };
    // Screen text, matched against the ROM font (for failure reports).
    auto screen = [&]() {
        std::string text;
        for (unsigned row = 0; row < 24; ++row) {
            std::string line;
            for (unsigned col = 0; col < 32; ++col) {
                uint8_t glyph[8];
                for (unsigned y = 0; y < 8; ++y)
                    glyph[y] = m.ram[((row & 0x18) << 8) | (y << 8) | ((row & 7) << 5) | col];
                char c = '?';
                for (unsigned ch = 32; ch < 128; ++ch)
                    if (!memcmp(glyph, &m.rom48[0x3d00 + (ch - 32) * 8], 8)) { c = char(ch); break; }
                line += c;
            }
            while (!line.empty() && line.back() == ' ') line.pop_back();
            if (!line.empty()) text += line + "\n";
        }
        return text;
    };
    frames(150); // 48 ROM start-up and RAM test
    // RANDOMIZE USR 15616: T, extended mode (CAPS+SYM) L, digits, ENTER.
    press({T}); press({CAPS, SYM}); press({L});
    for (char c : std::string("15616")) press({DIGIT[c - '0']});
    press({ENTER});
    frames(200);
    printf("after USR 15616: dos entries %u, sectors read %u\n%s", m.dos_entries, beta.sectors_read(), screen().c_str());
    assert(m.dos_entries > 0);
    const uint32_t catalog_reads = beta.sectors_read();
    // TR-DOS prompt: RUN (K-mode R) loads and runs "boot".
    press({R}); press({ENTER});
    frames(600);
    printf("TR-DOS entries %u, sectors read %u (catalog %u), written %u\n%s",
           m.dos_entries, beta.sectors_read(), catalog_reads, beta.sectors_written(), screen().c_str());
    assert(beta.sectors_read() > catalog_reads);
    assert(m.ram[0x8000 - 0x4000] == 42);       // boot ran
    assert(beta.sectors_written() >= 3);        // 2 data sectors + catalog + disk info
    assert(store.flush());
    uint8_t s[256];
    store.read_sector(0, 0, s);
    assert(!memcmp(s + 16, "out     C", 9));
    const unsigned length = s[16+11] | s[16+12] << 8, sector = s[16+14], track = s[16+15];
    const unsigned start = s[16+9] | s[16+10] << 8;
    printf("catalog: start %u length %u\n", start, length);
    assert(length == 300 && s[16+13] == 2);
    store.read_sector(0, (track * 16 + sector) * 256, s);
    assert(s[0] == 42); // The saved CODE starts with the POKEd byte.
    store.read_sector(0, 8 * 256, s);
    assert(s[0xe4] == 2);
    printf("rom ok: boot ran, SAVE wrote \"out\" at track %u sector %u\n", track, sector);
}
'''

Z80USER = r'''
#ifndef __Z80USER_INCLUDED__
#define __Z80USER_INCLUDED__
#include <stdint.h>
uint8_t m_read(void*, uint16_t); uint8_t m_fetch(void*, uint16_t);
void m_write(void*, uint16_t, uint8_t); uint8_t m_in(void*, uint16_t); void m_out(void*, uint16_t, uint8_t);
#define Z80_READ_BYTE(address, x) { (x) = m_read(context, (address) & 0xffff); }
#define Z80_FETCH_BYTE(address, x) { (x) = m_fetch(context, (address) & 0xffff); }
#define Z80_READ_WORD(address, x) { (x) = m_read(context, (address) & 0xffff) | (m_read(context, ((address) + 1) & 0xffff) << 8); }
#define Z80_FETCH_WORD(address, x) Z80_READ_WORD((address), (x))
#define Z80_WRITE_BYTE(address, x) { m_write(context, (address) & 0xffff, (x)); }
#define Z80_WRITE_WORD(address, x) { m_write(context, (address) & 0xffff, (x)); m_write(context, ((address) + 1) & 0xffff, (x) >> 8); }
#define Z80_READ_WORD_INTERRUPT(address, x) Z80_READ_WORD((address), (x))
#define Z80_WRITE_WORD_INTERRUPT(address, x) Z80_WRITE_WORD((address), (x))
#define Z80_INPUT_BYTE(port, x) { (x) = m_in(context, (port)); }
#define Z80_OUTPUT_BYTE(port, x) { m_out(context, (port), (x)); }
#endif
'''


def compile_and_run(folder, name, source, extra=(), args=()):
    (folder/f'{name}.cpp').write_text(source)
    exe = folder/name
    subprocess.run([CXX, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover',
                    f'-I{root}', f'-I{folder}', str(folder/f'{name}.cpp'), *extra, '-o', str(exe)], check=True)
    run = subprocess.run([str(exe), *map(str, args)], text=True, stdout=subprocess.PIPE)
    if run.returncode:
        print(run.stdout, end='')
        raise SystemExit(f'FAIL: {name} exited with {run.returncode}')
    return run.stdout


def check_media_helpers():
    blank = media.blank_trd('WORK')
    assert len(blank) == 4096 and blank[0x8e3] == 0x16 and blank[0x8e1:0x8e3] == bytes([0, 1])
    assert int.from_bytes(blank[0x8e5:0x8e7], 'little') == 2544 and blank[0x8f5:0x8fd] == b'WORK    '
    scl = make_scl()
    trd = media.scl_to_trd(scl, 'TEST')
    assert len(trd) == media.TRD_SIZE and trd[:9] == b'boot    B' and trd[14:16] == bytes([0, 1])
    assert trd[0x8e4] == 1 and trd[0x8e1:0x8e3] == bytes([1, 1])
    for bad in (b'NOTSCL', scl[:20]):
        try: media.scl_to_trd(bad, 'x'); raise AssertionError('accepted a bad SCL')
        except ValueError: pass
    assert media.parse_drive('b') == 1 and media.parse_drive('D:') == 3
    try: media.parse_drive('E'); raise AssertionError('accepted drive E')
    except ValueError: pass
    return scl


def main():
    scl = check_media_helpers()
    with tempfile.TemporaryDirectory() as name:
        folder = Path(name)
        print(compile_and_run(folder, 'unit', UNIT), end='')
        scl_path = folder/'test.scl'; scl_path.write_bytes(scl)
        image = media.disk_image(scl_path)
        assert len(image) == 4096 + 256 and image[:9] == b'boot    B' # Trimmed after "boot".
        (folder/'test.trd').write_bytes(image)
        z80emu = Path(os.environ.get('Z80EMU', Path.home()/'Projects/speccy/z80emu'))
        if not (z80emu/'z80emu.c').exists():
            print(f'SKIP: TR-DOS ROM run needs z80emu at {z80emu} (set Z80EMU)')
            print('PASS: disk store, WD1793/Beta 128 and SCL conversion')
            return
        for header in ('z80emu.c', 'z80emu.h', 'instructions.h', 'macros.h', 'tables.h'):
            shutil.copy(z80emu/header, folder/header)
        (folder/'z80config.h').write_text('#define __Z80CONFIG_INCLUDED__\n')
        (folder/'z80user.h').write_text(Z80USER)
        subprocess.run(['cc', '-O2', '-c', '-w', str(folder/'z80emu.c'), '-o', str(folder/'z80emu.o')],
                       check=True, cwd=folder)
        output = compile_and_run(folder, 'rom', ROM_TEST, [str(folder/'z80emu.o')],
                                 [root/'roms/48.rom', root/'roms/trdos.rom', folder/'test.trd'])
        print(output, end='')
    print('PASS: disk store, WD1793/Beta 128, SCL conversion, TR-DOS 5.03 boot + SAVE on the real ROMs')


if __name__ == '__main__':
    main()

#pragma once
#include <cstdint>
#include <cstddef>

// Core0 owns the matrix and input decoder. Row order follows A8..A15;
// columns are bits 0..4, active low. Upper bits retain the existing EAR=0 idle.
class ZxKeyboard {
public:
    enum HostKey : uint16_t {
        CapsShift = 0x100, SymbolShift, Left, Down, Up, Right,
        Backspace, Escape, Enter, CapsLock, Tab, Reset
    };
    static constexpr unsigned max_keys = 16;
    void clear() { for (auto& row : rows_) row = 0x1f; }
    void set_key(unsigned row, unsigned column, bool down) {
        if (row >= 8 || column >= 5) return;
        if (down) rows_[row] &= uint8_t(~(1u << column));
        else rows_[row] |= uint8_t(1u << column);
    }
    uint8_t read(uint16_t port) const {
        if (port & 1) return 0xff;
        uint8_t value = 0xbf;
        for (unsigned row = 0; row < 8; ++row)
            if (!(port & (0x100u << row))) value &= uint8_t(0xe0 | rows_[row]);
        return value;
    }
    // Rebuild from the entire held set: overlapping synthetic modifiers cannot
    // release each other (e.g. releasing quote while semicolon remains held).
    void set_host_keys(const uint16_t* keys, unsigned count) {
        clear();
        for (unsigned i = 0; i < count && i < max_keys; ++i) press_host_key(keys[i]);
    }
private:
    uint8_t rows_[8] = {31,31,31,31,31,31,31,31};
    void caps() { set_key(0,0,true); }
    void symbol() { set_key(7,1,true); }
    void character(char ch) {
        constexpr char matrix[] = "\0zxcv" "asdfg" "qwert" "12345" "09876" "poiuy" "\rlkjh" " \0mnb";
        for (unsigned i=0; i<40; ++i)
            if (ch && matrix[i] == ch) set_key(i/5,i%5,true);
    }
    void press_host_key(uint16_t key) {
        if (key >= 'A' && key <= 'Z') { caps(); character(char(key-'A'+'a')); return; }
        if ((key >= 'a' && key <= 'z') || (key >= '0' && key <= '9') || key == ' ') {
            character(char(key)); return;
        }
        switch (key) {
        case CapsShift: caps(); return;
        case SymbolShift: symbol(); return;
        case Left: caps(); character('5'); return;
        case Down: caps(); character('6'); return;
        case Up: caps(); character('7'); return;
        case Right: caps(); character('8'); return;
        case Backspace: case 8: caps(); character('0'); return;
        case Escape: caps(); character(' '); return;
        case Enter: case 13: case 10: character('\r'); return;
        case CapsLock: caps(); character('2'); return;
        case Tab: caps(); symbol(); return;
        default: break;
        }
        constexpr char symbols[] = "!@#$%&'()_\";<>-+*/=?,.:";
        constexpr char bases[]   = "1234567890poryjkbvlcnmz";
        static_assert(sizeof(symbols) == sizeof(bases));
        for (unsigned i=0; i<sizeof(symbols)-1; ++i)
            if (key == uint8_t(symbols[i])) { symbol(); character(bases[i]); return; }
        if (key == 0xa3) { symbol(); character('x'); } // Pound sign.
    }
};

// Wire packet: 'Z','K', sixteen little-endian uint16 host keys (zero padded),
// then sum(payload) modulo 256. Sliding resync tolerates lost/corrupt bytes.
class ZxKeyboardReceiver {
public:
    static constexpr unsigned header_size = 2;
    static constexpr unsigned payload_size = ZxKeyboard::max_keys * 2;
    static constexpr unsigned packet_size = header_size + payload_size + 1;
    bool take_reset_request() {
        const bool requested=reset_requested_; reset_requested_=false; return requested;
    }
    bool feed(uint8_t byte, uint32_t now_ms, ZxKeyboard& keyboard) {
        if (used_ && uint32_t(now_ms - last_byte_) > 200) used_ = 0;
        last_byte_ = now_ms;
        bytes_[used_++] = byte;
        if (used_ < packet_size) return false;
        uint8_t sum = 0;
        for (unsigned i=header_size; i<header_size+payload_size; ++i) sum += bytes_[i];
        if (bytes_[0] == 'Z' && bytes_[1] == 'K' && sum == bytes_[packet_size-1]) {
            uint16_t keys[ZxKeyboard::max_keys];
            const uint8_t* payload = bytes_ + header_size;
            for (unsigned i=0; i<ZxKeyboard::max_keys; ++i)
                keys[i] = payload[i*2] | (uint16_t(payload[i*2+1]) << 8);
            keyboard.set_host_keys(keys, ZxKeyboard::max_keys);
            bool reset_down = false;
            for (const auto key : keys) reset_down |= key == ZxKeyboard::Reset;
            if (reset_down && !reset_down_) reset_requested_ = true; // Edge only.
            reset_down_ = reset_down;
            last_packet_ = now_ms;
            active_ = true;
            used_ = 0;
            return true;
        }
        // Slide one byte to resynchronise on the next 'ZK' header.
        for (unsigned i=1; i<packet_size; ++i) bytes_[i-1] = bytes_[i];
        --used_;
        return false;
    }
    void expire(uint32_t now_ms, ZxKeyboard& keyboard) {
        if (active_ && uint32_t(now_ms-last_packet_) >= 500) {
            keyboard.clear(); active_ = false; reset_down_=false;
        }
    }
private:
    uint8_t bytes_[packet_size]{};
    unsigned used_ = 0;
    uint32_t last_byte_ = 0, last_packet_ = 0;
    bool active_ = false;
    bool reset_down_=false, reset_requested_=false;
};

#pragma once
#include <cstdint>
#include <cstddef>
#include <memory>
#include <new>

inline uint32_t tape_crc_update(uint32_t crc, const uint8_t* data, size_t size) {
    while (size--) {
        crc ^= *data++;
        for (unsigned i=0;i<8;++i) crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320u : 0);
    }
    return crc;
}
inline uint32_t tape_crc(const uint8_t* data, size_t size) {
    return tape_crc_update(0xffffffffu, data, size) ^ 0xffffffffu;
}

// Standard TAP playback for the unmodified 48K/128K ROM LD-BYTES routine.
// Each block starts when the real CPU enters that loader. Time advances from
// observed opcode fetches, counting Z80 T states without external WAIT cycles.
class ZxTape {
public:
    static constexpr uint32_t capacity = 256 * 1024;
    enum class State { Empty, Uploading, Armed, Playing, Stopped, Finished };
    enum class Phase { Pilot, Sync1, Sync2, Data, Done };
    const char* state_name() const {
        switch(state_) {
        case State::Empty:return "empty"; case State::Uploading:return "uploading";
        case State::Armed:return "armed"; case State::Playing:return "playing";
        case State::Stopped:return "stopped"; case State::Finished:return "finished";
        } return "unknown";
    }
    uint32_t size() const { return size_; }
    uint32_t received() const { return received_; }
    uint32_t position() const { return state_==State::Playing ? byte_ : cursor_; }
    unsigned block() const { return block_; }
    unsigned blocks() const { return blocks_; }
    enum class Mode { Normal, Fast };
    const char* mode_name() const { return mode_==Mode::Fast ? "fast" : "normal"; }
    const char* playback_name() const {
        return state_==State::Playing ? (fast_active_ ? "fast" : "normal") : "idle";
    }
    unsigned fast_blocks() const { return fast_blocks_; }
    unsigned normal_blocks() const { return normal_blocks_; }
    bool set_mode(Mode mode) {
        if (in_loader_ || fast_active_ || state_==State::Playing) return false;
        mode_=mode; return true;
    }
    // Overlay only an identified standard ROM during one active loader call.
    // Keep its original flag, LOAD/VERIFY, destination and checksum handling.
    uint8_t rom_byte(uint16_t address, uint8_t original) const {
        if (!fast_active_) return original;
        static constexpr uint8_t skip_pilot[]={0x0e,0x02,0xc3,0x9f,0x05}; // LD C,2; JP 059F
        static constexpr uint8_t get_byte[]={
            0xdb,0xfd,0xb7,0xc8, // IN A,(FD); OR A; RET Z (no bytes/error)
            0xdb,0xfb,0x6f,0xc3,0xd8,0x05 // IN A,(FB); LD L,A; JP 05D8
        };
        // When a file arrives after LOAD is waiting, enter at a whole-instruction
        // boundary. The ROM has already pushed SA-LD-RET and saved AF'.
        // LD-EDGE-1 was called directly, or via LD-EDGE-2 (return 05E6).
        // Discard those frames, retaining the loader's pushed SA-LD-RET.
        static constexpr uint8_t resume[]={
            0xe1,0x7d,0xfe,0xe6,0x20,0x01,0xe1,0xc3,0x62,0x05
        }; // POP HL; LD A,L; CP E6; JR NZ,+1; POP HL; JP 0562
        if (address>=0x05ed && address<0x05ed+sizeof(resume)) return resume[address-0x05ed];
        if (address>=0x0562 && address<0x0562+sizeof(skip_pilot)) return skip_pilot[address-0x0562];
        if (address>=0x05c8 && address<0x05c8+sizeof(get_byte)) return get_byte[address-0x05c8];
        return original;
    }
    bool fast_io(uint16_t port, uint8_t& value) {
        if (!fast_active_) return false;
        if (uint8_t(port)==0xfd) { value=state_==State::Playing && byte_<end_; return true; }
        if (uint8_t(port)!=0xfb) return false;
        value=state_==State::Playing && byte_<end_ ? memory_[byte_++] : 0;
        return true;
    }
    bool ear() const { return level_; }
    bool has_tape() const { return blocks_ != 0; }
    bool loader_call_active() const { return in_loader_ || fast_active_; }
    // Maintained on state changes, so ordinary memory reads need one flag load.
    bool observes_cpu() const { return observes_cpu_; }
    bool begin(uint32_t size, uint32_t crc) {
        if (fast_active_ || size < 4 || size > capacity) return false;
        stop(); memory_.reset(); size_=received_=cursor_=block_=blocks_=0;
        state_=State::Empty;
        memory_.reset(new(std::nothrow) uint8_t[size]);
        if (!memory_) return false;
        size_=size; expected_crc_=crc; running_crc_=0xffffffffu;
        state_=State::Uploading;
        refresh_observer();
        return true;
    }
    bool chunk(uint32_t offset, const uint8_t* data, uint32_t size) {
        if (state_!=State::Uploading || offset!=received_ || size>size_-received_) return false;
        for (uint32_t i=0;i<size;++i) memory_[offset+i]=data[i];
        running_crc_=tape_crc_update(running_crc_,data,size); received_+=size;
        return true;
    }
    bool commit() {
        if (state_!=State::Uploading || received_!=size_ || (running_crc_^0xffffffffu)!=expected_crc_) return false;
        unsigned blocks=0;
        for (uint32_t p=0;p<size_;) {
            if (size_-p<2) return false;
            const uint32_t n=word(p); p+=2;
            if (n<2 || n>size_-p) return false;
            p+=n; ++blocks;
        }
        blocks_=blocks; state_=State::Armed; cursor_=block_=0;
        fast_blocks_=normal_blocks_=0;
        in_loader_=previous_valid_=level_=false;
        refresh_observer();
        return true;
    }
    void stop() {
        if (state_==State::Uploading) {
            memory_.reset(); size_=received_=cursor_=block_=blocks_=0;
            state_=State::Empty;
        }
        if (state_!=State::Empty && state_!=State::Uploading) state_=State::Stopped;
        level_=in_loader_=previous_valid_=false;
        refresh_observer();
    }
    bool rewind() {
        if (fast_active_ || !blocks_ || state_==State::Uploading) return false;
        cursor_=block_=0; state_=State::Armed; fast_blocks_=normal_blocks_=0;
        level_=in_loader_=previous_valid_=false;
        refresh_observer();
        return true;
    }
    // A machine reset stops playback but retains the uploaded file.
    void reset() { stop(); fast_active_=false; refresh_observer(); }

    void observe_fetch(uint16_t address, uint8_t opcode, bool standard_rom) {
        const bool inside=standard_rom && address>=0x0556 && address<=0x0604;
        if (previous_valid_ && !fast_active_) {
            const unsigned total=instruction_ticks(address);
            advance(total>partial_ ? total-partial_ : 0);
        }
        if (!inside) {
            if (in_loader_ && state_==State::Playing) finish_block(); // Wrong flag/BREAK/verify exit.
            in_loader_=previous_valid_=level_=fast_active_=false;
            refresh_observer();
            return;
        }
        if (!in_loader_) {
            in_loader_=true;
            if (state_==State::Armed) {
                start_block();
            }
        }
        // A commit/rewind can happen after the CPU has entered LD-BYTES. Wait
        // for its entry or sampling-loop boundary before swapping instructions.
        if (state_==State::Playing && mode_==Mode::Fast && !fast_active_ &&
            (address==0x0556 || address==0x05ed)) {
            fast_active_=true; previous_valid_=false;
        }
        const uint8_t prefix=previous_valid_ && address==previous_address_+1 &&
            (previous_opcode_==0xdd || previous_opcode_==0xcb) ? previous_opcode_ : 0;
        previous_address_=address; previous_opcode_=opcode; previous_prefix_=prefix;
        partial_=0; previous_valid_=state_==State::Playing && !fast_active_;
        refresh_observer();
    }
    // IN A,(n) samples EAR partway through the instruction. The remaining
    // T states are charged at the next fetch, without double counting.
    bool read_ear() {
        if (previous_valid_ && previous_opcode_==0xdb && !partial_) {
            advance(7); partial_=7;
        }
        return level_;
    }
    // Public for instruction/pulse regression tests; units are Z80 T states.
    void advance(uint32_t ticks) {
        while (state_==State::Playing && ticks>=remaining_) {
            ticks-=remaining_; level_=!level_; next_pulse();
        }
        if (state_==State::Playing) remaining_-=ticks;
    }
private:
    std::unique_ptr<uint8_t[]> memory_;
    State state_=State::Empty;
    Mode mode_=Mode::Normal;
    bool fast_active_=false;
    unsigned fast_blocks_=0, normal_blocks_=0;
    Phase phase_=Phase::Done;
    uint32_t size_=0, received_=0, cursor_=0, expected_crc_=0, running_crc_=0;
    uint32_t remaining_=0, byte_=0, end_=0;
    unsigned block_=0, blocks_=0, pilot_=0, bit_=0, half_=0;
    bool level_=false, in_loader_=false, previous_valid_=false, observes_cpu_=false;
    uint16_t previous_address_=0;
    uint8_t previous_opcode_=0, previous_prefix_=0;
    unsigned partial_=0;
    void refresh_observer() {
        observes_cpu_=state_==State::Armed || state_==State::Playing ||
                      previous_valid_ || in_loader_ || fast_active_;
    }
    uint16_t word(uint32_t p) const { return memory_[p] | (uint16_t(memory_[p+1])<<8); }
    unsigned data_ticks() const { return memory_[byte_] & (0x80u>>bit_) ? 1710 : 855; }
    void start_block() {
        if (cursor_>=size_) { state_=State::Finished; return; }
        byte_=cursor_+2; end_=byte_+word(cursor_);
        pilot_=memory_[byte_]<128 ? 8063 : 3223;
        bit_=half_=0; level_=false; phase_=Phase::Pilot;
        remaining_=2168; state_=State::Playing;
    }
    void finish_block() {
        if (fast_active_) ++fast_blocks_; else ++normal_blocks_;
        cursor_=end_; ++block_; phase_=Phase::Done;
        state_=cursor_==size_ ? State::Finished : State::Armed;
        refresh_observer();
        // Preserve the final edge until the ROM leaves the loader.
    }
    void next_pulse() {
        switch(phase_) {
        case Phase::Pilot:
            if (--pilot_) remaining_=2168;
            else { phase_=Phase::Sync1; remaining_=667; }
            break;
        case Phase::Sync1: phase_=Phase::Sync2; remaining_=735; break;
        case Phase::Sync2: phase_=Phase::Data; remaining_=data_ticks(); break;
        case Phase::Data:
            if (++half_==2) {
                half_=0;
                if (++bit_==8) { bit_=0; ++byte_; }
            }
            if (byte_==end_) finish_block(); else remaining_=data_ticks();
            break;
        case Phase::Done: break;
        }
    }
    unsigned instruction_ticks(uint16_t next) const {
        const uint8_t op=previous_opcode_;
        if (previous_prefix_==0xdd) return (op==0x23) ? 6 : 15; // INC IX / indexed LD.
        if (previous_prefix_==0xcb) return 4; // RL C / RL L, after prefix's four T states.
        if (op==0xdd || op==0xcb) return 4;
        if (op==0x10) return next==previous_address_+2 ? 8 : 13;
        if (op==0x20 || op==0x28 || op==0x30 || op==0x38)
            return next==previous_address_+2 ? 7 : 12;
        if (op==0x18) return 12;
        if ((op&0xc7)==0xc0) return next==previous_address_+1 ? 5 : 11;
        if (op==0xc9) return 10;
        if (op==0xcd) return 17;
        if ((op&0xc7)==0xc2) return 10;
        if ((op&0xcf)==0xc5) return 11;
        if ((op&0xcf)==0x01) return 10;
        if ((op&0xcf)==0x03 || (op&0xcf)==0x0b) return 6;
        if ((op&0xc7)==0x06 || (op&0xc7)==0xc6) return 7;
        if (op==0xdb || op==0xd3) return 11;
        return 4; // Remaining loader instructions are register operations.
    }
};

#pragma once

#include <cstdint>
#include <cstdio>

#include <hardware/pio.h>

#ifndef Z80_BUS_MODE_MANUAL
#define Z80_BUS_MODE_MANUAL 0
#endif

#ifndef Z80_BUS_MODE_WAIT
#define Z80_BUS_MODE_WAIT 1
#endif

#ifndef Z80_BUS_MODE_FROZEN
#define Z80_BUS_MODE_FROZEN 2
#endif

#ifndef Z80_BUS_MODE
#define Z80_BUS_MODE Z80_BUS_MODE_WAIT
#endif

namespace z80pio {

// Requests preserve the native GPIO0..31 image: data[7:0], address[23:8],
// and control[31:24].
enum RawBusBits : uint32_t {
    kRawClk   = 1u << 24,
    kRawReset = 1u << 25,
    kRawWait  = 1u << 26,
    kRawM1    = 1u << 27,
    kRawMreq  = 1u << 28,
    kRawIorq  = 1u << 29,
    kRawRd    = 1u << 30,
    kRawWr    = 1u << 31,
};

// Bits 8..15 are loaded directly into the eight data-pin direction controls.
constexpr uint32_t kReplyDriveData = 0xffu << 8;

struct BusRequest {
    uint32_t raw;

    uint16_t address() const { return static_cast<uint16_t>(raw >> 8); }
    uint8_t data() const { return static_cast<uint8_t>(raw); }

    bool m1() const { return !(raw & kRawM1); }
    bool mreq() const { return !(raw & kRawMreq); }
    bool iorq() const { return !(raw & kRawIorq); }
    bool rd() const { return !(raw & kRawRd); }
    bool wr() const { return !(raw & kRawWr); }

    void dump(uint8_t mem) const {
        printf("busreq %04x %02x m1 %d mreq %d ioreq %d rd %d wr %d mem %02x\n",
            address(), data(), m1(), mreq(), iorq(), rd(), wr(), mem
        );
    }
};

constexpr uint32_t read_reply(uint8_t data)
{
    return kReplyDriveData | data;
}

constexpr uint32_t write_reply()
{
    return 0;
}

// reset_cpu() is for startup or another quiescent point. While servicing a
// request, use begin_reset(), write_reply(), end_reset() in that order so a
// WAIT/frozen-clock transaction cannot leave the reset without clock edges.
class ManualBusDriver {
public:
    static constexpr char const* id = "manual";

    void init(uint32_t z80_hz);
    void begin_reset();
    void end_reset();
    void reset_cpu() { begin_reset(); end_reset(); }
    BusRequest read_request();
    void write_reply(uint32_t reply);

private:
    uint32_t previous_raw_ = 0;
    bool next_clock_high_ = true;
};

class WaitStateBusDriver {
public:
    static constexpr char const* id = "wait state";

    void init(uint32_t z80_hz);
    void begin_reset();
    void end_reset();
    void reset_cpu() { begin_reset(); end_reset(); }
    BusRequest read_request();
    void write_reply(uint32_t reply);

private:
    PIO bus_pio_ = pio0;
    PIO clock_pio_ = pio1;
    uint clock_sm_ = 0;
    uint bus_sm_ = 0;
    uint32_t reset_hold_us_ = 10;
};

class FrozenClockBusDriver {
public:
    static constexpr char const* id = "frozen clock";

    void init(uint32_t z80_hz);
    void begin_reset();
    void end_reset();
    void reset_cpu() { begin_reset(); end_reset(); }
    BusRequest read_request();
    void write_reply(uint32_t reply);

private:
    PIO bus_pio_ = pio0;
    PIO clock_pio_ = pio1;
    uint bus_sm_ = 0;
    uint clock_sm_ = 0;
    uint32_t reset_hold_us_ = 10;
};

#if Z80_BUS_MODE == Z80_BUS_MODE_MANUAL
using ActiveBusDriver = ManualBusDriver;
#elif Z80_BUS_MODE == Z80_BUS_MODE_WAIT
using ActiveBusDriver = WaitStateBusDriver;
#elif Z80_BUS_MODE == Z80_BUS_MODE_FROZEN
using ActiveBusDriver = FrozenClockBusDriver;
#else
#error "Z80_BUS_MODE must be MANUAL, WAIT or FROZEN"
#endif

} // namespace z80pio

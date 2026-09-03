#pragma once

#include <cstdint>

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

// PIO IN_BASE is GPIO8. This rotates the physical GPIO0..31 image so
// address, control, and data occupy convenient fields in one FIFO word.
enum RawBusBits : uint32_t {
    kRawClk   = 1u << 16,
    kRawReset = 1u << 17,
    kRawWait  = 1u << 18,
    kRawM1    = 1u << 19,
    kRawMreq  = 1u << 20,
    kRawIorq  = 1u << 21,
    kRawRd    = 1u << 22,
    kRawWr    = 1u << 23,
};

constexpr uint32_t kReplyDriveData = 1u << 8;

struct BusRequest {
    uint32_t raw;

    uint16_t address() const { return static_cast<uint16_t>(raw); }
    uint8_t data() const { return static_cast<uint8_t>(raw >> 24); }

    bool m1() const { return !(raw & kRawM1); }
    bool mreq() const { return !(raw & kRawMreq); }
    bool iorq() const { return !(raw & kRawIorq); }
    bool rd() const { return !(raw & kRawRd); }
    bool wr() const { return !(raw & kRawWr); }
};

constexpr uint32_t read_reply(uint8_t data)
{
    return kReplyDriveData | data;
}

constexpr uint32_t write_reply()
{
    return 0;
}

class ManualBusDriver {
public:
    void init(uint32_t z80_hz);
    BusRequest read_request();
    void write_reply(uint32_t reply);

private:
    uint32_t previous_raw_ = 0;
    bool next_clock_high_ = true;
};

class WaitStateBusDriver {
public:
    void init(uint32_t z80_hz);
    BusRequest read_request();
    void write_reply(uint32_t reply);

private:
    PIO pio_ = pio0;
    uint clock_sm_ = 0;
    uint bus_sm_ = 0;
};

class FrozenClockBusDriver {
public:
    void init(uint32_t z80_hz);
    BusRequest read_request();
    void write_reply(uint32_t reply);

private:
    PIO bus_pio_ = pio0;
    PIO clock_pio_ = pio1;
    uint bus_sm_ = 0;
    uint clock_sm_ = 0;
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

#pragma once

#include <cstdint>
#include <cstdio>

#include <hardware/pio.h>

#ifndef Z80_BUS_MODE_MANUAL
#define Z80_BUS_MODE_MANUAL 0
#endif

#ifndef Z80_BUS_MODE_ASYNC
#define Z80_BUS_MODE_ASYNC 1
#endif

#ifndef Z80_BUS_MODE_FROZEN
#define Z80_BUS_MODE_FROZEN 2
#endif

#ifndef Z80_BUS_MODE
#define Z80_BUS_MODE Z80_BUS_MODE_ASYNC
#endif

namespace z80pio {

// Requests preserve the native GPIO0..31 image: data[7:0], address[23:8],
// and control[31:24].
enum RawBusBits : uint32_t {
    kRawClk   = 1u << 24,
    kRawReset = 1u << 25,
    kRawWait  = 1u << 26,
    kRawM1    = 1u << 27,
    kRawIorq  = 1u << 28,
    kRawMreq  = 1u << 29,
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
    // MREQ+WR with M1, IORQ and RD inactive: exactly the snapshot the async
    // detector posts without a reply (bits 27..31 = M1 IORQ MREQ RD WR).
    bool posted_write() const { return ((raw >> 27) & 0x1fu) == 0x0bu; }

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
    static constexpr bool posts_memory_writes = false;

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

class AsyncBusDriver {
public:
    static constexpr char const* id = "async WAIT (detector/service)";
    // Memory writes are posted: no WAIT, no reply (see z80_bus_async.pio).
    static constexpr bool posts_memory_writes = true;

    void init(uint32_t z80_hz);
    void begin_reset();
    void end_reset();
    void reset_cpu() { begin_reset(); end_reset(); }
    struct FifoAccess {
        const volatile uint32_t* status;
        const volatile uint32_t* rx;
        volatile uint32_t* tx;
        uint32_t rx_empty;
        __attribute__((always_inline)) BusRequest read_request() const {
            while (*status & rx_empty) {}
            return {*rx};
        }
        __attribute__((always_inline)) void write_reply(uint32_t reply) const {
            // Exactly one reply per synchronous request; never for a posted
            // write. The detector rearms for the next synchronous request only
            // after the service SM has pulled the previous reply and retired
            // the bus cycle (IRQ5). Consequently TX cannot be full, including
            // a transaction-safe reset's final reply.
            *tx = reply;
        }
    };
    // Cache this value once in the owner loop; SM assignments remain fixed.
    FifoAccess fifo_access() const { return fifo_access_; }
    __attribute__((always_inline)) BusRequest read_request() { return fifo_access().read_request(); }
    __attribute__((always_inline)) void write_reply(uint32_t reply) { fifo_access().write_reply(reply); }

private:
    PIO bus_pio_ = pio0;
    PIO clock_pio_ = pio1;
    uint clock_sm_ = 0;
    uint wait_sm_ = 0;
    uint detector_sm_ = 0;
    uint bus_sm_ = 0;
    uint32_t reset_hold_us_ = 10;
    FifoAccess fifo_access_{};
};

class FrozenClockBusDriver {
public:
    static constexpr char const* id = "frozen clock";
    static constexpr bool posts_memory_writes = false;

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
#elif Z80_BUS_MODE == Z80_BUS_MODE_ASYNC
using ActiveBusDriver = AsyncBusDriver;
#elif Z80_BUS_MODE == Z80_BUS_MODE_FROZEN
using ActiveBusDriver = FrozenClockBusDriver;
#else
#error "Z80_BUS_MODE must be MANUAL, ASYNC or FROZEN"
#endif

} // namespace z80pio

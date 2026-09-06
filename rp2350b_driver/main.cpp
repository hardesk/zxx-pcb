#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <algorithm>
// #include <memory>

#include <pico/stdlib.h>
#include <pico/stdio.h>
#include <hardware/gpio.h>

#include "z80_pins.hpp"
#include "z80_pio_bus.hpp"

using std::size_t;

#define PIN_DEBUG 1

#define IO_DATA_SHIFT 0
#define IO_DATA 0x0000'00ffu
#define IO_ADDR_SHIFT 8
#define IO_ADDR 0x00ff'ff00u
#define IO_CTRL 0x1f'ff00'0000ull
#define IO_CTRL_SHIFT 24
#define IO_CTRLL_WIDTH 8
#define IO_CTRLH_WIDTH 5
#define IO_ALL ((uint64_t)IO_DATA|(uint64_t)IO_ADDR|(uint64_t)IO_CTRL)

inline uint32_t extract_ctrl(uint64_t ctrl_addr_data) {
    return (ctrl_addr_data & IO_CTRL) >> IO_CTRL_SHIFT;
}

inline uint32_t extract_ctrl(uint32_t ctrl_addr_data, uint32_t ctrlhi) {
    uint32_t lo = (ctrl_addr_data & IO_CTRL) >> IO_CTRL_SHIFT;
    uint32_t hi = ctrlhi & (IO_CTRL >> 32);
    return lo | (hi << IO_CTRLL_WIDTH);
}

struct ZxDbgPins
{
    uint16_t addr;
    uint8_t data;
    union {
        struct {
            bool CLK:1, RESET:1, WAIT:1, M1:1, MREQ:1, IORQ:1, RD:1, WR:1,
                 INT:1, NMI:1, BUSREQ:1, BUSACK:1, HALT:1;
        };
        uint16_t value;
    } pins;

    ZxDbgPins(uint32_t lo, uint32_t hi) {
        addr = (lo & IO_ADDR) >> IO_ADDR_SHIFT;
        data = (lo & IO_DATA) >> IO_DATA_SHIFT;
        pins.value = extract_ctrl(lo, hi);
    }

    ZxDbgPins(uint64_t v) {
        addr = (v & IO_ADDR) >> IO_ADDR_SHIFT;
        data = (v & IO_DATA) >> IO_DATA_SHIFT;
        pins.value = extract_ctrl(v);
    }

    void dump_state(unsigned T) {
        printf("T%4d %04x %02x clk %d rst %d mreq %d m1 %d iorq %d rd %d wr %d int %d halt %d wait %d nmi %d busreq %d busack %d\n",
            T, addr, data,
            pins.CLK, pins.RESET, pins.MREQ, pins.M1, pins.IORQ, pins.RD, pins.WR,
            pins.INT, pins.HALT, pins.WAIT, pins.NMI, pins.BUSREQ, pins.BUSACK
        );
    }
};

template<class DerivedT>
struct ZxEnv
{
    // typedef uint8_t (*f_io_read_t)(uint16_t addr);
    // typedef void (*f_io_write_t)(uint16_t addr, uint8_t data);

    DerivedT& self() { return *static_cast<DerivedT*>(this); }

    char* m_ram;
    size_t m_ram_size;

    #define DAT(x) ((addr_data&IO_DATA)>>IO_DATA_SHIFT)
    #define ADR(x) ((addr_data&IO_ADDR)>>IO_ADDR_SHIFT)

    #define IS_LO(pin,bits) ((bits & (1U<<(pin-IO_CTRL_SHIFT))) == 0)
    #define IS_HI(pin,bits) ((bits & (1U<<(pin-IO_CTRL_SHIFT))) != 0)

    uint16_t m_ctrl_prev = (uint16_t)(IO_CTRL>>IO_CTRL_SHIFT);

    uint8_t peek(uint16_t addr) const { return m_ram[addr]; }

    // ctrl is shifted to 0 bits
    void react(uint16_t ctrl, uint32_t addr_data) {
        uint32_t ctrlx = m_ctrl_prev ^ ctrl; // =1 which signal changed
        m_ctrl_prev = ctrl;

        // MEMORY ACCESS
        if (IS_LO(pMREQ, ctrl)) {
            // CPU WRITEs
            if (IS_LO(pWR, ctrl) && IS_HI(pWR, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = DAT(addr_data);
                if (addr == 0) {
                    self().impl_debug_trap(addr, dat);
                }
                self().impl_on_memwrite(addr, dat);
                m_ram[addr] = dat;
            } else
            // CPU READs
            if (IS_LO(pRD, ctrl) && IS_HI(pRD, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = m_ram[addr];
                self().impl_on_memread(addr, IS_LO(pM1, ctrl));
                if (IS_LO(pM1, ctrl)) {
                    // printf("\033[34mcode %04x %02x\033[0m\n", addr, dat);
                    if (addr==0)
                        printf("\033[31mSOFT RESET DETECTED\033[0m\n");
                }
                self().expose_data(dat);
            }
        } else
        // CPU done reading/writing memory
        if (IS_HI(pMREQ, ctrl) && IS_HI(pMREQ, ctrlx)) {
            self().clear_data_bus();
        }
        // IO ACCESS
        if (IS_LO(pIORQ, ctrl)) {
            // CPU WRITEs IO
            if (IS_LO(pWR, ctrl) && IS_HI(pWR, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = DAT(addr_data);
                self().handle_io_out(addr, dat);
            } else
            // CPU READs IO
            if (IS_LO(pRD, ctrl) && IS_HI(pRD, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = self().handle_io_in(addr);
                self().expose_data(dat);
            }
        } else
        // CPU done reading/writing IO
        if (IS_HI(pIORQ, ctrl) && IS_HI(pIORQ, ctrlx)) {
            self().clear_data_bus();
        }
    }

    struct MemoryDumpOpts {
        short width = 16;
        bool show_address:1 = true;
        bool ascii:1 = false;
    };

    void dump_memory(unsigned addr, size_t size, MemoryDumpOpts opts = MemoryDumpOpts()) {
        for (size_t i=0; i<size; ) {
            char const* pl = m_ram + addr + i;
            size_t mx = std::min(size-i, (size_t)opts.width);
            if (opts.show_address)
                printf("%08x  ", addr + i);
            for (size_t q=0; q<mx; ++q)
                printf("%02x%s", pl[q], q == mx-1 ? "" : " ");
            printf("%*s", 1 + (opts.width-mx)*3, "");
            if (opts.ascii) {
                printf("%c", ' ');
                for (size_t q=0; q<mx; ++q)
                    printf("%c", pl[q] >= 32 && pl[q] <= 127 ? pl[q] : '.' );
            }
            printf("\n");
            i += mx;
        }
    }

protected:
    void impl_debug_trap(uint16_t addr, uint8_t trapno) {}

    void impl_on_memread(uint16_t addr, bool m1) {}
    void impl_on_memwrite(uint16_t addr, uint8_t dat) {}
};

struct Rp2350ZxEnv : public ZxEnv<Rp2350ZxEnv>
{
    template<class T> friend class ZxEnv;

    Rp2350ZxEnv() {
        m_ram_size = 256*256;
        m_ram = new char[m_ram_size];
        memset(m_ram, 0, m_ram_size);
    }

    ~Rp2350ZxEnv() {
        delete[] m_ram;
    }
    
    static constexpr uint64_t kInitialHighPins =
        (1ull << pINT) | (1ull << pWAIT) | (1ull << pNMI) | (1ull << pBUSRQ);

    void init() {
        uint64_t pins_oe = 
            (1ull << pCLK)     |
            (1ull << pRESET)   |
            (1ull << pINT)     |
            (1ull << pWAIT)    |
            (1ull << pNMI)     |
            (1ull << pBUSRQ) 
            ;
        for(int i=0; i<pPIN_COUNT; ++i)
            gpio_set_pulls(i, false, false);
        gpio_set_function_masked64(IO_ALL, GPIO_FUNC_SIO);

        // Set the output latches before enabling them. RESET and CLK start
        // low; interrupt inputs, WAIT and BUSRQ start inactive (high).
        gpio_put_all64(kInitialHighPins);
        gpio_set_dir_all_bits64(pins_oe);
    }

    void expose_data(uint8_t dat) {
        // gpio_set_dir_out_masked(IO_LOW_OUT | IO_DATA);
        gpio_set_dir_masked(IO_DATA, IO_DATA);
        gpio_put_masked(IO_DATA, dat << IO_DATA_SHIFT);
    }

    void clear_data_bus() {
        // gpio_set_dir_out_masked(IO_LOW_OUT);
        gpio_set_dir_masked(IO_DATA, 0);
    }

    void handle_io_out(uint16_t addr, uint8_t data) {
        if (addr == 0xff81) {
            printf("DATA on port %04x: %02x\n", addr, data);
        } else if (addr == 0xff83) {
            printf("%c", data);
        }
    }
    uint8_t handle_io_in(uint16_t addr) { return 0; }

    uint8_t handle_interrupt_ack() { return 0xff; }

    uint32_t service_pio_request(z80pio::BusRequest const& request) {
        const uint16_t addr = request.address();
        const uint8_t data = request.data();

        if (request.mreq() && request.rd()) {
            uint8_t value = static_cast<uint8_t>(m_ram[addr]);
            impl_on_memread(addr, request.m1());
            return z80pio::read_reply(value);
        }

        if (request.mreq() && request.wr()) {
            if (addr == 4)
                impl_debug_trap(addr, data);
            impl_on_memwrite(addr, data);
            m_ram[addr] = static_cast<char>(data);
            return z80pio::write_reply();
        }

        if (request.iorq() && request.rd())
            return z80pio::read_reply(handle_io_in(addr));

        if (request.iorq() && request.wr()) {
            handle_io_out(addr, data);
            return z80pio::write_reply();
        }

        if (request.iorq() && request.m1())
            return z80pio::read_reply(handle_interrupt_ack());

        return z80pio::write_reply();
    }

    template<class... Bytes>
    static char* store_bytes(char* p, Bytes... bytes) { ( (*p++ = bytes), ... ); return p; }

    void prepare_vectors(uint16_t jump_on_reset_addr = 0x100) {
        store_bytes( m_ram + 0, 0xc3, jump_on_reset_addr & 0xff, jump_on_reset_addr >> 8);
        store_bytes( m_ram + 3, 0, 0);

        // for CP/M we store the trap inline without additionl jumps
        char* p = m_ram + 5;
        p = store_bytes(p, 0xed, 0x43, 0x80, 0x00);            // ld (0x0080), bc
        p = store_bytes(p, 0xed, 0x53, 0x82, 0x00);            // ld (0x0082), de
        p = store_bytes(p, 0x3e, 0x01);                        // ld a, 1
        p = store_bytes(p, 0x32, 0x03, 0x00);                  // ld (3), a <-- trigger trap
        p = store_bytes(p, 0xc9);                              // ret
    }

    void load(unsigned char const* data, size_t size, uint16_t origin) {
        unsigned char* dest = (unsigned char*)m_ram + origin;
        memcpy(dest, data, size);
    }

private:
    void impl_debug_trap(uint16_t addr, uint8_t trapno) {
        if (addr == 4) {
            printf("MEM4 <- %02x\n", trapno);
        }
        if (addr == 3 && trapno == 1) {
            uint8_t c = *(m_ram+0x80);
            uint16_t de = *(uint16_t*)(m_ram+0x82);
            if (c == 2) {
                uint8_t e = de&0xff;
                printf("%c", e);
            } else if (c==9) {
                char const* str = (char const*)m_ram + de;
                while (*str != '$' && *str != 0) {
                    printf("%c", *str++);
                }
            }
        }
    }

    void impl_on_memwrite(uint16_t addr, uint8_t dat) {
        // if (addr >= 0x1d30 && addr <= 0x1db8) {
        //     printf(">> writing %02x to %04x\n", dat, addr);
        //     dump_memory(0x1d00, 256, { .width = 8, .show_address = true, .ascii = true } );
        // }
    }

};

inline static uint32_t gpio_get_all_hi() {
#if PICO_USE_GPIO_COPROCESSOR
    return gpioc_hi_in_get();
#elif NUM_BANK0_GPIOS <= 32
    return 0;
#else
    return sio_hw->gpio_hi_in;
#endif
}

#define LED_PIN (32+14)

constexpr uint kZ80ResetButtonPin = 40;

void init_z80_reset_button()
{
    gpio_init(kZ80ResetButtonPin);
    gpio_set_dir(kZ80ResetButtonPin, GPIO_IN);
    gpio_pull_up(kZ80ResetButtonPin);
}

bool z80_reset_button_pressed()
{
    return !gpio_get(kZ80ResetButtonPin);
}

void blink_hello() {
    for(size_t i=0; i<10; ++i) {
        gpio_put(LED_PIN, (i&1) == 0);
        sleep_ms(50);
    }
}

struct DebButton {
    static constexpr unsigned POLL_MS = 10;
    DebButton() : next_poll(make_timeout_time_ms(POLL_MS)), last_sample(false), debounced(false) {
    }

    template<class F>
    bool check( F f ) {
        bool pressed = false;
        if (time_reached(next_poll)) {
            next_poll = make_timeout_time_ms(POLL_MS);
            const bool sample = f();
            if (sample == last_sample && sample != debounced)
                pressed = debounced = sample;
            last_sample = sample;
        }
        return pressed;
    }

private:
    absolute_time_t next_poll = 0;
    bool last_sample:1;
    bool debounced:1;
};

#ifdef DATA_ASM_FILE

#if __has_include(DATA_ASM_FILE)
#include DATA_ASM_FILE
#define z80_prog DATA_ASM_LABEL
#endif

#else 

// #if __has_include("zexdoc.h")
// #include "zexdoc.h"
// #define z80_prog zexdoc_prog
// #endif

#if __has_include("test.h")
#include "test.h"
#define z80_prog test_prog
#endif

#endif

// unsigned char copy_str_code[] = {
//   0x11, 0xc0, 0x00, 0x21, 0x0e, 0x01, 0x7e, 0x12, 0x13, 0x23, 0xb7, 0x20,
//   0xf9, 0xc9, 0x48, 0x65, 0x6c, 0x6c, 0x6f, 0x20, 0x57, 0x6f, 0x72, 0x6c,
//   0x64, 0x21, 0x00
// };

int main()
{
    stdio_init_all();

    gpio_set_dir(LED_PIN, true);
    gpio_set_function(LED_PIN, GPIO_FUNC_SIO);
    blink_hello();

    Rp2350ZxEnv zx;
    zx.init();
    init_z80_reset_button();

    uint16_t prog_org = 0x8000;
    zx.prepare_vectors(prog_org);
    zx.load(z80_prog, count_of(z80_prog), prog_org);
    zx.dump_memory(0, 32, { .width = 16, .ascii = true } );
    zx.dump_memory(prog_org, 64, { .width = 16, .ascii = true } );

    printf("Hello from RP2350 over RTT!\n");
    char buf[128];
    auto fmt_pad = [&buf](uint32_t pad) {
        #define GB(x, def) ((x & PADS_BANK0_GPIO0_ ## def ## _BITS) >> PADS_BANK0_GPIO0_ ## def ## _LSB)
        snprintf(buf, sizeof(buf), "iso %d od %d ie %d drive %d pue %d pde %d schmitt %d slewfast %d",
            GB(pad, ISO),
            GB(pad, OD),
            GB(pad, IE),
            GB(pad, DRIVE),
            GB(pad, PUE),
            GB(pad, PDE),
            GB(pad, SCHMITT),
            GB(pad, SLEWFAST));
        return buf;
    };

    // printf("pins oe hi %08x lo %08x func-A0 %d outlevel-A0 %d\n", sio_hw->gpio_hi_oe, sio_hw->gpio_oe, gpio_get_function(pA0), gpio_get_out_level(pA0));
    // printf(" oe h %08x l %08x\n", sio_hw->gpio_hi_oe, sio_hw->gpio_oe);
    // for (int i=0; i<36; ++i){
    //     printf(" - pin %2d func %d oe %d PAD [[ %s ]]\n", i, gpio_get_function(i), gpio_get_dir(i), fmt_pad(pads_bank0_hw->io[i]));
    // }

    constexpr uint32_t kZ80ClockHz = 3'500'000;
    z80pio::ActiveBusDriver bus;
    bus.init(kZ80ClockHz);
    bus.reset_cpu();

    DebButton reset_btn;
    while (true) {
        const z80pio::BusRequest request = bus.read_request();

        // bool reset_requested = reset_btn.check(&z80_reset_button_pressed);

        // Assert RESET before replying so the currently stalled transaction
        // is the last one. Once the reply releases the CPU, the PIO reset
        // guard keeps subsequent samples out of the request FIFO.
        // if (reset_requested)
        //     bus.begin_reset();

        request.dump(zx.peek(request.address()));

        bus.write_reply(zx.service_pio_request(request));

        // if (reset_requested) {
        //     bus.end_reset();
        //     printf("Z80 reset from GPIO40 button\n");
        // }
    }
}

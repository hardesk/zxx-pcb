#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <algorithm>
// #include <memory>

#include <pico/stdlib.h>
#include <pico/stdio.h>
#include <hardware/gpio.h>

using std::size_t;

#define PIN_DEBUG 1

enum Pins {
	pD0  =  0,
	pD1  =  1,
	pD2  =  2,
	pD3  =  3,

	pD4  =  4,
	pD5  =  5,
	pD6  =  6,
	pD7  =  7,

	pA0  =  8,
	pA1  =  9,
	pA2  = 10,
	pA3  = 11,

	pA4  = 12,
	pA5  = 13,
	pA6  = 14,
	pA7  = 15,

	pA8  = 16,
	pA9  = 17,
	pA10 = 18,
	pA11 = 19,

	pA12 = 20,
	pA13 = 21,
	pA14 = 22,
	pA15 = 23,

	pCLK = 24,      // cpu in 
    pRESET = 25,    // cpu in
    pINT = 26,      // cpu in
    pHALT = 27,     // cpu out

	pMREQ = 28,     // cpu out
    pIORQ = 29,     // cpu out
	pWR = 30,       // cpu out
	pRD = 31,       // cpu out

    pWAIT = 32,     // cpu in
    pNMI = 33,      // cpu in
    pBUSRQ = 34,    // cpu in
    pBUSACK = 35,   // cpu out

    pPIN_COUNT
};

#define IO_DATA_SHIFT 0
#define IO_DATA 0x0000'00ffu
#define IO_ADDR_SHIFT 8
#define IO_ADDR 0x00ff'ff00u
#define IO_CTRL 0xf'ff00'0000ull
#define IO_CTRL_SHIFT 24
#define IO_CTRLL_WIDTH 8
#define IO_CTRLH_WIDTH 4
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
            bool CLK:1, RESET:1, INT:1, HALT:1, MREQ:1, IORQ:1, WR:1, RD:1, WAIT:1, NMI:1, BUSREQ:1, BUSACK:1;
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
        printf("T%4d %04x %02x clk %d rst %d int %d halt %d mreq %d iorq %d wr %d rd %d wait %d nmi %d busreq %d busack %d\n",
            T, addr, data,
            pins.CLK, pins.RESET, pins.INT, pins.HALT, pins.MREQ, pins.IORQ, pins.WR, pins.RD, pins.WAIT, pins.NMI, pins.BUSREQ, pins.BUSACK
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

    #define DAT(x) (addr_data&0xffu)
    #define ADR(x) ((addr_data&0xffffu) >> 8u)

    #define IS_LO(pin,bits) ((bits & (1U<<(pin-IO_CTRL_SHIFT))) == 0)
    #define IS_HI(pin,bits) ((bits & (1U<<(pin-IO_CTRL_SHIFT))) != 0)

    uint16_t m_ctrl_prev = (uint16_t)(IO_CTRL>>IO_CTRL_SHIFT);

    // ctrl is shifted to 0 bits
    void react(uint16_t ctrl, uint32_t addr_data) {
        uint32_t ctrlx = m_ctrl_prev ^ ctrl; // =1 which signal changed
        m_ctrl_prev = ctrl;

        // MEMORY ACCESS
        if (IS_LO(pMREQ, ctrl)) {
            // CPU WRITEs
            if (IS_LO(pWR, ctrl) && IS_HI(pWR, ctrlx)) {
                if (ADR(addr_data) == 0) {
                    self().impl_debug_trap(DAT(addr_data));
                }
                m_ram[ADR(addr_data)] = DAT(addr_data);
            } else
            // CPU READs
            if (IS_LO(pRD, ctrl) && IS_HI(pRD, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = m_ram[addr];
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
        bool address:1 = true;
        bool ascii:1 = false;
    };

    void dump_memory(unsigned addr, size_t size, MemoryDumpOpts opts = MemoryDumpOpts()) {
        for (size_t i=0; i<size; ) {
            char const* pl = m_ram + addr + i;
            size_t mx = std::min(size-i, (size_t)opts.width);
            if (opts.address)
                printf("%08x  ", addr + i);
            for (size_t q=0; q<mx; ++q)
                printf("%02x%s", pl[q], q == mx-1 ? "" : " ");
            printf("%*s", 1 + (opts.width-mx)*3, "");
            if (opts.ascii)
                for (size_t q=0; q<mx; ++q)
                    printf("%c", pl[q] >= 32 && pl[q] <= 127 ? pl[q] : '.' );
            printf("\n");
            i += mx;
        }
    }

private:
    void impl_debug_trap(uint8_t trapno) {}
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
    
    static constexpr uint64_t kInitOne = (1ull<<pINT) | (1ull<<pWAIT) | (1ull<<pNMI) | (1ull<<pBUSRQ);

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
        gpio_set_dir_all_bits64(pins_oe);
        gpio_put_all64(kInitOne);
    }

    void expose_data(uint8_t dat) {
        gpio_set_dir_masked(IO_DATA, IO_DATA);
        gpio_put_masked(IO_DATA, dat << IO_DATA_SHIFT);
    }

    void clear_data_bus() {
        gpio_set_dir_masked(IO_DATA, 0);
    }

    void handle_io_out(uint16_t addr, uint8_t data) {}
    uint8_t handle_io_in(uint16_t addr) { return 0; }

    void half_clk(bool raise) {
        gpio_put(pCLK, raise);
    }

    void reset() {
        #if PIN_DEBUG
        printf("ZxEnv: Resetting CPU.\n");
        #endif
        gpio_put_masked64(kInitOne, kInitOne);
        gpio_put_masked(1u<<pRESET, 0u);
        for(size_t i=0; i<64; ++i) {
            half_clk((i&1) == 0);
            #if PIN_DEBUG
            ZxDbgPins dbg(gpio_get_all64());
            dbg.dump_state(i);
            #endif
            sleep_us(1);
        }
        gpio_put_masked64((1u<<pRESET), (1u<<pRESET));
        #if PIN_DEBUG
        printf("ZxEnv: Reset finished.\n");
        ZxDbgPins dbg(gpio_get_all64());
        dbg.dump_state(7);
        #endif
    }

    void prepare_trap(unsigned offset = 0) {
        auto prep = [](uint8_t*& code, auto... bytes) -> void {
            (( *code++ = bytes), ... );
        };
        uint8_t* start = (uint8_t*)&m_ram[offset];
        uint8_t* p = start;
        prep(p, 0xc3, 0x00, 0x01);                  // jp 0x100
        prep(p, 0x00, 0x00, 0x00, 0x00, 0x00);
        assert(p - start == 8);
        prep(p, 0xed, 0x43, 0x80, 0x00);            // ld (0x0080), bc
        prep(p, 0xed, 0x53, 0x82, 0x00);            // ld (0x0082), de
        prep(p, 0x3e, 0x01);                        // ld a, 1
        prep(p, 0x32, 0x00, 0x00);                  // ld (0), a <-- trigger trap
        prep(p, 0xc9);                              // ret
    }

    void load(unsigned char const* data, size_t size, uint16_t origin) {
        unsigned char* dest = (unsigned char*)m_ram + origin;
        memcpy(dest, data, size);
    }

private:
    void impl_debug_trap(uint8_t trapno) {
        if (trapno == 1) {
            //uint16_t bc = *(uint16_t*)(m_ram+0x80);
            uint8_t c = *(m_ram+0x80);
            uint16_t de = *(uint16_t*)(m_ram+0x82);
            uint8_t e = de&0xff;
            if (c == 2) {
                printf("%c", e);
            } else if (c==9) {
                char const* str = (char const*)m_ram + de;
                while (*str != '$') {
                    printf("%c", *str++);
                }
            }
        }
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

void blink_hello() {
    for(size_t i=0; i<10; ++i) {
        gpio_put(LED_PIN, (i&1) == 0);
        sleep_ms(50);
    }
}

// #if __has_include("zexdoc.h")
// #include "zexdoc.h"
// #define z80_prog zexdoc
// #endif

#if __has_include("test.h")
#include "test.h"
#define z80_prog test_prog
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
    zx.reset();

    zx.prepare_trap();
    //zx.load(copy_str_code, count_of(copy_str_code), 0x100);
    zx.load(z80_prog, count_of(z80_prog), 0x100);
    zx.dump_memory(0, 512, { .width = 16, .ascii = true } );

    uint64_t tick = 0;
    unsigned clk_level = 0;

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

    printf("pins oe hi %08x lo %08x func-A0 %d outlevel-A0 %d\n", sio_hw->gpio_hi_oe, sio_hw->gpio_oe, gpio_get_function(pA0), gpio_get_out_level(pA0));
    printf(" oe h %08x l %08x\n", sio_hw->gpio_hi_oe, sio_hw->gpio_oe);
    for (int i=0; i<36; ++i){
        printf(" - pin %2d func %d oe %d PAD [[ %s ]]\n", i, gpio_get_function(i), gpio_get_dir(i), fmt_pad(pads_bank0_hw->io[i]));
    }

    while (1) {
        zx.half_clk(clk_level==0);

        #if 0
        uint64_t addr_data_ctrl = gpio_get_all64();
        uint16_t ctrl_shifted = extract_ctrl(addr_data_ctrl); 
        #else
        uint32_t addr_data_ctrl = gpio_get_all();
        uint32_t ctrlhi = gpio_get_all_hi();
        uint16_t ctrl_shifted = extract_ctrl(addr_data_ctrl, ctrlhi);
        #endif
#if PIN_DEBUG
        // printf("pins hilo %08x %08x\n", gpio_get_all_hi(), gpio_get_all());
#endif 

        ZxDbgPins dbg(addr_data_ctrl, ctrlhi);
        // if (clk_level == 0)// && dbg.pins.RD == 0 && dbg.pins.MREQ == 0)
            dbg.dump_state(tick);

        zx.react(ctrl_shifted, addr_data_ctrl & (IO_ADDR|IO_DATA));

        clk_level = 1u - clk_level;
        if (clk_level == 0)
            ++tick;

        // if ((tick & 0x0f'ffffull) == 0) {
        //     gpio_put(LED_PIN, true);
        // } else if ((tick & 0x0f'ffffull) == 10000u) {
        //     gpio_put(LED_PIN, false);
        // }
    }
}
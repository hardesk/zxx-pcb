#include <cstddef>
#include <cstdint>
// #include <memory>

#include <pico/stdlib.h>
#include <pico/stdio.h>
#include <hardware/gpio.h>

using std::size_t;

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
	pA12 = 21,
	pA13 = 22,
	pA14 = 23,
	pA15 = 24,

	pCLK = 0,
	pMREQ = 1,
    pIORQ = 2,
	pRD = 3,
	pWR = 4,
    pRESET = 5,
    pINT = 6,
};

template<class DerivedT>
struct ZxEnv
{
    // typedef uint8_t (*f_io_read_t)(uint16_t addr);
    // typedef void (*f_io_write_t)(uint16_t addr, uint8_t data);

    DerivedT& self() { return *static_cast<DerivedT*>(this); }

    char* m_ram;
    size_t m_ram_size;

    // f_io_read_t m_io_read = NULL;
    // f_io_write_t m_io_write = NULL;

    // struct OutState
    // {
    //     uint8_t data;
    //     uint16_t ctrl, ctrl_mask;
    // };

    // uin8_t m_data_temp;

    // enum { sMREQ=1U<<pMREQ, sIORQ=1U<<pIORQ, sWR=1U<<pWR, sRD=1U<<pRD, sRESET=1<<pRESET, sINT=1<<pINT };

    #define DAT(x) ((addr_data&0xff0000u)>>16)
    #define ADR(x) (addr_data&0xffffu)

    #define IS_LO(pin,bits) ((bits & (1U<<pin)) == 0)
    #define IS_HI(pin,bits) ((bits & (1U<<pin)) != 0)

    uint16_t m_ctrl_prev = 0xffffu;

    void react(uint16_t ctrl, uint32_t addr_data) {
        // INT, NMI, HALT, 
        // MREQ, IORQ, WR, RD, WAIT, RFSH, M1, RESET, 
        // BUSACK, BUSRQ
        uint16_t ctrlx = m_ctrl_prev ^ ctrl; // =1 which signal changed
        m_ctrl_prev = ctrl;

        // MEMORY ACCESS
        if (IS_LO(pMREQ, ctrl)) {
            // CPU WRITEs
            if (IS_LO(pWR, ctrl) && IS_HI(pWR, ctrlx)) {
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
};

#define IO_DATA 0x000000ffu
#define IO_ADDR 0x00ffff00u
#define IO_CTRL 0x0000ffffu // mask for high 32bit gpios, need to shift left by 32 to get full mask
#define IO_CTRL_BASE 32u
#define IO_ALL ((uint64_t)IO_DATA|(uint64_t)IO_ADDR|(uint64_t)IO_CTRL<<32u)

struct Rp2350ZxEnv : public ZxEnv<Rp2350ZxEnv>
{
    void init() {
        for(size_t i=0; i<32; ++i) {
            gpio_set_dir_in_masked64(IO_ALL);
            gpio_put_all64(0u);
            gpio_set_function_masked64(IO_ALL, GPIO_FUNC_SIO);
        }

        gpio_set_dir_out_masked64(
            (1ull << (IO_CTRL_BASE + pCLK))       |
            (1ull << (IO_CTRL_BASE + pRESET))
        );
    }

    void expose_data(uint8_t dat) {
        gpio_set_dir_masked(IO_DATA, IO_DATA);
        gpio_put_masked(IO_DATA, dat);
    }

    void clear_data_bus() {
        gpio_set_dir_masked(IO_DATA, 0);
    }

    void handle_io_out(uint16_t addr, uint8_t data) {}
    uint8_t handle_io_in(uint16_t addr) { return 0; }

    void half_clk(bool raise) {
        gpio_put(IO_CTRL_BASE + pCLK, raise);
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

int main()
{
    stdio_init_all();

    gpio_set_dir(LED_PIN, true);
    gpio_set_function(LED_PIN, GPIO_FUNC_SIO);
    for(size_t i=0; i<16; ++i) {
        gpio_put(LED_PIN, (i&1) == 0);
        sleep_ms(250);
    }

    Rp2350ZxEnv zx;
    zx.init();

    for(size_t i=0; i<64; ++i) {
        gpio_put_masked_n(1, 1u<<pRESET, 0u);
    }
    gpio_put_masked_n(1, 1u<<pRESET, 1u);

    uint64_t tick = 0;
    unsigned clk_level = 0;

    while (1) {
        zx.half_clk(clk_level==0);

        uint32_t addr_data = gpio_get_all();
        uint32_t ctrl = gpio_get_all_hi();
        zx.react(ctrl, addr_data);

        clk_level = 1u - clk_level;
        if (clk_level == 0)
            ++tick;

    }
}
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

	pRD  = 0,
	pWR,
	pMREQ,
    pIORQ,
    pRESET,
    pINT,
	pCLK,
};

template<class DerivedT>
struct ZxEnv
{
    // typedef uint8_t (*f_io_read_t)(uint16_t addr);
    // typedef void (*f_io_write_t)(uint16_t addr, uint8_t data);

    DerivedT& self() { return static_cast<DerivedT*>(this); }

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

    bool step(uint16_t ctrl, uint32_t addr_data) {
        OutState os = {};
        // INT, NMI, HALT, 
        // MREQ, IORQ, WR, RD, WAIT, RFSH, M1, RESET, 
        // BUSACK, BUSRQ
        uint16_t ctrlx = m_ctrl_prev ^ ctrl; // =1 which signal changed
        m_ctrl_prev = ctrl;

        bool out_active = false;

        // MEMORY ACCESS
        if (IS_LO(pMREQ, ctrl)) {
            // WRITE
            if (IS_LO(pWR, ctrl) && IS_HI(pWR, ctrlx) {
                m_ram[ADR(addr_data)] = DAT(addr_data);
                out_active = true;
            } else
            // READ
            if (IS_LO(pRD, ctrl) && IS_HI(pRD, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = m_ram[addr];
                // os.data = m_ram[];
                self().expose_data(dat);
                out_active = true;
            }
        } else if (IS_HI(pMREQ, ctrl) && IS_HI(pMREQ, ctrlx) {
            out_active = false;
        }
        // IO ACCESS
        if (IS_LO(pIORQ, ctrl)) {
            // WRITE
            if (IS_LO(pWR, ctrl) && IS_HI(pWR, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = DAT(addr_data);
                self().handle_io_out(addr, dat);
            } else
            // READ
            if (IS_LO(pRD, ctrl) && IS_HI(pRD, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = self().handle_io_in(addr);
                self().expose_data(dat);
            }
        } else if (IS_HI(pIORQ, ctrl) && IS_HI(pIORQ, ctrlx) {
            out_active = false;
        }

        return out_active;
    }
};

#ifndef LED_PIN
#define LED_PIN 25   // adjust to your board (e.g. on Pico it's 25)
#endif

struct Rp2350ZxEnv : public ZxEnv<Rp2350ZxEnv>
{
    void expose_data(uint8_t dat) {
        gpio_set_pins(GPIO_PORT_B, dat);
    }

    void handle_io_out() {}
    uint8_t handle_io_in() { return 0; }
};

#define IO_DATA 0x000000ffu
#define IO_ADDR 0x00ffff00u
#define IO_CTRL 0x0000ffffu

int main()
{
    stdio_init_all();
    gpio_init(LED_PIN);

    Rp2350ZxEnv zx;
    while (1) {

        sio_hw->gpio_oe = 0xffu;
        sio_hw->gpio_hi_oe = 0xffffu;

        gpio_set_dir


        if (zx.step(
        e.step(true, 0, 0);
    }

}
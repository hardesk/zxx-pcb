#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <algorithm>
// #include <memory>

#include <pico/stdlib.h>
#include <pico/stdio.h>
#include <hardware/gpio.h>
#include <hardware/clocks.h>
#include <hardware/vreg.h>
#include <hardware/structs/qmi.h>

#include "z80_pins.hpp"
#include "z80_pio_bus.hpp"
#include "z80_frame_interrupt.hpp"
#include "zx_keyboard.hpp"
#include "zx_ula.hpp"
#include "zx_tape.hpp"
#include "zx_tape_rtt.hpp"
#include "zx_disk.hpp"
#include "zx_disk_flash.hpp"
#include <atomic>
#include "zx_keyboard_rtt.hpp"
#include "roms/48.h"
#include "roms/128-0.h"
#include "roms/128-1.h"
#include "roms/128p-0.h"
#include "roms/trdos.h"
static_assert(sizeof(spectrum_128_0_rom) == 16384 && sizeof(spectrum_128_1_rom) == 16384);
static_assert(sizeof(trdos_rom) == 16384);
static_assert(sizeof(spectrum_48_rom) == 16 * 1024);
#include "scrs/Rambo.h"
#include "scrs/GameOver.h"
#include "scrs/RoboCop2.h"
static_assert(sizeof(rambo_scr) == 6912 && sizeof(gameover_scr) == 6912
              && sizeof(robocop2_scr) == 6912);
#ifndef Z80_WAIT_CAPTURE
#include <pico/multicore.h>
#include "zxdisplay.hpp"
#include <atomic>

namespace {
const std::atomic<const volatile uint8_t*>* core1_screen = nullptr;
const ZxUla* core1_ula = nullptr;
std::atomic<ZxDisplay*> core1_display{nullptr};

void display_core1() {
    // Acquire ownership after core0 has initialized the controller and buffer.
    ZxDisplay* display;
    while (!(display = core1_display.load(std::memory_order_acquire)))
        tight_loop_contents();
    // Disk writes program flash: core0 parks this core in SRAM meanwhile.
    multicore_lockout_victim_init();
    // Read the selected physical screen bank directly (5 or 7).
    // Z80 writes may become visible during conversion; there is no snapshot.
    constexpr uint64_t frame_us = 20000;
    constexpr uint64_t flash_half_period_us = 16 * frame_us;
    const uint64_t epoch = time_us_64();
    uint64_t next_frame = epoch;
    while (true) {
        const bool flash = ((time_us_64() - epoch) / flash_half_period_us) & 1;
        const auto* screen = core1_screen->load(std::memory_order_acquire);
        display->render(screen, flash, core1_ula); // Convert/transmit alternate eight-line buffers.
        next_frame += frame_us;
        const uint64_t now = time_us_64();
        // If rendering misses a deadline, resume immediately without building
        // up a backlog or dropping to a fixed 25 Hz schedule.
        if (next_frame < now) next_frame = now;
        // Stay on core1: sleep_until() may use the default alarm pool on
        // core0, adding timer interrupts to the time-sensitive bus service.
        busy_wait_until(from_us_since_boot(next_frame));
    }
}
} // namespace
#endif
#ifdef Z80_WAIT_CAPTURE
#include "tests/wait_capture.hpp"
#endif

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
            bool CLK:1, RESET:1, WAIT:1, M1:1, IORQ:1, MREQ:1, RD:1, WR:1,
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

    uint8_t peek(uint16_t addr) const {
        return static_cast<const DerivedT*>(this)->read_memory(addr);
    }

    uint8_t read_memory(uint16_t addr) const { return static_cast<uint8_t>(m_ram[addr]); }
    void write_memory(uint16_t addr, uint8_t data) {
        self().impl_debug_trap(addr, data);
        self().impl_on_memwrite(addr, data);
        m_ram[addr] = static_cast<char>(data);
    }

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
                self().write_memory(addr, dat);
            } else
            // CPU READs
            if (IS_LO(pRD, ctrl) && IS_HI(pRD, ctrlx)) {
                uint16_t addr = ADR(addr_data);
                uint8_t dat = peek(addr);
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
            size_t mx = std::min(size-i, (size_t)opts.width);
            if (opts.show_address)
                printf("%08x  ", addr + i);
            for (size_t q=0; q<mx; ++q)
                printf("%02x%s", peek(uint16_t(addr + i + q)), q == mx-1 ? "" : " ");
            printf("%*s", 1 + (opts.width-mx)*3, "");
            if (opts.ascii) {
                printf("%c", ' ');
                for (size_t q=0; q<mx; ++q) {
                    const uint8_t value = peek(uint16_t(addr + i + q));
                    printf("%c", value >= 32 && value <= 127 ? value : '.');
                }
            }
            printf("\n");
            i += mx;
        }
    }

protected:
    __attribute__((noinline)) void impl_debug_trap(uint16_t addr, uint8_t trapno) {}

    void impl_on_memread(uint16_t addr, bool m1) {}
    void impl_on_memwrite(uint16_t addr, uint8_t dat) {}
};

struct Rp2350ZxEnv : public ZxEnv<Rp2350ZxEnv>
{
    template<class T> friend class ZxEnv;

    Rp2350ZxEnv() {
        m_ram_size = 256*256;
        // Eight physical RAM banks plus the legacy RAM backing below 0x4000.
        // Keep banks 5/2/0 at their old flat addresses for the display and 48K use.
        m_ram = new char[9 * page_size]{};
        m_ram_banks[5] = m_ram + 0x4000;
        m_ram_banks[2] = m_ram + 0x8000;
        m_ram_banks[0] = m_ram + 0xc000;
        unsigned storage_page = 4;
        constexpr unsigned extra_banks[] = {1, 3, 4, 6, 7};
        for (unsigned bank : extra_banks)
            m_ram_banks[bank] = m_ram + page_size * storage_page++;
        for (unsigned page = 0; page < 4; ++page) {
            m_ram_pages[page] = m_ram + page_size * page;
            m_read_pages[page] = reinterpret_cast<const uint8_t*>(m_ram_pages[page]);
        }
        display_screen.store(reinterpret_cast<const volatile uint8_t*>(m_ram_banks[5]));
    }

    Rp2350ZxEnv(const Rp2350ZxEnv&) = delete;
    Rp2350ZxEnv& operator=(const Rp2350ZxEnv&) = delete;

    ~Rp2350ZxEnv() {
        delete[] m_ram;
    }
    
    static constexpr uint64_t kInitialHighPins =
        (1ull << pINT) | (1ull << pWAIT) | (1ull << pNMI) | (1ull << pBUSRQ);
    static constexpr uint16_t CPM_TRAP_TRIGGER = 0x03;
    static constexpr uint16_t CPM_TRAP_CODE = 0xffe0; // Note: zexall sets SP to address at (6)
    static constexpr uint16_t CPM_TRAP_STORE = 0xfff0;

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

    void __no_inline_not_in_flash_func(handle_io_out)(uint16_t addr, uint8_t data) {
        // Independent partial decoders: an even paging alias reaches both.
        if (!(addr & 1)) ula.write(data);
        if (m_trdos && ZxBetaDisk::decodes(addr)) m_beta->write(addr, data, time_us_32());
        if (m_128k && !(addr & 0x8002) && !(m_paging & 0x20)) {
            m_paging = data & 0x3f;
            select_ram_bank(data & 7);
            select_rom((data >> 4) & 1);
            display_screen.store(reinterpret_cast<const volatile uint8_t*>(
                m_ram_banks[(data & 8) ? 7 : 5]), std::memory_order_release);
        }
        if (addr == 0xff81) {
            printf("DATA on port %04x: %02x\n", addr, data);
        } else if (addr == 0xff83) {
            printf("%c", data);
        }
    }
    ZxKeyboard keyboard;
    ZxUla ula;
    ZxTape tape;
    std::atomic<const volatile uint8_t*> display_screen{nullptr};

    // ROM slots 0/1 must contain the 128 editor and its companion BASIC ROM.
    bool enable_128k() {
        if (!m_roms[0] || !m_roms[1]) return false;
        m_128k = true;
        reset_machine();
        return true;
    }
    uint8_t paging_register() const { return m_paging; }
    void reset_machine() {
        // Reset mapping/peripherals, not physical RAM. Call with RZ80 held reset.
        m_paging = 0;
        m_rom_mask = 0;
        m_trdos = false;
        m_ram_pages[0] = m_ram;
        m_ram_pages[1] = m_ram_banks[5];
        m_ram_pages[2] = m_ram_banks[2];
        for (unsigned page=0;page<3;++page)
            m_read_pages[page]=reinterpret_cast<const uint8_t*>(m_ram_pages[page]);
        select_ram_bank(0);
        select_rom(0);
        display_screen.store(reinterpret_cast<const volatile uint8_t*>(m_ram_banks[5]),
                             std::memory_order_release);
        ula.reset();
        keyboard.clear();
        tape.reset();
        if (m_beta) {
            m_beta->reset();
            m_disks->flush();
        }
    }

    uint8_t __no_inline_not_in_flash_func(handle_io_in)(uint16_t port) {
        if (m_trdos && ZxBetaDisk::decodes(port)) return m_beta->read(port, time_us_32());
        uint8_t fast_byte;
        if (tape.fast_io(port, fast_byte)) return fast_byte;
        if (port & 1) return 0xff;
        const uint8_t value = ula.read(keyboard, port);
        return tape.has_tape() ? uint8_t((value & ~0x40) | (tape.read_ear() ? 0x40 : 0)) : value;
    }

    uint8_t handle_interrupt_ack() { return 0xff; }

    static constexpr unsigned page_size = 0x4000;
    static constexpr unsigned max_roms = 4, ram_bank_count = 8;

    // Register a borrowed 16 KiB ROM in a numbered slot (0..3). Registration
    // does not select it. Keep the data alive; call mapping APIs on core0 only.
    bool add_rom(const unsigned char* data, size_t size, unsigned bank) {
        if (!data || size != page_size || bank >= max_roms || m_roms[bank]) return false;
        m_roms[bank] = data;
        // Timing profile is only valid for the standard ROM tape routine.
        m_rom_has_loader[bank] = memcmp(data+0x0556, standard_loader_code,
                                        sizeof(standard_loader_code)) == 0;
        return true;
    }

    // Normally page=0; other 16 KiB CPU slots can also be write-protected ROM.
    bool select_rom(unsigned bank, unsigned page = 0) {
        if (bank >= max_roms || page >= 4 || !m_roms[bank]) return false;
        m_rom_mask |= uint8_t(1u << page);
        if (page == 0) {
            m_rom_bank = bank;
            // TR-DOS overrides page 0 until the CPU leaves it; 7FFD only
            // chooses the ROM that comes back.
            if (m_trdos) { update_beta_trap(); return true; }
        }
        m_rom_pages[page] = m_roms[bank];
        m_read_pages[page] = m_roms[bank];
        if (page == 0) {
            m_standard_loader_rom = m_rom_has_loader[bank];
            update_beta_trap();
        }
        return true;
    }

    bool unmap_rom(unsigned page = 0) {
        if (page >= 4) return false;
        m_rom_mask &= uint8_t(~(1u << page));
        m_read_pages[page] = reinterpret_cast<const uint8_t*>(m_ram_pages[page]);
        if (page == 0) {
            m_standard_loader_rom = false;
            if (m_trdos) leave_trdos();
            update_beta_trap();
        }
        return true;
    }

    // Select RAM at 0xc000..0xffff. Banks 5 and 2 alias the fixed lower slots.
    bool select_ram_bank(unsigned bank) {
        if (bank >= ram_bank_count) return false;
        m_ram_pages[3] = m_ram_banks[bank];
        m_read_pages[3] = reinterpret_cast<const uint8_t*>(m_ram_banks[bank]);
        m_rom_mask &= uint8_t(~(1u << 3));
        return true;
    }

    uint8_t read_memory(uint16_t addr) const {
        // Paging changes select the pointer; every bus read is one lookup.
        return m_read_pages[addr >> 14][addr & (page_size - 1)];
    }

    void write_memory(uint16_t addr, uint8_t data) {
        const unsigned page = addr >> 14;
        if (m_rom_mask & (1u << page)) return;
        if (!m_128k && page==0) impl_debug_trap(addr, data);
        impl_on_memwrite(addr, data);
        m_ram_pages[page][addr & (page_size - 1)] = static_cast<char>(data);
    }

    // True for MREQ+RD (fetch or read) while no tape loader observes the CPU.
    // Also false inside the Beta 128 paging window (see beta_fetch).
    __attribute__((always_inline)) bool fast_memory_read(z80pio::BusRequest request) const {
        return !(request.raw & (z80pio::kRawMreq | z80pio::kRawRd)) && !tape.observes_cpu() &&
               uint32_t(uint16_t(request.address() - m_trap_base)) >= m_trap_length;
    }

    // MREQ+WR to RAM in 128K mode (no 48K CP/M trap). ROM pages ignore writes.
    __attribute__((always_inline)) bool fast_memory_write(z80pio::BusRequest request) {
        if ((request.raw & (z80pio::kRawMreq | z80pio::kRawWr)) || !m_128k) return false;
        const uint16_t addr = request.address();
        const unsigned page = addr >> 14;
        if (!(m_rom_mask & (1u << page)))
            m_ram_pages[page][addr & (page_size - 1)] = static_cast<char>(request.data());
        return true;
    }

    // Complete request handling; the bus loop inlines only the fast paths.
    uint32_t __no_inline_not_in_flash_func(service_pio_request)(z80pio::BusRequest request) {
        const uint16_t addr = request.address();
        const uint8_t data = request.data();

        if (request.mreq()) {
            if (request.rd()) {
                if (request.m1()) beta_fetch(addr);
                uint8_t value = read_memory(addr);
                // Only the ROM loader and its first outgoing fetch need tape work.
                // Ordinary ROM/RAM reads never run the tape state machine.
                if (tape.observes_cpu() &&
                    ((m_standard_loader_rom && uint16_t(addr-0x0556)<=0x00ae) ||
                     tape.loader_call_active()))
                    value = service_tape_read(addr, value, request.m1());
                return z80pio::read_reply(value);
            }

            if (request.wr()) {
                write_memory(addr, data);
                return z80pio::write_reply();
            }
        }

        if (request.iorq()) {
            if (request.rd())
                return z80pio::read_reply(handle_io_in(addr));

            if (request.wr()) {
                handle_io_out(addr, data);
                return z80pio::write_reply();
            }
            if (request.m1())
                return z80pio::read_reply(handle_interrupt_ack());
        }

        return z80pio::write_reply();
    }

    uint8_t __no_inline_not_in_flash_func(service_tape_read)(uint16_t addr, uint8_t value, bool m1) {
        if (m1 && tape.observes_cpu()) tape.observe_fetch(addr,value,m_standard_loader_rom);
        return m_standard_loader_rom ? tape.rom_byte(addr,value) : value;
    }

    // Beta 128: TR-DOS (in ROM slot rom_bank) replaces the 48 BASIC ROM
    // (slot basic_bank) at an opcode fetch from 3D00..3DFF, and leaves at
    // an opcode fetch from RAM (4000h up). Its ports decode only meanwhile.
    bool enable_beta(ZxBetaDisk& beta, ZxDiskStore& disks, unsigned rom_bank, unsigned basic_bank) {
        if (rom_bank >= max_roms || !m_roms[rom_bank] || basic_bank >= max_roms) return false;
        m_beta = &beta; m_disks = &disks;
        m_trdos_bank = rom_bank; m_basic_bank = basic_bank;
        beta.reset();
        update_beta_trap();
        return true;
    }
    bool trdos_active() const { return m_trdos; }

    void __no_inline_not_in_flash_func(beta_fetch)(uint16_t addr) {
        if (uint32_t(uint16_t(addr - m_trap_base)) >= m_trap_length) return;
        if (m_trdos) {
            leave_trdos();
        } else {
            m_trdos = true;
            m_rom_pages[0] = m_roms[m_trdos_bank];
            m_read_pages[0] = m_roms[m_trdos_bank];
            m_standard_loader_rom = false;
        }
        update_beta_trap();
    }

    template<class... Bytes>
    static char* store_bytes(char* p, Bytes... bytes) { ( (*p++ = bytes), ... ); return p; }

    void prepare_vectors(uint16_t jump_on_reset_addr = 0x100) {
        store_bytes( m_ram + 0, 0xc3, jump_on_reset_addr & 0xff, jump_on_reset_addr >> 8);
        store_bytes( m_ram + CPM_TRAP_TRIGGER, 0, 0);

        // hook up to CP/M call 5
        store_bytes(m_ram + 5, 0xc3, CPM_TRAP_CODE, CPM_TRAP_CODE >> 8);    // jp CPM_TRAP_CODE

        // by default 0x100 jumps to 0x8000
        store_bytes(m_ram + 0x100, 0xc3, 0x00, 0x80);    // jp 0x8000

        char* p = ram_pointer(CPM_TRAP_CODE);
        p = store_bytes(p, 0xed, 0x43, CPM_TRAP_STORE, CPM_TRAP_STORE >> 8);    // ld (CPM_TRAP_STORE+0), bc
        p = store_bytes(p, 0xed, 0x53, CPM_TRAP_STORE+2, CPM_TRAP_STORE >> 8);  // ld (CPM_TRAP_STORE+2), de
        p = store_bytes(p, 0x3e, 0x01);                                 // ld a, 1
        p = store_bytes(p, 0x32, CPM_TRAP_TRIGGER, CPM_TRAP_TRIGGER >> 8);      // ld (CPM_TRAP_TRIGGER), a <-- trigger trap
        p = store_bytes(p, 0xc9);                                       // ret
    }

    template<class... Bytes>
    void fill(uint16_t addr, uint16_t count, Bytes... bytes) {
        static_assert(sizeof...(bytes) > 0);
        if (!count) return;
        uint8_t templ[] = { static_cast<uint8_t>(bytes)... };
        unsigned written = 0;
        do {
            char* p = ram_pointer(uint16_t(addr + written));
            unsigned i = written % sizeof(templ);
            *p = templ[i];
        } while(++written, --count);
    }

    void load(unsigned char const* data, size_t size, uint16_t origin) {
        // Host loading bypasses ROM protection but targets the mapped RAM
        // underneath it. Split at page boundaries, including a banked top page.
        if (!data || size > 0x10000u - unsigned(origin)) return;
        unsigned address = origin;
        while (size) {
            const size_t chunk = std::min(size, size_t(page_size - (address & (page_size - 1))));
            memcpy(ram_pointer(uint16_t(address)), data, chunk);
            address += chunk;
            data += chunk;
            size -= chunk;
        }
    }

private:
    static constexpr uint8_t standard_loader_code[] = {
        0x14, 0x08, 0x15, 0xf3, 0x3e, 0x0f, 0xd3, 0xfe, 0x21, 0x3f, 0x05, 0xe5, 0xdb, 0xfe, 0x1f, 0xe6,
        0x20, 0xf6, 0x02, 0x4f, 0xbf, 0xc0, 0xcd, 0xe7, 0x05, 0x30, 0xfa, 0x21, 0x15, 0x04, 0x10, 0xfe,
        0x2b, 0x7c, 0xb5, 0x20, 0xf9, 0xcd, 0xe3, 0x05, 0x30, 0xeb, 0x06, 0x9c, 0xcd, 0xe3, 0x05, 0x30,
        0xe4, 0x3e, 0xc6, 0xb8, 0x30, 0xe0, 0x24, 0x20, 0xf1, 0x06, 0xc9, 0xcd, 0xe7, 0x05, 0x30, 0xd5,
        0x78, 0xfe, 0xd4, 0x30, 0xf4, 0xcd, 0xe7, 0x05, 0xd0, 0x79, 0xee, 0x03, 0x4f, 0x26, 0x00, 0x06,
        0xb0, 0x18, 0x1f, 0x08, 0x20, 0x07, 0x30, 0x0f, 0xdd, 0x75, 0x00, 0x18, 0x0f, 0xcb, 0x11, 0xad,
        0xc0, 0x79, 0x1f, 0x4f, 0x13, 0x18, 0x07, 0xdd, 0x7e, 0x00, 0xad, 0xc0, 0xdd, 0x23, 0x1b, 0x08,
        0x06, 0xb2, 0x2e, 0x01, 0xcd, 0xe3, 0x05, 0xd0, 0x3e, 0xcb, 0xb8, 0xcb, 0x15, 0x06, 0xb0, 0xd2,
        0xca, 0x05, 0x7c, 0xad, 0x67, 0x7a, 0xb3, 0x20, 0xca, 0x7c, 0xfe, 0x01, 0xc9, 0xcd, 0xe7, 0x05,
        0xd0, 0x3e, 0x16, 0x3d, 0x20, 0xfd, 0xa7, 0x04, 0xc8, 0x3e, 0x7f, 0xdb, 0xfe, 0x1f, 0xd0, 0xa9,
        0xe6, 0x20, 0x28, 0xf3, 0x79, 0x2f, 0x4f, 0xe6, 0x07, 0xf6, 0x08, 0xd3, 0xfe, 0x37, 0xc9,
    };
    void leave_trdos() {
        m_trdos = false;
        if (m_rom_mask & 1) {
            const unsigned char* rom = m_roms[m_rom_bank];
            m_rom_pages[0] = rom;
            m_read_pages[0] = rom;
            m_standard_loader_rom = m_rom_has_loader[m_rom_bank];
        }
    }
    void update_beta_trap() {
        if (m_beta && m_trdos) {
            m_trap_base = 0x4000; m_trap_length = 0xc000;
        } else if (m_beta && (m_rom_mask & 1) && m_rom_bank == m_basic_bank) {
            m_trap_base = 0x3d00; m_trap_length = 0x100;
        } else {
            m_trap_base = 0; m_trap_length = 0;
        }
    }

    bool m_standard_loader_rom = false;
    bool m_128k = false;
    bool m_trdos = false;
    unsigned m_rom_bank = 0, m_trdos_bank = 0, m_basic_bank = 0;
    // fast_memory_read() leaves [m_trap_base, +m_trap_length) to beta_fetch().
    uint16_t m_trap_base = 0;
    uint32_t m_trap_length = 0;
    ZxBetaDisk* m_beta = nullptr;
    ZxDiskStore* m_disks = nullptr;
    uint8_t m_paging = 0;
    uint8_t m_rom_mask = 0; // Bit n: CPU addresses n*16K..(n+1)*16K-1 are ROM.
    const unsigned char* m_roms[max_roms]{}; // Registered ROM bank images.
    bool m_rom_has_loader[max_roms]{};
    const unsigned char* m_rom_pages[4]{};  // Selected ROM pointer per CPU page.
    char* m_ram_banks[ram_bank_count]{};
    char* m_ram_pages[4]{};
    const uint8_t* m_read_pages[4]{}; // Cached current ROM-or-RAM read mapping.

    char* ram_pointer(uint16_t addr) {
        return m_ram_pages[addr >> 14] + (addr & (page_size - 1));
    }

    __attribute__((noinline)) void impl_debug_trap(uint16_t addr, uint8_t trapno) {
        if (addr == 4) {
            printf("MEM4 <- %02x\n", trapno);
        }
        if (addr == CPM_TRAP_TRIGGER && trapno == 1) {
            uint8_t c = read_memory(CPM_TRAP_STORE);
            uint16_t de = read_memory(CPM_TRAP_STORE+2) | (uint16_t(read_memory(CPM_TRAP_STORE+3)) << 8);
            if (c == 2) {
                uint8_t e = de&0xff;
                printf("%c", e);
            } else if (c==9) {
                for (unsigned i = de; i < 0x10000; ++i) {
                    const uint8_t ch = read_memory(uint16_t(i));
                    if (ch == '$' || ch == 0) break;
                    printf("%c", ch);
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

constexpr uint kZ80ResetButtonPin = 38;

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

// Disk writes stay in the store's one-block cache until the drive has been
// quiet for a while; the flash write then holds the Z80 for one erase.
struct DiskFlushTimer {
    static constexpr uint32_t quiet_ms = 500;
    uint32_t written = 0, since = 0;
    void poll(ZxDiskStore& disks, const ZxBetaDisk& beta) {
        const uint32_t now = to_ms_since_boot(get_absolute_time());
        if (!disks.dirty() || beta.sectors_written() != written) {
            written = beta.sectors_written(); since = now;
        } else if (uint32_t(now - since) >= quiet_ms) {
            disks.flush();
        }
    }
};

ZxFlashDiskBackend disk_backend;
ZxDiskStore disk_store(disk_backend);
ZxBetaDisk beta_disk(disk_store);
DiskFlushTimer disk_flush_timer;

static __attribute__((noinline)) bool poll_z80_controls(Rp2350ZxEnv& zx,
    ZxKeyboardRtt& keyboard_rtt, ZxTapeRtt& tape_rtt, DebButton& reset_btn)
{
    keyboard_rtt.poll(zx.keyboard);
    tape_rtt.poll(zx.tape, &disk_store);
    disk_flush_timer.poll(disk_store, beta_disk);
    const bool keyboard_reset = keyboard_rtt.take_reset_request();
    const bool tape_reset = tape_rtt.take_reset_request();
    return reset_btn.check(&z80_reset_button_pressed) || keyboard_reset || tape_reset;
}

// Assert RESET before replying so the currently stalled transaction is the
// last one. Once the reply releases the CPU, the PIO reset guard keeps
// subsequent samples out of the request FIFO.
template<class RequestIo>
static void __no_inline_not_in_flash_func(reset_on_next_request)(Rp2350ZxEnv& zx,
    z80pio::ActiveBusDriver& bus, RequestIo& request_io,
    Z80FrameInterrupt& frame_interrupt, uint32_t kZ80ClockHz)
{
    z80pio::BusRequest request = request_io.read_request();
    // A posted write does not hold the CPU in WAIT. Keep servicing them until
    // a synchronous request parks it, then reset with that one outstanding.
    while (z80pio::ActiveBusDriver::posts_memory_writes && request.posted_write()) {
        (void)zx.service_pio_request(request);
        request = request_io.read_request();
    }
    frame_interrupt.stop();
    bus.begin_reset();
    request_io.write_reply(zx.service_pio_request(request));
    zx.reset_machine();
    bus.end_reset();
    frame_interrupt.start(kZ80ClockHz);
}

// SRAM avoids flash-cache misses in the request-to-reply path. Tape/RTT
// helpers remain separate, so normal memory transfers keep a small hot loop.
static void __no_inline_not_in_flash_func(run_z80_bus)(Rp2350ZxEnv& zx,
    z80pio::ActiveBusDriver& bus, ZxKeyboardRtt& keyboard_rtt,
    ZxTapeRtt& tape_rtt, Z80FrameInterrupt& frame_interrupt, uint32_t kZ80ClockHz)
{
    constexpr const unsigned char* screens[] = {rambo_scr, gameover_scr, robocop2_scr};
    unsigned next_screen = 0;
    absolute_time_t next_screen_time = get_absolute_time();
    DebButton reset_btn;
#if Z80_REPLY_DELAY_US > 0
    uint32_t delay_state = 1;
#endif
#ifdef Z80_WAIT_CAPTURE
    // Capture buffer is 4 KiB: keep it off the core's small stack.
    static WaitCapture capture;
    unsigned capture_request = 0;
#endif
    unsigned housekeeping_divider = 0;
#if Z80_BUS_MODE == Z80_BUS_MODE_ASYNC
    const auto request_io = bus.fifo_access();
#else
    auto& request_io = bus;
#endif
    while (true) {
        const z80pio::BusRequest request = request_io.read_request();

#if Z80_REPLY_DELAY_US > 0
        delay_state = delay_state * 1664525u + 1013904223u;
        busy_wait_us_32(delay_state % (Z80_REPLY_DELAY_US + 1u));
#endif

        // Ordinary MREQ+RD (fetch/read) with no tape observer and 128K RAM
        // writes are inline; everything else takes the outlined SRAM path.
        uint32_t reply;
        if (zx.fast_memory_read(request)) {
            reply = z80pio::read_reply(zx.read_memory(request.address()));
        } else if (z80pio::ActiveBusDriver::posts_memory_writes && request.posted_write()) {
            // Posted memory write: the CPU did not wait and takes no reply.
            // The shared FIFO keeps bus order. Housekeeping (and a requested
            // reset) only follows synchronous requests.
            if (!zx.fast_memory_write(request))
                (void)zx.service_pio_request(request);
            continue;
        } else {
            reply = zx.fast_memory_write(request) ? z80pio::write_reply()
                                                  : zx.service_pio_request(request);
        }
#ifdef Z80_WAIT_CAPTURE
        if (capture_request < 8)
            capture.start();
#endif
        request_io.write_reply(reply);
#ifdef Z80_WAIT_CAPTURE
        if (capture_request < 8)
            capture.finish(capture_request++);
#endif

        // Reply first. Bound host/button work to every 256 transfers instead
        // of doing timer checks and RTT parsing in every stalled transaction.
        // A requested reset completes on the next transaction, off the hot path.
        if ((++housekeeping_divider & 255u) == 0 &&
            poll_z80_controls(zx, keyboard_rtt, tape_rtt, reset_btn))
            reset_on_next_request(zx, bus, request_io, frame_interrupt, kZ80ClockHz);
    }
}

#ifndef RP_SYS_CLOCK_KHZ
#define RP_SYS_CLOCK_KHZ 300000
#endif

// Rewrite XIP timing while executing from SRAM; the next flash access uses it.
static void __no_inline_not_in_flash_func(set_flash_timing)(uint32_t clkdiv, uint32_t rxdelay)
{
    uint32_t timing = qmi_hw->m[0].timing;
    timing &= ~(QMI_M0_TIMING_CLKDIV_BITS | QMI_M0_TIMING_RXDELAY_BITS);
    qmi_hw->m[0].timing = timing | (clkdiv << QMI_M0_TIMING_CLKDIV_LSB) |
                          (rxdelay << QMI_M0_TIMING_RXDELAY_LSB);
    (void)qmi_hw->m[0].timing;
}

// The Z80 reply path is a fixed number of RP cycles, so its latency scales
// with clk_sys. LCD, CLK, PWM and counter dividers derive from clk_sys.
static void configure_system_clock()
{
    static_assert(RP_SYS_CLOCK_KHZ >= 150000 && RP_SYS_CLOCK_KHZ <= 300000);
    if constexpr (RP_SYS_CLOCK_KHZ != 150000) {
        vreg_set_voltage(VREG_VOLTAGE_1_20);
        busy_wait_us_32(1000);
        // Boot timing is clkdiv 3 / rxdelay 2 at 150 MHz (50 MHz SCK). Keep
        // SCK and sampling delay in nanoseconds before raising clk_sys.
        constexpr uint32_t scale_num = RP_SYS_CLOCK_KHZ, scale_den = 150000;
        set_flash_timing((3 * scale_num + scale_den - 1) / scale_den,
                         std::min<uint32_t>(7, (2 * scale_num + scale_den - 1) / scale_den));
        if (!set_sys_clock_khz(RP_SYS_CLOCK_KHZ, false)) panic("Unsupported RP_SYS_CLOCK_KHZ");
    }
}

int main()
{
    configure_system_clock();
    stdio_init_all();

    gpio_set_dir(LED_PIN, true);
    gpio_set_function(LED_PIN, GPIO_FUNC_SIO);
    blink_hello();

    Rp2350ZxEnv zx;
    zx.init();
    static ZxKeyboardRtt keyboard_rtt;
    keyboard_rtt.init();
    static ZxTapeRtt tape_rtt;
    tape_rtt.init();
    init_z80_reset_button();

    // 128K editor/menu ROM and companion 48K BASIC ROM. The Pentagon editor
    // (default) adds a TR-DOS menu item; its 48 BASIC ROM is the Spectrum's.
#if ZX_PENTAGON_ROM
    const unsigned char* const editor_rom = pentagon_128_0_rom;
#else
    const unsigned char* const editor_rom = spectrum_128_0_rom;
#endif
    if (!zx.add_rom(editor_rom, sizeof(spectrum_128_0_rom), 0) ||
        !zx.add_rom(spectrum_128_1_rom, sizeof(spectrum_128_1_rom), 1) ||
        !zx.enable_128k())
        panic("Failed to configure 128K ROMs");
    // Beta 128 / TR-DOS 5.03 in ROM slot 2, entered from 48 BASIC (slot 1),
    // e.g. RANDOMIZE USR 15616. Mounted images persist in flash.
    disk_store.load();
    if (!zx.add_rom(trdos_rom, sizeof(trdos_rom), 2) || !zx.enable_beta(beta_disk, disk_store, 2, 1))
        panic("Failed to configure TR-DOS");

    // CP/M test-program setup (disabled while booting the Spectrum ROM).
    // uint16_t prog_org = 0x8000;
    // zx.prepare_vectors(prog_org);
    // zx.load(z80_prog, count_of(z80_prog), prog_org);
    // zx.fill(0, 0, 0x7e);
    // zx.dump_memory(0, 32, { .width = 16, .ascii = true } );
    // zx.dump_memory(prog_org, 64, { .width = 16, .ascii = true } );

    printf("Hello from RP2350 over RTT!\n");
    for (unsigned d = 0; d < ZxDiskStore::drives; ++d)
        if (disk_store.present(d))
            printf("Disk %c: %s (%lu bytes)\n", 'A' + d, disk_store.info(d).name,
                   (unsigned long)disk_store.info(d).size);
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

    constexpr uint32_t kZ80ClockHz = Z80_CLOCK_HZ;
    printf("RZ80 speed %dkHz, RP %lukHz, bus driver '%s'\n", kZ80ClockHz/1000,
           (unsigned long)(clock_get_hz(clk_sys)/1000), z80pio::ActiveBusDriver::id);
    z80pio::ActiveBusDriver bus;
#ifndef Z80_WAIT_CAPTURE
    // Z80 remains held in reset while the LCD initializes. After launch,
    // core1 exclusively owns display conversion, commands, DMA and pacing.
    core1_screen = &zx.display_screen;
    core1_ula = &zx.ula;
    static ZxDisplay display;
    display.init_lcd();
    core1_display.store(&display, std::memory_order_release);
#else
    // WaitCapture needs PIO2 GPIO0..31; the LCD needs GPIO16..47.
    printf("LCD disabled: PIO2 reserved for WAIT capture\n");
#endif
    bus.init(kZ80ClockHz);
#ifndef Z80_WAIT_CAPTURE
    display.start_tstate_counter(kZ80ClockHz);
    multicore_launch_core1(display_core1);
#endif
    bus.reset_cpu();

    // Optional hardware 50 Hz active-low INT on GPIO32. At 5 MHz the
    // 32-T-state pulse rounds up to 7 us; no main-loop polling is needed.
    Z80FrameInterrupt frame_interrupt;
    frame_interrupt.start(kZ80ClockHz); // Required by the ROM keyboard scanner.
    // frame_interrupt.stop(); // Use before a later reset if interrupts were enabled.

    run_z80_bus(zx, bus, keyboard_rtt, tape_rtt, frame_interrupt, kZ80ClockHz);
}

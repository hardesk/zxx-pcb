#include <defs.h>
#include <stub.h>

#define NOPULL

#define reg_mprj_proj_sel (*(volatile uint32_t*)0x30100004)
#define reg_mprj_counter (*(volatile uint32_t*)0x30100008)
#define reg_mprj_settings (*(volatile uint32_t*)0x3010000C)

#define FREQ_CPU 7550000

//#define EARLY_SIGNALS

void delay(const unsigned d) {
	#if 1

	reg_timer0_config = 0;			// disable timer
	reg_timer0_data = d;			// load the start value
	reg_timer0_data_periodic = 0u;
	reg_timer0_irq_en = 0;
	reg_timer0_config = 1;			// enable timer

	do { 
		reg_timer0_update = 1;
		//reg_gpio_out = (reg_timer0_value >> 31) & 1;

		// on the chip at hand it appears that the timer does not stop at 0. check underflow manually
	} while (reg_timer0_value > 0 && reg_timer0_value <= d);

	#else
    for(uint64_t i=d>>2; i-- > 0; )
        (void)0;
	#endif
}

#define DELAY_US(us) delay(FREQ_CPU / 1000000 * (us))
#define DELAY_MS(ms) delay(FREQ_CPU / 1000 * (ms))

// this only works in -O0 builds
void ldelay(int d) {
    for(uint64_t i=d>>2; i-- > 0; )
        (volatile void)0;
}

void configure_io() {

#ifdef NOPULL
	// Pins [1-4] are used for flashing. If not INPUT, the setting will interfere with data transfer. If so,
	// keep RESET (of SOC) active while accessing the flash.
	reg_mprj_io_0 = GPIO_MODE_USER_STD_INPUT_NOPULL;	// /RESET
	reg_mprj_io_1 = GPIO_MODE_USER_STD_OUTPUT;			// /BUSACK [HK_SDO]
	reg_mprj_io_2 = GPIO_MODE_USER_STD_OUTPUT;			// /M1 [HK_SDI]
	reg_mprj_io_3 = GPIO_MODE_USER_STD_INPUT_NOPULL;	// [HK_CSB]
	reg_mprj_io_4 = GPIO_MODE_USER_STD_OUTPUT;			// /RD + [HK_SCK]
	reg_mprj_io_5 = GPIO_MODE_USER_STD_OUTPUT;			// /WR + [ser_rx]
	reg_mprj_io_6 = GPIO_MODE_USER_STD_INPUT_NOPULL;	// /WAIT + [ser_tx]
	reg_mprj_io_7 = GPIO_MODE_USER_STD_OUTPUT;			// /RFSH

	// io8:io23 -> A0:A15
	reg_mprj_io_8 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_9 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_10 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_11 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_12 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_13 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_14 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_15 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_16 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_17 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_18 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_19 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_20 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_21 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_22 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_23 = GPIO_MODE_USER_STD_OUTPUT;
	// io24:io31 -> D0:D7
	reg_mprj_io_24 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_25 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_26 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_27 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_28 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_29 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_30 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_31 = GPIO_MODE_USER_STD_BIDIRECTIONAL;

	reg_mprj_io_32 = GPIO_MODE_USER_STD_INPUT_NOPULL;	// /NMI
	reg_mprj_io_33 = GPIO_MODE_USER_STD_INPUT_NOPULL;	// /INT
	reg_mprj_io_34 = GPIO_MODE_USER_STD_OUTPUT;			// /HALT
	reg_mprj_io_35 = GPIO_MODE_USER_STD_OUTPUT;			// /MREQ
	reg_mprj_io_36 = GPIO_MODE_USER_STD_OUTPUT;			// /IORQ
	reg_mprj_io_37 = GPIO_MODE_USER_STD_INPUT_NOPULL;	// /BUSRQ
#else
	reg_mprj_io_0 = GPIO_MODE_USER_STD_INPUT_PULLUP;
	reg_mprj_io_1 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_2 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_3 = GPIO_MODE_MGMT_STD_INPUT_PULLUP;
	reg_mprj_io_4 = GPIO_MODE_USER_STD_OUTPUT;
	
	reg_mprj_io_5 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_6 = GPIO_MODE_USER_STD_INPUT_PULLUP;
	reg_mprj_io_7 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_8 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_9 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_10 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_11 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_12 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_13 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_14 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_15 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_16 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_17 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_18 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_19 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_20 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_21 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_22 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_23 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_24 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_25 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_26 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_27 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_28 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_29 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_30 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_31 = GPIO_MODE_USER_STD_BIDIRECTIONAL;
	reg_mprj_io_32 = GPIO_MODE_USER_STD_INPUT_PULLUP;
	reg_mprj_io_33 = GPIO_MODE_USER_STD_INPUT_PULLUP;
	reg_mprj_io_34 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_35 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_36 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_37 = GPIO_MODE_USER_STD_INPUT_PULLUP;
#endif
    reg_mprj_xfer = 1;
    while (reg_mprj_xfer == 1); // this condition works, tested
}

void main() {

	reg_wb_enable = 1;
	reg_uart_enable = 0;
	reg_gpio_mode1 = 1;
	reg_gpio_mode0 = 0;
	reg_gpio_ien = 1;
	reg_gpio_oe = 1;

	for (int i=3; i --> 0; ) {
		reg_gpio_out = 1;
		DELAY_MS(80);
		reg_gpio_out = 0;
		DELAY_MS(80);
	}

	reg_mprj_counter = 0;
	configure_io();

	reg_spi_enable = 0;

    reg_mprj_proj_sel = 0b00101;
#ifdef EARLY_SIGNALS
	reg_mprj_settings = 1+65536;
#else
	reg_mprj_settings = 65536;
#endif
	reg_mprj_proj_sel = 0b00100;

	unsigned cycle = 0;
	while(1) {
		unsigned dels[] = { FREQ_CPU / 1000 * 40, FREQ_CPU / 1000 * 80, FREQ_CPU / 1000 * 70, FREQ_CPU / 1000 * 650 };

		unsigned x = cycle & 3;
		unsigned l = 1 - (cycle & 1);

        reg_gpio_out = l;
		delay(dels[x]);

		cycle++;
	}
}

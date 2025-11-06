#include <defs.h>
#include <stub.h>

#define NOPULL

#define reg_mprj_proj_sel (*(volatile uint32_t*)0x30100004)
#define reg_mprj_counter (*(volatile uint32_t*)0x30100008)
#define reg_mprj_settings (*(volatile uint32_t*)0x3010000C)

//#define EARLY_SIGNALS

void configure_io() {

#ifdef NOPULL
	reg_mprj_io_0 = GPIO_MODE_USER_STD_INPUT_PULLUP;	// /RESET (using with the pullup as board v1 misses a pullup resistor) 
	//reg_mprj_io_0 = GPIO_MODE_USER_STD_INPUT_NOPULL;	// /RESET
	reg_mprj_io_1 = GPIO_MODE_USER_STD_OUTPUT;			// /BUSACK
	reg_mprj_io_2 = GPIO_MODE_USER_STD_OUTPUT;			// /M1
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
	// io24:io31 -> D9:D7
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
    while (reg_mprj_xfer == 1);
}

void delay(const int d) {
	#if 0
	reg_timer0_config = 0;
	reg_timer0_data = d;
	reg_timer0_config = 1;

	reg_timer0_update = 1;
	while (reg_timer0_value > 0) {
		reg_timer0_update = 1;
	}
	#else
    for(uint64_t i=d>>3; i-- > 0; )
        (void)0;
	#endif
}

void mydelay(const int del)
{
    for(int i=del*2; i-- > 0; )
        (void)0;
}

void main() {

#if 1 // from blink.c
    reg_gpio_mode1 = 1;
    reg_gpio_mode0 = 0;
    reg_gpio_ien = 1;
    reg_gpio_oe = 1;

    // Configure All LA probes as inputs to the cpu
	reg_la0_oenb = reg_la0_iena = 0x00000000;    // [31:0]
	reg_la1_oenb = reg_la1_iena = 0x00000000;    // [63:32]
	reg_la2_oenb = reg_la2_iena = 0x00000000;    // [95:64]
	reg_la3_oenb = reg_la3_iena = 0x00000000;    // [127:96]

    print("Hello World !!\n");
#else
	reg_wb_enable = 1;
	reg_uart_enable = 0;
	reg_gpio_mode1 = 1;
	reg_gpio_mode0 = 0;
	reg_gpio_ien = 1;
	reg_gpio_oe = 1;
#endif
    reg_gpio_out = 1; // ON	
	
	//reg_gpio_out = 0;
	
	configure_io();

	while (1) {
        reg_gpio_out = 1; // ON

        // mydelay(100);
		mydelay(80000);

        //reg_gpio_out = 0;  // ON
        reg_gpio_out = 0;  // OFF

        mydelay(80000);

    }

	//delay(800000);

	reg_spi_enable = 0;
	reg_mprj_counter = 0;
	
	reg_mprj_xfer = 1;
	//while(reg_mprj_xfer == 1);
    reg_mprj_proj_sel = 0b00101;
#ifdef EARLY_SIGNALS
	reg_mprj_settings = 1+65536;
#else
	reg_mprj_settings = 65536;
#endif
	reg_mprj_proj_sel = 0b00100;
	reg_gpio_out = 0;
    
    reg_gpio_out = 1;
	unsigned cycle = 0;
	while(1) {
		unsigned dd = (cycle & 1) ? 80000 : 16000;
        reg_gpio_out = 1; // ON
        reg_mprj_datal = 0x00000000;
        reg_mprj_datah = 0x00000000;

		delay(dd);

        reg_gpio_out = 0;  // OFF
        reg_mprj_datah = 0x0000003f;
        reg_mprj_datal = 0xffffffff;

		delay(dd);
		cycle++;
	}
}
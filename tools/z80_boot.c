#include <defs.h>
#include <stub.c>

#define NOPULL

#define reg_mprj_proj_sel (*(volatile uint32_t*)0x30100004)
#define reg_mprj_counter (*(volatile uint32_t*)0x30100008)
#define reg_mprj_settings (*(volatile uint32_t*)0x3010000C)

//#define EARLY_SIGNALS

void delay(const int d) {
	reg_timer0_config = 0;
	reg_timer0_data = d;
	reg_timer0_config = 1;

	reg_timer0_update = 1;
	while (reg_timer0_value > 0) {
		reg_timer0_update = 1;
	}
}

void main() {
	reg_wb_enable = 1;
	reg_uart_enable = 0;
	reg_gpio_mode1 = 1;
	reg_gpio_mode0 = 0;
	reg_gpio_ien = 1;
	reg_gpio_oe = 1;
	
	reg_gpio_out = 0;
	
#ifdef NOPULL
	reg_mprj_io_0 = GPIO_MODE_USER_STD_INPUT_NOPULL;
	reg_mprj_io_1 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_2 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_3 = GPIO_MODE_USER_STD_INPUT_NOPULL;
	reg_mprj_io_4 = GPIO_MODE_USER_STD_OUTPUT;
	
	reg_mprj_io_5 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_6 = GPIO_MODE_USER_STD_INPUT_NOPULL;
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
	reg_mprj_io_32 = GPIO_MODE_USER_STD_INPUT_NOPULL;
	reg_mprj_io_33 = GPIO_MODE_USER_STD_INPUT_NOPULL;
	reg_mprj_io_34 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_35 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_36 = GPIO_MODE_USER_STD_OUTPUT;
	reg_mprj_io_37 = GPIO_MODE_USER_STD_INPUT_NOPULL;
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
	
	delay(800000);
	reg_spi_enable = 0;
	reg_mprj_counter = 0;
	
	reg_mprj_xfer = 1;
	// while(reg_mprj_xfer == 1);
    reg_mprj_proj_sel = 0b00101;
#ifdef EARLY_SIGNALS
	reg_mprj_settings = 1+65536;
#else
	reg_mprj_settings = 65536;
#endif
	reg_mprj_proj_sel = 0b00100;
	reg_gpio_out = 0;
    
    reg_gpio_out = 1;
	while(1) {
        reg_gpio_out = 1; // OFF
        reg_mprj_datal = 0x00000000;
        reg_mprj_datah = 0x00000000;

		delay(8000000);

        reg_gpio_out = 0;  // ON
        reg_mprj_datah = 0x0000003f;
        reg_mprj_datal = 0xffffffff;

		delay(8000000);
	}
}

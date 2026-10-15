.DEFAULT_GOAL := help

PROJECT       := rp2350_driver
BUILD_DIR     ?= derived/drv_rel
BUILD_TYPE    ?= Release
BUS_MODE      ?= ASYNC
# The external CPU clock is independent of the bus service backend.
# The early-request async guard is qualified at 5 MHz on the attached FPGA.
Z80_CLOCK_HZ  ?= 6000000
# RP2350 system clock (300 MHz halves bus reply latency; see tests/bus_speed_20261008.md).
# Above 150 MHz, main() raises VREG and slows flash SCK. Use 150000 for stock speed.
RP_SYS_CLOCK_KHZ ?= 300000

CMAKE         ?= cmake
PYTHON        ?= python3
OPENOCD       ?= /opt/openocd-master/bin/openocd
TELNET        ?= telnet
NC            ?= nc

OPENOCD_HOST  ?= 127.0.0.1
SWD_SPEED     ?= 5000
MONITOR_PORT  ?= 4444
RTT_PORT      ?= 9090
KEYBOARD_PORT ?= 9091
TAPE_PORT     ?= 9092
TAP_FILE      ?=
BENCHMARK_OUTPUT ?= derived/bus_benchmarks/latest.json

ELF           := $(BUILD_DIR)/$(PROJECT).elf
BIN           := $(BUILD_DIR)/$(PROJECT).bin
HEX           := $(BUILD_DIR)/$(PROJECT).hex

FLASH_CFG     := $(CURDIR)/weact-openocd.cfg
RTT_CFG       := $(CURDIR)/rtt.cfg

CMAKE_CONFIG_ARGS := \
	-DCMAKE_BUILD_TYPE=$(BUILD_TYPE) \
	-DZ80_BUS_MODE=$(BUS_MODE)

CMAKE_CONFIG_ARGS += -DZ80_CLOCK_HZ=$(Z80_CLOCK_HZ)
CMAKE_CONFIG_ARGS += -DRP_SYS_CLOCK_KHZ=$(RP_SYS_CLOCK_KHZ)

ifneq ($(strip $(PICO_SDK_PATH)),)
CMAKE_CONFIG_ARGS += -DPICO_SDK_PATH=$(PICO_SDK_PATH)
endif

.PHONY: help configure build artifacts elf bin hex flash flash-bin \
	openocd monitor rtt keyboard tape rtt1 rtt2 test-async-pio test-bus-benchmarks

help:
	@printf '%s\n' \
		'make build                 Configure and build ELF/BIN/HEX' \
		'make flash                 Build and program ELF through WeAct CMSIS-DAP' \
		'make flash-bin             Build and program the raw BIN at XIP base' \
		'make openocd               Attach OpenOCD + RTT channels 0/1/2 without reset' \
		'make monitor               Connect to the OpenOCD command monitor' \
		'make rtt                   Connect to RTT channel 0' \
		'make keyboard              Held-key keyboard window on RTT channel 1 (alias: rtt1)' \
		'make tape                  Interactive tape prompt on RTT channel 2 (alias: rtt2)' \
		'make tape TAP_FILE=game.tap Upload and arm a TAP file' \
		'make test-async-pio        Test the active asynchronous WAIT driver' \
		'make test-bus-benchmarks   RAM/IO workloads on matching flashed firmware; requires local OpenOCD' \
		'' \
		'Useful overrides:' \
		'  BUS_MODE=MANUAL|(ASYNC)|FROZEN  BUILD_TYPE=(Release)|Debug' \
		'  Z80_CLOCK_HZ=5000000 (all modes; overrides cached clock)' \
		'  BUILD_DIR=($(BUILD_DIR))  PICO_SDK_PATH=...  OPENOCD=...  PYTHON=...' \
		'  OPENOCD_HOST=...  RTT_PORT=9090  KEYBOARD_PORT=9091  TAPE_PORT=9092' \
		'  SWD_SPEED=5000 (kHz; try 1000 for connection troubleshooting)' \
		'' \
		'Run openocd, keyboard, and tape in separate terminals; Ctrl-C stops each (close the keyboard window).'

configure:
	$(CMAKE) -S . -B "$(BUILD_DIR)" $(CMAKE_CONFIG_ARGS)

build: configure
	$(CMAKE) --build "$(BUILD_DIR)" --target "$(PROJECT)" --parallel

artifacts: build
	@printf 'ELF: %s\nBIN: %s\nHEX: %s\n' "$(ELF)" "$(BIN)" "$(HEX)"

elf: build
	@printf '%s\n' "$(ELF)"

bin: build
	@printf '%s\n' "$(BIN)"

hex: build
	@printf '%s\n' "$(HEX)"

flash: build
	$(OPENOCD) -c "set ELF {$(abspath $(ELF))}" -f "$(FLASH_CFG)"

flash-bin: build
	$(OPENOCD) -c "set BIN {$(abspath $(BIN))}" -f "$(FLASH_CFG)"

# Keep this process in the foreground. Run RTT clients from other terminals.
openocd:
	$(OPENOCD) \
		-f interface/cmsis-dap.cfg \
		-f target/rp2350.cfg \
		-c "set SWD_SPEED $(SWD_SPEED)" \
		-c "set RTT_PORT $(RTT_PORT)" \
		-c "set KEYBOARD_PORT $(KEYBOARD_PORT)" \
		-c "set TAPE_PORT $(TAPE_PORT)" \
		-f "$(RTT_CFG)"

monitor:
	$(TELNET) "$(OPENOCD_HOST)" "$(MONITOR_PORT)"

# OpenOCD's RTT server is raw TCP, so netcat is preferable to Telnet here.
rtt:
	$(NC) "$(OPENOCD_HOST)" "$(RTT_PORT)"

# Channels 1 and 2 carry framed messages, so use their protocol-aware clients.
keyboard rtt1:
	$(PYTHON) tools/zx_keyboard.py --host "$(OPENOCD_HOST)" --port "$(KEYBOARD_PORT)"

tape rtt2:
	$(PYTHON) tools/zx_tape.py --host "$(OPENOCD_HOST)" --port "$(TAPE_PORT)" $(if $(strip $(TAP_FILE)),tape "$(TAP_FILE)")

test-async-pio:
	$(PYTHON) tests/test_wait_manual_pio.py
	$(PYTHON) tests/test_high_wait_pio.py

test-bus-benchmarks:
	$(PYTHON) tests/run_bus_benchmarks.py "$(BENCHMARK_OUTPUT)" --elf "$(ELF)" --z80-hz $(Z80_CLOCK_HZ)

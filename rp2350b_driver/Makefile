.DEFAULT_GOAL := help

PROJECT       := rp2350_driver
BUILD_DIR     ?= derived/drv_dbg
BUILD_TYPE    ?= Debug
#BUILD_DIR     ?= derived/drv_rel
#BUILD_TYPE    ?= Release
BUS_MODE      ?= WAIT

CMAKE         ?= cmake
OPENOCD       ?= /opt/openocd-master/bin/openocd
TELNET        ?= telnet
NC            ?= nc

OPENOCD_HOST  ?= 127.0.0.1
MONITOR_PORT  ?= 4444
RTT_PORT      ?= 9090

ELF           := $(BUILD_DIR)/$(PROJECT).elf
BIN           := $(BUILD_DIR)/$(PROJECT).bin
HEX           := $(BUILD_DIR)/$(PROJECT).hex

FLASH_CFG     := $(CURDIR)/weact-openocd.cfg
RTT_CFG       := $(CURDIR)/rtt.cfg

CMAKE_CONFIG_ARGS := \
	-DCMAKE_BUILD_TYPE=$(BUILD_TYPE) \
	-DZ80_BUS_MODE=$(BUS_MODE)

ifneq ($(strip $(PICO_SDK_PATH)),)
CMAKE_CONFIG_ARGS += -DPICO_SDK_PATH=$(PICO_SDK_PATH)
endif

.PHONY: help configure build artifacts elf bin hex flash flash-bin program \
	openocd server monitor rtt

help:
	@printf '%s\n' \
		'make build                 Configure and build ELF/BIN/HEX' \
		'make flash                 Build and program ELF through WeAct CMSIS-DAP' \
		'make flash-bin             Build and program the raw BIN at XIP base' \
		'make openocd               Run OpenOCD + RTT server in this terminal' \
		'make monitor               Connect to the OpenOCD command monitor' \
		'make rtt                   Connect to RTT channel 0' \
		'' \
		'Useful overrides:' \
		'  BUS_MODE=MANUAL|WAIT|FROZEN  BUILD_TYPE=Release|Debug' \
		'  BUILD_DIR=...  PICO_SDK_PATH=...  OPENOCD=...'

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

program: flash

# Keep this process in the foreground. Run monitor and rtt from other terminals.
openocd:
	$(OPENOCD) \
		-f interface/cmsis-dap.cfg \
		-f target/rp2350.cfg \
		-f "$(RTT_CFG)"

server: openocd

monitor:
	$(TELNET) "$(OPENOCD_HOST)" "$(MONITOR_PORT)"

# OpenOCD's RTT server is raw TCP, so netcat is preferable to Telnet here.
rtt:
	$(NC) "$(OPENOCD_HOST)" "$(RTT_PORT)"

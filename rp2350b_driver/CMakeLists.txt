cmake_minimum_required(VERSION 3.13...3.27)

message(INFO "PICO_SDK_PATH: ${PICO_SDK_PATH}, ENV: $ENV{PICO_SDK_PATH}")

if (NOT DEFINED PICO_SDK_PATH AND NOT DEFINED ENV{PICO_SDK_PATH})
	message(FATAL_ERROR "Expecting PICO_SDK_PATH (env or define) to point to Pico SDK")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(PICO_PLATFORM rp2350-arm-s)
set(PICO_BOARD solderparty_rp2350_stamp_xl)

# initialize the sdk based on PICO_SDK_PATH (must happen before project())
include(pico_sdk_import.cmake)

project(rp2350_driver)

# init the sdk
pico_sdk_init()

set(CMAKE_C_FLAGS_DEBUG "-O3 -g" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_DEBUG "-O3 -g" CACHE STRING "" FORCE)

# Paths for the data build
# set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/test.asm)
#set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/prelim_test.asm)
#set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/ram_test.asm)
#set(DATA_ASM $ENV{HOME}/Projects/speccy/zexall.git/zexdoc.asm)
#set(DATA_ASM $ENV{HOME}/Projects/speccy/zexall.git/zexall.asm)
#set(DATA_ASM $ENV{HOME}/Projects/speccy/z80test.git/src/z80full.asm)
set(DATA_ASM $ENV{HOME}/Projects/speccy/z80test.git/src/z80doc.asm)
#set(DATA_ASM ${CMAKE_CURRENT_SOURCE_DIR}/cpd_test.asm)
cmake_path(GET DATA_ASM STEM DATA_FILENAME_STEM)
set(DATA_BIN     ${CMAKE_CURRENT_BINARY_DIR}/${DATA_FILENAME_STEM}.bin)
set(DATA_LST     ${CMAKE_CURRENT_BINARY_DIR}/${DATA_FILENAME_STEM}.lst)
set(DATA_SLD     ${CMAKE_CURRENT_BINARY_DIR}/${DATA_FILENAME_STEM}.sld)
set(DATA_HEADER  ${CMAKE_CURRENT_BINARY_DIR}/${DATA_FILENAME_STEM}.h)
set(DATA_SYMBOL_NAME ${DATA_FILENAME_STEM}_prog)

find_program(SJASMPLUS_EXECUTABLE
	NAMES sjasmplus
	DOC "Path do sjasmplus assembler"
)

find_program(SJASM_EXECUTABLE
	NAMES sjasm
	DOC "Path do sjasm assembler"
)

add_custom_command(
    OUTPUT ${DATA_BIN}
    # without the --syntax=a, ops like `and a, 3' are assembled into two operations, that is incorrectly
    # COMMAND ${SJASMPLUS_EXECUTABLE} --fullpath --syntax=aF --color=on ${DATA_ASM} --sld=${DATA_SLD} --raw=${DATA_BIN} --lst=${DATA_LST}
    COMMAND ${SJASM_EXECUTABLE} ${DATA_ASM} ${DATA_BIN}
    DEPENDS ${DATA_ASM}
    COMMENT "Assembling ${DATA_ASM} -> ${DATA_BIN}"
    VERBATIM
)

add_custom_command(
    OUTPUT ${DATA_HEADER}
    COMMAND xxd -i -n ${DATA_SYMBOL_NAME} ${DATA_BIN} ${DATA_HEADER}
    DEPENDS ${DATA_BIN}
    COMMENT "Generating ${DATA_HEADER} from ${DATA_BIN}"
    VERBATIM
)
add_custom_target(generate_z80_code
    DEPENDS ${DATA_HEADER}
)

add_executable(rp2350_driver
	main.cpp
	${DATA_HEADER}
)

set(Z80_BUS_MODE "WAIT" CACHE STRING
    "Z80 bus backend: MANUAL, WAIT or FROZEN")
set_property(CACHE Z80_BUS_MODE PROPERTY STRINGS MANUAL WAIT FROZEN)

if (Z80_BUS_MODE STREQUAL "MANUAL")
    target_sources(rp2350_driver PRIVATE z80_bus_manual.cpp)
    target_compile_definitions(rp2350_driver PRIVATE Z80_BUS_MODE=0)
elseif (Z80_BUS_MODE STREQUAL "WAIT")
    target_sources(rp2350_driver PRIVATE z80_pio_bus_wait.cpp)
    pico_generate_pio_header(
        rp2350_driver
        ${CMAKE_CURRENT_LIST_DIR}/z80_bus_wait.pio
    )
    target_compile_definitions(rp2350_driver PRIVATE Z80_BUS_MODE=1)
elseif (Z80_BUS_MODE STREQUAL "FROZEN")
    target_sources(rp2350_driver PRIVATE z80_pio_bus_frozen.cpp)
    pico_generate_pio_header(
        rp2350_driver
        ${CMAKE_CURRENT_LIST_DIR}/z80_bus_frozen.pio
    )
    target_compile_definitions(rp2350_driver PRIVATE Z80_BUS_MODE=2)
else()
    message(FATAL_ERROR
        "Z80_BUS_MODE must be MANUAL, WAIT or FROZEN, got: ${Z80_BUS_MODE}")
endif()

target_compile_definitions(rp2350_driver
    PUBLIC SEGGER_RTT_MODE_DEFAULT=SEGGER_RTT_MODE_BLOCK_IF_FIFO_FULL
    PUBLIC DATA_ASM_FILE="${DATA_FILENAME_STEM}.h"
    PUBLIC DATA_ASM_LABEL=${DATA_FILENAME_STEM}_prog
)

target_include_directories(rp2350_driver PRIVATE
    ${CMAKE_CURRENT_BINARY_DIR}
)
add_dependencies(rp2350_driver generate_z80_code)

pico_enable_stdio_uart(rp2350_driver 0)
pico_enable_stdio_usb(rp2350_driver 0)
pico_enable_stdio_rtt(rp2350_driver 1)

target_link_libraries(rp2350_driver
    pico_stdlib
    hardware_clocks
    hardware_pio
)
pico_add_extra_outputs(rp2350_driver)

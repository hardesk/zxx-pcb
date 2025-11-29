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

set(CMAKE_C_FLAGS_DEBUG "-O0 -g" CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_DEBUG "-O0 -g" CACHE STRING "" FORCE)

# Paths for the data build
#set(DATA_FILENAME_BASE zexdoc)
set(DATA_FILENAME_BASE test)
#set(DATA_ASM     $ENV{HOME}/Projects/speccy/zexall.git/zexdoc.asm)
set(DATA_ASM     ${CMAKE_CURRENT_SOURCE_DIR}/test.asm)
set(DATA_BIN     ${CMAKE_CURRENT_BINARY_DIR}/${DATA_FILENAME_BASE}.bin)
set(DATA_HEADER  ${CMAKE_CURRENT_BINARY_DIR}/${DATA_FILENAME_BASE}.h)
set(DATA_SYMBOL_NAME ${DATA_FILENAME_BASE}_prog)

find_program(SJASMPLUS_EXECUTABLE
	NAMES sjasmplus
	DOC "Path do sjasmplus assembler"
)

add_custom_command(
    OUTPUT ${DATA_BIN}
    COMMAND ${SJASMPLUS_EXECUTABLE} --color=on ${DATA_ASM} --raw=${DATA_BIN}
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

target_compile_definitions(rp2350_driver PUBLIC SEGGER_RTT_MODE_DEFAULT=SEGGER_RTT_MODE_BLOCK_IF_FIFO_FULL)

target_include_directories(rp2350_driver PRIVATE
    ${CMAKE_CURRENT_BINARY_DIR}
)
add_dependencies(rp2350_driver generate_z80_code)

pico_enable_stdio_uart(rp2350_driver 0)
pico_enable_stdio_usb(rp2350_driver 0)
pico_enable_stdio_rtt(rp2350_driver 1)

target_link_libraries(rp2350_driver pico_stdlib)
pico_add_extra_outputs(rp2350_driver)

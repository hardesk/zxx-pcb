cmake_minimum_required(VERSION 3.13...3.27)

message(INFO "PICO_SDK_PATH: ${PICO_SDK_PATH}, ENV: $ENV{PICO_SDK_PATH}")

if (NOT DEFINED PICO_SDK_PATH AND NOT DEFINED ENV{PICO_SDK_PATH})
	message(FATAL_ERROR "Expecting PICO_SDK_PATH (env or define) to point to Pico SDK")
endif()


# initialize the sdk based on PICO_SDK_PATH (must happen before project())
include(pico_sdk_import.cmake)

project(rp2350_driver)

# init the sdk
pico_sdk_init()

add_executable(rp2350_driver
	main.cpp
)

pico_enable_stdio_uart(rp2350_driver 1)
pico_enable_stdio_usb(rp2350_driver 0)

target_link_libraries(rp2350_driver pico_stdlib)
pico_add_extra_outputs(rp2350_driver)

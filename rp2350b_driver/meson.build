project('rp2350z80', 'c',
    version: '0.1.0',
    meson_version: '>=1.2',
    default_options: ['warning_level=2', 'c_std=c11'])

PICO_SDK_PATH = '~/Projects/pico-sdk'

cm = import('cmake')

opt_platform = get_option('platform')
opt_board = get_option('board')

pico_opts = cm.subproject_options()
pico_opts.add_cmake_defines({
    'PICO_PLATFORM': opt_platform, # rp2350-arm-s
    'PICO_BOARD': opt_board, # solderparty_rp2350_stamp_xl
    'PICO_SDK_PATH': PICO_SDK_PATH,
    'CMAKE_SYSTEM_NAME': 'Generic',
    'CMAKE_TRY_COMPILE_TARGET_TYPE': 'STATIC_LIBRARY',
    'TARGET_SUPPORTS_SHARED_LIBS': 'FALSE'
})
pico_opts.set_override_option('c_std', 'c11')

pico = cm.subproject('pico-sdk', options: pico_opts)

dep_pico_stdlib = pico.dependency('pico_stdlib')
dep_hardware_gpio = pico.dependency('hardware_gpio')


# APP
srcs = files('main.cpp')

exe = executable('rpz80d', srcs,
    dependencies: [
        dep_pico_stdlib, dep_hardware_gpio
    ],
    link_language: 'c',
    install: false
)

# make UF2
elf2uf2 = find_program('elf2uf2', required: false)
if elf2uf2.found()
    custom_target('rpz80d.uf2',
        input: exe,
        output: 'rpz80d.uf2',
        command: [elf2uf2, '@INPUT@', '@OUTPUT@'],
        build_by_default: true
    )
endif

message('PICO_PLATFORM ' + opt_platform + ' PICO_BOARD ' + opt_board)

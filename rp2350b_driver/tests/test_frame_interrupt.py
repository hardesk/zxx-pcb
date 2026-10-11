#!/usr/bin/env python3
"""Compile the production PWM interrupt driver against a host hardware model."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
stubs = r'''
#pragma once
#include <cassert>
#include <cstdint>
using uint = unsigned;
#define hard_assert(x) assert(x)
constexpr int clk_sys = 0, PWM_CHAN_A = 0, PWM_CHAN_B = 1;
constexpr int GPIO_FUNC_PWM = 4, GPIO_FUNC_SIO = 5, GPIO_OUT = 1;
struct pwm_config { uint divider=1, wrap=0; bool a=false,b=false; };
inline pwm_config applied;
inline bool enabled=false, sio_high=true;
inline uint counter=0, level=0;
inline int function=GPIO_FUNC_SIO;
inline uint sys_hz=150000000;
inline uint clock_get_hz(int) { return sys_hz; }
inline uint pwm_gpio_to_slice_num(uint pin) { assert(pin==32); return 8; }
inline uint pwm_gpio_to_channel(uint pin) { assert(pin==32); return PWM_CHAN_A; }
inline pwm_config pwm_get_default_config() { return {}; }
inline void pwm_config_set_clkdiv_int(pwm_config* c,uint d) { c->divider=d; }
inline void pwm_config_set_wrap(pwm_config* c,uint w) { c->wrap=w; }
inline void pwm_config_set_output_polarity(pwm_config* c,bool a,bool b) { c->a=a;c->b=b; }
inline void pwm_init(uint slice,const pwm_config* c,bool on) { assert(slice==8);applied=*c;enabled=on; }
inline void pwm_set_chan_level(uint slice,uint channel,uint l) { assert(slice==8 && channel==0);level=l; }
inline void pwm_set_counter(uint,uint c) { counter=c; }
inline void pwm_set_enabled(uint,bool on) { enabled=on; }
inline void busy_wait_us_32(uint t) { if(enabled) counter+=t; }
inline void gpio_put(uint pin,bool high) { assert(pin==32);sio_high=high; }
inline void gpio_set_dir(uint pin,int) { assert(pin==32); }
inline void gpio_set_function(uint pin,int f) {
    assert(pin==32);
    if(f==GPIO_FUNC_PWM) assert(enabled && counter>=level && applied.a);
    if(f==GPIO_FUNC_SIO) assert(sio_high);
    function=f;
}
'''
source = r'''
#include "z80_frame_interrupt.cpp"
static_assert(Z80FrameInterrupt::pulse_width_us(1000000)==32);
static_assert(Z80FrameInterrupt::pulse_width_us(3500000)==10);
static_assert(Z80FrameInterrupt::pulse_width_us(5000000)==7);
int main() {
    Z80FrameInterrupt irq;
    assert(!enabled && function==GPIO_FUNC_SIO); // Default stays inactive.
    irq.stop();
    irq.start(5000000);
    assert(enabled && function==GPIO_FUNC_PWM);
    assert(applied.divider==150 && applied.wrap==19999 && applied.a && !applied.b);
    assert(150000000 / applied.divider / (applied.wrap+1)==50);
    assert(level==7);
    // Model the active-low comparator over a complete PWM period.
    unsigned low_ticks=0;
    for(unsigned tick=0; tick<=applied.wrap; ++tick)
        low_ticks += tick < level;
    assert(low_ticks==7);
    irq.start(1000000); // Restart and default 32-T-state width at 1 MHz.
    assert(level==32 && enabled);
    irq.stop();
    assert(!enabled && function==GPIO_FUNC_SIO && sio_high);
    irq.stop();
    sys_hz=300000000; // Above 255 MHz: 0.5 us ticks, same period and pulse.
    irq.start(5000000);
    assert(applied.divider==150 && applied.wrap==39999 && level==14);
    assert(300000000 / applied.divider / (applied.wrap+1)==50);
    irq.stop();
}
'''
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / 'stub.hpp').write_text(stubs)
    for name in ['hardware/clocks.h','hardware/gpio.h','hardware/pwm.h','pico/stdlib.h']:
        p=path/name;p.parent.mkdir(exist_ok=True);p.write_text('#include "stub.hpp"\n')
    (path/'test.cpp').write_text(source)
    subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined','-I',tmp,
                    '-I',str(root),str(path/'test.cpp'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
print('PASS: 50 Hz PWM configuration at 150/300 MHz, pulse rounding, inactive default, restart and stop')

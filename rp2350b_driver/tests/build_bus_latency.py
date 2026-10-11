#!/usr/bin/env python3
"""Build an isolated GPIO39/WAIT latency capture; no flash or PIO bus changes."""
import argparse
from pathlib import Path
import shutil
import subprocess
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory',type=Path)
parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--hz',type=int,default=5000000)
args=parser.parse_args();source=args.source.resolve();target=args.directory.resolve()
if target==source or source in target.parents:parser.error('Use an isolated directory outside the source tree')
shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('derived','.venv','.git','__pycache__','build'))
main=target/'main.cpp';text=main.read_text()
helper=r'''
// PIO1 spare SM samples GPIO16..47. No pin mux or bus program is changed.
#include <hardware/dma.h>
volatile uint32_t bus_latency_samples[8192];
volatile int bus_latency_dma=-1;
class BusLatencyCapture {
    uint sm;
public:
    BusLatencyCapture() {
        sm=pio_claim_unused_sm(pio1,true);
        static const uint16_t instructions[]={static_cast<uint16_t>(pio_encode_in(pio_pins,32))};
        const pio_program program={instructions,1,-1,1,0};
        uint offset=pio_add_program(pio1,&program);
        auto config=pio_get_default_sm_config();
        sm_config_set_wrap(&config,offset,offset);
        sm_config_set_in_pins(&config,16);
        sm_config_set_in_pin_count(&config,32);
        sm_config_set_in_shift(&config,true,true,32);
        sm_config_set_fifo_join(&config,PIO_FIFO_JOIN_RX);
        sm_config_set_clkdiv(&config,4.0f);
        pio_sm_init(pio1,sm,offset,&config);
        bus_latency_dma=dma_claim_unused_channel(true);
        auto dma_config=dma_channel_get_default_config(bus_latency_dma);
        channel_config_set_read_increment(&dma_config,false);
        channel_config_set_write_increment(&dma_config,true);
        channel_config_set_dreq(&dma_config,pio_get_dreq(pio1,sm,false));
        dma_channel_configure(bus_latency_dma,&dma_config,
            const_cast<uint32_t*>(bus_latency_samples),&pio1->rxf[sm],8192,false);
    }
    void start() {
        dma_start_channel_mask(1u<<bus_latency_dma);
        pio_sm_set_enabled(pio1,sm,true);
    }
};
BusLatencyCapture* bus_latency_capture=nullptr;
'''
text=text.replace('int main()\n{',helper+'\nint main()\n{')
text=text.replace('    bus.init(kZ80ClockHz);','    bus.init(kZ80ClockHz);\n    static BusLatencyCapture latency;\n    bus_latency_capture=&latency;')
# Same two-instruction counter overhead in both builds, after the reply.
reply_call='request_io.write_reply(reply)' if 'request_io.write_reply(reply)' in text else 'bus.write_reply(reply)'
text=text.replace('        '+reply_call+';', '        '+reply_call+''';
        static unsigned latency_requests=0;
        if (++latency_requests==1024) bus_latency_capture->start();''')
# The SRAM loop precedes main(), so declarations must precede that loop too.
text=text.replace(helper+'\n','')
location=text.index('// SRAM avoids') if '// SRAM avoids' in text else text.index('int main()\n{')
text=text[:location]+helper+'\n'+text[location:]
main.write_text(text)
subprocess.run(['cmake','-S',str(target),'-B',str(target/'build'),'-DCMAKE_BUILD_TYPE=Release','-DZ80_BUS_MODE=ASYNC',f'-DZ80_CLOCK_HZ={args.hz}','-DPICO_SDK_PATH=/Users/orl/Projects/pico-sdk'],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['cmake','--build',str(target/'build'),'--target','rp2350_driver','-j','4'],check=True,stdout=subprocess.DEVNULL)
print(target/'build/rp2350_driver.elf')

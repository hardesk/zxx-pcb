#!/usr/bin/env python3
"""Passively count CLK sampling edges with WAIT/HALT low in 500 x 20-ms windows.

Uses unused PIO2 SM1/2/3 and DMA2..7 via OpenOCD Tcl, without flashing or halting
an RP core. Resets/replays the buffered VIBRATE TAP. No bus-loop instrumentation.
Requires the current 5 MHz firmware, LCD SM0, and a buffered VIBRATE.TAP.
"""
import argparse
import json
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from zx_keyboard import packet
from zx_tape import TapeClient
PIO=0x50400000
DMA=0x50000000
BUFFERS=(0x20060000,0x20060800,0x20061000)
RELOAD=0x20061800
SM_MASK=14
CLOCKS=100000
# Sixteen instructions in unused PIO2 words 0..15. OUT PC decodes RD/WR
# for the qualified counter; raw WAIT/HALT use CLK/RESET (falling) or the already-low gate pin (rising) as a constant
# nonzero decode. TX DMA supplies the per-window reload.
PROGRAM=[0x000a,0x008a,0x008a,0x008a,0x2088,0x2008,0x00ca,0xa0e8,
         0x6062,0x60a2,0x0044,0xa0ca,0x8020,0x80a0,0xa027,0xa04b]

class Probe:
    def __init__(self):
        self.sock=socket.create_connection(('localhost',6666),5)
        self.sock.settimeout(15)
    def command(self,text):
        self.sock.sendall(text.encode()+b'\x1a');data=b''
        while not data.endswith(b'\x1a'):
            block=self.sock.recv(65536)
            if not block:raise ConnectionError('OpenOCD disconnected')
            data+=block
        reply=data[:-1].decode()
        if 'Error:' in reply:raise RuntimeError(reply)
        return reply
    def read(self,address,count=1,bits=32):
        return [int(x,0) for x in self.command(f'read_memory {address:#x} {bits} {count}').split()]
    def write(self,address,value):self.command(f'mww {address:#x} {value:#x}')

def request(op,payload=b''):
    with socket.create_connection(('localhost',9092),3) as sock:
        sock.settimeout(3)
        return TapeClient(sock).request(op,payload)

def symbol(elf,name):
    output=subprocess.check_output(['arm-none-eabi-nm','-C',str(elf)],text=True)
    return next(int(line.split()[0],16) for line in output.splitlines() if line.endswith(' '+name))

def summary(wait,halt):
    useful=[CLOCKS-v for v in wait]
    return {'windows':len(wait),'mean_nonwait_clocks':statistics.mean(useful),
            'min_nonwait_clocks':min(useful),'max_nonwait_clocks':max(useful),
            'median_nonwait_clocks':statistics.median(useful),
            'mean_wait_clocks':statistics.mean(wait),
            'wait_percent':statistics.mean(wait)/CLOCKS*100,
            'effective_nonwait_mhz':statistics.mean(useful)/20000,
            'halt_percent':statistics.mean(halt)/CLOCKS*100}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--elf',type=Path,default=ROOT/'derived/drv_rel/rp2350_driver.elf')
    parser.add_argument('--interrupt-hz',type=int,choices=[50,25],default=50)
    parser.add_argument('--edge',choices=['rising','falling'],default='rising',help='RZ80/TV80 uses rising; classic Z80 uses falling')
    parser.add_argument('--synchronized-clock',action='store_true',help='Leave the two-stage CLK input synchronizer enabled (late-edge cross-check)')
    args=parser.parse_args();probe=Probe()
    assert probe.read(PIO+0x168)==[16],'Expected PIO2 GPIO base 16'
    assert probe.read(PIO)[0]&15==1,'PIO2 SM1/2/3 are already enabled'
    assert ((probe.read(PIO+0xcc)[0]>>7)&31)>=16,'LCD overlaps counter program'
    sm_original={sm:probe.read(PIO+0xc8+sm*24,6) for sm in (1,2,3)}
    dma_original={ch:probe.read(DMA+ch*64,4) for ch in range(2,8)}
    assert all(v[3]==0 for v in dma_original.values()),'DMA2..7 are not unused'
    env=probe.read(symbol(args.elf,'(anonymous namespace)::core1_screen'))[0]-112
    ram,ram_size=probe.read(env,2)
    assert ram_size==65536 and 0x20000000<ram<0x20040000
    tape_ptr=probe.read(env+20)[0]
    original=request(6)
    assert original['size']==(ROOT/'taps/VIBRATE.TAP').stat().st_size
    assert tape_ptr+original['size']<BUFFERS[0],'Capture buffers overlap TAP allocation'
    if args.edge=='rising':PROGRAM[4:6]=[0x2008,0x2088]
    input_bases=(24,28,34) if args.edge=='rising' else (22,28,22)
    sync_original=probe.read(PIO+0x38)[0]
    # CLK is generated synchronously by PIO1. Bypass its input synchronizer
    # while retaining WAIT/control synchronizers, compensating the WAIT-GPIO
    # plus JMP-PIN instruction latency at the sampling edge. No LCD input uses CLK.
    if not args.synchronized_clock:probe.write(PIO+0x38,sync_original|(1<<8))
    for index,word in enumerate(PROGRAM):probe.write(PIO+0x48+4*index,word)

    def stop():probe.write(PIO+0x3000,SM_MASK)
    def setup(count,pins=(26,26,36),all_clocks=False,input_base_override=None):
        stop()
        probe.write(PIO+0x2000,SM_MASK<<4) # Restart only the three monitor SMs.
        probe.write(RELOAD,CLOCKS-1)
        probe.write(PIO+0x60,0xa042 if all_clocks else PROGRAM[6])
        probe.write(PIO+0x64,0xa0eb if all_clocks else PROGRAM[7])
        for sm,ch,pin,buf,inbase in zip((1,2,3),(2,3,4),pins,BUFFERS,input_base_override or input_bases):
            reg=PIO+0xc8+sm*24
            probe.write(reg,0x10000)
            probe.write(reg+4,((pin-16)<<24)|(15<<12)|(4<<7))
            # Toggling FIFO join clears RX and TX without touching LCD SM0.
            probe.write(reg+8,0x800c0000);probe.write(reg+8,0xc0000)
            probe.write(reg+20,(inbase-16)<<15)
            probe.write(PIO+0x10+4*sm,CLOCKS-1)
            for instruction in (0x80a0,0xa027,0xa04b,4):probe.write(reg+16,instruction)
            d=DMA+ch*64
            probe.write(d+12,0)
            probe.write(d,PIO+0x20+4*sm)
            probe.write(d+4,buf)
            probe.write(d+8,count)
            # RP2350 DMA field positions differ from RP2040.
            probe.write(d+12,(1<<23)|((20+sm)<<17)|(ch<<13)|(1<<6)|(2<<2)|1)
            tx=ch+3;reg_dma=DMA+tx*64
            probe.write(reg_dma+12,0)
            probe.write(reg_dma,RELOAD)
            probe.write(reg_dma+4,PIO+0x10+4*sm)
            probe.write(reg_dma+8,count)
            probe.write(reg_dma+12,(1<<23)|((16+sm)<<17)|(tx<<13)|(2<<2)|1)
    def start():probe.write(PIO+0x2000,SM_MASK)
    def remaining():return probe.read(DMA+2*64+8)[0]
    def finish(timeout):
        deadline=time.monotonic()+timeout
        while remaining():
            if time.monotonic()>deadline:raise TimeoutError('Counter DMA did not finish')
            time.sleep(.002)
        stop()
    try:
        calibration=[]
        for all_clocks in (False,True):
            setup(1,(33,33,33),all_clocks) # NMI is inactive high; or unconditionally decrement.
            before=probe.read(0x400b0028)[0]
            start();finish(.2)
            after=probe.read(0x400b0028)[0]
            values=[probe.read(buf)[0] for buf in BUFFERS]
            expected=CLOCKS if all_clocks else 0
            assert values==[expected]*3,(all_clocks,values)
            elapsed=(after-before)&0xffffffff
            assert 19000<=elapsed<=26000,elapsed
            calibration.append({'count_every_clock':all_clocks,'counts':values,'observed_us':elapsed})
        # Validate GPIO-base decoding against known CLK/RESET levels. For
        # rising edges use non-inverted PINS; CLK/RESET are both high. The
        # active-low RD/WR pair is never simultaneously low either.
        setup(1,(33,33,33),False,(22,28,22))
        probe.write(PIO+0x60,0xa042)
        if args.edge=='rising':probe.write(PIO+0x64,0xa0e0)
        start();finish(.2)
        decode_values=[probe.read(buf)[0] for buf in BUFFERS]
        assert decode_values[0]==CLOCKS and decode_values[2]==CLOCKS,decode_values
        calibration.append({'gpio_decode_counts':decode_values})
        print('PASS: count-none/count-all/GPIO-decode calibration',calibration,flush=True)
        print('Resetting/replaying retained VIBRATE; interrupt Hz',args.interrupt_hz,flush=True)
        request(8);time.sleep(2);request(5)
        probe.write(0x400a80b0,1000000//args.interrupt_hz-1)
        setup(500)
        with socket.create_connection(('localhost',9091),3) as keyboard:
            keyboard.sendall(packet([13]));time.sleep(.12);keyboard.sendall(packet([]))
        seen_loader=False;deadline=time.monotonic()+35
        code=[0xf3,0x21,0x90,0x99]
        while time.monotonic()<deadline:
            value=probe.read(ram+0x8101,4,8)
            if value!=code:seen_loader=True
            if seen_loader and value==code and probe.read(ram+0xbfbf,3,8)==[0xc3,0xaf,0x81]:break
            time.sleep(.01)
        else:raise TimeoutError('Demo start signature not observed')
        started=time.monotonic();start()
        print('Demo drawing start observed; collecting 500 x 20 ms',flush=True)
        corrupt=None;deadline=started+12
        while (left:=remaining()):
            if corrupt is None and probe.read(ram+0x8101,4,8)!=code:
                corrupt=500-left
                print('Entry-code corruption observed near window',corrupt,flush=True)
            if time.monotonic()>deadline:raise TimeoutError('500-window capture timeout')
            time.sleep(.04)
        stop();elapsed=time.monotonic()-started
        wait=probe.read(BUFFERS[0],500)
        qualified=probe.read(BUFFERS[1],500)
        halt=probe.read(BUFFERS[2],500)
        assert all(q<=w for q,w in zip(qualified,wait))
        table=bytes(probe.read(ram+0x899f,768,8))
        table_words=[int.from_bytes(table[i:i+2],'little') for i in range(0,768,2)]
        invalid_table=[{'address':hex(0x899f+2*i),'value':hex(v)} for i,v in enumerate(table_words) if not 0xc000<=v<=0xe000]
        assert all(0<=v<=CLOCKS for v in wait+qualified+halt)
        result={'interrupt_hz':args.interrupt_hz,'clock_hz':5000000,'sampling_edge':args.edge,'clocks_per_window':CLOCKS,
                'window_us':20000,'clock_input_sync_bypassed':not args.synchronized_clock,
                'capture_observed_seconds':elapsed,'calibration':calibration,
                'corruption_first_observed_window':corrupt,'wait_low_sampling_edges':wait,
                'qualified_transfer_wait_low_sampling_edges':qualified,
                'invalid_drawing_table_entries_at_end':invalid_table,
                'halt_low_sampling_edges':halt,'all_windows_raw_wait':summary(wait,halt),
                'all_windows_qualified_wait':summary(qualified,halt)}
        if corrupt is not None and corrupt>2:
            # Drop two additional windows for polling latency/partially corrupt data.
            result['before_entry_corruption']=summary(wait[:corrupt-2],halt[:corrupt-2])
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2))
        print(json.dumps({k:v for k,v in result.items() if k not in ('wait_low_sampling_edges','qualified_transfer_wait_low_sampling_edges','halt_low_sampling_edges','invalid_drawing_table_entries_at_end')},indent=2))
    finally:
        stop()
        probe.write(DMA+0x464,sum(1<<ch for ch in dma_original))
        deadline=time.monotonic()+1
        while probe.read(DMA+0x464)[0]:
            if time.monotonic()>deadline:raise TimeoutError('DMA abort timed out')
        for ch,v in dma_original.items():
            d=DMA+ch*64;probe.write(d+12,0)
            for i in range(3):probe.write(d+i*4,v[i])
            probe.write(d+12,v[3])
        for sm,v in sm_original.items():
            reg=PIO+0xc8+sm*24
            probe.write(reg+8,0x800c0000);probe.write(reg+8,v[2])
            for i in (0,1,5):probe.write(reg+i*4,v[i])
            probe.write(reg+16,v[3]&31) # JMP back to the original PC, remain disabled.
        probe.write(PIO+8,SM_MASK|(SM_MASK<<8)|(SM_MASK<<16)|(SM_MASK<<24))
        probe.write(PIO+0x38,sync_original)
        for index in range(len(PROGRAM)):probe.write(PIO+0x48+4*index,0)
        request(8);time.sleep(2);request(5)
        assert probe.read(0x400a80b0)==[19999]
        print('Counters removed; 50 Hz menu restored; retained TAP rewound',flush=True)
        probe.sock.close()

if __name__=='__main__':main()

#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <pico/stdlib.h>
#include <hardware/pio.h>
#include "z80_pio_bus.hpp"
#include "z80_pins.hpp"
#include "snapshot_timing_capture.hpp"
extern "C" { volatile uint32_t event_test_case = 0xffffffffu; }
struct Case { const char *name; int kind, mode; bool enabled, halt, phase; int extra; };
// kind: RESET=0 INT=1 NMI=2; extra: reset pending=1, IM0 CALL=1/JP=2,
// INT EI-delay=3; NMI held=1/repeat=2/INT-after-RETN=3/simultaneous=4.
static const Case cases[] = {
 {"reset_run_high",0,0,false,false,true,0}, {"reset_run_low",0,0,false,false,false,0},
 {"reset_halt_high",0,0,false,true,true,0}, {"reset_halt_low",0,0,false,true,false,0},
 {"reset_wait_high",0,0,false,false,true,1}, {"reset_wait_low",0,0,false,false,false,1},
 {"im0_run",1,0,true,false,true,0}, {"im0_halt",1,0,true,true,false,0},
 {"im0_di",1,0,false,false,true,0}, {"im0_di_halt",1,0,false,true,false,0},
 {"im1_run",1,1,true,false,true,0}, {"im1_halt",1,1,true,true,false,0},
 {"im1_di",1,1,false,false,true,0}, {"im1_di_halt",1,1,false,true,false,0},
 {"im2_run",1,2,true,false,true,0}, {"im2_halt",1,2,true,true,false,0},
 {"im2_di",1,2,false,false,true,0}, {"im2_di_halt",1,2,false,true,false,0},
 {"im0_call",1,0,true,false,true,1}, {"im0_jp",1,0,true,false,false,2},
 {"im1_ei_delay",1,1,false,false,true,3},
 {"nmi_di_run",2,1,false,false,true,0}, {"nmi_ei_run",2,1,true,false,false,0},
 {"nmi_di_halt",2,1,false,true,true,0}, {"nmi_ei_halt",2,1,true,true,false,0},
 {"nmi_held",2,1,false,false,true,1}, {"nmi_two_edges",2,1,false,false,false,2},
 {"nmi_retn_ei",2,1,true,false,true,3}, {"nmi_retn_di",2,1,false,false,false,3},
 {"nmi_int_priority",2,1,true,false,true,4},
 {"im1_ei_di",1,1,false,false,true,4},
 {"reset_high_release_low",0,0,false,false,true,2},
 {"reset_low_release_high",0,0,false,false,false,2}
};
static uint8_t ram[65536];
static unsigned cursor;
void emit(std::initializer_list<uint8_t> bytes) { for(auto b:bytes)ram[cursor++]=b; }
struct Entry {uint32_t time,raw,reply;};
static Entry trace[2048];
static unsigned entries=0;
static int reset_phase_sm=-1;
void init_reset_phase() {
 const uint16_t code[]={
  uint16_t(pio_encode_pull(false,true)),uint16_t(pio_encode_out(pio_x,1)),uint16_t(pio_encode_out(pio_y,1)),uint16_t(pio_encode_jmp_not_y(10)),
  uint16_t(pio_encode_wait_gpio(false,pCLK)),uint16_t(pio_encode_wait_gpio(true,pCLK)),uint16_t(pio_encode_nop()|pio_encode_delay(8)),uint16_t(pio_encode_mov(pio_pins,pio_x)),uint16_t(pio_encode_irq_set(false,1)),uint16_t(pio_encode_jmp(0)),
  uint16_t(pio_encode_wait_gpio(true,pCLK)),uint16_t(pio_encode_wait_gpio(false,pCLK)),uint16_t(pio_encode_nop()|pio_encode_delay(8)),uint16_t(pio_encode_mov(pio_pins,pio_x)),uint16_t(pio_encode_irq_set(false,1)),uint16_t(pio_encode_jmp(0))};
 const pio_program program={code,16,-1,1,0};
 uint offset=pio_add_program(pio2,&program);reset_phase_sm=pio_claim_unused_sm(pio2,true);
 auto cfg=pio_get_default_sm_config();sm_config_set_wrap(&cfg,offset,offset+15);
 sm_config_set_out_pins(&cfg,pRESET,1);sm_config_set_out_shift(&cfg,true,false,32);
 pio_sm_init(pio2,reset_phase_sm,offset,&cfg);
 pio_sm_set_pins_with_mask(pio2,reset_phase_sm,1u<<pRESET,1u<<pRESET);
 pio_sm_set_consecutive_pindirs(pio2,reset_phase_sm,pRESET,1,true);
 pio_gpio_init(pio2,pRESET);pio_sm_set_enabled(pio2,reset_phase_sm,true);
}
// Direct SIO polling keeps the write well inside the requested 500 ns half-cycle.
// Debug-build SDK function calls were too slow to guarantee that phase.
__attribute__((optimize("O2"), noinline))
void phase_put(uint pin,bool level,bool phase) {
 if(pin==pRESET&&reset_phase_sm>=0){
  pio_interrupt_clear(pio2,1);
  pio_sm_put_blocking(pio2,reset_phase_sm,unsigned(level)|(unsigned(phase)<<1));
  while(!pio_interrupt_get(pio2,1))tight_loop_contents();
  return;
 }
 while(bool(sio_hw->gpio_in & (1u<<pCLK))==phase)asm volatile("" ::: "memory");
 while(bool(sio_hw->gpio_in & (1u<<pCLK))!=phase)asm volatile("" ::: "memory");
 if(pin<32) {
  if(level)sio_hw->gpio_set=1u<<pin;else sio_hw->gpio_clr=1u<<pin;
 } else {
  if(level)sio_hw->gpio_hi_set=1u<<(pin-32);else sio_hw->gpio_hi_clr=1u<<(pin-32);
 }
}

int main() {
 stdio_init_all();
 printf("event harness ready\n");
 while(event_test_case==0xffffffffu)sleep_ms(1);
 unsigned id=event_test_case;
 if(id>=sizeof(cases)/sizeof(*cases))panic("bad case");
 const auto c=cases[id];
 printf("case begin id=%u name=%s clock_hz=1000000 kind=%d mode=%d enabled=%d halt=%d phase=%d extra=%d\n",id,c.name,c.kind,c.mode,c.enabled,c.halt,c.phase,c.extra);
 for(uint p=0;p<=pHALT;++p){gpio_init(p);gpio_disable_pulls(p);}
 gpio_put_masked64((1ull<<pCLK)|(1ull<<pRESET)|(1ull<<pWAIT)|(1ull<<pINT)|(1ull<<pNMI)|(1ull<<pBUSRQ),
 (1ull<<pWAIT)|(1ull<<pINT)|(1ull<<pNMI)|(1ull<<pBUSRQ));
 for(uint p:{pCLK,pRESET,pWAIT,pINT,pNMI,pBUSRQ})gpio_set_dir(p,true);
 memset(ram,0,sizeof(ram));
 cursor=0;emit({0xc3,0x00,0x01});
 cursor=8;emit({0xc3,0x00,0x02}); cursor=0x38;emit({0xc3,0x00,0x02});
 cursor=0x66;emit({0x3e,0x5a,0x32,0x01,0x60,0xed,0x45}); // marker, RETN
 cursor=0x200;emit({0x3e,0xa5,0x32,0x00,0x60,0xed,0x4d});
 cursor=0x230;emit({0x3e,0xa5,0x32,0x00,0x60,0xed,0x4d});
 ram[0x4010]=0x30;ram[0x4011]=0x02;
 cursor=0x100;emit({0xf3,0x31,0x00,0x90,0x3e,0x40,0xed,0x47,0xed,uint8_t(c.mode==0?0x46:c.mode==1?0x56:0x5e)});
 if(c.enabled)emit({0xfb,0x00});
 emit({0x3e,0x77,0xd3,0xfe}); // arm marker
 unsigned after_marker=cursor;
 if(c.extra==4&&c.kind==1)emit({0xfb,0xf3,0x00});
 if(c.extra==3&&c.kind==1)emit({0xfb,0x04,0x00}); // EI; INC B must finish before INT ack
 if(c.halt)emit({0x76});
 for(int i=0;i<48;++i)emit({0x00});
 emit({0xc3,uint8_t(after_marker),uint8_t(after_marker>>8)});
 z80pio::AsyncBusDriver bus;bus.init(1000000);
 static SnapshotTimingCapture timing;
 bus.reset_cpu();
 if(c.kind==0)init_reset_phase();
 bool armed=false,triggered=false,released=false,second=false,int_after=false;
 uint64_t armed_at=0,trigger_at=0; uint32_t last_raw=0;unsigned ack=0,operands=0,nmi_writes=0,irq_writes=0;
 bool held_reply=false;uint32_t saved_reply=0;
 const uint64_t timeout=time_us_64()+100000;
 while(time_us_64()<timeout){
  uint64_t now=time_us_64();
  if(armed&&!triggered&&(now-armed_at>=5)&&(!c.halt||!gpio_get(pHALT))){
   phase_put(c.kind==0?pRESET:c.kind==1?pINT:pNMI,false,c.phase);
   if(c.kind==2&&c.extra==4)gpio_put(pINT,false);
   trigger_at=time_us_64();triggered=true;
   if(c.kind==1&&held_reply){bus.write_reply(saved_reply);held_reply=false;}
  }
  now=time_us_64(); // phase_put advances time; avoid unsigned elapsed underflow.
  if(triggered&&!released&&now-trigger_at>=uint64_t(c.kind==0?10:c.kind==2?(c.extra==1?90:10):100)){
   if(held_reply){bus.write_reply(saved_reply);held_reply=false;}
   phase_put(c.kind==0?pRESET:c.kind==1?pINT:pNMI,true,(c.kind==0&&c.extra==2)?!c.phase:c.phase);
   released=true;
  }
  if(triggered&&c.kind==2&&c.extra==2&&!second&&now-trigger_at>=90){gpio_put(pNMI,false);second=true;}
  if(second&&now-trigger_at>=100)gpio_put(pNMI,true);
  if(triggered&&c.kind==2&&c.extra==3&&!int_after&&now-trigger_at>=90){gpio_put(pINT,false);int_after=true;}
  if(armed&&now-armed_at>=190)break;
  // With no other PIO0 users, service SM0 and detector SM1 are claimed in init.
  if(pio_sm_is_rx_fifo_empty(pio0,1))continue;
  z80pio::BusRequest r=bus.read_request();last_raw=r.raw;
  uint32_t reply=0;
  if(r.iorq()&&r.m1()&&!r.rd()&&!r.wr()){
   ++ack; uint8_t v=c.mode==2?0x10:c.mode==1?0x00:c.extra==1?0xcd:c.extra==2?0xc3:0xcf;
   reply=z80pio::read_reply(v);gpio_put(pINT,true);
  } else if(r.mreq()&&r.rd()){
   uint8_t v=ram[r.address()];
   if(c.kind==1&&c.mode==0&&(c.extra==1||c.extra==2)&&ack&&operands<2&&!r.m1())v=operands++?0x02:0x00;
   reply=z80pio::read_reply(v);
  } else if(r.mreq()&&r.wr()){
   ram[r.address()]=r.data();
   nmi_writes+=r.address()==0x6001;irq_writes+=r.address()==0x6000;
  } else if(r.iorq()&&r.rd())reply=z80pio::read_reply(0xff);
  if(r.iorq()&&r.wr()&&(r.address()&255)==0xfe&&!armed){
   timing.start();armed_at=time_us_64();armed=true;
   if((c.kind==0&&c.extra==1)||(c.kind==1&&c.extra>=3)){held_reply=true;saved_reply=reply;}
  }
  if(entries<2048)trace[entries++]={uint32_t(now),r.raw,reply};
  if(!held_reply)bus.write_reply(reply);
 }
 if(armed)timing.finish(entries,last_raw);
 phase_put(pRESET,false,false);gpio_put(pINT,true);gpio_put(pNMI,true);
 printf("summary armed=%u triggered=%u ack=%u operands=%u irq_markers=%u nmi_markers=%u marker_irq=%02x marker_nmi=%02x arm_us=%llu trigger_us=%llu after_marker=%04x entries=%u\n",armed,triggered,ack,operands,irq_writes,nmi_writes,ram[0x6000],ram[0x6001],armed_at,trigger_at,after_marker,entries);
 for(unsigned i=0;i<entries;++i)printf("event %u %lu %08lx %04lx\n",i,(unsigned long)trace[i].time,(unsigned long)trace[i].raw,(unsigned long)trace[i].reply);
 printf("case end %s\n",c.name);
 while(true)tight_loop_contents();
}

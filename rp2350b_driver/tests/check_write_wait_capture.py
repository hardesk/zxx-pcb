#!/usr/bin/env python3
"""Check a --write-hold-us waveform for write-cycle retention until WAIT release."""
import argparse,json,re
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('log',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
s=a.log.read_text();block=s.split('timing begin ',1)[1].split('timing end',1)[0]
m={k:int(v,16 if k=='raw' else 10) for k,v in re.findall(r'(\w+)=([\da-f]+)',block.splitlines()[0])}
if m['nlow']!=m['nhigh'] or m['low_stall'] or m['high_stall']:raise ValueError('Invalid recorder timing')
e=[(int(i),int(l,16),int(h,16)) for i,l,h in re.findall(r'^timing (\d+) ([0-9a-f]{8}) ([0-9a-f]{8})$',block,re.M)]
if not e or e[0][0]!=0 or e[-1][0]!=m['count']-1:raise ValueError('Incomplete waveform')
lo=[]
for (i,l,h),(j,_,_) in zip(e,e[1:]+[(m['count'],0,0)]):lo.extend([l]*(j-i))
addr=m['raw']>>8&65535;data=m['raw']&255
start=next(i for i,l in enumerate(lo) if l>>8&65535==addr and not(l&(1<<29)) and not(l&(1<<31)))
assertion=next(i for i in range(start,len(lo)) if not(lo[i]&(1<<26)))
release=next(i for i in range(assertion+1,len(lo)) if lo[i]&(1<<26))
end=next(i for i in range(start+1,len(lo)) if lo[i]&(1<<29))
violations=[i for i in range(start,release) if lo[i]>>8&65535!=addr or lo[i]&255!=data or lo[i]&(1<<29) or not(lo[i]&(1<<30))]
rises=[i for i in range(start+1,release) if not(lo[i-1]&(1<<31)) and lo[i]&(1<<31)]
result={'request':m['request'],'address':f'{addr:04X}','data':f'{data:02X}','sample_ns':m['clocks']*1e9/m['hz'],'first_WR_low_sample':start,'WAIT_low_sample':assertion,'WAIT_release_sample':release,'MREQ_end_sample':end,'WAIT_low_before_WR':start>0 and not(lo[start-1]&(1<<26)),'bus_held_until_WAIT_release':not violations,'first_bus_violation_sample':violations[0] if violations else None,'WR_high_pulses_before_release':len(rises),'WR_continuously_low':not rises,'capture_shared_pin_disagreements':m['overlap_mismatch']}
wait_start=assertion
while wait_start>0 and not(lo[wait_start-1]&(1<<26)):wait_start-=1
request_start=start
while request_start>0 and not(lo[request_start-1]&(1<<29)):request_start-=1
result.update(initial_WAIT_high=bool(lo[0]&(1<<26)),
              WAIT_assertion_sample=wait_start, MREQ_assertion_sample=request_start,
              MREQ_to_WAIT_assertion_ns=(wait_start-request_start)*result['sample_ns'],
              WAIT_assertion_to_WR_ns=(start-wait_start)*result['sample_ns'])
result['write_start_to_WAIT_release_us']=(release-start)*result['sample_ns']/1000
result['WAIT_release_to_MREQ_end_us']=(end-release)*result['sample_ns']/1000
if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['WAIT_low_before_WR'] and result['bus_held_until_WAIT_release'] else 1)

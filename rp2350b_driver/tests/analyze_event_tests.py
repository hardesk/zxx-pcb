#!/usr/bin/env python3
"""Decode event-test paired GPIO recordings, export text, and plot every case."""
import argparse,re,json,csv,os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/z80-event-mpl')
p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--no-plots',action='store_true');a=p.parse_args()
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def edges(v,level):return np.flatnonzero((v[1:]==level)&(v[:-1]!=level))+1
allresults=[]
for f in sorted(a.directory.glob('*.log')):
 text=f.read_text(errors='replace')
 if 'case begin ' not in text or 'timing begin ' not in text:continue
 case=dict(re.findall(r'(\w+)=(\S+)',re.search(r'^case begin .*$',text,re.M)[0]))
 summary=dict(re.findall(r'(\w+)=(\S+)',re.search(r'^summary .*$',text,re.M)[0]))
 block=text.split('timing begin ',1)[1].split('timing end',1)[0]
 meta={k:int(v,16 if k=='raw' else 10) for k,v in re.findall(r'(\w+)=([\da-f]+)',block.splitlines()[0])}
 if meta['nlow']!=meta['nhigh'] or meta['low_stall'] or meta['high_stall']:raise ValueError(f'{f}: recorder invalid')
 ev=[(int(i),int(l,16),int(h,16)) for i,l,h in re.findall(r'^timing (\d+) ([0-9a-f]+) ([0-9a-f]+)$',block,re.M)]
 lo=np.zeros(meta['count'],dtype=np.uint32);hi=lo.copy()
 for (i,l,h),(j,_,_) in zip(ev,ev[1:]+[(len(lo),0,0)]):lo[i:j]=l;hi[i:j]=h
 dt=meta['clocks']/meta['hz']*1e6;t=np.arange(len(lo))*dt
 bit=lambda b: ((lo>>b)&1) if b<32 else ((hi>>(b-16))&1)
 bits={name:bit(b) for name,b in [('CLK',24),('RESET',25),('WAIT',26),('M1',27),('IORQ',28),('MREQ',29),('RD',30),('WR',31),('INT',32),('NMI',33),('HALT',36)]}
 addr=(lo>>8)&65535;data=lo&255
 trigger=edges(bits[['RESET','INT','NMI'][int(case['kind'])]],0)
 result={'case':case,'summary':summary,'metadata':meta,'trigger_sample':int(trigger[0]) if len(trigger) else None}
 idx=int(trigger[0]) if len(trigger) else 0
 result['trigger_clock_level']=int(bits['CLK'][idx]);result['trigger_us']=float(t[idx])
 cycles=[]
 for name,cond in [('MEM_READ',(bits['MREQ']==0)&(bits['RD']==0)),('WRITE',(bits['MREQ']==0)&(bits['WR']==0)),('ACK',(bits['IORQ']==0)&(bits['M1']==0)),('IO',(bits['IORQ']==0)&((bits['RD']==0)|(bits['WR']==0))),('IORQ_ONLY',(bits['IORQ']==0)&(bits['M1']==1)&(bits['RD']==1)&(bits['WR']==1))]:
  changes=np.diff(np.r_[False,cond,False].astype(int));starts=np.flatnonzero(changes==1);ends=np.flatnonzero(changes==-1)
  for start,end in zip(starts,ends):cycles.append(dict(type=('FETCH' if bits['M1'][start]==0 else 'READ') if name=='MEM_READ' else name,start=int(start),end=int(end),start_us=float(t[start]),end_us=float(end*dt),addr=f'{addr[start]:04X}',data=f'{data[end-1]:02X}'))
 cycles.sort(key=lambda c:c['start']);result['cycles']=cycles
 result['ack_candidates']=[c for c in cycles if c['type']=='IORQ_ONLY' and c['start']>=idx and c['end_us']-c['start_us']>1]
 result['ack_pulses']=sum(c['type']=='ACK' and c['start']>=idx for c in cycles)
 result['iorq_only_pulses']=sum(c['type']=='IORQ_ONLY' and c['start']>=idx for c in cycles)
 if int(case['kind'])==0:
  releases=edges(bits['RESET'],1);release=next((int(i) for i in releases if i>idx),None)
  result['release_sample']=release
  if release:
   fetch=next((c for c in cycles if c['type']=='FETCH' and c['start']>=release),None)
   result['first_fetch']=fetch
   result['reset_low_us']=(release-idx)*dt
   idle=(bits['MREQ']&bits['IORQ']&bits['RD']&bits['WR']&bits['M1'])!=0
   clear=next((i for i in range(idx,release) if idle[i]),None)
   result['assert_to_idle_us']=None if clear is None else (clear-idx)*dt
   m1=next((int(i) for i in edges(bits['M1'],0) if i>=release),None)
   result['release_clock_level']=int(bits['CLK'][release])
   result['release_to_m1_us']=None if m1 is None else (m1-release)*dt
   if fetch:
    result['release_to_fetch_us']=(fetch['start']-release)*dt
    result['rising_edges_release_to_fetch']=int(sum((edges(bits['CLK'],1)>release)&(edges(bits['CLK'],1)<=fetch['start'])))
   # CPU-side first received fetch after actual release (approximate host us aligned to arm).
   events=[(int(tm),int(raw,16),int(rep,16)) for _,tm,raw,rep in re.findall(r'^event (\d+) (\d+) ([0-9a-f]+) ([0-9a-f]+)',text,re.M)]
   # Raw GPIO capture is authoritative for the first external fetch.
 out=a.directory/f.stem;out.mkdir(exist_ok=True)
 (out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
 with (out/'samples.tsv').open('w') as stream:
  w=csv.writer(stream,delimiter='\t');w.writerow(['sample','time_us','GPIO0_31','GPIO16_47','ADDR','DATA',*bits,'shared_pins_agree'])
  for i in range(len(lo)):w.writerow([i,f'{t[i]:.6f}',f'{lo[i]:08X}',f'{hi[i]:08X}',f'{addr[i]:04X}',f'{data[i]:02X}',*[int(v[i]) for v in bits.values()],int(lo[i]>>16==hi[i]&65535)])
 def plot(end_us,suffix,pre_us=8):
  end=min(len(lo),int(end_us/dt));start=max(0,idx-int(pre_us/dt));xs=t[start:end]
  names=['CLK','RESET','INT','NMI','HALT','WAIT','M1','IORQ','MREQ','RD','WR']
  fig,ax=plt.subplots(figsize=(18,10),dpi=150);fig.subplots_adjust(left=.09,right=.98,top=.86,bottom=.1)
  fig.text(.03,.965,case['name'].replace('_',' '),weight='bold',size=20)
  fig.text(.03,.925,f"Measured on board • CLK 1 MHz • GPIO sampled every 26.667 ns • DMA stalls 0 • shared-pin disagreements {meta['overlap_mismatch']}",size=11)
  fig.text(.03,.893,f"INT acknowledgements delivered to driver: {summary['ack']}   IRQ handler markers: {summary['irq_markers']}   NMI handler markers: {summary['nmi_markers']}",size=11)
  colors=['#a78a00','#c03e36','#8357b5','#cc4b8b','#596579','#216dcc','#9254a5','#2d918a','#298251','#cc772b','#47769a']
  for j,(name,color) in enumerate(zip(names,colors)):
   y=12-j;ax.step(xs,y+.62*bits[name][start:end],where='post',color=color,lw=1.1)
  for y,vals,fmt in [(1,addr,'04X'),(0,data,'02X')]:
   bounds=[start,*[int(i) for i in np.flatnonzero(vals[1:]!=vals[:-1])+1 if start<i<end],end]
   for l,r in zip(bounds,bounds[1:]):
    ax.fill_between([t[l],r*dt],y,y+.62,color='#e4edf7',edgecolor='#6786a3',lw=.6)
    if (r-l)*dt>max(.7,(end-start)*dt/90):ax.text((l+r)/2*dt,y+.3,format(vals[l],fmt),ha='center',va='center',size=8)
  if int(case['kind'])==1:
   for c in result['ack_candidates']:
    if c['start_us']<end*dt:
     ax.axvspan(c['start_us'],c['end_us'],color='#d43a35',alpha=.09)
     ax.plot([c['start_us'],c['end_us']],[6,6],color='#bd2926',ls='--',lw=2)
     ax.text(c['start_us'],13.6,'ACK: M1 should remain low',size=9,color='#bd2926')
  ax.axvline(t[idx],color='#be3447',ls='--',lw=1)
  ax.text(t[idx]+.3,13.05,'stimulus asserted',color='#be3447',size=10)
  if result.get('release_sample'):
   rel=result['release_sample'];ax.axvline(t[rel],color='#555',ls=':',lw=1);ax.text(t[rel]+.3,13.5,'RESET released',size=10)
  if result.get('first_fetch'):
   ff=result['first_fetch'];ax.axvline(ff['start_us'],color='#298251',ls=':',lw=1);ax.text(ff['start_us']+.3,14.0,f"first fetch {ff['addr']}",size=10,color='#298251')
  ax.set_yticks([12-i+.3 for i in range(11)]+[1.3,.3],['CLK',*['/'+n for n in names[1:]],'ADDR [23:8]','DATA [7:0]'])
  ax.set_xlim(xs[0],end*dt);ax.set_ylim(-.3,14.7);ax.set_xlabel('Microseconds from capture start (1 µs = one CPU clock period)');ax.grid(axis='x',alpha=.2)
  for ext in ('png','svg'):fig.savefig(out/(suffix+'.'+ext))
  plt.close(fig)
 if not a.no_plots:
  plot(min(t[idx]+(35 if int(case['kind'])==0 else 85),t[-1]),'detail')
  plot(t[-1],'overview')
  if int(case['kind'])==0:
   plot(result.get('first_fetch',{}).get('start_us',t[idx]+25)+6,'focus',2)
  elif result['ack_candidates']:
   plot(result['ack_candidates'][0]['end_us']+9,'focus',3)
  else:
   plot(t[idx]+55,'focus',3)
 allresults.append(result)
(a.directory/'analysis.json').write_text(json.dumps(allresults,indent=2)+'\n')
for r in allresults:
 print(r['case']['name'],'ACK',r['ack_pulses'],'IORQ-only',r['iorq_only_pulses'],'first',r.get('first_fetch'), 'irq/nmi',r['summary']['irq_markers'],r['summary']['nmi_markers'])

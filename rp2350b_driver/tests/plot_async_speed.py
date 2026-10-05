#!/usr/bin/env python3
"""Export paired PIO samples and plot a selected interval (physical levels)."""
import argparse,json,os,re
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/z80-waveform-matplotlib')
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('log',type=Path);p.add_argument('--output',type=Path,required=True)
p.add_argument('--start',type=int);p.add_argument('--end',type=int)
p.add_argument('--title',default='Real-board async bus timing')
p.add_argument('--note',action='append',default=[],help='sample:text; vertical annotation')
a=p.parse_args();text=a.log.read_text();block=text.split('timing begin ',1)[1].split('timing end',1)[0]
meta={k:int(v,16 if k=='raw' else 10) for k,v in re.findall(r'(\w+)=([\da-f]+)',block.splitlines()[0])}
if meta['low_stall'] or meta['high_stall'] or meta['nlow']!=meta['nhigh']:raise ValueError('Stalled or unequal recorders')
events=[(int(i),int(l,16),int(h,16)) for i,l,h in re.findall(r'^timing (\d+) ([0-9a-f]{8}) ([0-9a-f]{8})$',block,re.M)]
if events[0][0]!=0 or events[-1][0]!=meta['count']-1:raise ValueError('Incomplete capture')
samples=[]
for (i,l,h),(j,_,_) in zip(events,events[1:]+[(meta['count'],0,0)]):samples.extend([(l,h)]*(j-i))
dt=meta['clocks']*1e9/meta['hz'];out=a.output;out.mkdir(parents=True,exist_ok=True)
with (out/'samples.tsv').open('w') as f:
 f.write('sample\tabsolute_sample\ttime_ns\tGPIO0_31\tGPIO16_47\tADDR\tDATA\tCLK\tRESET_n\tWAIT_n\tM1_n\tIORQ_n\tMREQ_n\tRD_n\tWR_n\tGPIO39\tshared_pins_agree\n')
 for i,(l,h) in enumerate(samples):f.write('\t'.join([str(i),str(meta['first']+i),f'{i*dt:.3f}',f'{l:08X}',f'{h:08X}',f'{l>>8&65535:04X}',f'{l&255:02X}']+[str(l>>b&1) for b in range(24,32)]+[str(h>>23&1),str(int(l>>16==h&65535))])+'\n')
(out/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
start=a.start if a.start is not None else max(0,len(samples)-220);end=a.end if a.end is not None else len(samples)
fig,ax=plt.subplots(figsize=(15,7.8),dpi=180);fig.subplots_adjust(left=.12,right=.97,top=.78,bottom=.15)
fig.text(.04,.95,a.title,size=19,weight='bold');fig.text(.04,.905,f"Captured request {meta['request']}; raw {meta['raw']:08X}. Sample interval {dt:.3f} ns (4 clocks at 150 MHz).",size=11)
fig.text(.04,.865,'GPIO39: rises after detector acceptance; falls after reply data/OE setup. Neither edge is an exact snapshot timestamp.',size=10)
fig.text(.04,.825,f"DMA stalls: 0. Shared-pin disagreements: {meta['overlap_mismatch']} (marked in TSV; GPIO0..31 use the low recorder).",size=10)
lanes=[(24,'CLK','#b58a00'),(26,'/WAIT','#2965d7'),(27,'/M1','#a535a8'),(29,'/MREQ','#1a8b64'),(30,'/RD','#d2582c'),(31,'/WR','#8757a8'),(28,'/IORQ','#408985'),(39,'GPIO39','#079ba3')]
xs=list(range(start,end))+[end]
for n,(bit,label,color) in enumerate(lanes):
 vals=[(l>>bit&1) if bit!=39 else h>>23&1 for l,h in samples[start:end]]
 ax.step(xs,[9-n+.65*v for v in vals+[vals[-1]]],where='post',lw=1.4,color=color)
for n,shift,mask,digits in [(8,8,65535,4),(9,0,255,2)]:
 y=9-n;positions=[start]+[i for i in range(start+1,end) if samples[i][0]>>shift&mask!=samples[i-1][0]>>shift&mask]+[end]
 for x1,x2 in zip(positions,positions[1:]):
  ax.fill_between([x1,x2],y,y+.65,color='#e5edf8',edgecolor='#66809c')
  if x2-x1>=2:ax.text((x1+x2)/2,y+.32,f'{samples[x1][0]>>shift&mask:0{digits}X}',ha='center',va='center',fontsize=9)
for n,note in enumerate(a.note):
 pos,label=note.split(':',1);pos=int(pos);ax.axvline(pos,color='#be3447',ls='--',lw=1)
 ax.annotate(label,(pos,9.8),(pos+3,10.6+(n%2)*.7),fontsize=10,color='#a02d3b',arrowprops={'arrowstyle':'->','color':'#a02d3b'})
ax.set_yticks([9-i+.3 for i in range(10)],[x[1] for x in lanes]+['ADDR [23:8]','DATA [7:0]'])
ax.set_xlim(start,end);ax.set_ylim(-.4,12);ax.grid(axis='x',alpha=.18);ax.set_xlabel('Sample count; ADDR and DATA are hexadecimal')
for ext in ('png','svg'):fig.savefig(out/f'waveform.{ext}')
print(out/'waveform.png')

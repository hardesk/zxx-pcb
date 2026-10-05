#!/usr/bin/env python3
"""Explain the captured request-14 failure without inventing waveform edges."""
from pathlib import Path
import os
os.environ.setdefault('MPLCONFIGDIR', '/tmp/z80-waveform-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle, FancyBboxPatch
from matplotlib.ticker import MultipleLocator
from plot_gpio_capture import read_capture

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'derived/wait_stability_20261003/waveforms'
meta, samples, events = read_capture(OUT.parent / 'accepted_ring.log')
assert meta['accepted_raw'] == '97010855' and meta['raw'] == 'f7010855'
assert samples[7982] == 0xf7010855
assert samples[7987] == 0xf3010855
assert samples[8001] == 0x92010855
assert (OUT.parent / 'wait_bus_stress.bin').read_bytes()[8] == 0x3a

fig = plt.figure(figsize=(16, 11), dpi=170, facecolor='#f7f9fc')
ink, muted = '#172b42', '#52677e'
red, green, amber = '#bc3346', '#16845b', '#ad6b0e'
fig.text(.025, .956, 'Where the failure is: the published request has inactive read strobes',
         size=20, weight='bold', color=ink)
fig.text(.025, .922, 'Measured GPIO waveforms below. The request snapshots are separate logged evidence, not extra waveform samples.',
         size=11, color=muted)

# A new render of the original numerical capture; no raster waveform editing.
ax = fig.add_axes([.10, .392, .875, .365], facecolor='white')
start, end = 7952, 8032
lanes = [('CLK', 24, '#aa7900'), ('/WAIT', 26, '#2757d5'),
         ('/M1', 27, '#a037bc'), ('/MREQ', 29, '#188275'), ('/RD', 30, '#cf593d')]
levels = [6, 5, 4, 3, 2, 1, 0]
ax.axvspan(7982, 8001, color=red, alpha=.07)
ax.axvspan(8001, end, color=green, alpha=.065)
for n, y in enumerate(levels):
    if n % 2 == 0:
        ax.axhspan(y-.08, y+.68, color='#eef2f7', alpha=.4)
for n, (name, bit, color) in enumerate(lanes):
    y = levels[n]
    values = [(raw >> bit) & 1 for raw in samples[start:end]]
    ax.step(list(range(start, end))+[end], [y+.54*v for v in values+[values[-1]]],
            where='post', lw=1.8, color=color)
    for val in (0, 1):
        ax.text(start-.7, y+.54*val, str(val), ha='right', va='center',
                fontsize=7, color='#8390a0')
for n, shift, mask, digits, color in [(5,8,65535,4,'#147d91'), (6,0,255,2,'#6d4bab')]:
    y = levels[n]
    values = [(v >> shift) & mask for v in samples[start:end]]
    changes = [start] + [i for i in range(start+1,end) if values[i-start] != values[i-start-1]] + [end]
    for a,b in zip(changes,changes[1:]):
        d=min(.35,(b-a)/4)
        ax.add_patch(Polygon([(a,y+.27),(a+d,y),(b-d,y),(b,y+.27),(b-d,y+.54),(a+d,y+.54)],
                             facecolor=color+'0d',edgecolor=color,lw=1.2))
        if b-a > 3:
            ax.text((a+b)/2,y+.27,f'{values[a-start]:0{digits}X}',ha='center',va='center',
                    family='monospace',size=11,color=color,
                    bbox=dict(facecolor='white',edgecolor='none',pad=.8))
ax.add_patch(Rectangle((7982,1.89),19,1.77,fill=False,lw=1.5,edgecolor=red,linestyle='--'))
ax.set_xlim(start,end)
ax.set_ylim(-.13,7)
ax.set_yticks([y+.27 for y in levels], [f'{n} [{b}]' for n,b,_ in lanes]+['ADDR [23:8]','DATA [7:0]'], fontsize=10)
ax.tick_params(axis='y',length=0,pad=13)
ax.xaxis.set_major_locator(MultipleLocator(8))
ax.xaxis.set_minor_locator(MultipleLocator(1))
ax.grid(axis='x',which='major',color='#dce2e9',lw=.7)
ax.grid(axis='x',which='minor',color='#eef1f5',lw=.4)
ax.set_xlabel('Sample index  →    ·    4 system clocks = 26.667 ns per sample',fontsize=10,labelpad=8)
for s in ax.spines.values(): s.set_color('#dce2e9')

# Distinct, untimed callouts: only their arrows land on measured transitions.
boxes = [(.10, .795, .265, 'A  ·  Sample 7982',
          'New fetch: ADDR = 0108, /M1 = 0.\n/MREQ and /RD are still HIGH.\nThis is not yet a qualified read.',red),
         (.403,.795,.265,'B  ·  Sample 7987',
          '/WAIT goes LOW.\nEarly WAIT is allowed; that edge\nis not itself the failure.',amber),
         (.706,.795,.268,'C  ·  Sample 8001',
          '/MREQ and /RD go LOW and stay low.\nThis is the sustained read to qualify\nand publish with its address/data.',green)]
for x,y,w,title,body,color in boxes:
    fig.add_artist(FancyBboxPatch((x,y),w,.091,boxstyle='round,pad=0.008',
                                  transform=fig.transFigure,facecolor='white',edgecolor=color,lw=1.3))
    fig.text(x+.007,y+.068,title,size=11,weight='bold',color=color)
    fig.text(x+.007,y+.046,body,size=10,color=ink,va='top',linespacing=1.45)
for sample,ylane,textpos,color in [(7982,4.27,(.235,.790),red),
                                  (7987,5.04,(.535,.790),amber),
                                  (8001,2.04,(.839,.790),green)]:
    ax.annotate('',xy=(sample,ylane),xycoords='data',xytext=textpos,textcoords=fig.transFigure,
                arrowprops=dict(arrowstyle='->',lw=1.3,color=color,connectionstyle='angle,angleA=-90,angleB=0,rad=5'))
    ax.plot(sample,ylane,'o',ms=5,color=color,zorder=8)

# The expectation is logical sequence, not fabricated counterfactual timing.
for x,w,color,title in [(.025,.455,red,'OBSERVED  ·  request 14 sent to the M33'),
                         (.51,.465,green,'EXPECTED  ·  a qualified opcode-read request')]:
    fig.add_artist(FancyBboxPatch((x,.139),w,.172,boxstyle='round,pad=0.009',
                                  transform=fig.transFigure,facecolor='white',edgecolor=color,lw=1.3))
    fig.text(x+.012,.286,title,size=12,weight='bold',color=color)
fig.text(.037,.254,'Detector accepted:  97010855  →  /MREQ = 0, /RD = 0\n'
                  'Service published:  F7010855  →  /MREQ = 1, /RD = 1',
         family='monospace',size=11,color=ink,linespacing=1.65,va='top')
fig.text(.037,.189,'The host receives an inactive control pattern, so it cannot\n'
                  'classify this request as a read of 0108. This is the failure.',
         size=11,color=red,va='top',linespacing=1.4)
fig.text(.522,.254,'Qualify sustained /MREQ = 0 and /RD = 0; keep ADDR = 0108.\n'
                  'Publish that validated read snapshot, not a different one.\n'
                  'The host returns opcode 3A; install data/OE, then release WAIT.',
         size=11,color=ink,va='top',linespacing=1.6)
fig.text(.522,.179,'DATA = 55 while WAIT is LOW is allowed.\n'
                  'The later response is outside the captured window.',
         size=10.5,color=green,va='top',linespacing=1.4)
fig.text(.025,.094,'The detector’s brief active snapshot is not resolved by the 26.667 ns GPIO recording. No unmeasured pulse has been drawn.',
         size=10,color=muted)
fig.text(.025,.066,'Red outline: the inactive read-control pattern that must not be published as a read. Green region: the sustained read is present.',
         size=10,color=muted)
fig.text(.025,.038,'Physical levels are shown (/ = active low). /RESET, /IORQ and /WR remain HIGH in this zoom. GPIO39 is not recorded. Exact snapshot time is unlogged.',
         size=9,color=muted)
OUT.mkdir(parents=True,exist_ok=True)
for extension in ('png','svg'):
    path=OUT/f'accepted_ring_failure_explained.{extension}'
    fig.savefig(path,facecolor=fig.get_facecolor())
    print(path)

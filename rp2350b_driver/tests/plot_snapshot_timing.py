#!/usr/bin/env python3
"""Plot synchronized GPIO0..31 + GPIO39 capture. Requires matplotlib.

Shows measured marker timestamps, not uncalibrated guesses of MOV ISR timing.
Exports every sample and marker edge as tab-separated plain text.
"""
import argparse
import json
import os
from pathlib import Path
import re
os.environ.setdefault('MPLCONFIGDIR', '/tmp/z80-waveform-matplotlib')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    text = args.log.read_text()
    block = text.split('timing begin ', 1)[1].split('timing end', 1)[0]
    meta = dict(re.findall(r'(\w+)=([\da-f]+)', block.splitlines()[0]))
    for key in list(meta):
        meta[key] = int(meta[key], 16 if key == 'raw' else 10)
    for key in ('low_stall', 'high_stall', 'overlap_mismatch'):
        if meta[key]:
            raise ValueError(f'Timing invalid: {key}={meta[key]}')
    if meta['nlow'] != meta['nhigh']:
        raise ValueError('Recorder sample counts differ')
    events = [(int(i), int(lo, 16), int(hi, 16)) for i, lo, hi in
              re.findall(r'^timing (\d+) ([\da-f]{8}) ([\da-f]{8})$', block, re.M)]
    if not events or events[0][0] != 0 or events[-1][0] != meta['count']-1:
        raise ValueError('Incomplete capture')
    if any(a[0] >= b[0] for a, b in zip(events, events[1:])):
        raise ValueError('Unordered samples')
    samples = []
    for (i, lo, hi), (end, _, _) in zip(events, events[1:] + [(meta['count'], 0, 0)]):
        samples.extend([(lo, hi)] * (end-i))
    if any(lo >> 16 != hi & 0xffff for lo, hi in samples):
        raise ValueError('Shared pins disagree')
    dt = meta['clocks'] * 1e9 / meta['hz']
    markers = [(i, (hi >> 23) & 1) for i, (lo, hi) in enumerate(samples)
               if i and ((hi ^ samples[i-1][1]) & (1 << 23))]
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    with (output/'samples.txt').open('w') as f:
        f.write('# Time relative to oldest retained sample; physical levels, controls active low.\n')
        f.write('sample\tabsolute_sample\ttime_ns\tGPIO0_31\tGPIO16_47\tADDR\tDATA\tCLK\tRESET_n\tWAIT_n\tM1_n\tIORQ_n\tMREQ_n\tRD_n\tWR_n\tGPIO39\n')
        for i, (lo, hi) in enumerate(samples):
            values = [str(i), str(meta['first']+i), f'{i*dt:.3f}', f'{lo:08X}', f'{hi:08X}',
                      f'{lo>>8&65535:04X}', f'{lo&255:02X}']
            values += [str(lo>>bit&1) for bit in range(24, 32)] + [str(hi>>23&1)]
            f.write('\t'.join(values)+'\n')
    with (output/'markers.txt').open('w') as f:
        f.write('# Actual marker edge lies after previous sample and at/before first changed sample.\n')
        f.write('# IRQ6 follows detector MOV ISR by 7 clocks (RD/WR) or 12 (INTACK).\n')
        f.write('# IRQ7 follows service MOV ISR by 1 clock. Helper/GPIO delays are NOT calibrated.\n')
        f.write('sample\ttime_ns\tlevel\tevent\n')
        for i, level in markers:
            f.write(f'{i}\t{i*dt:.3f}\t{level}\t'+('detector_accept_marker' if level else 'service_snapshot_marker')+'\n')
    (output/'metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
    if not markers:
        raise ValueError('No debug marker edges captured')
    fall = next(i for i, level in reversed(markers) if level == 0)
    rise = next(i for i, level in reversed(markers) if level and i < fall)
    address = meta['raw'] >> 8 & 65535
    setup = rise
    while setup and samples[setup-1][0] >> 8 & 65535 == address:
        setup -= 1
    active = next((i for i in range(fall, len(samples))
                   if samples[i][0] & ((1<<29)|(1<<30)) == 0), None)
    start = max(0, min(setup, rise)-28)
    end = min(len(samples), max(fall+30, (active or fall)+15))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(15, 7.6), dpi=170)
    fig.subplots_adjust(left=.12, right=.98, top=.75, bottom=.20)
    fig.patch.set_facecolor('#f7f9fc')
    fig.text(.025,.955,'Detector / service markers — real board capture',size=20,weight='bold')
    fig.text(.025,.912,f"Request {meta['request']} · published {meta['raw']:08X} · 150 MHz system · {dt:.3f} ns/sample",size=12)
    fig.text(.025,.862,f'Detector acceptance marker ↑ {rise}     Service snapshot marker ↓ {fall}',size=13,color='#067e93')
    fig.text(.025,.816,'Markers lag the snapshots: detector IRQ +7 clocks (RD/WR); service IRQ +1 clock; plus helper/GPIO delay.',size=10)
    labels = ['CLK [24]', 'GPIO39 marker', '/M1 [27]', '/WAIT [26]', '/MREQ [29]', '/RD [30]', '/IORQ [28]', '/WR [31]', 'ADDR [23:8]', 'DATA [7:0]']
    lanes = [(24,'#aa7900'),(39,'#009ab0'),(27,'#b32eb3'),(26,'#2757d5'),(29,'#16846c'),(30,'#d76039'),(28,'#16846c'),(31,'#7655a6')]
    xs = list(range(start,end)) + [end]
    for n, (bit, color) in enumerate(lanes):
        values = [(lo>>bit&1) if bit!=39 else (hi>>23&1) for lo,hi in samples[start:end]]
        ax.step(xs,[9-n+.6*v for v in values+[values[-1]]],where='post',color=color,lw=1.6)
    for n, shift, mask, digits in [(8,8,65535,4),(9,0,255,2)]:
        y=9-n
        positions=[start]+[i for i in range(start+1,end) if (samples[i][0]>>shift&mask)!=(samples[i-1][0]>>shift&mask)]+[end]
        for a,b in zip(positions,positions[1:]):
            ax.fill_between([a,b],y,y+.6,color='#e6eef7',edgecolor='#597188')
            ax.text((a+b)/2,y+.3,f'{samples[a][0]>>shift&mask:0{digits}X}',ha='center',va='center',size=10)
    if active is not None:
        ax.axvspan(setup,active,color='#e95757',alpha=.10,zorder=0)
        ax.text((setup+active)/2,-.55,'setup region',color='#b14040',ha='center',size=10)
        ax.axvline(active,color='#16846c',ls=':',lw=1.3)
        ax.annotate(f'sustained read\n{active}',(active,5.6),(active+3,6.6),fontsize=10,color='#16846c',arrowprops={'arrowstyle':'->','color':'#16846c'})
    for i,color in [(rise,'#008ea4'),(fall,'#465bb3')]:
        ax.axvspan(i-1,i,color=color,alpha=.18)
        ax.axvline(i,color=color,ls='--',lw=.9)
    ax.set_yticks([9-n+.3 for n in range(10)],labels)
    ax.set_xlim(start,end); ax.set_ylim(-.8,10)
    ax.set_xlabel('Sample count (4 system clocks per sample)')
    ax.grid(axis='x',alpha=.16)
    fig.text(.025,.073,'Shaded narrow bands = measured edge intervals, not exact snapshot times. Red = address/M1 setup before sustained RD/MREQ.',size=10)
    fig.text(.025,.035,f"Recorders: {meta['count']:,} paired samples · no FIFO stalls · all shared GPIO16–31 samples agree. ADDR/DATA are hexadecimal.",size=10)
    for ext in ('png','svg'):
        fig.savefig(output/f'failure_timing.{ext}')
    print(json.dumps({'request':meta['request'],'rise':rise,'fall':fall,'setup':setup,'active':active,'sample_ns':dt}))


if __name__ == '__main__':
    main()

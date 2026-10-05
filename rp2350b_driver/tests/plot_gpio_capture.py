#!/usr/bin/env python3
"""Render a change-compressed GPIO0..31 ring capture as waveforms and text.

Requires matplotlib for PNG/SVG; text and VCD exports use only the stdlib.
Example:
  python3.11 tests/plot_gpio_capture.py capture.log --output-dir output
"""
import argparse
import json
import os
import re
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/tmp/z80-waveform-matplotlib')

SIGNALS = [('CLK', 24), ('/RESET', 25), ('/WAIT', 26), ('/M1', 27),
           ('/IORQ', 28), ('/MREQ', 29), ('/RD', 30), ('/WR', 31)]
COLORS = {'CLK': '#aa7900', '/WAIT': '#2757d5', '/M1': '#a037bc',
          '/MREQ': '#188275', '/RD': '#cf593d', '/WR': '#7455ad',
          '/IORQ': '#188275', '/RESET': '#758398'}


def read_capture(path):
    lines = path.read_text(errors='replace').splitlines()
    begin = next(i for i, line in enumerate(lines) if line.startswith('ring begin '))
    meta = dict(re.findall(r'(\w+)=([0-9a-f]+)', lines[begin]))
    events = []
    end = None
    for i in range(begin + 1, len(lines)):
        if lines[i].strip() == 'ring end':
            end = i
            break
        match = re.fullmatch(r'ring (\d+) ([0-9a-f]{8})', lines[i].strip())
        if match:
            events.append((int(match[1]), int(match[2], 16)))
    if end is None or not events or events[0][0] != 0:
        raise ValueError('Expected a complete ring capture starting at sample zero')
    if any(b[0] <= a[0] for a, b in zip(events, events[1:])):
        raise ValueError('Sample indices must increase strictly')
    # The recorder prints the final sample even if unchanged. The original
    # recorder has an 8192-word ring; requiring its endpoint detects truncation.
    if events[-1][0] != 8191:
        raise ValueError('Expected the final ring sample at index 8191')
    samples = []
    for (index, raw), (next_index, _) in zip(events, events[1:] + [(8192, 0)]):
        samples.extend([raw] * (next_index - index))
    assert len(samples) == 8192
    assert all(samples[index] == raw for index, raw in events)
    meta.update(source=str(path.resolve()), sys_hz=int(meta['hz']),
                sample_period_clocks=4, sample_count=len(samples),
                emitted_records=len(events), request=int(meta['request']))
    meta['sample_period_ns'] = 4e9 / meta['sys_hz']
    meta['sample_index_origin'] = 'oldest retained sample, after ring rotation'
    meta['levels'] = 'physical GPIO levels; /-prefixed controls are active low'
    meta['reconstruction'] = 'unchanged samples expanded from change-compressed log'
    meta['gpio39_present'] = False
    for line in lines[end + 1:]:
        match = re.fullmatch(r'accepted ([0-9a-f]{8}) published ([0-9a-f]{8})', line.strip())
        if match:
            if match[2] == meta['raw']:
                meta['accepted_raw'] = match[1]
            break
    return meta, samples, events


def write_text_exports(directory, stem, meta, samples, events):
    fields = ['sample', 'time_us', 'raw_gpio_hex', 'ADDR_hex', 'DATA_hex']
    fields += [name.lstrip('/') + ('_n' if name.startswith('/') else '') for name, _ in SIGNALS]

    def row(index, raw):
        return [str(index), f"{index * 4e6 / meta['sys_hz']:.9f}", f'{raw:08X}',
                f'{(raw >> 8) & 0xffff:04X}', f'{raw & 0xff:02X}'] + [
                    str((raw >> bit) & 1) for _, bit in SIGNALS]

    header = (f"# {stem}: request {meta['request']}; {meta['sys_hz']} Hz system clock\n"
              f"# GPIO0..31 every 4 clocks = {meta['sample_period_ns']:.9f} ns/sample.\n"
              '# Sample 0 is the oldest retained sample. Levels are physical 0/1.\n'
              '# ADDR=GPIO23..8, DATA=GPIO7..0. DATA does not indicate output enable.\n')
    with (directory / f'{stem}_samples.txt').open('w') as f:
        f.write(header + '\t'.join(fields) + '\n')
        for i, raw in enumerate(samples):
            f.write('\t'.join(row(i, raw)) + '\n')
    changes = [(i, raw) for i, raw in events if i == 0 or raw != samples[i - 1]]
    with (directory / f'{stem}_changes.txt').open('w') as f:
        f.write(header + '# Only transitions; each row holds until the next row.\n')
        f.write('\t'.join(fields + ['held_samples']) + '\n')
        for k, (i, raw) in enumerate(changes):
            end = changes[k + 1][0] if k + 1 < len(changes) else len(samples)
            f.write('\t'.join(row(i, raw) + [str(end - i)]) + '\n')
    (directory / f'{stem}_metadata.json').write_text(json.dumps(meta, indent=2) + '\n')

    # 1 ps timebase represents 26.666... ns intervals to the nearest picosecond.
    with (directory / f'{stem}.vcd').open('w') as f:
        f.write('$version GPIO ring capture exporter $end\n$timescale 1ps $end\n')
        f.write('$comment GPIO0..31; no GPIO39; sample zero is oldest retained. $end\n')
        f.write('$scope module z80_bus $end\n')
        declarations = [('A', 16, 'ADDR'), ('D', 8, 'DATA')]
        declarations += [(chr(97 + n), 1, name.lstrip('/') + ('_n' if name.startswith('/') else ''))
                         for n, (name, _) in enumerate(SIGNALS)]
        for code, width, name in declarations:
            f.write(f'$var wire {width} {code} {name} $end\n')
        f.write('$upscope $end\n$enddefinitions $end\n')
        previous = None
        for i, raw in changes:
            f.write(f"#{round(i * 4e12 / meta['sys_hz'])}\n")
            values = [((raw >> 8) & 0xffff), raw & 0xff] + [(raw >> bit) & 1 for _, bit in SIGNALS]
            for n, ((code, width, _), value) in enumerate(zip(declarations, values)):
                if previous is None or value != previous[n]:
                    f.write(f'b{value:0{width}b} {code}\n' if width > 1 else f'{value}{code}\n')
            previous = values
        f.write(f"#{round((len(samples)-1) * 4e12 / meta['sys_hz'])}\n")


def render(directory, stem, meta, samples, start, end, suffix):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    from matplotlib.ticker import MultipleLocator

    fig, ax = plt.subplots(figsize=(16, 8.4), dpi=160)
    fig.patch.set_facecolor('#f7f9fc')
    ax.set_facecolor('white')
    fig.subplots_adjust(left=.115, right=.98, bottom=.16, top=.78)
    sample_us = 4e6 / meta['sys_hz']
    width = end - start
    title = 'Detector snapshot diagnostic' if 'accepted_raw' in meta else 'Asynchronous bus capture'
    fig.text(.025, .95, f'{title}  |  {"Full record" if start == 0 else "Failure detail"}',
             size=20, weight='bold', color='#14273d')
    fig.text(.025, .908,
             f"Request {meta['request']}  ·  GPIO0–31  ·  {meta['sys_hz']/1e6:g} MHz system clock  ·  "
             f"4 clocks/sample = {meta['sample_period_ns']:.3f} ns  ·  samples {start}–{end-1}",
             size=11, color='#516376')

    xs = list(range(start, end)) + [end]
    levels = [9 - n for n in range(10)]
    labels = [f'{name}  [{bit}]' for name, bit in SIGNALS] + ['ADDR  [23:8]', 'DATA  [7:0]']
    for n in range(10):
        if n % 2 == 0:
            ax.axhspan(levels[n] - .13, levels[n] + .72, color='#f5f7fb', zorder=0)
    for n, (name, bit) in enumerate(SIGNALS):
        y = levels[n]
        values = [(raw >> bit) & 1 for raw in samples[start:end]]
        values.append(values[-1])
        ax.step(xs, [y + .56 * v for v in values], where='post',
                linewidth=1.25 if start == 0 else 1.7, color=COLORS[name])
        ax.text(start - width*.008, y, '0', ha='right', va='center', size=7, color='#8390a0')
        ax.text(start - width*.008, y+.56, '1', ha='right', va='center', size=7, color='#8390a0')

    for n, shift, mask, color, digits in [(8, 8, 0xffff, '#147d91', 4), (9, 0, 255, '#6d4bab', 2)]:
        y = levels[n]
        values = [(v >> shift) & mask for v in samples[start:end]]
        changes = [start] + [i for i in range(start+1, end) if values[i-start] != values[i-start-1]] + [end]
        for a, b in zip(changes, changes[1:]):
            bevel = min(width*.002, (b-a)/4)
            poly = Polygon([(a, y+.28), (a+bevel, y), (b-bevel, y),
                            (b, y+.28), (b-bevel, y+.56), (a+bevel, y+.56)],
                           closed=True, facecolor=color+'12', edgecolor=color, linewidth=1.1)
            ax.add_patch(poly)
            if (b-a)/width > .038:
                ax.text((a+b)/2, y+.28, f'{values[a-start]:0{digits}X}',
                        ha='center', va='center', size=10, family='monospace', color=color,
                        bbox=dict(facecolor='white', edgecolor='none', alpha=.8, pad=1))
    ax.set_xlim(start, end)
    ax.set_ylim(-.3, 10)
    ax.set_yticks([y+.28 for y in levels], labels, fontsize=10)
    ax.tick_params(axis='y', length=0, pad=16)
    spacing = 1024 if start == 0 else 32
    ax.xaxis.set_major_locator(MultipleLocator(spacing))
    ax.xaxis.set_minor_locator(MultipleLocator(spacing/4))
    ax.grid(axis='x', which='major', color='#dce2e9', linewidth=.8)
    ax.grid(axis='x', which='minor', color='#eef1f5', linewidth=.4)
    ax.set_xlabel('Sample index  →  (oldest retained sample = 0)', fontsize=11, labelpad=10)
    time_axis = ax.secondary_xaxis('top', functions=(lambda v: v*sample_us, lambda v: v/sample_us))
    time_axis.set_xlabel('Elapsed time from sample 0 (µs)', fontsize=10, labelpad=9)
    for spine in ax.spines.values():
        spine.set_color('#dce2e9')
    if start == 0:
        ax.axvspan(len(samples)-384, len(samples), color='#ea9634', alpha=.10)
        ax.text(end, 9.82, 'Detail window →', ha='right', va='center', size=9, color='#a56a21')
    footer = 'Physical levels: / signals assert LOW. ADDR/DATA are hex. DATA is the observed pin value, not a validity/OE indicator.'
    fig.text(.025, .066, footer, size=10, color='#516376')
    note = 'The capture contains no GPIO39. Transitions between sample instants are unresolved; plotted levels are held between samples.'
    fig.text(.025, .037, note, size=9, color='#67798b')
    for extension in ('png', 'svg'):
        fig.savefig(directory / f'{stem}_{suffix}.{extension}', facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    meta, samples, events = read_capture(args.capture)
    stem = args.capture.stem
    write_text_exports(args.output_dir, stem, meta, samples, events)
    render(args.output_dir, stem, meta, samples, 0, len(samples), 'full')
    render(args.output_dir, stem, meta, samples, len(samples)-384, len(samples), 'detail')
    print(f'{stem}: {len(samples)} samples, {len(events)} emitted records; outputs: {args.output_dir}')


if __name__ == '__main__':
    main()

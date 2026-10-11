#!/usr/bin/env python3
"""Compare real-device completed-work throughput; no hardware access."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('before', type=Path)
p.add_argument('after', type=Path)
p.add_argument('--output', type=Path)
args = p.parse_args()
before, after = (json.loads(path.read_text()) for path in (args.before, args.after))
for field in ('clock_hz', 'rp_clock_hz', 'lcd_active', 'tape_present'):
    if before[field] != after[field]: p.error('Different benchmark conditions: '+field)
old = {row['case']: row for row in before['cases']}
rows = ['| Workload | Before ops/s | After ops/s | Throughput gain | Before / after seconds |',
        '| --- | ---: | ---: | ---: | ---: |']
for row in after['cases']:
    previous = old[row['case']]
    for field in ('operations', 'nominal_tstates'):
        if previous[field] != row[field]: p.error('Different workload: '+row['case'])
    a, b = previous['operations_per_second'], row['operations_per_second']
    rows.append(f'| {row["case"]} | {a:,.0f} | {b:,.0f} | {(b/a-1)*100:+.2f}% | '
                f'{previous["elapsed_seconds"]:.3f} / {row["elapsed_seconds"]:.3f} |')
text = '\n'.join(rows)+'\n'
if args.output:
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(text)
else: print(text, end='')

#!/usr/bin/env python3
"""Real-board high-idle WAIT experiments. Requires running local OpenOCD.

Each build is isolated in /tmp. Leaves the last test firmware on the board;
restore the normal firmware explicitly after all experiments.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--phase', choices=['sweep', 'soak', 'shorter', 'final', 'cleaninit'], default='sweep')
a = p.parse_args()
root = Path(__file__).resolve().parents[1]
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=True)
src = Path('/tmp/z80_async_high_20261005')
if a.phase == 'sweep':
    cases = [('service_write_1MHz', 'high-service', 1000000, 50, 0, 6)]
    cases += [(f'early_write_{hz}', 'high-request', hz, 50, 0, 8)
              for hz in (2000000, 3500000, 6000000, 8000000, 10000000, 12000000)]
elif a.phase == 'soak':
    cases = [(f'early_fast_{hz}', 'high-request', hz, 0, 0, 60)
              for hz in (1000000, 2000000, 3500000, 4000000, 5000000)]
    cases += [(f'early_delayed_{hz}', 'high-request', hz, 0, 50, 30)
              for hz in (1000000, 2000000, 3500000, 4000000, 5000000)]
elif a.phase == 'shorter':
    cases = [(f'shorter_write_{hz}', 'high-request-fast', hz, 50, 0, 8)
              for hz in (4000000, 5000000, 6000000, 8000000)]
elif a.phase == 'final':
    cases = [('shorter_fast_5MHz', 'high-request-fast', 5000000, 0, 0, 60),
             ('shorter_delayed_5MHz', 'high-request-fast', 5000000, 0, 50, 30),
             ('shorter_slow_5MHz', 'high-request-fast', 5000000, 0, 500, 15)]
else:
    cases = [('shorter_cleaninit_5MHz', 'high-request-fast', 5000000, 0, 0, 60)]
results = []
for name, variant, hz, hold, delay, seconds in cases:
    with (out / (name + '.build.log')).open('w') as f:
        subprocess.run([sys.executable, 'tests/build_async_speed.py', str(src),
                        '--hz', str(hz), '--variant', variant,
                        '--write-hold-us', str(hold), '--delay-us', str(delay)],
                       cwd=root, stdout=f, stderr=subprocess.STDOUT, check=True)
    elf = out / (name + '.elf')
    shutil.copy2(src / 'build/rp2350_driver.elf', elf)
    shutil.copy2(src / 'z80_bus_async.pio', out / (variant + '.pio'))
    shutil.copy2(src / 'z80_bus_async.cpp', out / (variant + '.cpp'))
    log = out / (name + '.log')
    subprocess.run([sys.executable, 'tests/capture_wait_trace.py', str(elf), str(log),
                    '--seconds', str(seconds), '--poll-ms', '1'], cwd=root, check=True)
    text = log.read_text()
    progress = re.findall(r'PASS progress requests=(\d+) loops=(\d+)', text)
    result = dict(name=name, variant=variant, clock_hz=hz, seconds=seconds,
                  hold_us=hold, random_reply_delay_us=delay,
                  failure=re.findall(r'FAIL[^\n]+', text),
                  last_progress=progress[-1] if progress else None)
    if hold and 'write probe' in text:
        checked = subprocess.run([sys.executable, 'tests/check_write_wait_capture.py',
                                  str(log), '--output', str(out / (name + '.metrics.json'))],
                                 cwd=root, capture_output=True, text=True)
        result['waveform_check_exit'] = checked.returncode
        if checked.returncode:
            result['waveform_diagnostic'] = checked.stdout + checked.stderr
    results.append(result)
    (out / (a.phase + '.json')).write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(result), flush=True)

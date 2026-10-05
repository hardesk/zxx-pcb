#!/usr/bin/env python3
"""Repeated RP resets of the already-flashed sequence checker via OpenOCD.

Every result requires at least one PASS progress record and no FAIL record.
Run only after flashing the intended test ELF; this script does not flash.
"""
import argparse
import json
from pathlib import Path
import re
import socket
import time
from capture_wait_trace import command

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--count', type=int, default=20)
p.add_argument('--seconds', type=float, default=2.5)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
results = []
with socket.create_connection(('localhost', 6666), timeout=30) as tcl:
    for n in range(a.count):
        command(tcl, 'rtt stop')
        command(tcl, 'reset run')
        command(tcl, 'rtt setup 0x20000000 0x80000 "SEGGER RTT"')
        command(tcl, 'rtt polling_interval 1')
        command(tcl, 'rtt start')
        data = bytearray()
        with socket.create_connection(('localhost', 9090), timeout=5) as rtt:
            rtt.settimeout(.2)
            deadline = time.monotonic() + a.seconds
            while time.monotonic() < deadline:
                try:
                    part = rtt.recv(65536)
                except TimeoutError:
                    continue
                if not part:
                    raise RuntimeError('RTT disconnected')
                data.extend(part)
        text = data.decode(errors='replace')
        (a.output / f'reset_{n:02}.log').write_bytes(data)
        progress = re.findall(r'PASS progress requests=(\d+) loops=(\d+)', text)
        failure = re.findall(r'FAIL[^\n]+', text)
        boot_seen = 'Hello from RP2350 over RTT!' in text
        result = dict(reset=n, progress=progress[-1] if progress else None,
                      failure=failure, boot_seen=boot_seen,
                      passed=boot_seen and bool(progress) and not failure)
        results.append(result)
        (a.output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        print(json.dumps(result), flush=True)

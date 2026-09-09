#!/usr/bin/env python3
"""Flash a test ELF through an existing local OpenOCD and capture RTT channel 0.

OpenOCD must expose TCL port 6666 and RTT port 9090 (make openocd).
--pause-every pauses RTT polling, filling blocking RTT and stretching /WAIT.
"""
import argparse
import socket
import time
from pathlib import Path


def command(sock, text):
    sock.sendall(text.encode() + b'\x1a')
    response = b''
    while not response.endswith(b'\x1a'):
        chunk = sock.recv(65536)
        if not chunk:
            raise RuntimeError('OpenOCD disconnected')
        response += chunk
    return response[:-1].decode(errors='replace')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('log', type=Path)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--pause-every', type=float, default=0)
    parser.add_argument('--pause-seconds', type=float, default=0.2)
    parser.add_argument('--poll-ms', type=int, default=10)
    args = parser.parse_args()
    elf = args.elf.resolve()
    if not elf.is_file() or any(c in str(elf) for c in '{}\n\r'):
        parser.error('ELF must exist and have a plain path')
    with socket.create_connection(('localhost', 6666), timeout=30) as tcl:
        command(tcl, 'rtt stop')
        result = command(tcl, f'capture {{program {{{elf}}} verify reset}}')
        print(result)
        if '** Verified OK **' not in result:
            raise RuntimeError('flash verification did not succeed')
        command(tcl, 'rtt setup 0x20000000 0x80000 "SEGGER RTT"')
        command(tcl, f'rtt polling_interval {args.poll_ms}')
        command(tcl, 'rtt start')
        # Pausing OpenOCD polling (not merely reading the TCP socket) ensures
        # host/kernel socket buffers cannot hide the intended firmware stall.
        with socket.create_connection(('localhost', 9090), timeout=5) as rtt:
            rtt.settimeout(0.2)
            deadline = time.monotonic() + args.seconds
            pause_at = time.monotonic() + args.pause_every
            with args.log.open('wb') as output:
                while time.monotonic() < deadline:
                    if args.pause_every and time.monotonic() >= pause_at:
                        command(tcl, 'rtt stop')
                        time.sleep(args.pause_seconds)
                        command(tcl, 'rtt start')
                        pause_at = time.monotonic() + args.pause_every
                    try:
                        data = rtt.recv(65536)
                    except TimeoutError:
                        continue
                    if not data:
                        raise RuntimeError('RTT disconnected')
                    output.write(data)
    print(f'Captured {args.log.stat().st_size} bytes to {args.log}')

#!/usr/bin/env python3
"""Upload a buffered TAP to RP2350 and control it over RTT channel 2.

Run without a command for an interactive tape/stop/rewind/status prompt.
Python standard library only.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import struct
import zlib

# readline adds Up/Down command recall to input() on macOS and Linux.
try:
    import readline
except ImportError:
    readline = None

HEADER = struct.Struct('<2sBBIH')
MAX_PAYLOAD = 516


def command_completions(line):
    """Complete the whole command, quoting paths so shlex can read them back."""
    commands = ('tape ', 'stop', 'rewind', 'status', 'reset', 'mode normal', 'mode fast', 'quit')
    if not line.startswith('tape '):
        return [command for command in commands if command.startswith(line)]
    raw = line[5:].lstrip()
    try:
        words = shlex.split(raw)
    except ValueError:
        # Tab is often pressed before the closing filename quote is typed.
        if not raw.startswith(('"', "'")):
            return []
        try:
            words = shlex.split(raw + raw[0])
        except ValueError:
            return []
    prefix = words[0] if len(words) == 1 else raw
    directory, name = os.path.split(prefix)
    try:
        entries = sorted(Path(directory or '.').expanduser().iterdir(), key=lambda p: p.name)
        matches = []
        for entry in entries:
            if not entry.name.startswith(name) or (entry.name.startswith('.') and not name.startswith('.')):
                continue
            path = os.path.join(directory, entry.name) if directory else entry.name
            if entry.is_dir():
                path += os.sep
            matches.append('tape ' + shlex.quote(path))
        return matches
    except OSError:
        return []


def setup_terminal():
    if readline is None:
        return
    matches = []

    def complete(text, state):
        if state == 0:
            matches[:] = command_completions(text)
        return matches[state] if state < len(matches) else None

    # Treat the whole prefix as one completion, including quoted filenames.
    readline.set_completer_delims('\n')
    readline.set_completer(complete)
    if getattr(readline, 'backend', '') == 'editline' or 'libedit' in (readline.__doc__ or ''):
        readline.parse_and_bind('bind ^I rl_complete')
    else:
        readline.parse_and_bind('tab: complete')


def frame(op, sequence, payload=b''):
    header = HEADER.pack(b'ZT', 1, op, sequence, len(payload))
    data = header + payload
    return data + struct.pack('<I', zlib.crc32(data))


def validate_tap(data):
    if not data:
        raise ValueError('Empty TAP file')
    position = blocks = 0
    while position < len(data):
        if len(data) - position < 2:
            raise ValueError(f'Truncated TAP length at {position}')
        size = int.from_bytes(data[position:position+2], 'little')
        position += 2
        if size < 2 or size > len(data) - position:
            raise ValueError(f'Invalid/truncated TAP block at {position-2}')
        position += size
        blocks += 1
    return blocks


class TapeClient:
    def __init__(self, sock):
        self.sock = sock
        self.sequence = secrets.randbits(32)
        self.buffer = bytearray()

    def read_reply(self, op, sequence):
        while True:
            while len(self.buffer) >= 2 and self.buffer[:2] != b'ZT':
                del self.buffer[0]
            if len(self.buffer) >= HEADER.size:
                magic, version, response_op, response_seq, size = HEADER.unpack_from(self.buffer)
                if version != 1 or size > MAX_PAYLOAD:
                    del self.buffer[0]
                    continue
                total = HEADER.size + size + 4
                if len(self.buffer) >= total:
                    data = bytes(self.buffer[:total])
                    del self.buffer[:total]
                    if zlib.crc32(data[:-4]) != int.from_bytes(data[-4:], 'little'):
                        continue
                    if response_op == op | 0x80 and response_seq == sequence:
                        return json.loads(data[HEADER.size:-4])
                    continue
            data = self.sock.recv(4096)
            if not data:
                raise ConnectionError('RTT server disconnected')
            self.buffer.extend(data)

    def request(self, op, payload=b''):
        self.sequence = (self.sequence + 1) & 0xffffffff
        data = frame(op, self.sequence, payload)
        for attempt in range(3):
            self.sock.sendall(data)
            try:
                result = self.read_reply(op, self.sequence)
                if not result.get('ok'):
                    raise ValueError(f'RP rejected command: {result}')
                return result
            except socket.timeout:
                if attempt == 2:
                    raise TimeoutError('No tape response. Load/resume the current firmware and '
                                       'start RTT channel 2 on port 9092.') from None

    def tape(self, filename):
        data = Path(filename).expanduser().read_bytes()
        blocks = validate_tap(data)
        status = self.request(6)
        if len(data) > status['capacity']:
            raise ValueError(f'TAP is {len(data)} bytes; RP capacity is {status["capacity"]} bytes')
        self.request(1, struct.pack('<II', len(data), zlib.crc32(data)))
        for offset in range(0, len(data), 512):
            self.request(2, struct.pack('<I', offset) + data[offset:offset+512])
            print(f'\rUploaded {min(offset+512,len(data))}/{len(data)} bytes', end='', flush=True)
        print()
        result = self.request(3)
        print(f'{blocks} blocks buffered. Armed for the Spectrum ROM loader.')
        return result

    def command(self, arguments):
        if not arguments:
            return
        name, *rest = arguments
        if name == 'tape' and len(rest) == 1:
            result = self.tape(rest[0])
        elif name == 'mode' and rest in (['normal'], ['fast']):
            result = self.request(7, bytes([rest[0] == 'fast']))
        elif name in ('stop', 'rewind', 'status', 'reset') and not rest:
            result = self.request({'stop': 4, 'rewind': 5, 'status': 6, 'reset': 8}[name])
        else:
            raise ValueError('Commands: tape <tap-file>, stop, rewind, status, reset, mode normal|fast, quit')
        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9092)
    parser.add_argument('command', nargs='*')
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port), timeout=3) as sock:
        sock.settimeout(3)
        client = TapeClient(sock)
        if args.command:
            client.command(args.command)
        else:
            setup_terminal()
            print('Commands: tape <tap-file>, stop, rewind, status, reset, mode normal|fast, quit')
            print('Tab completes filenames and commands; Up/Down recalls history.')
            print('Leaving this tool keeps the buffered tape on the RP.')
            client.command(['status'])
            while True:
                try:
                    words = shlex.split(input('tape> '), posix=os.name != 'nt')
                    if os.name == 'nt':
                        words = [w[1:-1] if len(w)>1 and w[0]==w[-1] and w[0] in '\"\'' else w for w in words]
                    if words in (['quit'], ['exit']):
                        break
                    client.command(words)
                except (ValueError, OSError) as error:
                    print(error)
                except (EOFError, KeyboardInterrupt):
                    print()
                    break


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))

#!/usr/bin/env python3
"""Tape and TR-DOS disk media for the RP2350 driver over RTT channel 2.

Uploads a buffered TAP and controls its playback, and mounts TRD/SCL disk
images in drives A..D (stored in RP flash, so they survive an RP reset).
Run without a command for an interactive prompt. Python standard library only.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import struct
import time
import zlib

# readline adds Up/Down command recall to input() on macOS and Linux.
try:
    import readline
except ImportError:
    readline = None

HEADER = struct.Struct('<2sBBIH')
MAX_PAYLOAD = 2052  # Request payload limit (disk chunk + offset).
DISK_CHUNK = 2048   # Tape chunks stay 512 bytes for older firmware.
DISK_WINDOW = 3     # Chunks in flight; the RP's 8 KiB RTT down buffer holds three.
MAX_REPLY = 1024    # Disk status replies are longer than requests.
DRIVES = 'ABCD'
COMMANDS = ('tape <tap-file>, stop, rewind, reset, mode normal|fast, '
            'disk <trd|scl-file> [A|B|C|D] [ro], eject [A|B|C|D], blank [A|B|C|D] [label], '
            'disks, status, quit')

# TR-DOS geometry: 80 cylinders x 2 sides x 16 sectors of 256 bytes.
SECTOR = 256
TRD_SIZE = 80 * 2 * 16 * SECTOR
TRD_SECTORS = TRD_SIZE // SECTOR


def command_completions(line):
    """Complete the whole command, quoting paths so shlex can read them back."""
    commands = ('tape ', 'disk ', 'eject', 'blank', 'disks', 'stop', 'rewind', 'status', 'reset',
                'mode normal', 'mode fast', 'quit')
    verb = next((v for v in ('tape ', 'disk ') if line.startswith(v)), None)
    if verb is None:
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
            matches.append(verb + shlex.quote(path))
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


def disk_info_sector(files, next_free, label):
    """TR-DOS track 0 sector 9: free-space pointer, disk type and label."""
    info = bytearray(SECTOR)
    info[0xe1] = next_free % 16           # first free sector
    info[0xe2] = next_free // 16          # first free logical track
    info[0xe3] = 0x16                     # 80 cylinders, double sided
    info[0xe4] = files
    info[0xe5:0xe7] = (TRD_SECTORS - next_free).to_bytes(2, 'little')
    info[0xe7] = 0x10                     # TR-DOS id
    info[0xea:0xf3] = b' ' * 9
    info[0xf5:0xfd] = label_bytes(label)
    return info


def label_bytes(label):
    return label.encode('ascii', 'replace')[:8].ljust(8, b' ')


def blank_trd(label):
    image = bytearray(16 * SECTOR)
    image[8 * SECTOR:9 * SECTOR] = disk_info_sector(0, 16, label)
    return bytes(image)


def scl_to_trd(data, label):
    """Lay out the SCL's files from track 1 like TR-DOS, with a catalog."""
    if data[:8] != b'SINCLAIR' or len(data) < 13:
        raise ValueError('Not an SCL file (no SINCLAIR signature)')
    count = data[8]
    position = 9 + 14 * count
    if count > 128 or position > len(data) - 4:
        raise ValueError(f'SCL catalog is truncated ({count} files)')
    if sum(data[:-4]) & 0xffffffff != int.from_bytes(data[-4:], 'little'):
        print('Warning: SCL checksum mismatch; converting anyway')
    image = bytearray(TRD_SIZE)
    next_free = 16
    for index in range(count):
        entry = data[9 + 14 * index:9 + 14 * (index + 1)]
        sectors = entry[13]
        size = sectors * SECTOR
        if position + size > len(data) - 4:
            raise ValueError(f'SCL file {index + 1} is truncated')
        if next_free + sectors > TRD_SECTORS:
            raise ValueError('SCL files do not fit on an 80-track double-sided disk')
        image[16 * index:16 * index + 14] = entry
        image[16 * index + 14] = next_free % 16
        image[16 * index + 15] = next_free // 16
        image[next_free * SECTOR:(next_free + sectors) * SECTOR] = data[position:position + size]
        position += size
        next_free += sectors
    image[8 * SECTOR:9 * SECTOR] = disk_info_sector(count, next_free, label)
    return bytes(image)


def disk_image(filename):
    """Return the TRD bytes to upload: SCL converted, empty tail trimmed.

    The RP reads past the uploaded size as zeros, so trimming only saves time."""
    path = Path(filename).expanduser()
    data = path.read_bytes()
    if data[:8] == b'SINCLAIR':
        data = scl_to_trd(data, path.stem)
    elif path.suffix.lower() not in ('.trd', ''):
        raise ValueError(f'{path.name}: expected a .trd or .scl image')
    if not data or len(data) > TRD_SIZE:
        raise ValueError(f'TRD is {len(data)} bytes; expected 1..{TRD_SIZE}')
    if len(data) % SECTOR:
        data += bytes(SECTOR - len(data) % SECTOR)
    end = len(data.rstrip(b'\0'))
    end = max(16 * SECTOR, -(-end // SECTOR) * SECTOR)
    return data[:end].ljust(16 * SECTOR, b'\0')


def parse_drive(word):
    drive = word.upper().rstrip(':')
    if len(drive) != 1 or drive not in DRIVES:
        raise ValueError(f'Drive must be one of {", ".join(DRIVES)}')
    return DRIVES.index(drive)


def format_disks(result):
    if not result.get('disk'):
        return 'Firmware has no disk support.'
    lines = []
    for drive in result['drives']:
        if drive['present']:
            flags = ' (read-only)' if drive['write_protect'] else ''
            lines.append(f"{drive['drive']}: {drive['name']}  {drive['size']} bytes{flags}")
        else:
            lines.append(f"{drive['drive']}: empty")
    if result.get('uploading', -1) >= 0:
        lines.append(f"Uploading to {DRIVES[result['uploading']]}: {result['received']} bytes")
    if result.get('dirty'):
        lines.append('Unsaved sector writes are pending (flushed after 0.5 s of drive inactivity).')
    return '\n'.join(lines)


class MediaClient:
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
                if version != 1 or size > MAX_REPLY:
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
                    raise TimeoutError('No media response. Load/resume the current firmware and '
                                       'start RTT channel 2 on port 9092.') from None

    def pipelined(self, op, payloads, total):
        """Keep DISK_WINDOW requests in flight; the RP answers them in order.

        No retransmission: a lost reply aborts, and the upload is restarted."""
        pending, sent = [], 0
        try:
            for payload in payloads:
                self.sequence = (self.sequence + 1) & 0xffffffff
                self.sock.sendall(frame(op, self.sequence, payload))
                pending.append((self.sequence, len(payload) - 4))
                while len(pending) >= DISK_WINDOW or (pending and sent + sum(n for _, n in pending) == total):
                    sequence, size = pending.pop(0)
                    result = self.read_reply(op, sequence)
                    if not result.get('ok'):
                        raise ValueError(f'RP rejected upload at byte {sent}: {result}')
                    sent += size
                    print(f'\rUploaded {sent}/{total} bytes', end='', flush=True)
        except socket.timeout:
            raise TimeoutError(f'Upload stalled at byte {sent}; run the command again') from None
        finally:
            print()

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

    def disk(self, filename, drive=0, write_protect=False, image=None, name=None):
        data = image if image is not None else disk_image(filename)
        name = (name or Path(filename).name)[:24].encode('ascii', 'replace')
        started = time.monotonic()
        self.request(0x10, struct.pack('<BBII', drive, int(write_protect), len(data), zlib.crc32(data)) + name)
        self.pipelined(0x11, [struct.pack('<I', offset) + data[offset:offset+DISK_CHUNK]
                              for offset in range(0, len(data), DISK_CHUNK)], len(data))
        result = self.request(0x12)
        elapsed = time.monotonic() - started
        print(f'Mounted in drive {DRIVES[drive]} in {elapsed:.1f} s ({len(data)/1024/elapsed:.1f} KiB/s).')
        return result

    def command(self, arguments):
        if not arguments:
            return
        name, *rest = arguments
        if name == 'disk' and 1 <= len(rest) <= 3:
            options = [word.lower() for word in rest[1:]]
            write_protect = 'ro' in options
            drives = [word for word in rest[1:] if word.lower() != 'ro']
            if len(drives) > 1 or options.count('ro') > 1:
                raise ValueError('Usage: disk <trd|scl-file> [A|B|C|D] [ro]')
            self.disk(rest[0], parse_drive(drives[0]) if drives else 0, write_protect)
            print(format_disks(self.request(0x14)))
            return
        if name == 'blank' and len(rest) <= 2:
            drive = parse_drive(rest[0]) if rest else 0
            label = rest[1] if len(rest) > 1 else 'BLANK'
            self.disk(label, drive, image=blank_trd(label), name=f'blank {label}')
            print(format_disks(self.request(0x14)))
            return
        if name == 'eject' and len(rest) <= 1:
            print(format_disks(self.request(0x13, bytes([parse_drive(rest[0]) if rest else 0]))))
            return
        if name == 'disks' and not rest:
            print(format_disks(self.request(0x14)))
            return
        if name == 'tape' and len(rest) == 1:
            result = self.tape(rest[0])
        elif name == 'mode' and rest in (['normal'], ['fast']):
            result = self.request(7, bytes([rest[0] == 'fast']))
        elif name in ('stop', 'rewind', 'status', 'reset') and not rest:
            result = self.request({'stop': 4, 'rewind': 5, 'status': 6, 'reset': 8}[name])
        else:
            raise ValueError('Commands: ' + COMMANDS)
        print(json.dumps(result, indent=2))
        if name == 'status':
            print(format_disks(self.request(0x14)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9092)
    parser.add_argument('command', nargs='*')
    args = parser.parse_args()
    with socket.create_connection((args.host, args.port), timeout=3) as sock:
        sock.settimeout(3)
        client = MediaClient(sock)
        if args.command:
            client.command(args.command)
        else:
            setup_terminal()
            print('Commands: ' + COMMANDS)
            print('Tab completes filenames and commands; Up/Down recalls history.')
            print('Leaving this tool keeps the buffered tape and mounted disks on the RP.')
            client.command(['status'])
            while True:
                try:
                    words = shlex.split(input('zx> '), posix=os.name != 'nt')
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

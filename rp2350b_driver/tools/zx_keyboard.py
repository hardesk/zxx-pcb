#!/usr/bin/env python3
"""Real-time held-key sender for RP2350 RTT channel 1 (stdlib only: tkinter).

A focused window gets real key-down / key-up events, so ZX keys are held exactly
as long as you hold them: games, chords and simultaneous keys work. Physical
keys are sent unshifted; host Shift = Caps Shift (0x100), host Ctrl = Symbol
Shift (0x101), as on a real Spectrum. F1/F2 also act as Caps/Symbol Shift.
F10 resets the RZ80. Focus loss releases everything. Spectrum conversion stays
on the RP.
"""
import argparse
import socket
import struct
import time
import tkinter as tk

MAX_KEYS = 16


def packet(keys):
    values = sorted(set(keys) - {0})
    if len(values) > MAX_KEYS:
        raise ValueError("At most 16 simultaneous host keys")
    payload = struct.pack('<16H', *(values + [0] * (MAX_KEYS - len(values))))
    return b'ZK' + payload + bytes([sum(payload) & 255])


def connect(host, port):
    """Open the RTT keyboard socket and wait for the RP2350 to acknowledge."""
    sock = socket.create_connection((host, port), timeout=2)
    try:
        sock.sendall(packet([]))
        sock.settimeout(3)
        try:
            if b'K' not in sock.recv(64):
                raise RuntimeError('No keyboard acknowledgement from RP2350.')
        except socket.timeout:
            raise RuntimeError('RTT connected, but RP2350 did not acknowledge input. '
                               'Load the latest firmware, resume the CPU, and check RTT channel 1.') from None
    except BaseException:
        sock.close()
        raise
    sock.setblocking(False)
    return sock


SPECIAL = {
    'Shift_L': 0x100, 'Shift_R': 0x100, 'F1': 0x100,
    'Control_L': 0x101, 'Control_R': 0x101, 'F2': 0x101,
    'Left': 0x102, 'Down': 0x103, 'Up': 0x104, 'Right': 0x105,
    'BackSpace': 0x106, 'Delete': 0x106, 'Escape': 0x107,
    'Return': 0x108, 'KP_Enter': 0x108, 'Tab': 0x10a, 'F10': 0x10b,
    'space': 0x20,
}
# Keysym name -> character on the *unshifted* physical key (US layout), so a
# key keeps one identity whether or not Shift was down at press/release time.
PUNCT = {
    'minus': '-', 'equal': '=', 'bracketleft': '[', 'bracketright': ']',
    'backslash': '\\', 'semicolon': ';', 'apostrophe': "'", 'comma': ',',
    'period': '.', 'slash': '/', 'grave': '`',
    'exclam': '1', 'at': '2', 'numbersign': '3', 'dollar': '4', 'percent': '5',
    'asciicircum': '6', 'ampersand': '7', 'asterisk': '8', 'parenleft': '9',
    'parenright': '0', 'underscore': '-', 'plus': '=', 'braceleft': '[',
    'braceright': ']', 'bar': '\\', 'colon': ';', 'quotedbl': "'",
    'less': ',', 'greater': '.', 'question': '/', 'asciitilde': '`',
}
SHIFTED_CHARS = dict(zip('!@#$%^&*()_+{}|:"<>?~', "1234567890-=[]\\;',./`"))
# Windows virtual-key codes are physical and layout-stable for these keys.
WIN_OEM = {0xBA: ';', 0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/',
           0xC0: '`', 0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: "'"}
NAMES = {0x100: 'CAPS', 0x101: 'SYM', 0x102: '←', 0x103: '↓', 0x104: '↑',
         0x105: '→', 0x106: 'DEL', 0x107: 'ESC', 0x108: 'ENTER', 0x10a: 'TAB',
         0x10b: 'RESET', 0x20: 'SPACE'}


def host_code(keysym, char, keycode, windows):
    """Map a Tk key event to the host key identity the RP expects (or None)."""
    if keysym in SPECIAL:
        return SPECIAL[keysym]
    if windows:
        if 0x30 <= keycode <= 0x39 or 0x41 <= keycode <= 0x5A:
            return ord(chr(keycode).lower())
        if keycode in WIN_OEM:
            return ord(WIN_OEM[keycode])
    if keysym in PUNCT:
        return ord(PUNCT[keysym])
    for c in (keysym, char):
        if c and len(c) == 1 and 32 < ord(c) <= 126:
            return ord(SHIFTED_CHARS.get(c, c).lower())
    return None  # Cmd/Alt/Caps Lock/unmapped keys are ignored.


class KeyState:
    """Held-key set with autorepeat suppression.

    Windows repeats as extra presses (ignored while held). X11 and macOS (Tk
    inserts a KeyRelease before each repeated KeyPress) repeat as release+press
    pairs. Releases are therefore confirmed only after a short grace period and
    cancelled if the same key is pressed again within it; otherwise every
    repeat would briefly release the key on the Spectrum.
    """

    def __init__(self, release_grace=0.04):
        self.grace = release_grace
        self.held = {}            # keycode -> host code
        self.pending = {}         # keycode -> time of tentative release

    def press(self, keycode, code, now):
        # macOS keycodes embed the character, so a repeat may arrive under a
        # different keycode if a modifier changed; match pending by host code.
        repeat = next((k for k in self.pending
                       if k == keycode or self.held.get(k) == code), None)
        if repeat is not None:
            del self.pending[repeat]
            return False          # Autorepeat release+press pair
        if keycode in self.held:
            return False          # Windows autorepeat
        self.held[keycode] = code
        return True

    def release(self, keycode, code, now):
        if keycode not in self.held:
            # macOS packs the character into keycode, which can change if a
            # modifier changed mid-hold; fall back to the host identity.
            keycode = next((k for k, v in self.held.items() if v == code), None)
            if keycode is None:
                return False
        if self.grace:
            self.pending[keycode] = now
            return False
        del self.held[keycode]
        return True

    def tick(self, now):
        done = [k for k, t in self.pending.items() if now - t >= self.grace]
        for k in done:
            del self.pending[k]
            del self.held[k]
        return bool(done)

    def clear(self):
        changed = bool(self.held)
        self.held.clear()
        self.pending.clear()
        return changed

    def keys(self):
        return sorted(set(self.held.values()))[:MAX_KEYS]


class App:
    def __init__(self, sock):
        self.sock = sock
        self.root = root = tk.Tk()
        self.windows = root.tk.call('tk', 'windowingsystem') == 'win32'
        self.state = KeyState()
        self.alive = True
        self.last_send = 0.0
        self.last_ack = time.monotonic()
        self.sent = None

        root.title('RZ80 keyboard')
        root.geometry('420x130')
        root.configure(bg='#202020')
        self.status = tk.Label(root, text='Focus this window and play.  Shift=CAPS  Ctrl=SYM  F10=reset',
                               fg='#9c9', bg='#202020', font=('TkDefaultFont', 11))
        self.status.pack(pady=(14, 6))
        self.view = tk.Label(root, text='—', fg='white', bg='#202020', font=('TkFixedFont', 18, 'bold'))
        self.view.pack()
        root.bind('<KeyPress>', self.on_press)
        root.bind('<KeyRelease>', self.on_release)
        root.bind('<FocusOut>', lambda e: self.update(self.state.clear()))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(1, self.tick)
        root.focus_force()

    def on_press(self, e):
        code = host_code(e.keysym, e.char, e.keycode, self.windows)
        if code is not None:
            self.update(self.state.press(e.keycode, code, time.monotonic()))
        return 'break'            # Stop Tab focus traversal, F10 menu, etc.

    def on_release(self, e):
        code = host_code(e.keysym, e.char, e.keycode, self.windows)
        if code is not None:
            self.update(self.state.release(e.keycode, code, time.monotonic()))
        return 'break'

    def update(self, changed):
        if not self.alive:
            return
        keys = self.state.keys()
        if changed and keys != self.sent:
            self.send(keys)
            self.view.config(text=' '.join(NAMES.get(k, chr(k).upper()) for k in keys) or '—')

    def send(self, keys):
        try:
            self.sock.sendall(packet(keys))
        except OSError as error:
            self.fail(f'Send failed: {error}')
            return
        self.sent, self.last_send = keys, time.monotonic()

    def tick(self):
        if not self.alive:
            return
        now = time.monotonic()
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    return self.fail('RTT server disconnected.')
                if b'K' in data:
                    self.last_ack = now
        except (BlockingIOError, InterruptedError):
            pass
        except OSError as error:
            return self.fail(f'Receive failed: {error}')
        if now - self.last_ack > 3:
            return self.fail('RP2350 stopped acknowledging keyboard input.')
        self.update(self.state.tick(now))
        if now - self.last_send >= 0.1:      # Keepalive; firmware times out at 500 ms.
            self.send(self.state.keys())
        self.root.after(5, self.tick)

    def fail(self, message):
        self.alive = False
        self.state.clear()
        self.status.config(text=message, fg='#f66')
        self.view.config(text='disconnected')
        self.root.unbind('<KeyPress>')
        self.root.unbind('<KeyRelease>')

    def close(self):
        try:
            self.sock.sendall(packet([]))
        except OSError:
            pass
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9091)
    args = parser.parse_args()
    sock = connect(args.host, args.port)
    print('RP2350 keyboard acknowledged. Keep the window focused; close it to exit.')
    try:
        App(sock).root.mainloop()
    finally:
        sock.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError) as error:
        raise SystemExit(str(error))

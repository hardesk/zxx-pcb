#!/usr/bin/env python3
"""Cross-check the Python wire encoder and actual C++ matrix/packet decoder."""
from pathlib import Path
import importlib.util
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zx_keyboard', root / 'tools/zx_keyboard.py')
sender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sender)
assert sender.packet([ord('a'), ord('a')]) == sender.packet([ord('a')])
try:
    sender.packet(range(1, 18))
    raise AssertionError('missing key limit')
except ValueError:
    pass
# Held-key state: autorepeat delivered as release+press pairs (X11, macOS Tk)
# must not release the key, even momentarily; a real release must.
s = sender.KeyState()
assert s.press(65, ord('a'), 0.0) and s.keys() == [ord('a')]
for t in (0.5, 0.53, 0.56):
    assert not s.release(65, ord('a'), t)
    assert not s.press(65, ord('a'), t)
    assert not s.tick(t + 0.01) and s.keys() == [ord('a')]
assert not s.press(65, ord('a'), 0.6)            # Windows-style repeat.
assert not s.release(65, ord('a'), 1.0) and s.keys() == [ord('a')]
assert not s.tick(1.0 + s.grace / 2) and s.keys() == [ord('a')]
assert s.tick(1.0 + s.grace) and s.keys() == []
# macOS keycode changes when a modifier changes mid-hold.
assert s.press(65, ord('a'), 2.0)
assert not s.release(97, ord('a'), 2.1) and not s.press(97, ord('a'), 2.1)
assert not s.tick(2.2) and s.keys() == [ord('a')]
assert not s.release(97, ord('a'), 2.3) and s.tick(2.4) and s.keys() == []
# Two physical keys with one identity: releasing one keeps the other.
assert s.press(1, 0x100, 3.0) and s.press(2, 0x100, 3.0)
s.release(1, 0x100, 3.1); s.tick(3.2)
assert s.keys() == [0x100]
assert s.clear() and s.keys() == []

source = r'''
#include "zx_keyboard.hpp"
#include <cassert>
#include <array>
#include <initializer_list>
int main() {
    ZxKeyboard k;
    auto keys = [&](std::initializer_list<uint16_t> codes) { k.set_host_keys(codes.begin(), codes.size()); };
    assert(k.read(0xfefe) == 0xbf);
    for (unsigned row=0; row<8; ++row) for (unsigned col=0; col<5; ++col) {
        k.clear(); k.set_key(row,col,true);
        assert(k.read(uint16_t(0xfffe ^ (0x100 << row))) == (0xbf & ~(1 << col)));
        assert(k.read(0xfffe) == 0xbf);
        assert(k.read(0x00fe) == (0xbf & ~(1 << col)));
        assert(k.read(0x00ff) == 0xff);
        k.set_key(row,col,false); assert(k.read(0x00fe) == 0xbf);
    }
    keys({'a','q'});
    assert(k.read(0xf9fe) == 0xbe); // Both selected rows combined with AND.
    keys({'"',';'});
    assert(k.read(0x7ffe) == 0xbd); // Symbol Shift.
    assert(k.read(0xdffe) == 0xbc); // P and O.
    keys({';'}); assert(k.read(0x7ffe) == 0xbd && k.read(0xdffe) == 0xbd);
    keys({}); assert(k.read(0x00fe) == 0xbf);
    keys({'A'}); assert(k.read(0xfdfe) == 0xbe && k.read(0xfefe) == 0xbe);
    keys({ZxKeyboard::Left, ZxKeyboard::Backspace});
    assert(k.read(0xf7fe) == 0xaf && k.read(0xeffe) == 0xbe && k.read(0xfefe) == 0xbe);
    keys({'?'}); assert(k.read(0xfefe) == 0xb7 && k.read(0x7ffe) == 0xbd);
    keys({'='}); assert(k.read(0xbffe) == 0xbd);
    keys({':'}); assert(k.read(0xfefe) == 0xbd);
    keys({','}); assert(k.read(0x7ffe) == 0xb5);
    keys({'.'}); assert(k.read(0x7ffe) == 0xb9);
    keys({0xa3}); assert(k.read(0xfefe) == 0xbb);
    keys({0xffff}); assert(k.read(0x00fe) == 0xbf);
    ZxKeyboardReceiver r;
    const uint8_t quote[] = {QUOTE_PACKET};
    const uint8_t empty[] = {EMPTY_PACKET};
    auto feed = [&](const uint8_t* packet, uint32_t now) {
        for(unsigned i=0;i<35;++i) r.feed(packet[i], now, k);
    };
    feed(quote, 100);
    assert(k.read(0xdffe) == 0xbe && k.read(0x7ffe) == 0xbd);
    r.expire(599,k); assert(k.read(0x7ffe) == 0xbd);
    r.expire(600,k); assert(k.read(0x00fe) == 0xbf);
    uint8_t corrupt[35]; for(unsigned i=0;i<35;++i) corrupt[i]=quote[i];
    corrupt[34] ^= 1;
    feed(corrupt,700); assert(k.read(0x00fe) == 0xbf);
    r.feed(0x5a,701,k); r.feed(0x33,701,k); // Extra noise followed by valid frame.
    feed(quote,702); assert(k.read(0x7ffe) == 0xbd);
    feed(empty,703); assert(k.read(0x00fe) == 0xbf);
    for(unsigned i=0;i<10;++i) r.feed(quote[i],800,k);
    feed(quote,1100); assert(k.read(0x7ffe) == 0xbd); // Stale partial packet discarded.
    const uint8_t reset[] = {RESET_PACKET};
    auto bad_reset=std::array<uint8_t,35>{};
    for(unsigned i=0;i<35;++i) bad_reset[i]=reset[i];bad_reset[34]^=1;
    feed(bad_reset.data(),1200);assert(!r.take_reset_request());
    feed(reset,1201);assert(r.take_reset_request());assert(!r.take_reset_request());
    assert(k.read(0x00fe)==0xbf); // Reset is not a Spectrum matrix key.
    feed(reset,1202);assert(!r.take_reset_request()); // Repeated held snapshots.
    k.clear();feed(reset,1203);assert(!r.take_reset_request()); // Machine reset cannot re-trigger held F10.
    feed(empty,1204);feed(reset,1205);assert(r.take_reset_request());
    r.expire(1705,k);feed(reset,1706);assert(r.take_reset_request());
    feed(quote,0xffffff00u);
    r.expire(0x100,k); assert(k.read(0x00fe) == 0xbf); // Millisecond counter wraps.
}
'''.replace('QUOTE_PACKET', ','.join(map(str, sender.packet([ord('"')])))).replace('RESET_PACKET', ','.join(map(str, sender.packet([0x10b])))).replace('EMPTY_PACKET', ','.join(map(str, sender.packet([]))))
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    (p/'test.cpp').write_text(source)
    subprocess.run(['c++','-std=c++20','-fsanitize=address,undefined','-I',str(root),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
print('PASS: sender autorepeat, wire compatibility, matrix, chords, releases, resync and timeout')

#!/usr/bin/env python3
"""Flash once, reset/run numbered event cases, and retain full RTT GPIO captures."""
import argparse,socket,time,re,json,subprocess
from pathlib import Path
from capture_wait_trace import command
p=argparse.ArgumentParser();p.add_argument('elf',type=Path);p.add_argument('output',type=Path);p.add_argument('--cases',default='0:33');p.add_argument('--no-flash',action='store_true');a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
cache=(a.elf.parent/'CMakeCache.txt').read_text();nm=re.search(r'^CMAKE_NM:FILEPATH=(.*)$',cache,re.M)[1]
symbols=subprocess.check_output([nm,str(a.elf)],text=True)
addr=int(re.search(r'^([0-9a-f]+) [A-Za-z] event_test_case$',symbols,re.M)[1],16)
ids=list(range(*map(int,a.cases.split(':')))) if ':' in a.cases else list(map(int,a.cases.split(',')))
with socket.create_connection(('localhost',6666),timeout=30) as tcl:
 command(tcl,'rtt stop')
 if not a.no_flash:
  reply=command(tcl,f'capture {{program {{{a.elf.resolve()}}} verify reset}}')
  if '** Verified OK **' not in reply:raise RuntimeError(reply)
 for case in ids:
  command(tcl,'rtt stop');command(tcl,'reset run')
  command(tcl,'rtt setup 0x20000000 0x80000 "SEGGER RTT"');command(tcl,'rtt polling_interval 1');command(tcl,'rtt start')
  data=bytearray();sent=False;deadline=time.monotonic()+15
  with socket.create_connection(('localhost',9090),timeout=5) as rtt:
   rtt.settimeout(.2)
   while time.monotonic()<deadline:
    try:part=rtt.recv(65536)
    except TimeoutError:continue
    if not part:raise RuntimeError('RTT disconnected')
    data.extend(part)
    if not sent and b'event harness ready' in data:
     command(tcl,f'mww 0x{addr:08x} {case}');sent=True
    if b'case end ' in data:break
  text=data.decode(errors='replace');m=re.search(r'case begin .*?name=(\S+)',text)
  name=m[1] if m else f'case_{case}'
  (a.output/(name+'.log')).write_bytes(data)
  summary=re.search(r'^summary .*$',text,re.M)
  print(name,summary[0] if summary else 'NO SUMMARY',flush=True)
  if b'case end ' not in data:raise RuntimeError(f'case {case} incomplete')

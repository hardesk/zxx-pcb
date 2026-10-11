#!/usr/bin/env python3
"""Check tape filename completion, shell quoting, and real terminal keys."""
import importlib.util
import os
from pathlib import Path
import pty
import select
import shlex
import subprocess
import sys
import tempfile
import time
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('zx_tape',root/'tools/zx_tape.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)
    (path/'game file.tap').touch()
    (path/'levels with spaces').mkdir()
    (path/'levels with spaces'/'part 2.tap').touch()
    previous=Path.cwd();os.chdir(path)
    try:
        assert module.command_completions('tape ga')==["tape 'game file.tap'"]
        assert shlex.split(module.command_completions('tape "game f')[0])==['tape','game file.tap']
        directory=module.command_completions('tape lev')[0]
        assert shlex.split(directory)==['tape','levels with spaces/']
        assert shlex.split(module.command_completions(directory+'pa')[0])==['tape','levels with spaces/part 2.tap']
        assert module.command_completions('tape nonexistent/')==[]
        assert module.command_completions('mo')==['mode normal','mode fast']
        assert shlex.split(module.command_completions('tape '+str(path)+'/ga')[0])==['tape',str(path/'game file.tap')]
        if module.readline is not None:
            # A PTY exercises actual Tab and Up-arrow handling, not just the callback.
            master,slave=pty.openpty()
            code=f"import runpy; m=runpy.run_path({str(root/'tools/zx_tape.py')!r}); m['setup_terminal'](); print('FIRST='+input('first> ')); print('SECOND='+input('second> '))"
            child=subprocess.Popen([sys.executable,'-c',code],stdin=slave,stdout=slave,stderr=slave,cwd=path)
            os.close(slave);output=bytearray()
            def until(marker):
                end=time.monotonic()+5
                while marker not in output:
                    if time.monotonic()>end:raise AssertionError(output.decode(errors='replace'))
                    if select.select([master],[],[],.1)[0]:output.extend(os.read(master,4096))
            try:
                until(b'first> ');os.write(master,b'tape ga\t\n')
                until(b'second> ');os.write(master,b'\x1b[A\n')
                until(b"SECOND=tape 'game file.tap'")
                child.wait(timeout=2)
                assert child.returncode==0 and b"FIRST=tape 'game file.tap'" in output
            finally:
                if child.poll() is None:child.kill();child.wait()
                os.close(master)
    finally:os.chdir(previous)
print('PASS: filename/directory completion, spaces, open quotes, command completion, Tab and Up history')

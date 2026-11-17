"""Opt-in continuous demo against the real Kodama source, never a mock kernel."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
import unittest


@unittest.skipUnless(os.environ.get('DBG3K_QEMU_TEST') == '1' and
                     os.environ.get('DBG3K_KODAMA_SOURCE'),
                     'requires opt-in QEMU and DBG3K_KODAMA_SOURCE checkout')
class LiveDemoTests(unittest.TestCase):
    def test_repeating_cycles_reclaim_frames_and_remain_debuggable(self):
        root = Path(__file__).resolve().parents[1]
        source = Path(os.environ['DBG3K_KODAMA_SOURCE']).resolve()
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            subprocess.run(['make', '-C', str(root / 'examples/kodama-live'),
                            f'KODAMA_DIR={source}', f'OUT={folder}'],
                           check=True, capture_output=True, timeout=40)
            elf = folder / 'live.elf'
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            with (folder / 'console.log').open('w+') as console:
                qemu = subprocess.Popen(['qemu-system-arm', '-M', 'mps2-an505', '-display', 'none',
                    '-serial', 'none', '-monitor', 'none', '-semihosting-config', 'enable=on,target=native',
                    '-device', f'loader,file={elf},cpu-num=0', '-S', '-gdb', f'tcp:127.0.0.1:{port}'],
                    stdout=console, stderr=console)
                try:
                    time.sleep(.2)
                    self.assertIsNone(qemu.poll())
                    # Reads only: no inferior calls, fabricated ticks or firmware patches.
                    expressions = dict(ticks='demo_ticks', triggers='demo_second_triggers',
                        started='demo_cycles_started', completed='demo_cycles_completed',
                        failed='demo_failed', live='g_live', allocations='g_allocations', frees='g_frees')
                    script = folder / 'inspect.gdb'
                    script.write_text('set pagination off\nset confirm off\n'
                        f'target remote 127.0.0.1:{port}\n'
                        'tbreak main\ncontinue\n'
                        'python\nimport gdb, json\n'
                        'assert gdb.selected_frame().find_sal().symtab is not None\nend\n'
                        'break demo_cycle_complete if demo_cycles_started == 3\ncontinue\n'
                        'python\n'
                        f'expressions = {expressions!r}\n'
                        'values = {k:int(gdb.parse_and_eval(v)) for k,v in expressions.items()}\n'
                        'values["occupied"] = sum(int(gdb.parse_and_eval("g_frames[%d].used" % i)) for i in range(3))\n'
                        'print("LIVE_ORACLE " + json.dumps(values))\nend\n'
                        'disable breakpoints\ndetach\nquit\n')
                    run = subprocess.run([os.environ.get('DBG3K_GDB', 'gdb'), '-q', '-nx', '-batch',
                        str(elf), '-x', str(script)], capture_output=True, text=True, timeout=20)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    values = json.loads(next(line.removeprefix('LIVE_ORACLE ') for line in run.stdout.splitlines()
                                             if line.startswith('LIVE_ORACLE ')))
                    self.assertEqual(values['started'], 3)
                    self.assertEqual(values['completed'], 2)  # breakpoint is before increment
                    self.assertGreaterEqual(values['triggers'], 2)
                    self.assertGreaterEqual(values['ticks'], 202)
                    self.assertEqual((values['failed'], values['live'], values['occupied']), (0, 0, 0))
                    self.assertEqual(values['allocations'], values['frees'])
                    # Detaching resumes the infinite app, including another full cycle.
                    time.sleep(1.2)
                    self.assertIsNone(qemu.poll(), 'main must not return/semihost-exit')
                finally:
                    if qemu.poll() is None:
                        qemu.terminate()
                    qemu.wait(timeout=5)
                console.seek(0)
                output = console.read()
                self.assertNotIn('LIVE ERROR', output)
                starts = [(int(cycle), int(tick)) for cycle, tick in re.findall(
                    r'LIVE cycle (\d+) started: tick (\d+)', output)]
                self.assertGreaterEqual(len(starts), 4, output)
                self.assertEqual(starts[:4], [(1, 0), (2, 100), (3, 200), (4, 300)])
                self.assertGreaterEqual(output.count('all frames reclaimed'), 4)
                self.assertGreaterEqual(output.count('local=42'), 4)
                receipt = os.environ.get('DBG3K_LIVE_RECEIPT')
                if receipt:
                    destination = Path(receipt)
                    destination.mkdir(parents=True, exist_ok=True)
                    (destination / 'console.log').write_text(output)
                    (destination / 'gdb.log').write_text(run.stdout + run.stderr)
                    (destination / 'oracle.json').write_text(json.dumps(values) + '\n')

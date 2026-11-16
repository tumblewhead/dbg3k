"""Opt-in end-to-end return capture with actual GDB and QEMU, no fake MI.

DBG3K_QEMU_TEST=1 PYTHONPATH=src python -m unittest discover -s tests -p test_qemu_returns.py -v
Requires gdb with ARM/Python, qemu-system-arm, arm-none-eabi-gcc.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import unittest

from dbg3k.app import DebuggerApp
from dbg3k.resources import EnergyModel


@unittest.skipUnless(os.environ.get('DBG3K_QEMU_TEST') == '1', 'opt-in real GDB/QEMU test')
class QemuReturnTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_step_continue_finish_and_return_retention(self):
        root = Path(__file__).resolve().parents[1]
        example = root / 'examples/an505'
        with TemporaryDirectory() as folder:
            elf = Path(folder) / 'firmware.elf'
            subprocess.run(['arm-none-eabi-gcc', '-mcpu=cortex-m33', '-mthumb',
                            '-O0', '-g3', '-ffreestanding', '-fno-builtin', '-nostdlib',
                            '-T', str(example / 'linker.ld'), str(example / 'startup.c'),
                            str(example / 'main.c'), '-o', str(elf)], check=True, capture_output=True)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            plugin_args = []
            if os.environ.get('DBG3K_QEMU_PLUGIN_TEST') == '1':
                plugin = Path(os.environ.get('DBG3K_PLUGIN', root / 'plugins/libdbg3k-counts.so')).resolve()
                plugin_args = ['-plugin', f'{plugin},out={folder}/counts.json,elf={elf}']
            qemu = subprocess.Popen([
                'qemu-system-arm', '-M', 'mps2-an505', '-display', 'none',
                '-serial', 'none', '-monitor', 'none', '-semihosting-config',
                'enable=on,target=native', '-kernel', str(elf), '-S',
                '-gdb', f'tcp:127.0.0.1:{port}', *plugin_args], stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE)
            try:
                await asyncio.sleep(.2)
                self.assertIsNone(qemu.poll())
                app = DebuggerApp(str(elf), os.environ.get('DBG3K_GDB', 'gdb'),
                                  f'127.0.0.1:{port}', history_dir=folder,
                                  instruction_profile=f'{folder}/counts.json' if plugin_args else None,
                                  energy_model=EnergyModel(100, 2, 3.3))
                async with app.run_test(size=(120, 40)) as pilot:
                    async def ready():
                        for _ in range(200):
                            await pilot.pause(.025)
                            if app.status == 'HALTED' and app.model.frames and not app.pending:
                                return
                        self.fail(f'Debugger not ready: {app.status}, {app.pending}, {list(app._log_lines)[-10:]}')
                    await ready()
                    app._send('-break-insert bar', 'test_break')
                    await ready()
                    app.action_continue_run()
                    await ready()
                    self.assertEqual(app.model.frames[0].function, 'bar')
                    self.assertIsNotNone(app.stack_profile.sample)
                    frames = app.stack_profile.sample['frames']
                    self.assertEqual(frames[0]['function'], 'bar')
                    self.assertIsNotNone(app.stack_profile.own_bytes(frames, 0))
                    self.assertGreaterEqual(app.stack_profile.own_bytes(frames, 0), 0)
                    # No finish command: ordinary stepping must capture bar(2)=6.
                    for _ in range(12):
                        app.action_step()
                        await ready()
                        if app._returns.for_caller(thread='1', caller='foo'):
                            break
                    series = app._returns.for_caller(thread='1', caller='foo')[0]
                    self.assertEqual(series.last.value, '6')
                    self.assertEqual(series.count, 1)
                    original = app._return_edge_nodes[series.key]
                    # A real o command must not double-count its probe + MI report.
                    self.assertEqual(app.model.frames[0].function, 'foo')
                    app.action_finish()
                    await ready()
                    foo_returns = app._returns.for_caller(thread='1', caller='main')
                    self.assertEqual(foo_returns[0].count, 1)
                    self.assertEqual(foo_returns[0].last.value, '8')
                    self.assertIs(app._return_edge_nodes[series.key], original)
                    app.action_continue_run()
                    await ready()
                    self.assertEqual(app.model.frames[0].function, 'bar')
                    # Continue from observed bar(3) catches 9 before next bar stop.
                    app.action_continue_run()
                    await ready()
                    self.assertEqual(series.count, 2)
                    self.assertEqual(series.last.value, '9')
                    self.assertIs(app._return_edge_nodes[series.key], original)
                    for _ in range(12):
                        app.action_next()
                        await ready()
                        if series.count == 3:
                            break
                    self.assertEqual(series.count, 3)
                    self.assertEqual(series.last.value, '12')
                    records = [json.loads(line) for line in app._trace.path.read_text().splitlines()]
                    self.assertTrue(all(record['schema'] == 'dbg3k.trace.v1' for record in records))
                    self.assertEqual([r['seq'] for r in records], list(range(1, len(records) + 1)))
                    returns = [r for r in records if r['kind'] == 'return' and r['callee'] == 'bar']
                    self.assertEqual([r['value'] for r in returns], ['6', '9', '12'])
                    self.assertTrue(all(r['origin'] == 'gdb-python-finish-breakpoint' for r in returns))
                    if plugin_args:
                        await pilot.pause(.3)
                        app._poll_instruction_profile()
                        self.assertEqual(app._count_status, '')
                        self.assertGreater(app.instruction_counts.total, 0)
                        body = app.catalog.lookup(app.stack_profile.sample['frames'][0]['pc'])
                        self.assertIsNotNone(body)
                        self.assertGreater(body.size, 0)
            finally:
                qemu.terminate()
                qemu.communicate(timeout=5)

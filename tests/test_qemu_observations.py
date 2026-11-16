"""Actual AN505/GDB capture; optional pinned Kodama ELF qualification.

DBG3K_QEMU_TEST=1 DBG3K_KODAMA_ELF=/path/demo.elf PYTHONPATH=src python -m unittest discover -s tests -p test_qemu_observations.py -v
"""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
import unittest
from elftools.elf.elffile import ELFFile

from dbg3k.app import DebuggerApp


def child(node, name):
    return next(c for c in node['children'] if c['name'] == str(name))


@unittest.skipUnless(os.environ.get('DBG3K_QEMU_TEST') == '1', 'opt-in real GDB/QEMU test')
class QemuObservationTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def debugger(self, elf, folder, expressions, *, sram=False):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        image = ['-device', f'loader,file={elf},cpu-num=0'] if sram else ['-kernel', str(elf)]
        qemu = subprocess.Popen(['qemu-system-arm', '-M', 'mps2-an505', '-display', 'none',
            '-serial', 'none', '-monitor', 'none', '-semihosting-config', 'enable=on,target=native',
            *image, '-S', '-gdb', f'tcp:127.0.0.1:{port}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            await asyncio.sleep(.2)
            self.assertIsNone(qemu.poll())
            app = DebuggerApp(str(elf), os.environ.get('DBG3K_GDB', 'gdb'), f'127.0.0.1:{port}',
                              history_dir=folder, observations=expressions)
            async with app.run_test(size=(120, 40)) as pilot:
                async def ready():
                    for _ in range(250):
                        await pilot.pause(.025)
                        if app.status == 'HALTED' and app.model.frames and not app.pending:
                            return
                    self.fail(f'Not ready: {app.status}, {app.pending}, {list(app._log_lines)[-12:]}')
                await ready()
                yield app, ready
        finally:
            qemu.terminate()
            qemu.communicate(timeout=5)

    def records(self, app):
        records = [json.loads(line) for line in app._trace.path.read_text().splitlines()]
        stops = {r['stop'] for r in records if r['kind'] == 'stop'}
        for record in records:
            self.assertEqual(record['schema'], 'dbg3k.trace.v1')
            self.assertEqual(record['session'], app._trace.session)
            if record['kind'] == 'observation':
                self.assertIn(record['stop'], stops)
                self.assertEqual(record['scope']['thread'], record['thread'])
                self.assertEqual(record['scope']['frame']['level'], 0)
        return records

    async def test_typed_aggregates_errors_limits_and_full_width(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'observations.c'
            source.write_text('''#include <stdint.h>
struct State { uint64_t large; int negative; int *pointer; int array[3]; };
volatile struct State state = {UINT64_MAX, -7, 0, {11,22,33}};
int huge[128];
int *bad = (int*)0xfffffff0;
__attribute__((noinline)) void checkpoint(void) { __asm volatile("nop"); }
int main(void) { checkpoint(); state.negative = -9; checkpoint(); for(;;){} }
''')
            elf = Path(folder) / 'observations.elf'
            # Older GNU linkers place an orphan build-ID note before .text,
            # which makes AN505 reset load the note header as SP/PC. Keep real
            # note provenance without moving the vector table off its base.
            linker = Path(folder) / 'linker.ld'
            linker.write_text((root / 'examples/an505/linker.ld').read_text().replace(
                '    .data :', '    .note.gnu.build-id : { *(.note.gnu.build-id) } > FLASH\n    .data :'))
            subprocess.run(['arm-none-eabi-gcc', '-mcpu=cortex-m33', '-mthumb', '-O0', '-g3',
                '-ffreestanding', '-fno-builtin', '-nostdlib', '-Wl,--build-id',
                '-T', str(linker), str(root / 'examples/an505/startup.c'),
                str(source), '-o', str(elf)], check=True, capture_output=True)
            with elf.open('rb') as stream:
                image = ELFFile(stream)
                text = image.get_section_by_name('.text')
                self.assertEqual(text['sh_addr'], 0x10000000)
                self.assertEqual(int.from_bytes(text.data()[:4], 'little'), 0x38010000)
                self.assertEqual(int.from_bytes(text.data()[4:8], 'little'), image['e_entry'])
            expressions = ['state', 'missing_symbol', 'state.large', 'huge', 'state.pointer',
                           '*state.pointer', 'bad', '*bad']
            async with self.debugger(elf, folder, expressions) as (app, ready):
                app._send('-break-insert checkpoint', 'test_break')
                await ready()
                snapshots = []
                for _ in range(2):
                    app.action_continue_run()
                    await ready()
                    records = self.records(app)
                    obs = {r['expression']: r for r in records if r['kind'] == 'observation' and r['stop'] == app.model.stop}
                    self.assertEqual(set(obs), set(expressions), list(app._log_lines)[-15:])
                    self.assertEqual(obs['state']['status'], 'ok', obs['state'])
                    self.assertEqual(child(obs['state']['value'], 'large')['value'], '18446744073709551615')
                    self.assertEqual(child(child(obs['state']['value'], 'array'), 1)['value'], '22')
                    self.assertEqual(obs['state.large']['value']['value'], '18446744073709551615')
                    self.assertEqual(obs['state.pointer']['value']['address'], '0x0')
                    self.assertFalse(obs['state.pointer']['value']['dereferenced'])
                    for expr in ('missing_symbol', '*state.pointer', '*bad'):
                        self.assertEqual(obs[expr]['status'], 'error', obs[expr])
                    self.assertEqual(obs['bad']['status'], 'ok')
                    self.assertEqual(obs['huge']['status'], 'partial')
                    self.assertTrue(obs['huge']['truncated'])
                    self.assertEqual(len(obs['huge']['value']['children']), 64)
                    self.assertEqual(obs['huge']['value']['total_children'], 128)
                    snapshots.append(child(obs['state']['value'], 'negative')['value'])
                self.assertEqual(snapshots, ['-7', '-9'])
                start = records[0]
                self.assertEqual(len(start['executable']['sha256']), 64)
                self.assertTrue(start['executable']['build_id'])
                self.assertTrue(any(r['kind'] == 'debugger_metadata' and r['gdb_version'] for r in records))
                # Independent GDB/MI oracle, not a second serializer read.
                oracle = []
                handle = app._handle
                def receive(record):
                    if record.kind == '^' and app.pending.get(record.token, (None,))[0] == 'oracle':
                        oracle.append(record.payload)
                    handle(record)
                app._handle = receive
                app._send('-data-evaluate-expression "state.large"', 'oracle')
                await ready()
                self.assertEqual(oracle[0]['value'], '18446744073709551615')

    @unittest.skipUnless(os.environ.get('DBG3K_KODAMA_ELF'), 'set DBG3K_KODAMA_ELF to real Kodama ARM example')
    async def test_kodama_tasks_across_event_stops(self):
        elf = Path(os.environ['DBG3K_KODAMA_ELF']).resolve()
        expressions = ["'kodama.c'::tasks", "'kodama.c'::running", "'kodama.c'::levels",
                       "'kodama.c'::clock_ticks", 'g_cmd', 'not_a_kodama_symbol']
        with TemporaryDirectory() as folder:
            async with self.debugger(elf, folder, expressions, sram=True) as (app, ready):
                app._send('-break-insert kodama_signal', 'test_break')
                app._send('-break-insert kodama_signal_and_pend', 'test_break')
                await ready()
                states = []
                for _ in range(2):
                    app.action_continue_run()
                    await ready()
                    records = self.records(app)
                    obs = {r['expression']: r for r in records if r['kind'] == 'observation' and r['stop'] == app.model.stop}
                    for expr in expressions[:-1]:
                        self.assertEqual(obs[expr]['status'], 'ok', obs[expr])
                    self.assertEqual(obs['not_a_kodama_symbol']['status'], 'error')
                    worker = child(obs["'kodama.c'::tasks"]['value'], 1)
                    values = {name: child(worker, name)['value'] for name in ('active', 'generation', 'waiting', 'seen')}
                    self.assertEqual(values['active'], '1')
                    self.assertEqual(values['generation'], '1')
                    self.assertEqual(values['waiting'], '1')
                    self.assertEqual(child(worker, 'subscription')['kind'], 'pointer')
                    oracle = []
                    handle = app._handle
                    def receive(record):
                        if record.kind == '^' and app.pending.get(record.token, (None,))[0] == 'oracle':
                            oracle.append(record.payload)
                        handle(record)
                    app._handle = receive
                    app._send('-data-evaluate-expression "\'kodama.c\'::tasks[1].seen"', 'oracle')
                    app._send('-var-create observation_oracle * "\'kodama.c\'::tasks"', 'oracle')
                    await ready()
                    self.assertEqual(oracle[0]['value'], values['seen'])
                    self.assertEqual(oracle[1]['type'], obs["'kodama.c'::tasks"]['type'])
                    app._send('-var-delete observation_oracle', 'oracle_delete')
                    await ready()
                    app._handle = handle
                    states.append(values)
                self.assertEqual([s['seen'] for s in states], ['0', '1'])
                if os.environ.get('DBG3K_OBSERVATION_RECEIPT'):
                    destination = Path(os.environ['DBG3K_OBSERVATION_RECEIPT'])
                    destination.mkdir(parents=True, exist_ok=True)
                    with app._trace.path.open('rb') as source, (destination / f'kodama-{app._trace.session}.jsonl').open('xb') as output:
                        shutil.copyfileobj(source, output)

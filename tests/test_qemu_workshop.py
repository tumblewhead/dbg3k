"""Run the handoff's paired launcher, GDB lesson and profiling on the real demo."""
import argparse
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
from test_demo_launcher import launcher, ROOT


@unittest.skipUnless(os.environ.get('DBG3K_QEMU_TEST') == '1' and
                     os.environ.get('DBG3K_QEMU_PLUGIN_TEST') == '1' and
                     os.environ.get('DBG3K_KODAMA_DEMO_ELF'), 'opt-in real demo, QEMU and counting plugin')
class WorkshopQemuTests(unittest.IsolatedAsyncioTestCase):
    async def test_guide_overview_plugin_rankings_and_short_api_trace(self):
        elf = Path(os.environ['DBG3K_KODAMA_DEMO_ELF']).resolve()
        kodama = elf.parents[2]
        with TemporaryDirectory() as directory:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            args = argparse.Namespace(kodama_dir=kodama, elf=elf,
                plugin=ROOT / 'plugins/libdbg3k-counts.so', output_dir=Path(directory),
                port=port, no_profile=False, api_probes=False, dbg3k=str(ROOT / '.venv/bin/dbg3k'),
                qemu='qemu-system-arm', gdb=os.environ.get('DBG3K_GDB', 'gdb'))
            qemu_command, debugger, run_dir = launcher.prepare(args)
            option = lambda name: debugger[debugger.index(name) + 1]
            with (run_dir / 'console.log').open('w+') as console:
                qemu = subprocess.Popen(qemu_command, stdout=console, stderr=console)
                try:
                    await asyncio.sleep(.2); self.assertIsNone(qemu.poll())
                    app = DebuggerApp(str(elf), args.gdb, option('--remote'),
                        history_dir=option('--history-dir'), instruction_profile=option('--instruction-profile'),
                        kodama=True, kodama_header=option('--kodama-header'), kodama_probes=False,
                        observations=['g_demo_shared.hfe_result', 'g_demo_shared.scratchpad.entries[0]'])
                    oracles = {}
                    handle = app._handle
                    def receive(record):
                        purpose = app.pending.get(record.token, (None,))[0]
                        if record.kind == '^' and purpose and purpose.startswith('workshop_oracle_'):
                            oracles[purpose.removeprefix('workshop_oracle_')] = record.payload
                        handle(record)
                    app._handle = receive
                    async with app.run_test(size=(150, 60)) as pilot:
                        async def ready():
                            for _ in range(600):
                                await pilot.pause(.025)
                                if app.status == 'HALTED' and app.model.frames and not app.pending:
                                    return
                            self.fail(f'Not ready: {app.status}, {app.pending}, {list(app._log_lines)[-8:]}')
                        def command(text):
                            app._send(f'-interpreter-exec console "{app._quoted(text)}"', 'workshop_command')
                        await ready()
                        app.set_visible_views({'source', 'console', 'kodama'})
                        for text in ['tbreak main', 'tbreak demo_checkpoint',
                                     'tbreak demo_checkpoint if g_demo_shared.runtime.elapsed_ticks >= 6000']:
                            command(text); await ready(); app.action_continue_run(); await ready()
                        for expression in ['g_demo_shared.runtime', 'g_demo_shared.notes.init',
                            'g_demo_shared.hfe_result', 'g_demo_shared.mellow', 'g_demo_shared.telemetry',
                            'g_demo_shared.scratchpad.entries[0]']:
                            command('print ' + expression)
                        for key, expression in dict(initialized='g_demo_shared.runtime.initialized',
                            failed='g_demo_shared.runtime.failed', mask='g_demo_shared.runtime.startup_mask',
                            hfe_count='g_demo_shared.hfe_result.stats.count',
                            launches='g_demo_shared.hfe_launches').items():
                            app._send(f'-data-evaluate-expression "{expression}"', 'workshop_oracle_' + key)
                        await ready()
                        values = {key: (int(data['value'] == 'true') if data['value'] in ('true', 'false')
                                        else int(data['value'], 0)) for key, data in oracles.items()}
                        self.assertEqual((values['initialized'], values['failed'], values['mask']), (1, 0, 1022))
                        self.assertGreater(values['hfe_count'], 0); self.assertGreater(values['launches'], 0)
                        for _ in range(80):
                            await pilot.pause(.025)
                            if app.instruction_counts.total > 0: break
                        self.assertGreater(app.instruction_counts.total, 0)
                        self.assertTrue(any('HFE' in name and app.instruction_counts.by_function.get(f.key, 0) > 0
                                            for f in app.catalog.functions for name in f.names))
                        app.set_energy_model(EnergyModel(48, 1, 1.8))  # Explicit teaching assumptions only.
                        app.set_visible_views({'kodama', 'run_graph', 'energy_graph'})
                        app._show_resources(); await pilot.pause()
                        self.assertTrue(app.query_one('#run_graph_content').rows)
                        self.assertTrue(app.query_one('#energy_graph_content').rows)
                        app.configure_kodama(True, option('--kodama-header'), True)
                        await ready()
                        command('tbreak kodama_pend'); await ready()
                        app.action_continue_run(); await ready()
                        self.assertTrue(any(s.origin == 'api' for s in app.kodama_history.samples))
                        profile = json.loads(Path(option('--instruction-profile')).read_text())
                        self.assertEqual(profile['elf_sha256'], app.catalog.sha256)
                        records = [json.loads(line) for line in app._trace.path.read_bytes().splitlines()]
                        chunks = [r for r in records if r['kind'] == 'code_catalog']
                        self.assertTrue(chunks)
                        self.assertEqual({r['elf_sha256'] for r in chunks}, {app.catalog.sha256})
                        self.assertEqual(len(chunks), chunks[0]['chunk_count'])
                        self.assertTrue(all(len(r['functions']) <= 128 for r in chunks))
                        self.assertEqual({f['key'] for r in chunks for f in r['functions']},
                                         {f.key for f in app.catalog.functions})
                        self.assertTrue(any(r['kind'] == 'observation' and r.get('status') == 'ok' for r in records))
                        receipt = os.environ.get('DBG3K_WORKSHOP_RECEIPT')
                        if receipt:
                            dest = Path(receipt); dest.mkdir(parents=True, exist_ok=True)
                            (dest / 'launch.json').write_bytes((run_dir / 'launch.json').read_bytes())
                            (dest / 'counts.json').write_text(json.dumps(profile) + '\n')
                            (dest / 'trace.jsonl').write_bytes(app._trace.path.read_bytes())
                            (dest / 'oracle.json').write_text(json.dumps(dict(values=values,
                                instruction_total=app.instruction_counts.total,
                                api_samples=sum(s.origin == 'api' for s in app.kodama_history.samples))) + '\n')
                finally:
                    if qemu.poll() is None: qemu.terminate()
                    qemu.wait(timeout=5)

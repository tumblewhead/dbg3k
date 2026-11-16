"""Growing JSONL replay, provenance, sticky assumptions and live IO recovery."""
from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from textual.widgets import DataTable, Static
from dbg3k.app import DebuggerApp
from dbg3k.graph_ui import RunRanking
from dbg3k.mi import Record
from dbg3k.profile_history import JsonlTail, ProfileHistory, recover_energy_model
from dbg3k.resources import EnergyModel, InstructionProfile
from dbg3k.trace import TraceWriter
from test_graphs import graph_catalog, counts


def event(kind, seq, session='session-a', **fields):
    return dict(schema='dbg3k.trace.v1', kind=kind, seq=seq, session=session, **fields)


def profile_event(code, seq=3, session='session-a', multiplier=1, run='run-a', **overrides):
    fields = dict(elf_sha256=code.sha256, run=run, profile_seq=multiplier, total=100 * multiplier,
                  unknown=5 * multiplier, complete=False,
                  functions={code.functions[0].key: 80 * multiplier, code.functions[1].key: 10 * multiplier,
                             code.functions[2].key: 5 * multiplier},
                  entry_hits={code.functions[0].key: 2 * multiplier, code.functions[1].key: 5 * multiplier,
                              code.functions[2].key: multiplier})
    fields.update(overrides)
    return event('instruction_profile', seq, session, **fields)


def model_event(seq=2, session='session-a', **fields):
    return event('energy_model', seq, session, ua_per_mhz=100, mips_per_mhz=2, voltage=3.3, **fields)


def append(path, record):
    with path.open('a') as stream:
        stream.write(json.dumps(record) + '\n')


class ProfileHistoryTests(unittest.TestCase):
    def test_writer_reopens_after_partial_multibyte_record(self):
        with TemporaryDirectory() as folder:
            with closing(TraceWriter('firmware.elf', 'localhost:1234', folder)) as first:
                path = first.path
            with path.open('ab') as stream:
                stream.write(b'{"truncated":"\xc2')
            with closing(TraceWriter('firmware.elf', 'localhost:1234', folder)) as writer:
                writer.record('return', stop=1, thread='1', caller='foo', callee='bar',
                              callee_display='bar(2)', value='6', origin='fixture')
                self.assertIn('bar(2)', writer.returns_tsv(thread='1', caller='foo', callee='bar'))
            tail = JsonlTail(path)
            records = tail.poll()
            self.assertEqual(tail.skipped, 1)
            self.assertTrue(any(r.get('kind') == 'return' for r in records))

    def test_tail_partial_utf8_malformed_and_in_place_rewrite(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'trace.jsonl'
            raw = json.dumps({'label': 'µA'}, ensure_ascii=False).encode() + b'\n'
            path.write_bytes(raw[:12])
            tail = JsonlTail(path)
            self.assertEqual(tail.poll(), [])
            with path.open('ab') as stream:
                stream.write(raw[12:] + b'broken\n')
            self.assertEqual(tail.poll(), [{'label': 'µA'}])
            self.assertEqual(tail.skipped, 1)
            self.assertEqual(tail.poll(), [])
            # Same inode, and replacement already larger than previous offset.
            replacement = {'new': 'x' * 80}
            path.write_text(json.dumps(replacement) + '\n')
            self.assertEqual(tail.poll(), [replacement])
            self.assertEqual(tail.generation, 1)

    def test_sessions_models_dedup_totals_and_build_validation(self):
        code = graph_catalog()
        state = ProfileHistory(code)
        state.apply(model_event())  # Legacy record without a build hash.
        state.apply(profile_event(code))
        self.assertEqual(state.profile.total, 100)
        self.assertEqual(state.energy_model.energy_pj(80), 13200)
        self.assertFalse(state.apply(profile_event(code)))
        state.apply(profile_event(code, seq=4, multiplier=2))
        self.assertEqual(state.profile.total, 200)  # cumulative replacement, not 100+200
        with self.assertRaises(ValueError):
            state.apply(profile_event(code, seq=5, multiplier=3, total=999))
        self.assertEqual(state.profile.total, 200)
        state.apply(event('session_start', 1, 'session-b', elf_sha256=code.sha256))
        state.apply(profile_event(code, session='session-b', run='run-b'))
        self.assertEqual(state.profile.total, 100)
        self.assertIsNone(state.energy_model)  # never attach session-a's model
        state.apply(profile_event(code, seq=6, multiplier=3))  # older session writes late
        self.assertEqual(state.selected_session, 'session-b')
        pinned = ProfileHistory(code, session='session-a')
        self.assertFalse(pinned.apply(profile_event(code, session='session-b')))
        with self.assertRaises(ValueError):
            pinned.apply(profile_event(code, elf_sha256='wrong-build'))
        self.assertIsNone(pinned.profile.run)

    def test_old_profile_without_entries_does_not_fabricate_zero_calls(self):
        code = graph_catalog()
        record = profile_event(code)
        del record['entry_hits']
        profile = InstructionProfile()
        profile.update_record(record, code)
        self.assertFalse(profile.entries_available)
        self.assertEqual(profile.total, 100)

    def test_recover_only_explicit_assumptions_bound_to_same_build(self):
        code = graph_catalog()
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'firmware_2026-11-16.jsonl'
            append(path, model_event())
            append(path, profile_event(code))
            # A later session has profiles but no configured model (user case).
            append(path, profile_event(code, session='session-b', run='run-b'))
            model, session = recover_energy_model(folder, 'firmware', code.sha256)
            self.assertEqual(model, EnergyModel(100, 2, 3.3))
            self.assertEqual(session, 'session-a')
            self.assertIsNone(recover_energy_model(folder, 'firmware', 'different-build'))


class HistoryWidgetTests(unittest.IsolatedAsyncioTestCase):
    def app(self, folder, **kwargs):
        code = graph_catalog()
        with patch('dbg3k.app.CodeCatalog', return_value=code):
            app = DebuggerApp('firmware.elf', 'gdb', 'localhost:1234', history_dir=folder, **kwargs)
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app._send = lambda *a, **k: None
        return app

    async def test_replay_grows_partial_lines_and_user_override_wins(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'recording.jsonl'
            code = graph_catalog()
            append(path, model_event())
            append(path, profile_event(code))
            app = self.app(folder, profile_history=str(path), profile_session='session-a')
            async with app.run_test(size=(140, 55)) as pilot:
                app.set_visible_views({'energy_graph'})
                await pilot.pause()
                graph = app.query_one('#energy_graph_content', RunRanking)
                self.assertEqual(graph.rows[0].energy_pj, 13200)
                self.assertIn('JSONL recording.jsonl', str(graph.query_one('.rank-summary', Static).render()))
                raw = json.dumps(profile_event(code, seq=4, multiplier=2))
                with path.open('a') as stream:
                    stream.write(raw[:40])
                app._poll_profile_history()
                self.assertEqual(app.instruction_counts.total, 100)
                with path.open('a') as stream:
                    stream.write(raw[40:] + '\n')
                app._poll_profile_history()
                await pilot.pause()
                self.assertEqual(app.instruction_counts.total, 200)
                self.assertEqual(graph.rows[0].energy_pj, 26400)
                app.set_energy_model(EnergyModel(10, 2, 3.3))
                append(path, model_event(seq=5))
                app._poll_profile_history()
                self.assertEqual(app.energy_model.ua_per_mhz, 10)

    async def test_live_jsonl_retains_data_on_io_failures_and_rejects_wrong_build(self):
        with TemporaryDirectory() as folder:
            code = graph_catalog()
            path = Path(folder) / 'live.json'
            path.write_text(json.dumps(counts(code)))
            app = self.app(folder, instruction_profile=str(path), energy_model=EnergyModel(100, 2, 3.3))
            async with app.run_test(size=(140, 55)) as pilot:
                app.set_visible_views({'energy_graph'})
                app.pending[90] = ('connect', None)
                app._handle(Record(90, '^', 'connected', {}))
                app._poll_instruction_profile()
                app._poll_profile_history()
                await pilot.pause()
                graph = app.query_one('#energy_graph_content', RunRanking)
                self.assertEqual(app.instruction_counts.total, 100)
                self.assertIn('JSONL', app._profile_source)
                self.assertEqual(graph.query_one(DataTable).row_count, 3)
                path.unlink()
                app._poll_instruction_profile()
                self.assertEqual(graph.query_one(DataTable).row_count, 3)
                self.assertEqual(graph.rows[0].energy_pj, 13200)
                self.assertIn('retaining', app._profile_input_warning)
                path.write_text('{partial')
                app._poll_instruction_profile()
                self.assertEqual(graph.query_one(DataTable).row_count, 3)
                path.write_text(json.dumps(dict(counts(code), elf_sha256='wrong')))
                app._poll_instruction_profile()
                self.assertEqual(graph.query_one(DataTable).row_count, 0)
                path.write_text(json.dumps(counts(code, seq=2)))
                app._poll_instruction_profile()
                self.assertEqual(graph.query_one(DataTable).row_count, 3)
                updated = counts(code, seq=3)
                updated['total'] = 200
                updated['pcs'] = [[pc, value * 2] for pc, value in updated['pcs']]
                path.write_text(json.dumps(updated))
                writer = app._trace
                with patch.object(writer, 'record', side_effect=OSError('simulated disk full')):
                    app._poll_instruction_profile()
                self.assertIsNone(app._trace)
                self.assertTrue(writer.closed)
                self.assertEqual(app.instruction_counts.total, 200)
                self.assertEqual(graph.rows[0].energy_pj, 26400)

    async def test_model_restored_on_restart_and_cli_override_preserved(self):
        with TemporaryDirectory() as folder:
            code = graph_catalog()
            with closing(TraceWriter('firmware.elf', 'localhost:1234', folder)) as writer:
                writer.record('energy_model', ua_per_mhz=48, mips_per_mhz=1, voltage=1.8)
                record = profile_event(code)
                writer.record('instruction_profile', **{key: value for key, value in record.items()
                                                       if key not in ('schema', 'kind', 'session', 'seq')})
            app = self.app(folder)
            async with app.run_test() as pilot:
                await pilot.pause()
                self.assertEqual(app.energy_model, EnergyModel(48, 1, 1.8))
                self.assertIn('Restored JSONL', app._energy_source)
            override = self.app(folder, energy_model=EnergyModel(100, 2, 3.3))
            async with override.run_test() as pilot:
                await pilot.pause()
                self.assertEqual(override.energy_model, EnergyModel(100, 2, 3.3))

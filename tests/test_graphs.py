"""Graph semantics and actual Textual sorting/selection interactions."""
import json
import unittest
from textual.widgets import DataTable, Select, Static

from dbg3k.app import DebuggerApp
from dbg3k.graph_model import code_coverage, function_stats, rank_functions, stack_ranges
from dbg3k.graph_ui import RunRanking, StackMap
from dbg3k.resources import EnergyModel, FunctionCode, InstructionProfile, decode_stack
from test_resources import catalog


def graph_catalog():
    code = catalog()
    code.functions.append(FunctionCode('.text', 0x1020, 6, ('baz',)))
    code.starts.append(0x1020)
    code.max_ends.append(0x1026)
    return code


def counts(code, seq=1):
    return dict(schema='dbg3k.qemu-counts.v1', metric='instruction-dispatch', elf_sha256=code.sha256,
                run='fixture-run', seq=seq, total=100, overflow=0, complete=False,
                pcs=[['0x1000', 2], ['0x1002', 78], ['0x1010', 5], ['0x1012', 5],
                     ['0x1020', 1], ['0x1022', 4], ['0x2000', 5]])


def sample():
    return dict(schema='dbg3k.stack.v1', stop=1, thread='1', registers={'sp': 0x38001000}, frames=[
        dict(level=0, function='foo', pc=0x1000, sp=0x38001000, kind='normal'),
        dict(level=1, function='bar', pc=0x1010, sp=0x38001010, kind='normal'),
        dict(level=2, function='reset', pc=0x9000, sp=0x38001030, kind='normal')],
        memory=dict(start=0x38001000, hex=bytes(range(48)).hex()))


class GraphModelTests(unittest.TestCase):
    def test_entry_hits_rankings_denominators_and_energy(self):
        code, profile = graph_catalog(), InstructionProfile()
        profile.update(counts(code), code)
        rows = function_stats(code, profile, EnergyModel(100, 2, 3.3))
        self.assertEqual([r.function.names[0] for r in rank_functions(rows, 'instructions')], ['foo', 'bar', 'baz'])
        self.assertEqual([r.function.names[0] for r in rank_functions(rows, 'calls')], ['bar', 'foo', 'baz'])
        self.assertEqual([r.function.names[0] for r in rank_functions(rows, 'per_entry')], ['foo', 'baz', 'bar'])
        self.assertEqual(rows[0].per_entry, 40)
        self.assertEqual(rows[0].energy_pj, 13200)
        self.assertEqual(sum(r.energy_pj for r in rows), 15675)
        self.assertEqual(profile.unknown, 5)
        self.assertEqual(code_coverage(code), 24)
        # Entrypoint dispatches are counted directly; no inferred divisions or
        # exact invocation promises when a loop jumps back to entry.
        self.assertEqual(profile.entry_hits[code.functions[0].key], 2)
        profile.update(dict(counts(code), run='new', total=0, overflow=0, pcs=[]), code)
        self.assertEqual(profile.entry_hits, {})
        self.assertTrue(all(r.per_entry is None for r in function_stats(code, profile)))

    def test_stack_geometry_and_memory_validation(self):
        data = sample()
        ranges = stack_ranges(data)
        self.assertEqual([(r.low, r.high) for r in ranges],
                         [(0x38001010, 0x38001030), (0x38001000, 0x38001010)])
        self.assertIsNotNone(decode_stack('__dbg3k_stack_v1__' + json.dumps(data)))
        data['memory']['hex'] = bytes(257).hex()
        self.assertIsNone(decode_stack('__dbg3k_stack_v1__' + json.dumps(data)))
        data['frames'][1]['kind'] = 'other'
        self.assertEqual(stack_ranges(data), [])


class GraphWidgetTests(unittest.IsolatedAsyncioTestCase):
    def app(self):
        app = DebuggerApp('fixture.elf', 'gdb', 'localhost:1234')
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app._send = lambda *a, **k: None
        app.catalog = graph_catalog()
        app.status = 'HALTED'
        app.model.begin_stop()
        app._active_thread = '1'
        app.stack_profile.update(sample(), app.catalog)
        app.instruction_counts.update(counts(app.catalog), app.catalog)
        app.energy_model = EnergyModel(100, 2, 3.3)
        app._count_status = ''
        return app

    async def test_stack_graph_has_real_addresses_contents_and_keeps_text_view(self):
        app = self.app()
        async with app.run_test(size=(140, 55)) as pilot:
            app.set_visible_views({'stack_graph'})
            await pilot.pause()
            graph = app.query_one(StackMap)
            rendered = str(graph.render())
            self.assertIn('0x38001030', rendered)
            self.assertIn('0x38001000', rendered)
            self.assertIn('00 01 02 03 04 05 06 07', rendered)
            self.assertIn('bounds: unknown', rendered)
            self.assertIn('████████', rendered)
            self.assertLess(rendered.index('#1 bar'), rendered.index('#0 foo'))
            self.assertIn('~16 B', str(app.query_one('#stack_content', Static).render()))
            app.theme = 'textual-light'
            await pilot.pause()
            app.model.begin_stop()
            app._show_resources()
            self.assertNotIn('00 01 02', str(graph.render()))

    async def test_run_rank_select_header_sort_and_live_cursor_stability(self):
        app = self.app()
        async with app.run_test(size=(140, 55)) as pilot:
            app.set_visible_views({'run_graph'})
            await pilot.pause()
            graph = app.query_one('#run_graph_content', RunRanking)
            table = graph.query_one(DataTable)
            self.assertEqual(graph.rows[0].function.names[0], 'foo')
            self.assertIn('rank 1/3', str(graph.query_one('.rank-summary', Static).render()))
            self.assertIn('Σ95.0%', str(graph.query_one('.rank-chart', Static).render()))
            self.assertEqual(table.get_row_at(0)[1:4], ['80', '2', '10'])
            graph.query_one(Select).value = 'calls'
            await pilot.pause()
            self.assertEqual(graph.rows[0].function.names[0], 'bar')
            self.assertIn('rank 2/3', str(graph.query_one('.rank-summary', Static).render()))
            # Actual mouse interaction with the Dispatches column heading.
            await pilot.click('#run_graph_content DataTable', offset=(35, 0))
            await pilot.pause()
            self.assertEqual(graph.sort_metric, 'instructions')
            self.assertEqual(graph.rows[0].function.names[0], 'foo')
            await pilot.click('#run_graph_content DataTable', offset=(35, 0))
            await pilot.pause()
            self.assertFalse(graph.descending)
            self.assertEqual(graph.rows[0].function.names[0], 'baz')
            table.move_cursor(row=1)
            old_key = graph._row_keys[table.cursor_row]
            app.instruction_counts.update(counts(app.catalog, seq=2), app.catalog)
            app._show_resources()
            await pilot.pause()
            self.assertEqual(graph._row_keys[table.cursor_row], old_key)

    async def test_energy_ranking_and_missing_data_are_explicit(self):
        app = self.app()
        async with app.run_test(size=(140, 55)) as pilot:
            app.set_visible_views({'energy_graph'})
            await pilot.pause()
            graph = app.query_one('#energy_graph_content', RunRanking)
            self.assertEqual(graph.rows[0].energy_pj, 13200)
            self.assertIn('16500 pJ', str(graph.query_one('.rank-summary', Static).render()))
            self.assertIn('unattributed: 825 pJ', str(graph.query_one('.rank-summary', Static).render()))
            app.energy_model = None
            app._show_resources()
            self.assertEqual(graph.query_one(DataTable).row_count, 0)
            self.assertIn('unavailable', str(graph.query_one('.rank-summary', Static).render()))
            app.energy_model = EnergyModel(100, 2, 3.3)
            app._count_status = 'ELF hash mismatch'
            app._show_resources()
            self.assertEqual(graph.query_one(DataTable).row_count, 0)

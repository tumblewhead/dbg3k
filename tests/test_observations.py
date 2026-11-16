import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from textual.widgets import TextArea
from dbg3k.app import DebuggerApp
from dbg3k.mi import Record
from dbg3k.observations import expression_parts, select_expressions
from dbg3k.observation_ui import ObservationsScreen
from dbg3k.trace import TraceWriter


class ObservationContractTests(unittest.TestCase):
    def test_read_only_selectors_and_explicit_pointer_reads(self):
        self.assertEqual(expression_parts("'kodama.c'::tasks[2].generation"),
                         ("'kodama.c'::tasks", [('[]', 2), ('.', 'generation')], False))
        self.assertEqual(expression_parts('*tasks[0].subscription')[2], True)
        self.assertEqual(expression_parts('ns::state->member')[1], [('->', 'member')])
        for expression in ('f()', 'x=1', 'x++', 'x[foo()]', 'x;continue',
                           'x += 1', '(int*)0', 'x ? y : z', 'x\ncontinue'):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                expression_parts(expression)
        self.assertEqual(select_expressions(['x', 'x']), ('x',))
        with self.assertRaises(ValueError):
            select_expressions([f'x{i}' for i in range(17)])


class ObservationFlowTests(unittest.IsolatedAsyncioTestCase):
    def app(self):
        app = DebuggerApp('demo.elf', 'gdb', 'localhost:1234')
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app.transport.send = lambda command: len(app.pending) + 1
        return app

    async def test_select_start_stop_ui_and_capture_provenance(self):
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.press('ctrl+p')
            await pilot.press(*'Observation capture')
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, ObservationsScreen)
            app.screen.query_one(TextArea).load_text("'kodama.c'::tasks\nmissing_symbol")
            await pilot.click('#observations_start')
            await pilot.pause()
            self.assertTrue(app.observation_enabled)
            self.assertEqual(len(app.observation_expressions), 2)
            app.action_observation_capture()
            await pilot.pause()
            await pilot.click('#observations_stop')
            self.assertFalse(app.observation_enabled)
            self.assertEqual(len(app.observation_expressions), 2)

    async def test_stale_async_values_never_receive_new_stop_identity(self):
        app = self.app()
        with TemporaryDirectory() as folder:
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                app._trace = TraceWriter('demo.elf', 'localhost:1234', folder)
                app.status, app._active_thread = 'HALTED', '1'
                app.model.begin_stop()
                app._trace_record('stop', stop=app.model.stop, thread='1')
                app._observation_ready = True
                app.set_observations(['state'])
                request = app._observation_request
                token = app._observation_pending[request]['token']
                vars_token = app._send('-stack-list-variables --all-values', 'vars', 0)
                app.model.begin_stop()
                app._accept_observation(dict(request=request, stop=1, thread='1',
                                             expression='state', status='ok', value='wrong'))
                app._handle(Record(vars_token, '^', 'done', {'variables': [{'name': 'stale', 'value': '1'}]}))
                app._handle(Record(token, '^', 'done', {}))
                records = [json.loads(line) for line in app._trace.path.read_text().splitlines()]
                observations = [r for r in records if r['kind'] == 'observation']
                self.assertEqual(len(observations), 1)
                self.assertEqual(observations[0]['stop'], 1)
                self.assertEqual(observations[0]['status'], 'error')
                self.assertNotIn('value', observations[0])
                self.assertFalse(any(r['kind'] == 'locals' for r in records))
                self.assertFalse(app._observation_pending)

    async def test_missing_gdb_python_records_unavailable_at_each_stop(self):
        app = self.app()
        with TemporaryDirectory() as folder:
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                app._trace = TraceWriter('demo.elf', 'localhost:1234', folder)
                app.status, app._active_thread = 'HALTED', '1'
                app.model.begin_stop()
                app.set_observations(['tasks'])
                token = app._send('install helper', 'observation_observer')
                app._handle(Record(token, '^', 'error', {'msg': 'Python unavailable'}))
                app.model.begin_stop()
                app._request_observations()
                app._request_observations()  # no duplicate record on redraw
                records = [json.loads(line) for line in app._trace.path.read_text().splitlines()]
                observations = [r for r in records if r['kind'] == 'observation']
                self.assertEqual([r['stop'] for r in observations], [1, 2])
                self.assertTrue(all(r['status'] == 'unavailable' and 'value' not in r for r in observations))

    async def test_capture_before_queued_execution_keeps_original_stop(self):
        app = self.app()
        with TemporaryDirectory() as folder:
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                app._trace = TraceWriter('demo.elf', 'localhost:1234', folder)
                app.status, app._active_thread = 'HALTED', '1'
                app.model.begin_stop()
                app._observation_ready = True
                app.set_observations(['state'])
                request = app._observation_request
                token = app._observation_pending[request]['token']
                # A user queues a step before the UI drains GDB's already
                # completed capture. GDB emits the read before *running.
                app.status = 'COMMANDING'
                app._accept_observation(dict(request=request, stop=1, thread='1',
                    expression='state', status='ok', value=dict(kind='integer', value='42')))
                app._handle(Record(token, '^', 'done', {}))
                records = [json.loads(line) for line in app._trace.path.read_text().splitlines()]
                observations = [r for r in records if r['kind'] == 'observation']
                self.assertEqual(len(observations), 1)
                self.assertEqual((observations[0]['stop'], observations[0]['status']), (1, 'ok'))

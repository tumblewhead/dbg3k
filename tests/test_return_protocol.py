"""Protocol validation and coexistence of automatic/MI return evidence."""
import json
import unittest

from dbg3k.app import DebuggerApp
from dbg3k.calltree import RETURN_PREFIX, probe_return
from dbg3k.mi import Record
from dbg3k.model import Frame


class ReturnProtocolTests(unittest.TestCase):
    def message(self, **changes):
        data = dict(schema='dbg3k.gdb-return.v1', thread='1', caller='foo',
                    callee='bar', callee_display='bar(2)', value='6')
        data.update(changes)
        return RETURN_PREFIX + json.dumps(data)

    def test_only_structured_helper_evidence_is_accepted(self):
        self.assertEqual(probe_return(self.message())['value'], '6')
        self.assertIsNone(probe_return('bar returned 6'))
        self.assertIsNone(probe_return(RETURN_PREFIX + '{broken'))
        self.assertIsNone(probe_return(RETURN_PREFIX + '[]'))
        self.assertIsNone(probe_return(self.message(schema='unknown')))
        self.assertIsNone(probe_return(self.message(callee=None)))
        self.assertIsNone(probe_return(self.message(value=0)))
        missing = json.loads(self.message()[len(RETURN_PREFIX):])
        del missing['value']
        self.assertIsNone(probe_return(RETURN_PREFIX + json.dumps(missing)))
        self.assertIsNone(probe_return(self.message(value=None))['value'])

    def test_probe_and_mi_finish_count_once_then_next_call_counts_again(self):
        app = DebuggerApp('demo.elf', 'gdb', 'localhost:1234')
        app._show_scope = lambda: None
        app._show_status = lambda: None
        app._log = lambda text: None
        app._send = lambda *a, **k: None
        app.status = 'HALTED'
        app._active_thread = '1'
        app.model.set_frames([Frame(0, 'bar', 'test.c', 3)])
        records = []
        app._trace_record = lambda kind, **fields: records.append((kind, fields))
        app.action_finish()
        app._handle(Record(None, '~', 'stream', self.message()))
        app._handle(Record(None, '*', 'stopped', {
            'reason': 'function-finished', 'thread-id': '1',
            'frame': {'func': 'foo'}, 'return-value': '6'}))
        series = next(iter(app._returns.series.values()))
        self.assertEqual(series.count, 1)
        self.assertEqual([r[1]['origin'] for r in records if r[0] == 'return'],
                         ['gdb-python-finish-breakpoint'])
        app.action_step()
        app._handle(Record(None, '~', 'stream', self.message(value='9')))
        self.assertEqual(series.count, 2)
        self.assertEqual(series.last.value, '9')
        app._handle(Record(None, '*', 'stopped', {
            'reason': 'signal-received', 'thread-id': '1', 'frame': {'func': 'foo'}}))
        self.assertEqual(series.count, 2)

    def test_gdb_without_python_leaves_finish_fallback_available(self):
        app = DebuggerApp('demo.elf', 'gdb', 'localhost:1234')
        logs = []
        app._log = logs.append
        app._show_scope = lambda: None
        app._show_status = lambda: None
        app.pending[1] = ('return_observer', None)
        app._handle(Record(1, '^', 'error', {'msg': 'Python scripting is not supported'}))
        self.assertTrue(any('use o / finish' in log for log in logs))
        app.model.set_frames([Frame(0, 'bar', 'test.c', 3)])
        app._handle(Record(None, '*', 'stopped', {
            'reason': 'function-finished', 'thread-id': '1',
            'frame': {'func': 'foo'}, 'return-value': '6'}))
        self.assertEqual(next(iter(app._returns.series.values())).last.value, '6')

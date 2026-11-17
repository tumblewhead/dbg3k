"""Collector budget/lifecycle checks; actual GDB/QEMU qualification is separate."""
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch


class Breakpoint:
    def __init__(self, *args, **kwargs):
        self.valid = True

    def is_valid(self):
        return self.valid

    def delete(self):
        self.valid = False


def collector():
    messages = []
    frame = types.SimpleNamespace(block=lambda: None, older=lambda: None,
        name=lambda: 'fixture', pc=lambda: 0x10000000, read_register=lambda name: 0,
        find_sal=lambda: types.SimpleNamespace(symtab=None, line=1))
    gdb = types.SimpleNamespace(Breakpoint=Breakpoint, error=RuntimeError,
        execute=lambda *a, **k: 'little endian',
        decode_line=lambda spec: (None, [types.SimpleNamespace(pc=0x10000000)]),
        newest_frame=lambda: frame, selected_thread=lambda: types.SimpleNamespace(global_num=1),
        write=lambda message: messages.append(json.loads(message.removeprefix('__dbg3k_kodama_v1__'))))
    path = Path(__file__).resolve().parents[1] / 'src/dbg3k/gdb_kodama.py'
    ns = {'__file__': str(path)}
    with patch.dict('sys.modules', gdb=gdb):
        exec(compile(path.read_text(), str(path), 'exec'), ns)
    ns['snapshot'] = lambda: dict(core={}, tasks=[], pool=[], errors=[])
    return ns, messages, gdb


class KodamaBudgetTests(unittest.TestCase):
    def test_default_budget_rearms_across_stops_without_sequence_or_capture_reset(self):
        ns, messages, gdb = collector()
        observer = ns['_observer']
        observer.control(True, True, 'same-capture', 1, [('kodama_signal', 'kodama_signal')])
        probe = observer.probes[0]
        ns['dbg3k_kodama_snapshot'](1)
        limit = ns['EVENT_LIMIT']
        for _ in range(limit + 5):
            self.assertFalse(probe.stop())  # Internal probes never create visible stops.
        raw = [m for m in messages if 'sample_seq' in m]
        self.assertEqual(len(raw), limit + 1)
        self.assertTrue(messages[-2]['coverage']['api_budget']['exhausted'])
        self.assertEqual(messages[-1]['diagnostic_code'], 'api-budget')
        # Exhausted probes skip frame/argument/memory reads.
        with patch.object(gdb, 'newest_frame', side_effect=AssertionError('unnecessary frame read')):
            self.assertFalse(probe.stop())
        ns['dbg3k_kodama_snapshot'](2)
        second_stop = messages[-1]
        self.assertEqual((second_stop['origin'], second_stop['stop']), ('stop', 2))
        self.assertEqual(second_stop['capture_gap']['skipped_probe_entries'], 6)
        self.assertEqual(second_stop['capture_gap']['preceding_stop'], 1)
        self.assertFalse(messages[-2]['coverage']['api_budget']['exhausted'])
        for _ in range(limit + 2):
            self.assertFalse(probe.stop())
        raw = [m for m in messages if 'sample_seq' in m]
        self.assertEqual([m['sample_seq'] for m in raw], list(range(1, 2 * limit + 3)))
        self.assertTrue(all(m['capture'] == 'same-capture' for m in raw))
        for stop in (1, 2):
            api = [m for m in raw if m['origin'] == 'api' and m['stop'] == stop]
            self.assertEqual(len(api), limit)
            self.assertTrue(all(m['stop_anchor'] == 'preceding-visible-stop' for m in api))

    def test_duplicate_refresh_does_not_refill_budget_and_paused_capture_stays_paused(self):
        ns, messages, _ = collector()
        ns['EVENT_LIMIT'] = 2
        observer = ns['_observer']
        observer.control(True, True, 'capture', 1, [('kodama_signal', 'kodama_signal')])
        ns['dbg3k_kodama_snapshot'](1)
        probe = observer.probes[0]
        probe.stop()
        ns['dbg3k_kodama_snapshot'](1)  # Same visible stop; still only one API slot left.
        probe.stop(); probe.stop()
        self.assertEqual(observer.api_count, 2)
        self.assertTrue(observer.limited)
        observer.control(False, True, 'capture', 1, [])
        before = len(messages)
        ns['dbg3k_kodama_snapshot'](2)
        self.assertEqual(len(messages), before)
        observer.control(True, False, 'new-capture', 2, [])
        ns['dbg3k_kodama_snapshot'](2)
        self.assertEqual(messages[-1]['sample_seq'], 1)
        self.assertNotIn('capture_gap', messages[-1])

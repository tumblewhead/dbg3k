"""Global symbol discovery and shared watch-history regression tests."""
import unittest

from dbg3k.globals import discover_globals
from dbg3k.mi import parse_record
from dbg3k.model import Frame, ScopeModel


class GlobalWatchTests(unittest.TestCase):
    def test_mi_globals_and_file_static_collision(self):
        line = (
            '7^done,symbols={debug=['
            '{filename="main.c",fullname="/a/main.c",symbols=['
            '{line="4",name="total",type="volatile unsigned int",'
            'description="static volatile unsigned int total;"},'
            '{line="5",name="ticks",type="int",description="int ticks;"}]},'
            '{filename="other.c",fullname="/b/other.c",symbols=['
            '{line="2",name="total",type="int",description="static int total;"},'
            '{line="3",name="ticks",type="int",description="extern int ticks;"}]}'
            ']}'
        )
        payload = parse_record(line).payload
        found, truncated = discover_globals(payload)
        self.assertFalse(truncated)
        self.assertEqual(len(found), 3)
        self.assertEqual([x.label for x in found],
                         ["main.c::total", "global.ticks", "other.c::total"])
        self.assertEqual(found[0].expression, "'/a/main.c'::total")
        self.assertEqual(found[1].expression, "ticks")
        self.assertNotEqual(found[0].key, found[2].key)

    def test_symbol_limit_and_non_debug_ignored(self):
        payload = {"symbols": {
            "debug": [{"filename": "main.c", "symbols": [
                {"name": "a", "description": "int a;"},
                {"name": "b", "description": "int b;"}]}],
            "nondebug": [{"name": "runtime_linker"}]}}
        found, truncated = discover_globals(payload, limit=1)
        self.assertEqual([x.name for x in found], ["a"])
        self.assertTrue(truncated)

    def test_invalid_expression_and_ambiguous_static_not_evaluated(self):
        payload = {"symbols": {"debug": [
            {"symbols": [{"name": "hidden", "description": "static int hidden;"},
                         {"name": "x;evil", "description": "int x;"},
                         {"name": "safe", "description": "int safe;"}]}]}}
        found, _ = discover_globals(payload)
        self.assertEqual([x.name for x in found], ["safe"])

    def test_global_values_keep_independent_stop_histories(self):
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, "main", "main.c", 12)])
        model.set_variables(0, [{"name": "n", "value": "1"}])
        model.set_global_value("static:main.c:total", "main.c::total", "total", "2", "int")
        model.set_global_value("static:main.c:total", "main.c::total", "total", "99", "int")
        self.assertEqual(model.active_globals()[0].value, "2")  # same stop sampled once
        self.assertEqual(len(model.active_watches()), 1)

        model.begin_stop()
        model.set_frames([Frame(0, "main", "main.c", 13)])
        model.set_global_value("static:main.c:total", "main.c::total", "total", "5", "int")
        watch = model.active_globals()[0]
        self.assertEqual((watch.previous, watch.value), ("2", "5"))
        self.assertTrue(watch.changed)
        self.assertEqual(list(watch.numeric), [2.0, 5.0])
        self.assertEqual(len(model.active_watches()), 1)


class GlobalEventFlowTests(unittest.TestCase):
    def test_stop_scoped_global_replies_ignore_stale_results(self):
        # No running GDB needed; exercise the same token/stop path as the UI.
        from dbg3k.app import DebuggerApp
        from dbg3k.globals import GlobalSymbol
        from dbg3k.mi import Record

        app = DebuggerApp("example.elf", "gdb", "localhost:1234")
        app._show_scope = lambda: None
        app._show_watches = lambda: None
        app.status = "HALTED"
        app._globals = [GlobalSymbol("global:counter", "global.counter",
                                      "counter", "counter", "int")]
        app._globals_discovered = True
        sent = []

        def fake_send(command, purpose, level=None):
            token = len(sent) + 1
            sent.append((command, purpose, level))
            app.pending[token] = (purpose, level)
            return token

        app._send = fake_send
        app.model.begin_stop()
        app._refresh_globals()
        app._refresh_globals()
        self.assertEqual(len(sent), 1)
        self.assertIn('counter', sent[0][0])
        app.model.begin_stop()  # previous stop's reply is now stale
        app._handle(Record(1, '^', 'done', {'value': '9'}))
        self.assertEqual(app.model.active_globals(), [])
        app._refresh_globals()
        app._handle(Record(2, '^', 'done', {'value': '11'}))
        self.assertEqual(app.model.active_globals()[0].value, '11')


if __name__ == "__main__":
    unittest.main()

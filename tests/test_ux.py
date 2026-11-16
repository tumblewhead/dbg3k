"""dbg3k call labels, sampled watch UX, and whole-theme regression tests."""
import unittest

from dbg3k.calltree import display_call, observed_return
from dbg3k.mi import parse_record
from dbg3k.model import (
    Frame, ScopeModel, HISTORY_LIMIT, parse_stack_arguments,
)


class CallTreeTests(unittest.TestCase):
    def test_live_mi_stack_arguments(self):
        record = parse_record(
            '21^done,stack-args=['
            'frame={level="0",args=[{name="n",value="2"}]},'
            'frame={level="1",args=[{name="n",value="11"},{name="ptr",value="0x21"}]}'
            ']'
        )
        args = parse_stack_arguments(record.payload)
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, "foo", "main.c", 5), Frame(1, "main", "main.c", 9)])
        model.set_frame_arguments(args)
        self.assertEqual(display_call(model.frames[0]), "foo(2)")
        self.assertEqual(display_call(model.frames[1]), "main(11, 0x21)")

    def test_finish_return_is_attributed_to_caller(self):
        previous = Frame(0, "foo", "main.c", 7, arguments=(("n", "2"),))
        finished = parse_record(
            '*stopped,reason="function-finished",frame={func="main",line="17"},'
            'return-value="4",thread-id="1"'
        )
        observed = observed_return(finished.payload, previous, stop=20)
        self.assertEqual(observed.caller_function, "main")
        self.assertIn("foo(2)", observed.display)
        self.assertIn("4", observed.display)
        self.assertEqual(observed.stop, 20)
        not_return = observed_return(
            {"reason": "end-stepping-range", "return-value": "999"}, previous, 21)
        self.assertIsNone(not_return)

    def test_unknown_return_not_fabricated(self):
        previous = Frame(0, "g", "g.c", 9)
        result = observed_return(
            {"reason": "function-finished", "frame": {"func": "main"}}, previous, 4)
        self.assertIn("value not reported", result.display)
        self.assertNotIn("-> 0", result.display)


class HistoryTests(unittest.TestCase):
    def test_number_list_then_sparkline_and_tooltip(self):
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, "foo", "main.c", 2)])
        for i in range(1, 15):
            if i > 1:
                model.begin_stop()
            model.set_variables(0, [{"name": "value", "value": str(i)}])
            watch = model.active_watches()[0]
            if i == 1:
                self.assertEqual(watch.trend, "[1]")
            if i == 2:
                self.assertEqual(watch.trend, "[1, 2]")
            if i == 3:
                self.assertNotIn("[", watch.trend)
        self.assertEqual(len(watch.history), 14)
        self.assertEqual(len(watch.tooltip_history.splitlines()), 12)
        self.assertIn("stop 14: 14", watch.tooltip_history)
        self.assertNotIn("stop 4:", watch.tooltip_history)
        self.assertIn("1\tfoo.value@frame0#gen1\t1",
                      model.export_history_tsv())
        self.assertIn("stop 14", watch.tooltip_history)

    def test_export_keeps_expired_scopes(self):
        model = ScopeModel()
        model.begin_stop()
        model.set_frames([Frame(0, "foo", "a.c", 10)])
        model.set_variables(0, [{"name": "n", "value": "7"}])
        model.begin_stop()
        model.set_frames([Frame(0, "main", "a.c", 20)])
        self.assertEqual(model.active_watches(), [])
        self.assertIn("foo.n@frame0", model.export_history_tsv())
        self.assertEqual(HISTORY_LIMIT, 4096)


class ThemeTests(unittest.IsolatedAsyncioTestCase):
    async def test_theme_updates_whole_app_not_only_command_palette(self):
        from dbg3k.app import DebuggerApp
        from textual.widgets import Tree

        app = DebuggerApp("demo.elf", "gdb", "localhost:1234")
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app._send = lambda *args, **kwargs: None
        async with app.run_test() as pilot:
            app.theme = "textual-dark"
            await pilot.pause()
            dark = app.query_one("#scope", Tree).styles.background
            app.theme = "textual-light"
            await pilot.pause()
            light = app.query_one("#scope", Tree).styles.background
            self.assertNotEqual(str(dark), str(light))
            self.assertNotIn("#192733", app.CSS)
            self.assertIn("$surface", app.CSS)
            self.assertIn("$foreground", app.CSS)


if __name__ == "__main__":
    unittest.main()

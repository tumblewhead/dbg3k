"""Headless Textual smoke test for real watch-row widgets and return branches."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dbg3k.app import DebuggerApp
from dbg3k.calltree import ReturnObservation
from dbg3k.model import Frame
from dbg3k.mi import Record
from dbg3k.watch_ui import WatchRow
from textual.widgets import Static, Tree


class VisualSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_hover_cells_and_call_tree_nodes_exist(self):
        app = DebuggerApp("demo.elf", "gdb", "localhost:1234")
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app._send = lambda *a, **kw: None
        async with app.run_test() as pilot:
            app.status = "HALTED"
            app.model.begin_stop()
            app.model.set_frames([
                Frame(0, "main", "main.c", 12),
            ])
            app.model.set_frame_arguments({0: (("n", "2"),)})
            app.model.set_variables(0, [{"name": "n", "value": "2"}])
            app._returns.observe(
                ReturnObservation("main", "foo(2)", "4", app.model.stop),
                thread="unknown", callee_function="foo")
            app._show_scope()
            app._show_watches()
            await pilot.pause()
            tree = app.query_one("#scope", Tree)
            parent = tree.root.children[0]
            self.assertIn("main(2)", str(parent.label))
            self.assertTrue(any("foo(2)" in str(child.label)
                                for child in parent.children))
            row = app.query_one(WatchRow)
            history_cell = row.query_one(".watch-history", Static)
            self.assertIn("stop 1: 2", str(history_cell.tooltip))
            self.assertEqual(row.watch.trend, "[2]")
            app.theme = "textual-light"
            await pilot.pause()
            self.assertEqual(len(app.query(WatchRow)), 1)
            app.action_copy_history()


    async def test_initial_reset_handler_source_with_default_theme(self):
        """Regression: default textual-dark has Theme.background=None.

        A live GDB frame at startup used to render:
        'bold None on #4EBF71', crashing Rich with MissingStyle.
        """
        with TemporaryDirectory() as folder:
            src = Path(folder) / "startup.c"
            src.write_text("\n".join(f"int line_{i} = {i};" for i in range(1, 29)),
                           encoding="utf-8")
            app = DebuggerApp("demo.elf", "gdb", "localhost:1234")
            app.transport.start = lambda: None
            app.transport.close = lambda: None
            app._send = lambda *args, **kwargs: None
            async with app.run_test() as pilot:
                app.theme = "textual-dark"
                app.status = "HALTED"
                app._active_thread = "1"
                app.model.begin_stop()
                app.pending[5] = ("frames", None)
                record = Record(5, "^", "done", {
                    "stack": [{"frame": {
                        "level": "0",
                        "addr": "0x380000dc",
                        "func": "Reset_Handler",
                        "fullname": str(src),
                        "line": "22"
                    }}]
                })
                app._handle(record)
                await pilot.pause()
                self.assertEqual(app.model.frames[0].function, "Reset_Handler")
                self.assertEqual(app._contrast_ink("#4EBF71", dark=True), "black")
                self.assertNotIn("None on ", str(app.query_one("#source", Static).render()))
                app.theme = "textual-light"
                app._show_source()
                await pilot.pause()
                self.assertEqual(app.model.frames[0].line, 22)


if __name__ == "__main__":
    unittest.main()

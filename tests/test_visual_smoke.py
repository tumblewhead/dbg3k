"""Headless Textual smoke test for real watch-row widgets and return branches."""
import unittest

from dbg3k.app import DebuggerApp
from dbg3k.calltree import ReturnObservation
from dbg3k.model import Frame
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
            app._last_return = ReturnObservation("main", "foo(2)", "4", app.model.stop)
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


if __name__ == "__main__":
    unittest.main()

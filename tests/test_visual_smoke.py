"""Headless Textual smoke test for real watch-row widgets and return branches."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dbg3k.app import DebuggerApp
from dbg3k.calltree import ReturnKey, ReturnObservation
from dbg3k.model import Frame
from dbg3k.mi import Record
from dbg3k.trace import TraceWriter
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


    async def test_finish_event_tree_tooltip_copy_backed_by_jsonl(self):
        """Replay two genuine function-finished events from bar into foo."""
        with TemporaryDirectory() as folder:
            app = DebuggerApp("demo.elf", "gdb", "localhost:1234",
                              history_dir=folder)
            app.transport.start = lambda: None
            app.transport.close = lambda: None
            sent = []
            def fake_send(command, purpose, level=None):
                token = len(sent) + 10
                sent.append((token, command, purpose, level))
                app.pending[token] = (purpose, level)
                return token
            app._send = fake_send
            async with app.run_test() as pilot:
                app._trace = TraceWriter("demo.elf", "localhost:1234", folder)
                app._connected = True
                app._active_thread = "1"
                app.status = "HALTED"
                captured = []
                app._copy = lambda text, description: captured.append((text, description))
                for n in (2, 3):
                    # GDB's current frame still shows the callee at the stop
                    # before the finish. The next stack result shows its caller.
                    app.model.set_frames([
                        Frame(0, "bar", "test.c", 4,
                              arguments=(("n", str(n)),)),
                        Frame(1, "foo", "test.c", 9)
                    ])
                    app._handle(Record(None, "*", "stopped", {
                        "reason": "function-finished",
                        "thread-id": "1",
                        "frame": {"func": "foo", "line": "9"},
                        "return-value": str(n * 3)
                    }))
                    frames_token = next(
                        token for token, cmd, purpose, _ in reversed(sent)
                        if purpose == "frames")
                    app._handle(Record(frames_token, "^", "done", {
                        "stack": [{"frame": {"level": "0", "func": "foo",
                                              "file": "test.c", "line": "9"}}]
                    }))
                    await pilot.pause()

                self.assertEqual(len(app._returns.series), 1)
                series = next(iter(app._returns.series.values()))
                self.assertEqual(series.count, 2)
                self.assertIn("bar(3)", series.label)
                self.assertIn("9", series.label)
                self.assertIn("stop 1", series.tooltip)
                self.assertIn("stop 2", series.tooltip)

                tree = app.query_one("#scope", Tree)
                return_nodes = [
                    tree.get_node_at_line(i)
                    for i in range(tree.last_line + 1)
                ]
                node = next(node for node in return_nodes
                            if node is not None and isinstance(node.data, ReturnKey))
                tree.watch_hover_line(next(
                    i for i in range(tree.last_line + 1)
                    if tree.get_node_at_line(i) is node))
                self.assertIn("stop 2", str(tree.tooltip))
                app.on_tree_node_selected(Tree.NodeSelected(node))
                self.assertEqual(len(captured), 1)
                self.assertIn("bar(2)", captured[0][0])
                self.assertIn("bar(3)", captured[0][0])
                self.assertIn("gdb-mi-function-finished", captured[0][0])
                self.assertTrue(app._trace.path.exists())
                app._trace.close()
                app._trace = None


if __name__ == "__main__":
    unittest.main()

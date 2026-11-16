"""Exercise pane selection through Textual and isolation of visible scopes."""
import unittest

from textual.widgets import SelectionList, Static, Tree
from textual.command import CommandInput, CommandList

from dbg3k.app import DebuggerApp
from dbg3k.calltree import ReturnObservation
from dbg3k.model import Frame
from dbg3k.views import VIEWS, ViewsScreen
from dbg3k.watch_ui import WatchRow


class ViewTests(unittest.IsolatedAsyncioTestCase):
    def app(self):
        app = DebuggerApp('demo.elf', 'gdb', 'localhost:1234')
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app._send = lambda *args, **kwargs: None
        return app

    async def test_palette_checkbox_dialog_and_layout(self):
        app = self.app()
        async with app.run_test(size=(120, 40)) as pilot:
            # Reach the dialog through the real command palette.
            await pilot.press('ctrl+p')
            await pilot.press('v', 'i', 'e', 'w', 's')
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()
            self.assertIsInstance(app.screen, ViewsScreen)
            choices = app.screen.query_one(SelectionList)
            self.assertEqual(set(choices.selected), set(VIEWS) - {'kodama'})
            # Keyboard toggles the focused Source checkbox without closing.
            choices.focus()
            await pilot.press('space')
            await pilot.pause()
            self.assertNotIn('source', app.visible_views)
            self.assertFalse(app.query_one('#left').display)
            self.assertEqual(app.query_one('#right').size.width,
                             app.query_one('#workbench').size.width)
            choices.deselect('globals')
            await pilot.pause()
            self.assertFalse(app.query_one('#global_panel').display)
            self.assertTrue(app.query_one('#scope').display)
            app._show_watches()  # MI refreshes continue while the modal is open.
            await pilot.press('escape')
            await pilot.pause()
            commands = list(app.get_system_commands(app.screen))
            unchecked = next(c for c in commands if c.title == '☐ View: Globals')
            unchecked.callback()
            await pilot.pause()
            self.assertTrue(app.query_one('#global_panel').display)
            self.assertIn('✓ View: Globals', [c.title for c in app.get_system_commands(app.screen)])
            app.set_visible_views(set())
            await pilot.pause()
            self.assertFalse(app.query_one('#workbench').display)
            await pilot.press('f2')
            await pilot.pause()
            self.assertTrue(app.query_one('#console_panel').display)
            self.assertEqual(app.focused.id, 'gdb_input')
            app.set_visible_views(set(VIEWS))
            await pilot.pause()
            self.assertTrue(app.query_one('#workbench').display)
            self.assertGreater(app.query_one('#scope').size.height, 0)

    async def test_left_right_toggle_in_palette_without_losing_search(self):
        app = self.app()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press('ctrl+p')
            await pilot.press(*'view globals')
            await pilot.pause()
            palette = app.screen
            commands = palette.query_one(CommandList)
            selected = commands.highlighted
            self.assertEqual(palette._highlighted_view(), 'globals')
            await pilot.press('left')
            await pilot.pause()
            self.assertIs(app.screen, palette)
            self.assertNotIn('globals', app.visible_views)
            self.assertEqual(palette.query_one(CommandInput).value, 'view globals')
            self.assertEqual(commands.highlighted, selected)
            self.assertIn('☐ View: Globals', str(commands.get_option_at_index(selected).prompt))
            await pilot.press('right')
            await pilot.pause()
            self.assertIn('globals', app.visible_views)
            self.assertIn('✓ View: Globals', str(commands.get_option_at_index(selected).prompt))
            search = palette.query_one(CommandInput)
            search.value = 'theme'
            search.action_end()
            await pilot.pause()
            self.assertIsNone(palette._highlighted_view())
            cursor = search.cursor_position
            await pilot.press('left')
            self.assertEqual(search.cursor_position, cursor - 1)
            await pilot.press('escape')
            app.action_choose_views()
            await pilot.pause()
            choices = app.screen.query_one(SelectionList)
            choices.focus()
            await pilot.press('right')
            await pilot.pause()
            self.assertNotIn('source', app.visible_views)
            await pilot.press('left')
            await pilot.pause()
            self.assertIn('source', app.visible_views)

    async def test_immediate_and_global_scopes_and_returns_survive_hidden_tree(self):
        app = self.app()
        async with app.run_test(size=(120, 40)) as pilot:
            app._active_thread = '1'
            app.model.begin_stop()
            app.model.set_frames([Frame(0, 'foo', 'main.c', 3), Frame(1, 'main', 'main.c', 12)])
            app.model.set_variables(0, [{'name': 'local', 'value': '41'}])
            app.model.set_variables(1, [{'name': 'outer', 'value': '7'}])
            app.model.set_global_value('global:tick', 'global.tick', 'tick', '9')
            app._show_scope()
            app._show_watches()
            await pilot.pause()
            self.assertEqual([r.watch.name for r in app.query_one('#watch_rows').query(WatchRow)], ['local'])
            self.assertEqual([r.watch.name for r in app.query_one('#global_rows').query(WatchRow)], ['tick'])
            tree = app.query_one('#scope', Tree)
            self.assertEqual(len(tree.root.children), 2)  # returns and active stack
            self.assertIn('outer = 7', str(app._stack_branch.children[0].children[0].label))
            app.on_tree_node_selected(Tree.NodeSelected(app._stack_branch.children[0]))
            app._show_watches()
            self.assertIn('foo(', str(app.query_one('#watch_heading', Static).render()))

            app.action_toggle_view('tree')
            series = app._returns.observe(ReturnObservation('main', 'foo()', '42', 1), thread='1')
            app.model.begin_stop()
            app.model.set_frames([Frame(0, 'main', 'main.c', 13)])
            app._show_scope()
            original = app._return_edge_nodes[series.key]
            app._show_scope()
            app.action_toggle_view('tree')
            await pilot.pause()
            self.assertIs(app._return_edge_nodes[series.key], original)
            self.assertIn('42', str(original.label))
            # Latest return also remains beside its active caller.
            active = app._stack_branch.children[0]
            self.assertTrue(any(child.data == series.key for child in active.children))
            app.model.set_frames([])
            app._show_scope()
            self.assertIs(app._return_edge_nodes[series.key], original)

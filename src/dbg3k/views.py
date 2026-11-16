"""View choices shared by the command palette and multi-select dialog."""
from textual.app import ComposeResult
from functools import partial
from rich.text import Text
from textual.binding import Binding
from textual.command import Command, CommandList, CommandPalette, Hit
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, SelectionList, Static, Input, Label
from .resources import EnergyModel


VIEWS = {
    'source': ('Source', '#source_scroll'),
    'tree': ('Stack tree and observed returns', '#scope'),
    'immediate': ('Immediate scope watch', '#watch_panel'),
    'globals': ('Globals', '#global_panel'),
    'console': ('GDB console', '#console_panel'),
    'stack': ('Stack frames and stack watch', '#stack_panel'),
    'instructions': ('Code and instruction counts', '#instruction_panel'),
    'energy': ('Energy estimate', '#energy_panel'),
    'stack_graph': ('Graphical stack map and contents', '#stack_graph_panel'),
    'run_graph': ('Run statistics and Pareto ranking', '#run_graph_panel'),
    'energy_graph': ('Graphical energy ranking', '#energy_graph_panel'),
}


class ViewCommandPalette(CommandPalette):
    """Toggle a highlighted view without closing or changing the search."""

    BINDINGS = [
        Binding('left,right', 'toggle_view', 'Toggle view', priority=True, show=False),
    ]

    def _highlighted_view(self):
        commands = self.query_one(CommandList)
        if commands.highlighted is None:
            return None
        option = commands.get_option_at_index(commands.highlighted)
        if isinstance(option, Command):
            callback = option.hit.command
            if isinstance(callback, partial) and callback.func == self.app.action_toggle_view:
                return callback.args[0]
        return None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'toggle_view':
            return self._highlighted_view() is not None
        return super().check_action(action, parameters)

    def action_toggle_view(self) -> None:
        key = self._highlighted_view()
        if key is None:
            return
        self.app.action_toggle_view(key)
        commands = self.query_one(CommandList)
        # Refresh checks in place; retain search, highlight and list order.
        for index in range(commands.option_count):
            option = commands.get_option_at_index(index)
            if not isinstance(option, Command):
                continue
            callback = option.hit.command
            if not isinstance(callback, partial) or callback.func != self.app.action_toggle_view:
                continue
            view = callback.args[0]
            title = f'{"✓" if view in self.app.visible_views else "☐"} View: {VIEWS[view][0]}'
            option.hit.text = title
            option.hit.help = 'Left/Right: toggle view; palette stays open'
            if isinstance(option.hit, Hit):
                option.hit.match_display = Text(title)
            else:
                option.hit.display = Text(title)
            commands.replace_option_prompt_at_index(
                index, Text(title + '\n' + option.hit.help))


class ViewsScreen(ModalScreen):
    """Apply checkbox changes immediately without dismissing the dialog."""

    DEFAULT_CSS = """
    ViewsScreen { align: center middle; }
    #view_choices { width: 62; height: auto; padding: 1 2;
        border: round $accent; background: $surface; }
    #view_choices SelectionList { height: 13; }
    #view_choices Button { margin-top: 1; }
    """
    BINDINGS = [('escape', 'dismiss', 'Done'),
                Binding('left,right', 'toggle_highlighted', 'Toggle view', priority=True)]

    def __init__(self, enabled: set[str]) -> None:
        super().__init__()
        self.enabled = enabled.copy()

    def compose(self) -> ComposeResult:
        with Vertical(id='view_choices'):
            yield Static('Views · Left/Right, Space or click to toggle')
            yield SelectionList(*(
                (label, key, key in self.enabled)
                for key, (label, _) in VIEWS.items()
            ), id='view_list')
            yield Button('Done', id='views_done', variant='primary')

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        self.app.set_visible_views(set(event.selection_list.selected))

    def action_toggle_highlighted(self) -> None:
        choices = self.query_one(SelectionList)
        if choices.highlighted is not None:
            choices.toggle(choices.get_option_at_index(choices.highlighted).value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'views_done':
            self.dismiss()


class EnergyScreen(ModalScreen):
    DEFAULT_CSS = """
    EnergyScreen { align: center middle; }
    #energy_form { width: 62; height: auto; padding: 1 2;
        border: round $accent; background: $surface; }
    #energy_error { color: $error; height: auto; }
    """
    BINDINGS = [('escape', 'dismiss', 'Cancel')]

    def compose(self):
        model = self.app.energy_model
        with Vertical(id='energy_form'):
            yield Static('Active-core energy model · user assumptions')
            for key, label in [('ua_per_mhz', 'Active current slope (µA/MHz)'),
                               ('mips_per_mhz', 'Throughput (MIPS/MHz)'), ('voltage', 'Supply (V)')]:
                yield Label(label)
                yield Input(str(getattr(model, key)) if model else '', id=key, type='number')
            yield Static('', id='energy_error')
            yield Button('Apply assumptions', id='energy_apply', variant='primary')

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != 'energy_apply':
            return
        try:
            model = EnergyModel(*(float(self.query_one('#' + key, Input).value)
                                  for key in ('ua_per_mhz', 'mips_per_mhz', 'voltage')))
        except ValueError as exc:
            self.query_one('#energy_error', Static).update(str(exc))
            return
        self.app.set_energy_model(model)
        self.dismiss()

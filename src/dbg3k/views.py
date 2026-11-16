"""View choices shared by the command palette and multi-select dialog."""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, SelectionList, Static


VIEWS = {
    'source': ('Source', '#source_scroll'),
    'tree': ('Stack tree and observed returns', '#scope'),
    'immediate': ('Immediate scope watch', '#watch_panel'),
    'globals': ('Globals', '#global_panel'),
    'console': ('GDB console', '#console_panel'),
}


class ViewsScreen(ModalScreen):
    """Apply checkbox changes immediately without dismissing the dialog."""

    DEFAULT_CSS = """
    ViewsScreen { align: center middle; }
    #view_choices { width: 62; height: auto; padding: 1 2;
        border: round $accent; background: $surface; }
    #view_choices SelectionList { height: 7; }
    #view_choices Button { margin-top: 1; }
    """
    BINDINGS = [('escape', 'dismiss', 'Done')]

    def __init__(self, enabled: set[str]) -> None:
        super().__init__()
        self.enabled = enabled.copy()

    def compose(self) -> ComposeResult:
        with Vertical(id='view_choices'):
            yield Static('Views · Space or click to toggle')
            yield SelectionList(*(
                (label, key, key in self.enabled)
                for key, (label, _) in VIEWS.items()
            ), id='view_list')
            yield Button('Done', id='views_done', variant='primary')

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        self.app.set_visible_views(set(event.selection_list.selected))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'views_done':
            self.dismiss()

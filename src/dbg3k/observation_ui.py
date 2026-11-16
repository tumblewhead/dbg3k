"""Expression selection for the existing JSONL evidence stream."""
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Button, Static, TextArea


class ObservationsScreen(ModalScreen):
    DEFAULT_CSS = """
    ObservationsScreen { align: center middle; }
    #observation_form { width: 78; height: auto; max-height: 95%; padding: 1 2;
        border: round $accent; background: $surface; }
    #observation_expressions { height: 10; }
    #observation_error { height: auto; color: $error; }
    #observation_buttons { height: 3; }
    """
    BINDINGS = [('escape', 'dismiss', 'Close')]

    def compose(self):
        app = self.app
        with Vertical(id='observation_form'):
            yield Static('Observation capture · selected values only · local JSONL')
            yield Static('One C/C++ selector per line. Fields and integer subscripts allowed.\n'
                         'Pointers remain addresses; *pointer / pointer->field explicitly read memory.\n'
                         'Snapshots at stops; no target calls or continuous event history.')
            yield TextArea('\n'.join(app.observation_expressions), id='observation_expressions')
            yield Static(('Capturing' if app.observation_enabled else 'Stopped') + ' · ' + app.observation_status,
                         markup=False)
            yield Static(str(app._trace.path) if app._trace else 'JSONL unavailable until connected; see console diagnostics',
                         markup=False)
            yield Static('', id='observation_error')
            with Horizontal(id='observation_buttons'):
                yield Button('Start / apply', id='observations_start', variant='primary')
                yield Button('Stop capture', id='observations_stop')
                yield Button('Close', id='observations_close')

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == 'observations_close':
            self.dismiss()
            return
        enabled = event.button.id == 'observations_start'
        expressions = ([s.strip() for s in self.query_one(TextArea).text.splitlines() if s.strip()]
                       if enabled else self.app.observation_expressions)
        try:
            self.app.set_observations(expressions, enabled)
        except ValueError as exc:
            self.query_one('#observation_error', Static).update(str(exc))
            return
        self.dismiss()

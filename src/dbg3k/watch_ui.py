"""Individual watch-row widgets with native per-sparkline tooltips."""
from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from .model import Watch


class WatchRow(Horizontal):
    """One scannable row. Click anywhere to copy this watch's retained history."""

    def __init__(self, watch: Watch) -> None:
        super().__init__(classes="watch-row")
        self.watch = watch

    def compose(self) -> ComposeResult:
        yield Static(classes="watch-name")
        yield Static(classes="watch-value")
        yield Static(classes="watch-delta")
        yield Static(classes="watch-history")

    def on_mount(self) -> None:
        self._update_cells()

    def set_watch(self, watch: Watch) -> None:
        self.watch = watch
        if self.is_mounted:
            self._update_cells()

    def _update_cells(self) -> None:
        watch = self.watch
        self.query_one(".watch-name", Static).update(watch.label)
        self.query_one(".watch-value", Static).update(watch.value)
        self.query_one(".watch-delta", Static).update("◆" if watch.changed else "·")
        history = self.query_one(".watch-history", Static)
        history.update(watch.trend)
        history.tooltip = watch.tooltip_history

    def on_click(self, event: events.Click) -> None:
        event.stop()
        if not self.watch.history:
            return
        self.app.copy_to_clipboard("stop\tscope\tvalue\n" + self.watch.export_tsv())
        self.app.notify(
            f"Copied {len(self.watch.history)} samples: {self.watch.label}")

"""Scope tree with hoverable, inspectable GDB-observed function returns."""
from __future__ import annotations

from typing import Callable
from textual.widgets import Tree

from .calltree import ReturnKey


class ScopeTree(Tree):
    def __init__(self, label: str, **kwargs) -> None:
        super().__init__(label, **kwargs)
        self.return_tooltip: Callable[[ReturnKey], str] | None = None

    def watch_hover_line(self, line_no: int) -> None:
        node = self.get_node_at_line(line_no) if line_no >= 0 else None
        key = node.data if node is not None else None
        if isinstance(key, ReturnKey) and self.return_tooltip:
            self.tooltip = self.return_tooltip(key)
        else:
            self.tooltip = None

    def on_leave(self) -> None:
        self.tooltip = None

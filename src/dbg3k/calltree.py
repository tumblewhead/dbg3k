"""Formatting and provenance for GDB-observed call frames and return events."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import Frame


def display_call(frame: Frame, *, max_args: int = 5) -> str:
    """Render observed argument values. Missing debug info stays unknown."""
    args = []
    for _name, value in frame.arguments[:max_args]:
        compact = value.replace("\n", " ").strip()
        if len(compact) > 28:
            compact = compact[:25] + "…"
        args.append(compact)
    if len(frame.arguments) > max_args:
        args.append("…")
    return f"{frame.function}({', '.join(args)})"


@dataclass(frozen=True)
class ReturnObservation:
    """A return value *reported* by GDB, shown inside its caller's frame."""
    caller_function: str
    callee_display: str
    value: str | None
    stop: int

    @property
    def display(self) -> str:
        if self.value is None:
            return f"↳ {self.callee_display}  ↩  returned (value not reported)"
        return f"↳ {self.callee_display}  ⟵ {self.value}"


def observed_return(
    payload: dict[str, Any], previous_top: Frame | None, stop: int
) -> ReturnObservation | None:
    """Accept only genuine GDB/MI function-finished notifications."""
    if payload.get("reason") != "function-finished":
        return None
    caller = payload.get("frame")
    if not isinstance(caller, dict):
        return None
    caller_func = str(caller.get("func") or "")
    if not caller_func:
        return None
    callee = display_call(previous_top) if previous_top is not None else "(callee)"
    value = payload.get("return-value")
    return ReturnObservation(caller_func, callee,
                             str(value) if value is not None else None, stop)

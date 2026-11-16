"""Formatting and provenance for GDB-observed call frames and return events."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any
import json

from .model import Frame

RETURN_PREFIX = '__dbg3k_return_v1__'


def probe_return(message: str) -> dict[str, Any] | None:
    """Decode our GDB helper's protocol, never parse human console prose."""
    if not message.startswith(RETURN_PREFIX):
        return None
    try:
        data = json.loads(message[len(RETURN_PREFIX):])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get('schema') != 'dbg3k.gdb-return.v1':
        return None
    if not all(isinstance(data.get(key), str) and data[key]
               for key in ('thread', 'caller', 'callee', 'callee_display')):
        return None
    if 'value' not in data or (data['value'] is not None and not isinstance(data['value'], str)):
        return None
    return data


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


@dataclass(frozen=True)
class ReturnKey:
    """An aggregated caller-to-callee edge within one GDB thread."""
    thread: str
    caller: str
    callee: str


@dataclass
class ReturnSeries:
    """Constant-size UI memory; full return evidence lives in JSONL."""
    key: ReturnKey
    count: int = 0
    last: ReturnObservation | None = None
    recent: deque[ReturnObservation] = field(default_factory=lambda: deque(maxlen=10))

    @property
    def label(self) -> str:
        if self.last is None:
            return ""
        result = (self.last.value if self.last.value is not None
                  else "return (unreported)")
        return f"↳ {self.last.callee_display}  ⟵ {result}  ·  {self.count}×"

    @property
    def tooltip(self) -> str:
        lines = [f"{self.key.callee} → {self.key.caller}  ({self.count} observed returns)"]
        lines.extend(
            f"stop {item.stop}: {item.callee_display} → "
            f"{item.value if item.value is not None else '(unreported)'}"
            for item in self.recent
        )
        lines.append("Click to copy all returns from this session")
        return "\n".join(lines)


class ReturnLedger:
    def __init__(self) -> None:
        self.series: dict[ReturnKey, ReturnSeries] = {}

    def observe(self, event: ReturnObservation, *, thread: str,
                callee_function: str | None = None) -> ReturnSeries:
        if not callee_function:
            callee_function = event.callee_display.split("(", 1)[0]
        key = ReturnKey(thread, event.caller_function, callee_function)
        current = self.series.get(key)
        if current is None:
            current = ReturnSeries(key)
            self.series[key] = current
        current.count += 1
        current.last = event
        current.recent.append(event)
        return current

    def for_caller(self, *, thread: str, caller: str) -> list[ReturnSeries]:
        return sorted((value for key, value in self.series.items()
                       if key.thread == thread and key.caller == caller),
                      key=lambda value: value.key.callee)

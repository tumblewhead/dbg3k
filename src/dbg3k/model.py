"""Scope-qualified variable observations, bounded numeric histories, frame identities."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field, replace
from math import isfinite
from typing import Any

SPARK = '▁▂▃▄▅▆▇█'
HISTORY_LIMIT = 4096  # Host-side observation buffer, not embedded target SRAM.

def number_of(value: str, kind: str = '') -> float | None:
    if '*' in kind or '[' in kind or '{' in value or '<' in value:
        return None
    try:
        n = float(int(value, 0)) if value.lower().startswith(('0x', '-0x')) else float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return n if isfinite(n) else None

def sparkline(values: list[float], max_width: int = 18) -> str:
    values = values[-max_width:]
    if not values:
        return ''
    lo, hi = min(values), max(values)
    if lo == hi:
        return SPARK[3] * len(values)
    return ''.join(SPARK[min(7, int((v - lo) * 7 / (hi - lo) + 0.5))] for v in values)

def parse_arguments(items: Any) -> tuple[tuple[str, str], ...]:
    """Handle GDB/MI argument tuples and older name=value list shapes."""
    if not isinstance(items, list):
        return ()
    result: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if 'name' in item:
            result.append((str(item['name']), str(item.get('value', '?'))))
        else:
            for name, value in item.items():
                result.append((str(name), str(value)))
    return tuple(result)


def parse_stack_arguments(payload: dict[str, Any]) -> dict[int, tuple[tuple[str, str], ...]]:
    """Decode the GDB/MI -stack-list-arguments stack-args response."""
    frames: dict[int, tuple[tuple[str, str], ...]] = {}
    for item in payload.get('stack-args', []):
        if not isinstance(item, dict):
            continue
        frame = item.get('frame', item)
        if not isinstance(frame, dict):
            continue
        try:
            level = int(frame['level'])
        except (ValueError, KeyError, TypeError):
            continue
        frames[level] = parse_arguments(frame.get('args', []))
    return frames


@dataclass(frozen=True)
class Frame:
    level: int
    function: str
    filename: str
    line: int
    pc: str = ''
    arguments: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_mi(cls, data: dict[str, Any]) -> 'Frame':
        return cls(
            level=int(data.get('level', 0)),
            function=str(data.get('func', '??')),
            filename=str(data.get('fullname') or data.get('file') or ''),
            line=int(data.get('line') or 0),
            pc=str(data.get('addr', '')),
            arguments=parse_arguments(data.get('args', [])),
        )

    @property
    def signature(self) -> tuple[str, str]:
        return self.filename, self.function

@dataclass
class Watch:
    label: str
    frame_level: int
    generation: int
    name: str
    symbol_id: str = ''
    type_name: str = ''
    value: str = ''
    previous: str | None = None
    numeric: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    history: deque[tuple[int, str]] = field(
        default_factory=lambda: deque(maxlen=HISTORY_LIMIT))
    active: bool = True
    observed_stop: int = -1

    @property
    def changed(self) -> bool:
        return self.previous is not None and self.value != self.previous

    @property
    def trend(self) -> str:
        """Raw values until three numeric observations, then a compact sparkline."""
        values = list(self.numeric)
        if len(values) < 3:
            return '[' + ', '.join(f'{v:g}' for v in values) + ']' if values else '·'
        return sparkline(values, max_width=24)

    @property
    def tooltip_history(self) -> str:
        recent = list(self.history)[-10:]
        if not recent:
            return 'No samples yet'
        return self.label + '\n' + '\n'.join(
            f'stop {stop}: {value}' for stop, value in recent
        ) + '\nClick row to copy full retained history'

    def export_tsv(self) -> str:
        label = self.label if self.frame_level == -1 else (
            f'{self.label}@frame{self.frame_level}#gen{self.generation}')
        return '\n'.join(
            f'{stop}\t{label}\t{value}' for stop, value in self.history
        )

class ScopeModel:
    """Observed frames only. Calls entirely between debugger stops may be invisible."""
    def __init__(self) -> None:
        self.frames: list[Frame] = []
        self.watches: dict[tuple[int, int, str], Watch] = {}
        self.global_watches: dict[str, Watch] = {}
        self._frame_signatures: dict[int, tuple[str, str]] = {}
        self._generations: dict[int, int] = {}
        self._serial = 0
        self.stop = 0

    def begin_stop(self) -> None:
        self.stop += 1

    def set_frames(self, frames: list[Frame]) -> None:
        new_signatures = {f.level: f.signature for f in frames}
        for level, signature in new_signatures.items():
            if self._frame_signatures.get(level) != signature:
                self._serial += 1
                self._generations[level] = self._serial
        self._frame_signatures = new_signatures
        self.frames = sorted(frames, key=lambda f: f.level)
        for watch in self.watches.values():
            if (watch.frame_level not in new_signatures or
                    watch.generation != self._generations.get(watch.frame_level)):
                watch.active = False

    def set_frame_arguments(self, arguments_by_level: dict[int, tuple[tuple[str, str], ...]]) -> None:
        self.frames = [
            replace(frame, arguments=arguments_by_level[frame.level])
            if frame.level in arguments_by_level else frame
            for frame in self.frames
        ]

    def retained_watches(self) -> list[Watch]:
        """Active and expired observations, for complete bounded-history export."""
        return list(self.watches.values()) + list(self.global_watches.values())

    def export_history_tsv(self) -> str:
        records: list[tuple[int, str, str]] = []
        for watch in self.retained_watches():
            label = (watch.label if watch.frame_level == -1 else
                     f'{watch.label}@frame{watch.frame_level}#gen{watch.generation}')
            records.extend((stop, label, value) for stop, value in watch.history)
        records.sort(key=lambda entry: (entry[0], entry[1]))
        return 'stop\tscope\tvalue\n' + '\n'.join(
            f'{stop}\t{label}\t{value}' for stop, label, value in records
        )

    def set_variables(self, level: int, variables: list[dict[str, Any]]) -> None:
        frame = next((f for f in self.frames if f.level == level), None)
        if frame is None:
            return
        generation = self._generations[level]
        current: set[str] = set()
        for raw in variables:
            name = str(raw.get('name', ''))
            if not name:
                continue
            source = str(raw.get('fullname') or raw.get('filename') or '')
            decl = str(raw.get('line') or raw.get('shadowed_loc') or '')
            identity = f'{name}@{source}:{decl}' if source or decl else name
            current.add(identity)
            key = (level, generation, identity)
            label = f'{frame.function}.{name}' + (f'@{decl}' if decl else '')
            watch = self.watches.get(key)
            if watch is None:
                watch = Watch(label, level, generation, name, identity)
                self.watches[key] = watch
            value = str(raw.get('value', '<unavailable>'))
            if watch.observed_stop != self.stop:
                watch.previous = watch.value if watch.observed_stop >= 0 else None
                watch.value = value
                watch.observed_stop = self.stop
                watch.history.append((self.stop, value))
                n = number_of(value, str(raw.get('type', '')))
                if n is not None:
                    watch.numeric.append(n)
            watch.type_name = str(raw.get('type', ''))
            watch.active = True
        for watch in self.watches.values():
            if (watch.frame_level == level and watch.generation == generation
                    and watch.symbol_id not in current):
                watch.active = False

    def active_watches(self, level: int | None = None) -> list[Watch]:
        return [w for w in self.watches.values()
                if w.active and (level is None or w.frame_level == level)]

    def set_global_value(self, key: str, label: str, name: str,
                         value: str, type_name: str = '') -> None:
        """Observe one persistent global at the current debugger stop."""
        watch = self.global_watches.get(key)
        if watch is None:
            watch = Watch(label, -1, 0, name, key)
            self.global_watches[key] = watch
        if watch.observed_stop != self.stop:
            watch.previous = watch.value if watch.observed_stop >= 0 else None
            watch.value = value
            watch.observed_stop = self.stop
            watch.history.append((self.stop, value))
            number = number_of(value, type_name)
            if number is not None:
                watch.numeric.append(number)
        watch.type_name = type_name
        watch.active = True

    def active_globals(self) -> list[Watch]:
        return [watch for watch in self.global_watches.values() if watch.active]

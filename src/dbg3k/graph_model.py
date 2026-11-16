"""Derived run rankings and sampled stack ranges, independent of UI/transport."""
from dataclasses import dataclass

from .resources import CodeCatalog, EnergyModel, FunctionCode, InstructionProfile, StackProfile


@dataclass(frozen=True)
class FunctionStats:
    function: FunctionCode
    instructions: int
    entries: int | None
    energy_pj: float | None
    charge_pc: float | None

    @property
    def per_entry(self) -> float | None:
        return self.instructions / self.entries if self.entries else None

    @property
    def density(self) -> float:
        return self.instructions / self.function.size

    def metric(self, key: str) -> float | int | str | None:
        return {'instructions': self.instructions, 'calls': self.entries,
                'text': self.function.size, 'per_entry': self.per_entry,
                'density': self.density, 'energy': self.energy_pj,
                'charge': self.charge_pc, 'name': self.function.names[0]}[key]


def function_stats(catalog: CodeCatalog, profile: InstructionProfile,
                   energy: EnergyModel | None = None) -> list[FunctionStats]:
    return [FunctionStats(f, profile.by_function[f.key], profile.entry_hits[f.key] if profile.entries_available else None,
                          energy.energy_pj(profile.by_function[f.key]) if energy else None,
                          energy.charge_pc(profile.by_function[f.key]) if energy else None)
            for f in catalog.functions]


def rank_functions(rows: list[FunctionStats], metric: str, descending: bool = True) -> list[FunctionStats]:
    # Missing averages (no observed entry) always sort last. Stable name/address
    # order breaks ties; aliases remain one emitted body.
    ordered = sorted(rows, key=lambda r: (r.function.names[0], r.function.key))
    known = [r for r in ordered if r.metric(metric) is not None]
    unknown = [r for r in ordered if r.metric(metric) is None]
    return sorted(known, key=lambda r: r.metric(metric), reverse=descending) + unknown


def code_coverage(catalog: CodeCatalog) -> int:
    """Union of sized executable body ranges, not sum of overlapping aliases."""
    groups = {}
    for f in catalog.functions:
        groups.setdefault(f.section, []).append((f.start, f.start + f.size))
    total = 0
    for spans in groups.values():
        end = -1
        for low, high in sorted(spans):
            total += max(0, high - max(low, end))
            end = max(end, high)
    return total


def current_bodies(stack: StackProfile, catalog: CodeCatalog | None, stop: int,
                   selected_level: int) -> tuple[str | None, str | None]:
    if not catalog or not stack.sample or stack.sample['stop'] != stop:
        return None, None
    current, selected = None, None
    for frame in stack.sample['frames']:
        body = catalog.lookup(frame['pc'])
        if body:
            if frame['level'] == 0:
                current = body.key
            if frame['level'] == selected_level:
                selected = body.key
    return current, selected


@dataclass(frozen=True)
class StackRange:
    level: int
    function: str
    low: int
    high: int

    @property
    def size(self):
        return self.high - self.low


def stack_ranges(sample: dict) -> list[StackRange]:
    frames = sample['frames']
    ranges = []
    for index, frame in enumerate(frames):
        size = StackProfile.own_bytes(frames, index)
        if size is not None:
            ranges.append(StackRange(frame['level'], frame['function'], frame['sp'], frame['sp'] + size))
    # Descending address order, stack grows downward. Do not bridge a missing
    # inline/exception/unwind boundary with a fabricated contiguous segment.
    return sorted(ranges, key=lambda r: (-r.high, -r.low, r.level))

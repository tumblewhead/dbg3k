"""ELF footprint, sampled stack estimates, QEMU dispatch counts and energy.

No frontend or debugger transport dependencies. Missing evidence stays unknown.
"""
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection


@dataclass(frozen=True)
class FunctionCode:
    section: str
    start: int
    size: int
    names: tuple[str, ...]

    @property
    def key(self) -> str:
        return f'{self.section}:0x{self.start:x}:{self.size}'


class CodeCatalog:
    def __init__(self, elf: str):
        self.sha256 = hashlib.sha256(Path(elf).read_bytes()).hexdigest()
        self.build_id = None
        groups = {}
        with open(elf, 'rb') as stream:
            image = ELFFile(stream)
            self.machine = image['e_machine']
            for table in image.iter_sections():
                if hasattr(table, 'iter_notes'):
                    for note in table.iter_notes():
                        if note['n_type'] == 'NT_GNU_BUILD_ID':
                            self.build_id = note['n_desc']
                if not isinstance(table, SymbolTableSection):
                    continue
                for symbol in table.iter_symbols():
                    index = symbol['st_shndx']
                    size = symbol['st_size']
                    if symbol['st_info']['type'] != 'STT_FUNC' or not isinstance(index, int) or not size:
                        continue
                    section = image.get_section(index)
                    if not section['sh_flags'] & 4:  # SHF_EXECINSTR
                        continue
                    start = symbol['st_value']
                    if self.machine == 'EM_ARM':
                        start &= ~1  # Thumb symbol tag, not an extra code byte.
                    if start < section['sh_addr'] or start + size > section['sh_addr'] + section['sh_size']:
                        continue
                    groups.setdefault((section.name, start, size), set()).add(symbol.name)
        self.functions = sorted((FunctionCode(*key, tuple(sorted(names))) for key, names in groups.items()),
                                key=lambda f: f.start)
        self.starts = [f.start for f in self.functions]
        self.max_ends = []
        for f in self.functions:
            self.max_ends.append(max(f.start + f.size, self.max_ends[-1] if self.max_ends else 0))

    def lookup(self, pc: int) -> FunctionCode | None:
        if self.machine == 'EM_ARM':
            pc &= ~1
        at = bisect_right(self.starts, pc) - 1
        found = []
        while at >= 0 and self.max_ends[at] > pc:
            f = self.functions[at]
            if f.start <= pc < f.start + f.size:
                found.append(f)
            at -= 1
        # Exact aliases share one body; overlapping unequal bodies are unknown.
        return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class EnergyModel:
    ua_per_mhz: float
    mips_per_mhz: float
    voltage: float

    def __post_init__(self):
        if not all(isfinite(x) and x > 0 for x in (self.ua_per_mhz, self.mips_per_mhz, self.voltage)):
            raise ValueError('All energy assumptions must be finite and greater than zero')

    def charge_pc(self, instructions: int) -> float:
        return instructions * self.ua_per_mhz / self.mips_per_mhz

    def energy_pj(self, instructions: int) -> float:
        return self.charge_pc(instructions) * self.voltage


class InstructionProfile:
    def __init__(self):
        self.run = None
        self.seq = 0
        self.total = 0
        self.unknown = 0
        self.by_function = Counter()
        self.entry_hits = Counter()  # Dispatches at body entry; a qualified call-count proxy.
        self.entries_available = True
        self.complete = False

    def update(self, data: dict, catalog: CodeCatalog) -> bool:
        if (data.get('schema') != 'dbg3k.qemu-counts.v1' or
                data.get('metric') != 'instruction-dispatch' or
                data.get('elf_sha256') != catalog.sha256):
            raise ValueError('Instruction snapshot schema/metric/ELF hash mismatch')
        run, seq, total, overflow = (data.get(k) for k in ('run', 'seq', 'total', 'overflow'))
        if not isinstance(run, str) or not run or not all(type(x) is int and x >= 0 for x in (seq, total, overflow)):
            raise ValueError('Invalid instruction snapshot counters')
        if type(data.get('complete')) is not bool or not isinstance(data.get('pcs'), list):
            raise ValueError('Invalid instruction snapshot payload')
        if run == self.run and seq <= self.seq:
            return False
        by_function = Counter()
        entry_hits = Counter()
        accounted = overflow
        unknown = overflow
        seen = set()
        for address, count in data['pcs']:
            pc = int(address, 0)
            if pc < 0 or pc in seen or type(count) is not int or count < 0:
                raise ValueError('Invalid or duplicated instruction PC')
            seen.add(pc)
            accounted += count
            function = catalog.lookup(pc)
            if function is None:
                unknown += count
            else:
                by_function[function.key] += count
                normalized = pc & ~1 if catalog.machine == 'EM_ARM' else pc
                if normalized == function.start:
                    entry_hits[function.key] += count
        if accounted != total or (run == self.run and total < self.total):
            raise ValueError('Inconsistent instruction snapshot totals')
        changed = (run, total, data.get('complete')) != (self.run, self.total, self.complete)
        self.run, self.seq, self.total, self.unknown = run, seq, total, unknown
        self.by_function, self.complete = by_function, data.get('complete') is True
        self.entry_hits = entry_hits
        self.entries_available = True
        return changed

    def update_record(self, record: dict, catalog: CodeCatalog) -> bool:
        """Restore one cumulative journal snapshot; never sum cumulative totals."""
        if record.get('elf_sha256') != catalog.sha256:
            raise ValueError('JSONL profile ELF hash mismatch')
        run, seq, total, unknown = (record.get(k) for k in ('run', 'profile_seq', 'total', 'unknown'))
        if (not isinstance(run, str) or not run or
                not all(type(x) is int and x >= 0 for x in (seq, total, unknown)) or
                type(record.get('complete')) is not bool):
            raise ValueError('Invalid JSONL profile metadata')
        functions, entries = record.get('functions'), record.get('entry_hits', {})
        keys = {f.key for f in catalog.functions}
        for mapping in (functions, entries):
            if not isinstance(mapping, dict) or any(
                    key not in keys or type(value) is not int or value < 0 for key, value in mapping.items()):
                raise ValueError('Invalid JSONL function counters')
        if sum(functions.values()) + unknown != total:
            raise ValueError('Inconsistent JSONL profile total')
        if any(value > functions.get(key, 0) for key, value in entries.items()):
            raise ValueError('JSONL entry hits exceed instruction counts')
        if run == self.run and seq <= self.seq:
            return False
        if run == self.run and total < self.total:
            raise ValueError('JSONL profile regressed within a QEMU run')
        changed = (run, total, record['complete']) != (self.run, self.total, self.complete)
        self.run, self.seq, self.total, self.unknown = run, seq, total, unknown
        self.by_function, self.entry_hits = Counter(functions), Counter(entries)
        self.entries_available = 'entry_hits' in record
        self.complete = record['complete']
        return changed


def decode_stack(message: str) -> dict | None:
    prefix = '__dbg3k_stack_v1__'
    if not message.startswith(prefix):
        return None
    try:
        data = json.loads(message[len(prefix):])
        if data.get('schema') != 'dbg3k.stack.v1' or type(data['stop']) is not int:
            return None
        if not isinstance(data['thread'], str) or not isinstance(data['registers'], dict):
            return None
        for f in data['frames']:
            if (type(f['level']) is not int or type(f['pc']) is not int or
                    not isinstance(f['function'], str) or f['kind'] not in ('normal', 'inline', 'other') or
                    (f['sp'] is not None and type(f['sp']) is not int)):
                return None
        memory = data.get('memory')
        if memory is not None:
            if type(memory.get('start')) is not int or memory['start'] < 0:
                return None
            if not isinstance(memory.get('hex'), str) or len(bytes.fromhex(memory['hex'])) > 256:
                return None
        return data
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


class StackProfile:
    def __init__(self):
        self.sample = None
        self.peaks = {}  # Aggregate sampled estimates, never invocation guarantees.

    @staticmethod
    def own_bytes(frames: list[dict], index: int) -> int | None:
        if index + 1 >= len(frames):
            return None
        current, caller = frames[index:index + 2]
        if any(f['kind'] != 'normal' or f['sp'] is None for f in (current, caller)):
            return None
        delta = caller['sp'] - current['sp']
        return delta if delta >= 0 else None

    @staticmethod
    def inclusive_bytes(frames: list[dict], index: int) -> int | None:
        if any(StackProfile.own_bytes(frames, i) is None for i in range(index + 1)):
            return None
        return frames[index + 1]['sp'] - frames[0]['sp']

    def update(self, sample: dict, catalog: CodeCatalog | None):
        self.sample = sample
        for index, f in enumerate(sample['frames']):
            function = catalog.lookup(f['pc']) if catalog else None
            key = (sample['thread'], function.key if function else f['function'])
            peak = self.peaks.setdefault(key, [None, None])
            for at, value in enumerate((self.own_bytes(sample['frames'], index),
                                         self.inclusive_bytes(sample['frames'], index))):
                if value is not None:
                    peak[at] = max(peak[at] or 0, value)

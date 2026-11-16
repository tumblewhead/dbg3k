"""Terminal stack maps and interactive whole-run ranking charts."""
from math import ceil
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Select, Static

from .graph_model import code_coverage, function_stats, rank_functions, stack_ranges


def compact(value: float | int | None) -> str:
    if value is None:
        return '—'
    if isinstance(value, int):
        return str(value)
    return f'{value:.3g}'


def bar(value, maximum, width=12):
    if value is None or not maximum:
        return '░' * width
    filled = min(width, max(1, ceil(value / maximum * width))) if value else 0
    return '█' * filled + '░' * (width - filled)


class StackMap(Static):
    """Scaled unwind gaps plus a bounded, actual raw stack-memory snapshot."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sample = None
        self.level = 0
        self.stop = 0

    def set_sample(self, sample, level, stop):
        self.sample, self.level, self.stop = sample, level, stop
        self.redraw()

    def on_resize(self):
        self.redraw()

    def redraw(self):
        text = Text()
        if not self.sample or self.sample['stop'] != self.stop:
            self.update('Stack map unavailable until a current halted snapshot exists.')
            return
        sample = self.sample
        text.append(f'Stop {self.stop} · thread {sample["thread"]}\n', style='bold')
        text.append('Higher addresses ↑ · stack grows ↓\n')
        theme = self.app.current_theme
        colors = [theme.primary or '#7dd3fc', theme.success or '#4EBF71',
                  theme.warning or '#EFC75E', theme.secondary or '#C4A7E7']
        selected_color = theme.accent or '#EFA5C8'
        ranges = stack_ranges(sample)
        overlap = any(b.high > a.low for a, b in zip(ranges, ranges[1:]))
        if not ranges or overlap:
            text.append('No consistent normal-frame ranges to map.\n', style='dim')
        else:
            text.append('Oldest-frame allocation / total stack bounds: unknown\n', style='dim')
            oldest = sample['frames'][-1]
            text.append(f'Oldest sampled frame: #{oldest["level"]} {oldest["function"]} · allocation unknown\n',
                        style=f'bold {selected_color}' if oldest['level'] == self.level else 'dim')
            total = sum(segment.size for segment in ranges)
            previous = None
            label_width = max(10, self.size.width - 24)
            for segment in ranges:
                if previous is not None and previous != segment.high:
                    text.append(f'0x{previous:08x} ┆????????┆ unknown boundary\n', style='dim')
                selected = segment.level == self.level
                color = selected_color if selected else colors[segment.level % len(colors)]
                text.append(f'0x{segment.high:08x} ┏━━━━━━━━┓\n', style=color)
                label = f'{"▸" if selected else " "}#{segment.level} {segment.function}'[:label_width]
                if segment.size:
                    height = max(1, round(24 * segment.size / total)) if total else 1
                    text.append(f'           ┃████████┃ {label}\n', style=color)
                    for _ in range(height - 1):
                        text.append('           ┃████████┃\n', style=color)
                else:
                    text.append(f'           ┣━━━━━━━━┫ {label} · zero SP gap\n', style=color)
                text.append(f'0x{segment.low:08x} ┗━━━━━━━━┛ ~{segment.size} B unwound gap\n', style=color)
                previous = segment.low
            text.append('Bar scale: observed byte gaps; minimum one row per gap.\n', style='dim')
        registers = sample['registers']
        for name in ('sp', 'msp', 'psp'):
            value = registers.get(name)
            text.append(f'{name.upper()}: {"unavailable" if value is None else f"0x{value:08x}"}\n')
        text.append('\nRAW STACK CONTENTS · address : bytes\n', style='bold')
        memory = sample.get('memory')
        if memory is None:
            text.append('Memory bytes unavailable' + (': ' + sample['memory_error'] if sample.get('memory_error') else '') + '\n')
        else:
            raw = bytes.fromhex(memory['hex'])
            start = memory['start']
            text.append(f'Observed [0x{start:08x}, 0x{start + len(raw):08x}) · {len(raw)} B (cap 256 B)\n')
            for at in range(0, len(raw), 8):
                text.append(f'0x{start + at:08x} : {raw[at:at + 8].hex(" ")}\n')
        text.append('SP ranges are estimates, not verified allocation/variable ownership.\n'
                    'No unobserved free space or coroutine storage is drawn.', style='dim')
        self.update(text)


class RunRanking(Vertical):
    """Pareto-style bars plus a sortable full table; cursor survives updates."""

    DEFAULT_CSS = """
    RunRanking { height: auto; }
    RunRanking .rank-controls { height: 3; }
    RunRanking Select { width: 1fr; }
    RunRanking Button { width: 10; min-width: 10; }
    RunRanking .rank-summary, RunRanking .rank-chart, RunRanking .rank-note { height: auto; }
    RunRanking DataTable { height: 12; }
    RunRanking .rank-note { color: $text-muted; }
    """

    METRICS = {
        'instructions': 'Instructions (dispatches)', 'calls': 'Calls† (entry hits)',
        'text': 'ELF code bytes', 'per_entry': 'Instructions / entry',
        'density': 'Instructions / code byte', 'name': 'Function name',
        'energy': 'Estimated energy (pJ)', 'charge': 'Estimated charge (pC)',
    }

    def __init__(self, *, energy=False, **kwargs):
        super().__init__(**kwargs)
        self.energy = energy
        self.sort_metric = 'energy' if energy else 'instructions'
        self.descending = True
        self.data = None
        self.rows = []
        self._row_keys = []

    def compose(self) -> ComposeResult:
        keys = ('energy', 'charge', 'instructions', 'calls', 'text', 'per_entry', 'density', 'name') if self.energy else (
            'instructions', 'calls', 'text', 'per_entry', 'density', 'name')
        with Horizontal(classes='rank-controls'):
            yield Select([(self.METRICS[key], key) for key in keys], value=self.sort_metric,
                         allow_blank=False, classes='rank-sort')
            yield Button('↓ Desc', classes='rank-order')
            if self.energy:
                yield Button('Model…', classes='rank-model')
        yield Static('Waiting for QEMU run data…', classes='rank-summary', markup=False)
        yield Static('', classes='rank-chart')
        yield DataTable(classes='rank-table', cursor_type='row', fixed_columns=1)
        yield Static('', classes='rank-note', markup=False)

    def on_mount(self):
        table = self.query_one(DataTable)
        for title, key in [('Function', 'name'), ('Dispatches', 'instructions'), ('Calls†', 'calls'),
                           ('Code B', 'text'), ('Instr/entry', 'per_entry'), ('Instr/B', 'density')]:
            table.add_column(title, key=key, width=28 if key == 'name' else None)
        if self.energy:
            table.add_column('Energy pJ', key='energy')
            table.add_column('Charge pC', key='charge')
        table.add_column('Share %', key='share')
        table.add_column('Cumul %', key='cumulative')
        table.tooltip = 'Click a column heading to sort; click again to reverse. Calls† = entry dispatches, a call-count proxy.'

    def set_data(self, catalog, profile, model, current, selected, status, halted, source_note=''):
        self.data = (catalog, profile, model, current, selected, status, halted, source_note)
        if self.is_mounted:
            self.redraw()

    def on_resize(self):
        if self.data and self.is_mounted:
            self.redraw()

    def on_select_changed(self, event: Select.Changed):
        event.stop()
        if event.value == Select.BLANK:
            return
        metric = str(event.value)
        if metric != self.sort_metric:
            self.sort_metric = metric
            self.redraw()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.has_class('rank-model'):
            event.stop()
            self.app.action_energy_model()
            return
        if event.button.has_class('rank-order'):
            event.stop()
            self.descending = not self.descending
            event.button.label = '↓ Desc' if self.descending else '↑ Asc'
            self.redraw()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected):
        event.stop()
        key = event.column_key.value
        if key in ('share', 'cumulative'):
            key = 'energy' if self.energy else 'instructions'
        if key not in self.METRICS:
            return
        if key == self.sort_metric:
            self.descending = not self.descending
        else:
            self.sort_metric, self.descending = key, key != 'name'
        self.query_one(Select).value = self.sort_metric
        self.query_one('.rank-order', Button).label = '↓ Desc' if self.descending else '↑ Asc'
        self.redraw()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        row = next((r for r in self.rows if r.function.key == event.row_key.value), None)
        if row:
            event.data_table.tooltip = (f'{", ".join(row.function.names)}\n{row.function.key}\n'
                                        'Calls† = entry hits. Click headings to sort.')

    def redraw(self):
        if not self.data or not self.is_mounted:
            return
        catalog, profile, model, current, selected, status, halted, source_note = self.data
        table = self.query_one(DataTable)
        old_key = self._row_keys[table.cursor_row] if 0 <= table.cursor_row < len(self._row_keys) else None
        old_scroll = (table.scroll_x, table.scroll_y)
        table.clear()
        self._row_keys = []
        self.rows = []
        summary = self.query_one('.rank-summary', Static)
        chart_widget = self.query_one('.rank-chart', Static)
        note = self.query_one('.rank-note', Static)
        if catalog is None or profile.run is None or status:
            summary.update((status or 'ELF / instruction profile unavailable.')
                           + ('\n' + source_note if source_note else ''))
            chart_widget.update('No run ranking available.')
            note.update('The existing resource panes remain independently selectable.')
            return
        rows = rank_functions(function_stats(catalog, profile, model), self.sort_metric, self.descending)
        self.rows = rows
        active = sum(row.instructions > 0 for row in rows)
        total_entries = sum(row.entries for row in rows) if profile.entries_available else 'unavailable'
        lines = [f'Run {profile.run[:8]} · since QEMU launch · {"final" if profile.complete else "periodic snapshot"}',
                 f'{profile.total} dispatches · {active}/{len(rows)} executed bodies · {total_entries} entry hits',
                 f'Sized body coverage: {code_coverage(catalog)} B · unknown: {profile.unknown} dispatches']
        if source_note:
            lines.append(source_note)
        if self.energy and model is not None:
            lines += [f'Estimated run: {model.energy_pj(profile.total):.6g} pJ · '
                      f'unattributed: {model.energy_pj(profile.unknown):.6g} pJ',
                      f'Assumptions: {model.ua_per_mhz:g} µA/MHz ÷ {model.mips_per_mhz:g} MIPS/MHz × {model.voltage:g} V']
        elif self.energy:
            lines.append('Energy unavailable: use Model… to configure assumptions. Recorded work remains visible.')
        for rank, row in enumerate(rows, 1):
            if row.function.key == current:
                rank_label = (f'rank {rank}/{len(rows)} by {self.METRICS[self.sort_metric]}'
                              if row.metric(self.sort_metric) is not None
                              else f'{self.METRICS[self.sort_metric]} rank unavailable')
                lines.append(f'{"Current" if halted else "Last stopped"}: {row.function.names[0]} · '
                             f'{row.instructions} dispatches · {rank_label}')
                break
        else:
            lines.append('Current function: unavailable (no current mapped GDB frame).')
        summary.update('\n'.join(lines))
        chart = Text()
        numerical = self.sort_metric != 'name'
        maximum = max((row.metric(self.sort_metric) or 0 for row in rows), default=0) if numerical else 0
        chart.append(('Pareto' if self.descending and self.sort_metric in ('instructions', 'energy', 'charge')
                      else 'Ranking') + f' · {self.METRICS[self.sort_metric]}\n', style='bold')
        cumulative = 0
        width = max(8, min(30, self.size.width - 35))
        theme = self.app.current_theme
        highlight = theme.accent or '#7dd3fc'
        shown = set(range(min(8, len(rows))))
        shown.update(i for i, r in enumerate(rows) if r.function.key == current)
        for index, row in enumerate(rows):
            key = row.function.key
            cumulative += row.instructions
            share = 100 * row.instructions / profile.total if profile.total else None
            cumulative_share = 100 * cumulative / profile.total if profile.total else None
            marker = '▶' if key == current else '▸' if key == selected else ' '
            name = Text(f'{marker} {index + 1}. {row.function.names[0]}', style='bold' if key == current else '')
            cells = [name, str(row.instructions), compact(row.entries), str(row.function.size),
                     compact(row.per_entry), compact(row.density)]
            if self.energy:
                cells += [compact(row.energy_pj), compact(row.charge_pc)]
            cells += [f'{share:.2f}' if share is not None else '—',
                      f'{cumulative_share:.2f}' if cumulative_share is not None else '—']
            table.add_row(*cells, key=key)
            self._row_keys.append(key)
            if index in shown:
                if index >= 8:
                    chart.append('…\n', style='dim')
                value = row.metric(self.sort_metric) if numerical else None
                chart.append(f'{marker}{index + 1:>3} {row.function.names[0][:16]:16} ',
                             style=f'bold {highlight}' if key == current else '')
                chart.append(bar(value, maximum, width) if numerical else '', style=highlight)
                cumulative_label = f'{cumulative_share:.1f}%' if cumulative_share is not None else 'unavailable'
                chart.append(f' {compact(value) if numerical else ""} · Σ{cumulative_label}\n')
        chart_widget.update(chart)
        notes = ['Calls† = function-entry dispatch hits (call proxy); tail entries / entry loops can affect counts.',
                 'Σ and Share use ALL run dispatches, including unknown. Stable name/address order breaks ties.',
                 'Top 8 plus current function shown above; scroll the table for all bodies. Headers / selector sort.']
        if self.energy:
            notes += ['Estimated exclusive active-core energy; average POWER unavailable without target time.',
                      'One model for all bodies: energy order matches instruction order.']
        note.update('\n'.join(notes))
        if old_key in self._row_keys:
            table.move_cursor(row=self._row_keys.index(old_key), scroll=False)
            self.call_after_refresh(table.scroll_to, x=old_scroll[0], y=old_scroll[1], animate=False)

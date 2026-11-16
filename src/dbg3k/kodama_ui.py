"""Wide graphical Kodama timelines and memory map, backed by observed samples."""
from rich.text import Text
from textwrap import wrap as wrap_text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, Switch

from .kodama_model import integer, val

GLYPHS = dict(running='▶', interrupted='!', ready='◆', waiting='▒', sleeping='z', free='·', retired='×', parked='◇', unknown='?')


class KodamaCanvas(Static, can_focus=True):
    BINDINGS = [Binding('left', 'older', 'Older'), Binding('right', 'newer', 'Newer'),
                Binding('end', 'live', 'Live'), Binding('up', 'task(-1)', 'Task ↑'),
                Binding('down', 'task(1)', 'Task ↓')]
    DEFAULT_CSS = 'KodamaCanvas { height: auto; } KodamaCanvas:focus { background: $surface; }'

    def __init__(self, history, **kwargs):
        super().__init__(**kwargs)
        self.history = history
        self.cursor = None
        self.selected = None
        self.selection_pinned = False
        self.selected_signal = None
        self.signal_hits = {}
        self.hits = {}
        self.visible_samples = []
        self.lane_gutter = 32
        self.target_status = ''
        self.capture_enabled = False

    def on_resize(self):
        self.redraw()

    def action_older(self):
        samples = list(self.history.samples)
        if samples:
            current = next((i for i, s in enumerate(samples) if s.index == self.cursor), len(samples) - 1)
            self.cursor = samples[max(0, current - 1)].index
            self.redraw()

    def action_newer(self):
        samples = list(self.history.samples)
        if samples:
            current = next((i for i, s in enumerate(samples) if s.index == self.cursor), len(samples) - 1)
            self.cursor = samples[min(len(samples) - 1, current + 1)].index
            self.redraw()

    def action_live(self):
        self.cursor = None
        self.redraw()

    def action_task(self, delta):
        lanes = self.history.lanes()
        if lanes:
            at = next((i for i, t in enumerate(lanes) if t.key == self.selected), 0)
            self.selected = lanes[(at + delta) % len(lanes)].key
            self.selection_pinned = True
            self.selected_signal = None
            self.redraw()

    def on_click(self, event):
        self.focus()
        offset = event.get_content_offset(self)
        if offset is None:
            return
        y, x = offset.y, offset.x
        if y in self.hits:
            self.selected = self.hits[y]
            self.selected_signal = None
            self.selection_pinned = True
        elif y in self.signal_hits:
            self.selected_signal = self.signal_hits[y]
        column = (x - self.lane_gutter) // 2
        if (y in self.hits or y in self.signal_hits) and 0 <= column < len(self.visible_samples):
            self.cursor = self.visible_samples[column].index
        self.redraw()

    def on_mouse_move(self, event):
        offset = event.get_content_offset(self)
        key = self.hits.get(offset.y) if offset is not None else None
        if key and self.history.samples:
            sample = next((s for s in self.history.samples if s.index == self.cursor), self.history.samples[-1])
            task = next((t for t in sample.tasks if t.key == key), None)
            self.tooltip = self.history.wait_text(task, sample) if task else 'Task identity not present in this sample'
        else:
            self.tooltip = None

    def redraw(self):
        theme = self.app.current_theme
        colors = dict(running=theme.success or '#4EBF71', ready=theme.primary or '#7DD3FC',
            waiting=theme.warning or '#EFC75E', sleeping='#C4A7E7' if theme.dark else '#704090',
            free=theme.foreground or '#BBBBBB', parked=theme.accent or '#EFA5C8',
            retired=theme.warning or '#EFC75E',
            interrupted=theme.warning or '#EFC75E',
            unknown=theme.error or '#FF7788')
        accent = theme.accent or '#EFA5C8'
        out = Text(no_wrap=True, overflow='crop')
        self.hits = {}
        self.signal_hits = {}
        def line(text='', style=None, wrap=False):
            for part in (wrap_text(text, width=max(10, self.size.width), replace_whitespace=False) or ['']) if wrap else [text]:
                out.append(part + '\n', style=style)
        samples = list(self.history.samples)
        if not samples:
            line('KODAMA  ·  waiting for a scheduler snapshot', 'bold')
            line('No build-matched recorded samples yet; check ELF/session/path.' if self.target_status.startswith('RECORDED') else
                 'Enable the view at a halted target. Setup selects a signal header and optional API probes.')
            line('Snapshots + observed API entries form the timeline; logical ticks are not physical time.', 'dim')
            if self.history.diagnostic:
                line(self.history.diagnostic, colors['unknown'])
            self.update(out)
            return
        if self.cursor is not None and self.cursor < samples[0].index:
            self.cursor = samples[0].index
        current = next((s for s in samples if s.index == self.cursor), samples[-1])
        coverage = self.history.coverage
        recorded = self.target_status.startswith('RECORDED')
        mode = ('FOLLOW JOURNAL' if recorded else 'FOLLOW LIVE') if self.cursor is None else 'HISTORY · target unchanged'
        line(f'KODAMA  {mode}  │  sample {current.index}  stop {current.stop}  tick {current.tick if current.tick is not None else "?"}  │  {self.target_status}', 'bold')
        line(f'{"Recorded capture" if recorded else "Capture ON" if self.capture_enabled else "Capture PAUSED"} · API probes {"ON" if coverage.get("probes") else "OFF"} '
             f'({len(coverage.get("installed", []))} installed) · {self.history.evicted} older samples evicted', 'dim')
        active = sum(t.active is True for t in current.tasks)
        ready = sum(t.active is True and val(t.fields, 'ready') == 1 for t in current.tasks)
        running = next((t for t in current.tasks if t.state in ('running', 'interrupted')), None)
        predicted = next((t for t in current.tasks if t.key == current.predicted), None)
        best = predicted or next((t for t in current.tasks if current.candidates and t.key == current.candidates[0]), None)
        policy = any('cluster' in t.fields for t in current.tasks)
        rank = f'{("MUST", "MAY", "IF_I_MUST")[best.effective_cluster] if best and best.effective_cluster in (0, 1, 2) else "BASIC" if not policy else "?"} p{best.priority if best else "?"}'
        boxes = [(f'ACTIVE {active}/{current.raw.get("task_capacity", "?")}', accent),
                 (f'READY {ready}', colors['ready']), (rank, colors['waiting']),
                 ('IRQ ' + str(current.frame.get('exception')) if running and running.state == 'interrupted' else
                  'RUN ' + running.name if running else 'NEXT ' + predicted.name if predicted else 'NO SELECTION', colors['running'])]
        inner = max(10, min(20, (self.size.width - 9) // 4 - 2))
        for part in range(3):
            for i, (label, color) in enumerate(boxes):
                out.append(('╭' + '─' * inner + '╮') if part == 0 else
                           ('╰' + '─' * inner + '╯') if part == 2 else
                           ('│' + label[:inner].center(inner) + '│'), style='bold ' + color)
                if i < 3:
                    out.append(' → ' if part == 1 else '   ', style='dim')
            out.append('\n')
        line('  ' + current.decision, accent)
        if current.candidates:
            candidates = {t.key: t for t in current.tasks}
            line('  ready path  ' + '  →  '.join(
                f'{candidates[k].name}[p{candidates[k].priority}]' for k in current.candidates[:12]))
        line('  Derived policy: MUST < MAY < IF_I_MUST → smaller priority → stable ties → yield deferral; cooperative' if policy else
             '  Derived basic policy: smaller numeric priority → stable slot ties; cooperative', 'dim')
        line('TASK LANES  ▶ running  ! interrupted  ◆ ready  ▒ waiting  z sleeping  ◇ parked  · free  × retired  ? unavailable', 'bold')
        width = max(4, (self.size.width - self.lane_gutter - 2) // 2)
        position = samples.index(current)
        start = max(0, min(position - width // 2, len(samples) - width))
        visible = self.visible_samples = samples[start:start + width]
        axis = ['  '] * len(visible)
        for i, s in enumerate(visible):
            if i % 5 == 0:
                label = str(s.index)
                for j, char in enumerate(label[:4]):
                    at, part = divmod(i * 2 + j, 2)
                    if at < len(axis):
                        chars = list(axis[at]); chars[part] = char; axis[at] = ''.join(chars)
        line('sample #'.ljust(self.lane_gutter) + ''.join(axis), 'dim')
        lanes = self.history.lanes()
        if (self.selected is None or not self.selection_pinned) and lanes:
            self.selected = next((t.key for t in current.tasks if t.state == 'running'),
                next((t.key for t in current.tasks if t.state == 'waiting'), lanes[0].key))
        current_tasks = {t.key: t for t in current.tasks}
        for lane in lanes:
            task = current_tasks.get(lane.key)
            cluster = ('!', 'M', 'L')[(task or lane).effective_cluster] if (task or lane).effective_cluster in (0, 1, 2) and (task or lane).active else '—'
            epoch = f'e{lane.epoch}' if lane.epoch else ''
            label = f'{"▸" if lane.key == self.selected else " "} {lane.name[:12]} #{lane.slot}/g{lane.generation if lane.generation is not None else "?"}{epoch} p{task.priority if task and task.priority is not None else "—"}{cluster}'
            self.hits[out.plain.count('\n')] = lane.key
            out.append(label[:self.lane_gutter - 1].ljust(self.lane_gutter), style='bold' if lane.key == self.selected else '')
            for s in visible:
                observed = next((t for t in s.tasks if t.key == lane.key), None)
                glyph = GLYPHS[observed.state] if observed else ' '
                style = colors[observed.state] if observed else 'dim'
                if s.index == current.index:
                    style += ' reverse'
                out.append(glyph + ' ', style=style)
            out.append('\n')
        line('  Priority suffix: ! MUST (including promotion) · M MAY · L IF_I_MUST · hover/click a lane for waits', 'dim')
        if self.history.hidden_lanes:
            line(f'  {self.history.hidden_lanes} older generation lanes omitted (128-lane display limit); raw journal retains evidence.', colors['waiting'])
        line('SIGNALS  ● publication entry  △ API request  ↑/↓ level request  ━/· observed level high/low', 'bold')
        line('  ' + self.history.labels.get('status', 'Signal labels unavailable'), 'dim')
        if self.history.labels.get('skipped') or self.history.labels.get('truncated'):
            line('  Signal header has unsupported/truncated definitions; inspect setup/header and raw configuration.', colors['waiting'])
        signals = self.history.labels.get('signals', [])
        if not signals:
            # Unnamed observed bits remain visible and honestly named.
            seen = 0
            for s in samples:
                seen |= self.history.event_mask(s)
                seen |= s.core.get('levels') or 0
                for t in s.tasks:
                    seen |= val(t.fields, 'seen') or 0
            signals = [dict(name=f'bit{i}', mask=hex(1 << i)) for i in range(32) if seen & (1 << i)]
        selected_signal_detail = None
        for signal in signals:
            bit = int(signal['mask'], 0)
            published = [s for s in samples if s.index <= current.index and self.history.event_mask(s) & bit and
                         (s.event or {}).get('semantics') == 'publication-entry']
            last = published[-1] if published else None
            label = f'  {signal["name"]} {bit:#x}'
            self.signal_hits[out.plain.count('\n')] = signal
            out.append(label[:self.lane_gutter - 1].ljust(self.lane_gutter))
            for s in visible:
                event = s.event or {}
                mask = self.history.event_mask(s)
                level = s.core.get('levels')
                marker, color = ('━', colors['ready']) if level is not None and level & bit else ('·', 'dim') if level is not None else ('?', 'dim')
                if mask & bit:
                    function = event.get('function', '')
                    if event.get('semantics') == 'publication-entry':
                        marker, color = '●', colors['running']
                    elif function == 'kodama_level_set':
                        high = integer(event.get('arguments', {}).get('high'))
                        marker, color = ('↑' if high == 1 else '↓' if high == 0 else '?'), colors['waiting']
                    else:
                        marker, color = '△', colors['waiting']
                if s.index == current.index:
                    color += ' reverse'
                out.append(marker + ' ', style=color)
            out.append('\n')
            if self.selected_signal and self.selected_signal['name'] == signal['name']:
                level = current.core.get('levels')
                level_state = 'HIGH' if level is not None and level & bit else 'LOW' if level is not None else 'unknown'
                selected_signal_detail = f'{signal["name"]}: level {level_state} observed · {len(published)} retained publication entries through cursor · last ' + (
                    f'sample {last.index}, tick {last.tick if last.tick is not None else "?"}' if last else 'unobserved')
        line()
        line('COROUTINE POOL  ·  occupied slot capacity, separate from shared MSP stack', 'bold')
        used = [p for p in current.pool if p.used is True]
        uncertain = [p for p in current.pool if p.used is None]
        total_payload = sum(p.capacity for p in current.pool)
        used_payload = sum(p.capacity for p in used)
        if current.pool:
            line(f'  {len(used)}/{current.raw.get("pool_capacity", "?")} occupied · payload capacity {used_payload}/{total_payload} B '
                 f'· reserved incl. overhead {current.raw.get("pool_reserved_bytes", "?")} B'
                 + (' · incomplete/unknown slots' if uncertain or len(current.pool) != current.raw.get('pool_capacity') else ''))
            for p in current.pool:
                owner = next((t for t in current.tasks if t.key == p.owner), None)
                style = colors[owner.state] if owner else colors['waiting'] if p.used else 'dim' if p.used is False else colors['unknown']
                block = ('█' * 8) if p.used else ('░' * 8) if p.used is False else ('?' * 8)
                line(f'  [{block}] pool{p.index}  {p.address}  {p.capacity} B capacity  →  {p.name}', style)
            line('  Actual requested coroutine bytes per allocation unavailable; capacity is not a measured frame size.', 'dim')
            allocator = current.raw.get('allocator', {})
            diagnostics = [('alloc', 'g_allocations'), ('free', 'g_frees'), ('peak slots', 'g_peak'),
                           ('failures', 'g_failed_alloc'), ('largest request B', 'g_frame_max')]
            available = [(label, integer(allocator.get(key))) for label, key in diagnostics if integer(allocator.get(key)) is not None]
            if available:
                line('  Stored allocator diagnostics · ' + ' · '.join(f'{label} {value}' for label, value in available), 'dim')
        else:
            line('  Pool unavailable or this build uses another allocator.', 'dim')
        line()
        selected = current_tasks.get(self.selected)
        if self.selected_signal:
            line('SIGNAL  ' + (selected_signal_detail or self.selected_signal['name']), 'bold ' + accent, wrap=True)
        if selected:
            line(f'INSPECT  {selected.name}  slot {selected.slot}  generation {selected.generation}  epoch {selected.epoch}  token {hex(selected.token) if selected.token else "—"}', 'bold')
            line('  ' + self.history.wait_text(selected, current), wrap=True)
            if selected.subscription and selected.subscription.get('status') in ('ok', 'partial'):
                for i, alternative in enumerate(selected.subscription.get('alternatives', [])):
                    mask, kind = val(alternative, 'inputs'), val(alternative, 'kind')
                    seen = current.core.get('levels') if kind == 2 else val(selected.fields, 'seen')
                    out.append('  ' + ('OR ' if i else '   ') + ('LEVEL ' if kind == 2 else 'EVENT '), style='bold')
                    if mask is not None:
                        for bit in range(32):
                            flag = 1 << bit
                            if mask & flag:
                                matched = bool(seen & flag) if seen is not None else None
                                out.append('[' + ('● ' if matched else '○ ' if matched is False else '? ') +
                                    self.history.mask_names(flag) + '] ',
                                    style=colors['running'] if matched else colors['waiting'])
                    out.append('\n')
            line(f'  context {hex(val(selected.fields, "context")) if val(selected.fields, "context") is not None else "?"}'
                 f' · pool {selected.pool if selected.pool is not None else "unattributed"}'
                 f' · seen {self.history.mask_names(val(selected.fields, "seen"))}'
                 f' · wake alternatives {hex(val(selected.fields, "wake_mask")) if val(selected.fields, "wake_mask") is not None else "?"}')
        event = current.event
        if event:
            args = ', '.join(k + '=' + (v.get('value') or '?') for k, v in event.get('arguments', {}).items())
            line(f'  {event["semantics"]}: {event["function"]}({args})', accent)
            exception = current.frame.get('exception')
            line(f'  caller {event.get("caller") or "?"} · exception {exception if exception is not None else "unknown"}', 'dim')
        frame = current.frame
        line(f'  {frame.get("function", "?")} · {frame.get("filename") or "?"}:{frame.get("line") or "?"}', 'dim')
        notes = current.notes + self.history.coverage.get('unavailable', [])
        if self.history.diagnostic:
            notes.append(self.history.diagnostic)
        for note in notes[:5]:
            line('  ! ' + note, colors['unknown'])
        line('One cell = one observed sample; unequal spacing, not duration. Requests are not proof of success.', 'dim')
        line('Click task/cell to inspect · Left/Right scrub · End follows live · Up/Down select task', 'dim')
        self.update(out)


class KodamaPanel(Vertical):
    DEFAULT_CSS = '''
    KodamaPanel { border: round $accent; background: $surface; }
    KodamaPanel .kodama-controls { height: 3; }
    KodamaPanel Button { min-width: 10; width: auto; }
    KodamaPanel .kodama-scroll { height: 1fr; }
    '''

    def __init__(self, history, **kwargs):
        super().__init__(**kwargs)
        self.history = history

    def compose(self):
        with Horizontal(classes='kodama-controls'):
            yield Button('◀ Older', classes='kodama-older')
            yield Button('Newer ▶', classes='kodama-newer')
            yield Button('Follow live', classes='kodama-live')
            yield Button('Setup', classes='kodama-setup')
            yield Button('Expand', classes='kodama-expand')
        with VerticalScroll(classes='kodama-scroll'):
            yield KodamaCanvas(self.history)

    def redraw(self, status, enabled):
        canvas = self.query_one(KodamaCanvas)
        canvas.target_status, canvas.capture_enabled = status, enabled
        canvas.redraw()

    def on_mount(self):
        if isinstance(self.screen, KodamaScreen):
            self.query_one('.kodama-expand', Button).label = 'Close'

    def on_button_pressed(self, event):
        event.stop()
        canvas = self.query_one(KodamaCanvas)
        if event.button.has_class('kodama-older'):
            canvas.action_older()
        elif event.button.has_class('kodama-newer'):
            canvas.action_newer()
        elif event.button.has_class('kodama-live'):
            canvas.action_live()
        elif event.button.has_class('kodama-setup'):
            self.app.action_kodama_setup()
        elif event.button.has_class('kodama-expand'):
            if isinstance(self.screen, KodamaScreen):
                self.screen.dismiss()
            else:
                self.app.action_kodama_expand()


class KodamaScreen(ModalScreen):
    DEFAULT_CSS = 'KodamaScreen { background: $background; } KodamaScreen KodamaPanel { width: 100%; height: 1fr; }'
    BINDINGS = [('escape', 'dismiss', 'Close Kodama')]

    def compose(self):
        yield KodamaPanel(self.app.kodama_history)

    def on_mount(self):
        self.app._show_kodama()
        self.query_one(KodamaCanvas).focus()


class KodamaSetup(ModalScreen):
    DEFAULT_CSS = '''
    KodamaSetup { align: center middle; }
    #kodama-form { width: 78; max-height: 95%; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #kodama-form Static { height: auto; }
    #kodama-setup-error { color: $error; }
    '''
    BINDINGS = [('escape', 'dismiss', 'Close')]

    def compose(self):
        with Vertical(id='kodama-form'):
            yield Static('Kodama · graphical scheduler observations', classes='resource-title')
            yield Label('Application signal header (single-bit const/constexpr/enum/#define names)')
            yield Input(self.app.kodama_header or '', id='kodama-header')
            yield Label('Observe API entries between visible debugger stops')
            yield Switch(self.app.kodama_probes, id='kodama-probes')
            yield Static('Probes add internal host debugger breakpoints and overhead. No target calls.\n'
                         'Timeline uses observation order and logical ticks. API requests can fail.\n'
                         'Header names are source mappings, not verified against this ELF.\n'
                         'Changes apply at the next halted stop. Start begins a fresh bounded history.')
            yield Static(str(self.app._trace.path) if self.app._trace else 'JSONL unavailable until connection', markup=False)
            yield Static('', id='kodama-setup-error', markup=False)
            with Horizontal(classes='kodama-controls'):
                yield Button('Start / restart', id='kodama-start', variant='primary')
                yield Button('Pause capture', id='kodama-pause')
                yield Button('Close', id='kodama-close')

    def on_button_pressed(self, event):
        if event.button.id == 'kodama-close':
            self.dismiss()
            return
        try:
            self.app.configure_kodama(event.button.id == 'kodama-start',
                self.query_one('#kodama-header', Input).value.strip() or None,
                self.query_one('#kodama-probes', Switch).value)
        except (OSError, ValueError, UnicodeError) as exc:
            self.query_one('#kodama-setup-error', Static).update(str(exc))
            return
        self.dismiss()

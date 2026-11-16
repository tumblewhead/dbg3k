"""Textual frontend: source, scope tree, sampled watches, and single-key stepping."""
from __future__ import annotations

from pathlib import Path
from collections import deque
from functools import partial
from collections.abc import Iterable
import queue
import json
import time
from elftools.common.exceptions import ELFError
from rich.text import Text
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.screen import Screen
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, RichLog, Static, Tree

from .commands import select_thread_id, locals_request
from .globals import MAX_GLOBAL_WATCHES, GlobalSymbol, discover_globals

from .backend import GdbTransport
from .mi import Record
from .model import Frame, ScopeModel, Watch, parse_stack_arguments
from .calltree import ReturnKey, ReturnLedger, ReturnObservation, display_call, observed_return, probe_return
from .scope_ui import ScopeTree
from .trace import TraceWriter
from .watch_ui import WatchRow
from .views import VIEWS, ViewsScreen, ViewCommandPalette, EnergyScreen
from .resources import CodeCatalog, StackProfile, InstructionProfile, EnergyModel, decode_stack
from .resource_ui import resource_text
from .graph_ui import StackMap, RunRanking
from .graph_model import current_bodies

class DebuggerApp(App):
    TITLE = 'dbg3k'
    SUB_TITLE = 'Scope-first Cortex-M debugger · alpha'
    CSS = """
    Screen { background: $background; color: $foreground; }
    Header { background: $panel; color: $foreground; }
    Footer { background: $panel; color: $foreground; }
    #workbench { height: 1fr; background: $background; }
    #left { width: 63%; background: $background; }
    #right { width: 37%; background: $background; overflow-y: auto; }
    #source_scroll {
        height: 1fr; border: round $border;
        background: $surface; color: $foreground;
        overflow-y: auto; overflow-x: auto;
    }
    #source { height: auto; padding: 1 2; background: $surface; color: $foreground; }
    #stepbar { height: 3; background: $panel; color: $text-accent; padding: 0 1; }
    #scope {
        height: 2fr; min-height: 7; border: round $border;
        background: $surface; color: $foreground;
    }
    #watch_panel, #global_panel {
        height: 1fr; min-height: 6; border: round $border;
        background: $surface; color: $foreground; padding: 0 1;
    }
    #watch_heading, #global_heading { height: 1; color: $text-primary; text-style: bold; }
    #watch_status, #global_status { height: auto; max-height: 3; color: $text-muted; }
    #watch_scroll, #global_scroll { height: 1fr; background: $surface; }
    #watch_rows, #global_rows { height: auto; background: $surface; }
    .resource-panel { height: 1fr; min-height: 10; border: round $border;
        background: $surface; padding: 0 1; }
    .resource-title { height: 1; text-style: bold; color: $text-primary; }
    .resource-content { height: auto; }
    .graph-panel { height: 1fr; min-height: 20; border: round $border;
        background: $surface; padding: 0 1; }
    StackMap { height: auto; }
    WatchRow {
        height: 1; width: 100%; background: $surface;
        color: $foreground;
    }
    WatchRow:hover { background: $panel; }
    .watch-name { width: 38%; color: $text-primary; }
    .watch-value { width: 25%; color: $foreground; }
    .watch-delta { width: 6%; color: $text-warning; }
    .watch-history { width: 1fr; color: $text-accent; }
    #console_panel {
        height: 10; border: round $border;
        background: $surface; color: $foreground;
    }
    #console { height: 1fr; background: $surface; color: $foreground; }
    #gdb_input { height: 3; background: $panel; color: $foreground; }
    Tooltip { background: $panel; color: $foreground; border: round $border; }
    """
    BINDINGS = [
        Binding('n', 'next', 'Next'),
        Binding('s', 'step', 'Into'),
        Binding('i', 'instruction', 'Instruction'),
        Binding('I', 'next_instruction', 'Next instr'),
        Binding('o', 'finish', 'Out'),
        Binding('space', 'repeat', 'Repeat'),
        Binding('c', 'continue_run', 'Continue'),
        Binding('j', 'cursor_down', 'Cursor ↓', show=False),
        Binding('k', 'cursor_up', 'Cursor ↑', show=False),
        Binding('up', 'cursor_up', 'Cursor ↑', show=False),
        Binding('down', 'cursor_down', 'Cursor ↓', show=False),
        Binding('pageup', 'page_up_source', 'Page ↑', show=False),
        Binding('pagedown', 'page_down_source', 'Page ↓', show=False),
        Binding('home', 'source_home', 'Top', show=False),
        Binding('end', 'source_end', 'Bottom', show=False),
        Binding('b', 'breakpoint', 'Breakpoint'),
        Binding('r', 'run_to_cursor', 'Run to cursor'),
        Binding('y', 'copy_line', 'Copy line', show=False),
        Binding('Y', 'copy_source', 'Copy file', show=False),
        Binding('W', 'copy_watches', 'Copy watches', show=False),
        Binding('H', 'copy_history', 'Copy histories'),
        Binding('L', 'copy_log', 'Copy log', show=False),
        Binding('f2,colon', 'focus_console', 'GDB command'),
        Binding('escape', 'focus_source', 'Leave command', show=False),
        Binding('q', 'quit', 'Quit'),
    ]

    def __init__(self, elf: str, gdb: str, remote: str,
                 history_dir: str = "dbg3k-history", instruction_profile: str | None = None,
                 energy_model: EnergyModel | None = None) -> None:
        super().__init__()
        self.elf, self.remote = elf, remote
        self.history_dir = history_dir
        self.instruction_path = Path(instruction_profile).expanduser() if instruction_profile else None
        self.energy_model = energy_model
        self.stack_profile = StackProfile()
        self.instruction_counts = InstructionProfile()
        self._stack_ready = False
        self._stack_error = ''
        self._resource_poll_time = 0.0
        self._count_status = 'Start QEMU with the counts plugin and pass --instruction-profile PATH.'
        try:
            self.catalog = CodeCatalog(elf)
            self._catalog_error = ''
        except (OSError, ValueError, ELFError) as exc:
            self.catalog = None
            self._catalog_error = str(exc)
        self._trace: TraceWriter | None = None
        self._trace_error_reported = False
        self._returns = ReturnLedger()
        self._probe_returns_since_command: set[tuple[str, str, str]] = set()
        # Stable tree branches: only live frames are rebuilt at each GDB reply.
        # Return history nodes must survive frame exit and subsequent refreshes.
        self._stack_branch = None
        self._return_branch = None
        self._return_caller_nodes = {}
        self._return_edge_nodes = {}
        self.transport = GdbTransport(gdb)
        self.model = ScopeModel()
        self.pending: dict[int, tuple[str, int | None]] = {}
        self.status = 'CONNECTING'
        self.last_step = '-exec-next'
        self.nav_line = 1
        self.nav_file = ''
        self.selected_level = 0
        self.breaks: dict[tuple[str, int], str] = {}
        self._break_pending: tuple[str, int] | None = None
        self._source_lines = 0
        self._watches_error = ''
        self._watch_results: dict[int, int] = {}
        self._active_thread: str | None = None
        self._globals: list[GlobalSymbol] = []
        self._globals_discovered = False
        self._globals_truncated = False
        self._globals_error = ''
        self._global_result_stop: dict[int, int] = {}
        self._global_last_requested_stop = -1
        self._argument_result_stop: dict[int, int] = {}
        self._last_return: ReturnObservation | None = None
        self._rendered_theme: str | None = None
        self._watch_rows: dict[str, WatchRow] = {}
        self._global_rows: dict[str, WatchRow] = {}
        self.visible_views = set(VIEWS)
        self._connected = False
        self._log_lines: deque[str] = deque(maxlen=500)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id='workbench'):
            with Vertical(id='left'):
                with VerticalScroll(id='source_scroll'):
                    yield Static('Connecting to GDB...', id='source')
            with Vertical(id='right'):
                yield ScopeTree('cpu0 / observed call stack', id='scope')
                with Vertical(id='watch_panel'):
                    yield Static('IMMEDIATE SCOPE · executing frame', id='watch_heading')
                    yield Static('Locals and arguments appear when GDB stops.', id='watch_status')
                    with VerticalScroll(id='watch_scroll'):
                        yield Vertical(id='watch_rows')
                with Vertical(id='global_panel'):
                    yield Static('GLOBALS · hover history / click to copy', id='global_heading')
                    yield Static('Globals appear when GDB stops.', id='global_status')
                    with VerticalScroll(id='global_scroll'):
                        yield Vertical(id='global_rows')
                for key, title in [('stack', 'STACK FRAMES & STACK WATCH'),
                                   ('instruction', 'CODE & INSTRUCTIONS'), ('energy', 'ENERGY ESTIMATE')]:
                    with VerticalScroll(id=f'{key}_panel', classes='resource-panel'):
                        yield Static(title, classes='resource-title')
                        yield Static('Waiting for resource observations…', id=f'{key}_content',
                                     classes='resource-content', markup=False)
                with VerticalScroll(id='stack_graph_panel', classes='graph-panel'):
                    yield Static('STACK MAP & RAW CONTENTS', classes='resource-title')
                    yield StackMap(id='stack_graph_content')
                with VerticalScroll(id='run_graph_panel', classes='graph-panel'):
                    yield Static('RUN STATISTICS & PARETO RANKING', classes='resource-title')
                    yield RunRanking(id='run_graph_content')
                with VerticalScroll(id='energy_graph_panel', classes='graph-panel'):
                    yield Static('ENERGY RANKING · ESTIMATE', classes='resource-title')
                    yield RunRanking(energy=True, id='energy_graph_content')
        yield Static('s:into  n:next  i:instruction  Space:repeat  Ctrl+P:views', id='stepbar')
        with Vertical(id='console_panel'):
            yield RichLog(id='console', highlight=True, markup=False)
            yield Input(id='gdb_input', placeholder=': GDB console command (paste and press Enter)')
        yield Footer()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand('Views', 'Choose visible panes with checkboxes',
                            self.action_choose_views)
        yield SystemCommand('Energy model', 'Configure µA/MHz, MIPS/MHz and voltage assumptions',
                            lambda: self.push_screen(EnergyScreen()))
        for key, (label, _) in VIEWS.items():
            enabled = key in self.visible_views
            yield SystemCommand(
                f'{"✓" if enabled else "☐"} View: {label}',
                'Left/Right: toggle view; palette stays open',
                partial(self.action_toggle_view, key))

    def action_command_palette(self) -> None:
        if self.use_command_palette and not ViewCommandPalette.is_open(self):
            self.push_screen(ViewCommandPalette(id='--command-palette'))

    def action_choose_views(self) -> None:
        self.push_screen(ViewsScreen(self.visible_views))

    def action_toggle_view(self, key: str) -> None:
        self.set_visible_views(self.visible_views ^ {key})

    def set_visible_views(self, enabled: set[str]) -> None:
        self.visible_views = enabled & VIEWS.keys()
        # Look in the base screen even while the checkbox dialog is active.
        base = self.default_screen
        for key, (_, selector) in VIEWS.items():
            base.query_one(selector).display = key in self.visible_views
        source = 'source' in self.visible_views
        right = bool(self.visible_views - {'source', 'console'})
        base.query_one('#left').display = source
        base.query_one('#right').display = right
        base.query_one('#left').styles.width = '63%' if right else '100%'
        base.query_one('#right').styles.width = '37%' if source else '100%'
        base.query_one('#workbench').display = source or right

    def on_mount(self) -> None:
        self.query_one('#scope', ScopeTree).return_tooltip = self._return_tooltip
        self._show_resources()
        try:
            self.transport.start()
            self._send(f'-file-exec-and-symbols "{self._quoted(self.elf)}"', 'load')
            self.set_interval(0.05, self._poll)
        except OSError as exc:
            self._log(f'Failed to launch GDB: {exc}')
            self.status = 'ERROR'

    def on_unmount(self) -> None:
        if self._trace is not None:
            self._trace.close()
        self.transport.close()

    @staticmethod
    def _quoted(s: str) -> str:
        return s.replace('\\', '\\\\').replace('"', '\\"')

    def _log(self, line: str) -> None:
        self._log_lines.append(line.rstrip())
        self.query_one('#console', RichLog).write(line.rstrip())

    def _trace_record(self, kind: str, **fields: object) -> None:
        if self._trace is None:
            return
        try:
            self._trace.record(kind, **fields)
        except OSError as exc:
            if not self._trace_error_reported:
                self._trace_error_reported = True
                self._log(f'JSONL trace write failed: {exc}')
            try:
                self._trace.close()
            except OSError:
                pass
            self._trace = None

    def _return_tooltip(self, key: ReturnKey) -> str:
        series = self._returns.series.get(key)
        return series.tooltip if series is not None else ''

    def _record_probe_return(self, data: dict) -> None:
        # The probe may fire while continuing between visible stops. Anchor to
        # the preceding stop and label that provenance explicitly in JSONL.
        event = ReturnObservation(data['caller'], data['callee_display'],
                                  data['value'], self.model.stop)
        thread, callee = data['thread'], data['callee']
        self._probe_returns_since_command.add((thread, event.caller_function, callee))
        series = self._returns.observe(event, thread=thread, callee_function=callee)
        self._trace_record('return', stop=self.model.stop, thread=thread,
                           caller=series.key.caller, callee=callee,
                           callee_display=event.callee_display, value=event.value,
                           origin='gdb-python-finish-breakpoint',
                           stop_anchor='preceding-debugger-stop')
        self._show_scope()

    def _copy_return_history(self, key: ReturnKey) -> None:
        series = self._returns.series.get(key)
        if series is None:
            return
        if self._trace is not None:
            try:
                self._copy(self._trace.returns_tsv(
                    thread=key.thread, caller=key.caller, callee=key.callee),
                    f'all {series.count} observed returns for {key.callee} → {key.caller}')
                return
            except OSError as exc:
                self._log(f'Could not read JSONL return history: {exc}')
        # Fallback if file creation was denied; explicitly partial beyond 10.
        header = 'stop\tcaller\tcallee\targs\tvalue'
        rows = [
            f'{event.stop}\t{key.caller}\t{key.callee}\t{event.callee_display}\t'
            f'{event.value if event.value is not None else ""}'
            for event in series.recent
        ]
        self._copy(header + '\n' + '\n'.join(rows),
                   f'last {len(rows)} in-memory returns (file unavailable)')

    def _send(self, command: str, purpose: str, level: int | None = None) -> int | None:
        try:
            token = self.transport.send(command)
            self.pending[token] = (purpose, level)
            if purpose in ('execution', 'console', 'break_add', 'break_del'):
                self._trace_record('command', stop=self.model.stop,
                                   gdb_command=command, purpose=purpose)
            return token
        except (OSError, BrokenPipeError, AssertionError) as exc:
            self.status = 'ERROR'
            self._log(f'GDB send failed: {exc}')

    def _poll(self) -> None:
        for _ in range(300):
            try:
                record = self.transport.events.get_nowait()
            except queue.Empty:
                break
            self._handle(record)
        if self.theme != self._rendered_theme:
            # Textual repaints CSS variables automatically; Rich Text needs a
            # fresh rendering because its styles are snapshots, not CSS.
            self._rendered_theme = self.theme
            self._show_source()
            self._show_watches()
            self._show_resources()
        if time.monotonic() - self._resource_poll_time >= .25:
            self._resource_poll_time = time.monotonic()
            self._poll_instruction_profile()

    def set_energy_model(self, model: EnergyModel) -> None:
        self.energy_model = model
        self._trace_record('energy_model', ua_per_mhz=model.ua_per_mhz,
                           mips_per_mhz=model.mips_per_mhz, voltage=model.voltage,
                           origin='user-configured-active-core-model')
        self._show_resources()

    def _show_resources(self) -> None:
        texts = resource_text(self.stack_profile, self.catalog, self.instruction_counts,
                              self.selected_level, self.model.stop, self.energy_model,
                              self._count_status)
        for key, text in zip(('stack', 'instruction', 'energy'), texts):
            if key == 'stack' and self._stack_error:
                text += '\nGDB stack snapshot unavailable: ' + self._stack_error
            self.query_one(f'#{key}_content', Static).update(text)
        self.query_one('#stack_graph_content', StackMap).set_sample(
            self.stack_profile.sample, self.selected_level, self.model.stop)
        current, selected = current_bodies(self.stack_profile, self.catalog,
                                           self.model.stop, self.selected_level)
        for key in ('run', 'energy'):
            self.query_one(f'#{key}_graph_content', RunRanking).set_data(
                self.catalog, self.instruction_counts, self.energy_model, current, selected,
                self._count_status, self.status == 'HALTED')

    def _poll_instruction_profile(self) -> None:
        if self.instruction_path is None:
            return
        previous_status = self._count_status
        changed = False
        try:
            if self.catalog is None:
                raise ValueError('ELF unavailable: ' + self._catalog_error)
            data = json.loads(self.instruction_path.read_text())
            changed = self.instruction_counts.update(data, self.catalog)
            self._count_status = ''
            if changed:
                self._trace_record('instruction_profile', elf_sha256=self.catalog.sha256,
                                   run=self.instruction_counts.run, profile_seq=self.instruction_counts.seq,
                                   total=self.instruction_counts.total, unknown=self.instruction_counts.unknown,
                                   complete=self.instruction_counts.complete,
                                   functions=dict(self.instruction_counts.by_function),
                                   entry_hits=dict(self.instruction_counts.entry_hits),
                                   origin='qemu-plugin-instruction-dispatch')
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self._count_status = f'Instruction profile unavailable: {exc}'
        if changed or previous_status != self._count_status:
            self._show_resources()

    def _request_stack(self) -> None:
        if self._stack_ready and self.status == 'HALTED':
            code = f'python dbg3k_stack_snapshot({self.model.stop})'
            self._send(f'-interpreter-exec console "{code}"', 'stack_snapshot')

    def _handle(self, record: Record) -> None:
        if record.kind in ('~', '@', '&'):
            message = str(record.payload).strip()
            stack = decode_stack(message) if record.kind == '~' else None
            if stack is not None:
                if (self.status == 'HALTED' and stack['stop'] == self.model.stop and
                        stack['thread'] == self._active_thread):
                    self.stack_profile.update(stack, self.catalog)
                    self._stack_error = ''
                    self._trace_record('stack_sample', stop=stack['stop'], thread=stack['thread'],
                                       registers=stack['registers'], frames=stack['frames'],
                                       truncated=stack.get('truncated', False),
                                       memory=stack.get('memory'), memory_error=stack.get('memory_error'),
                                       origin='gdb-unwound-registers')
                    self._show_resources()
                return
            data = probe_return(message) if record.kind == '~' else None
            if data is not None:
                self._record_probe_return(data)
                return
            if message:
                self._log(message)
            return
        if record.kind == 'error':
            self.status = 'ERROR'
            self._log(f'{record.cls}: {record.payload}')
            return
        if record.kind == '*' and record.cls == 'running':
            self.status = 'RUNNING'
            self._show_status()
            self._show_resources()
            return
        if record.kind == '*' and record.cls == 'stopped':
            old_top = self.model.frames[0] if self.model.frames else None
            payload = record.payload if isinstance(record.payload, dict) else {}
            next_stop = self.model.stop + 1
            self._last_return = observed_return(payload, old_top, next_stop)
            thread = payload.get('thread-id')
            self._trace_record('stop', stop=next_stop, reason=payload.get('reason'),
                               thread=thread, frame=payload.get('frame'),
                               origin='gdb-mi-stopped')
            if self._last_return is not None:
                thread_id = str(thread or self._active_thread or 'unknown')
                callee_name = old_top.function if old_top is not None else None
                edge = (thread_id, self._last_return.caller_function, callee_name)
                if edge not in self._probe_returns_since_command:
                    series = self._returns.observe(self._last_return, thread=thread_id,
                                                   callee_function=callee_name)
                    self._trace_record(
                        'return', stop=next_stop, thread=thread_id,
                        caller=series.key.caller, callee=series.key.callee,
                        callee_display=self._last_return.callee_display,
                        value=self._last_return.value, caller_frame=payload.get('frame'),
                        origin='gdb-mi-function-finished')
            self._probe_returns_since_command.clear()
            self._show_scope()
            if thread is not None and str(thread).isdecimal():
                self._active_thread = str(thread)
            self.status = 'HALTED'
            if self._connected:
                if self._active_thread is None:
                    self._send('-thread-info', 'thread_info')
                else:
                    self._refresh()
            return
        if record.kind != '^':
            return
        purpose, level = self.pending.pop(record.token, ('unknown', None))
        global_result_stop = self._global_result_stop.pop(record.token, None)
        argument_result_stop = self._argument_result_stop.pop(record.token, None)
        if record.cls == 'error':
            self._log(f'{purpose}: {record.payload.get("msg", "GDB error")}')
            self._trace_record('gdb_error', stop=self.model.stop, purpose=purpose,
                               message=record.payload.get('msg', 'GDB error'))
            if purpose == 'return_observer':
                self._log('Automatic returns unavailable (GDB Python required); use o / finish to observe returns.')
            if purpose in ('stack_observer', 'stack_snapshot'):
                self._stack_error = str(record.payload.get('msg', 'GDB Python stack query failed'))
                self._show_resources()
            if purpose == 'vars':
                self._watches_error = str(record.payload.get('msg', 'GDB rejected locals request'))
                self._show_watches()
            if purpose == 'globals_discover':
                self._globals_discovered = True
                self._globals_error = str(record.payload.get('msg', 'GDB rejected global symbol query'))
                self._show_watches()
            if purpose == 'global_value' and level is not None and global_result_stop == self.model.stop:
                symbol = self._globals[level]
                self.model.set_global_value(symbol.key, symbol.label, symbol.name,
                                            '<unavailable>', symbol.type_name)
                self._finish_global_display()
            if purpose == 'execution':
                self.status = 'HALTED'
                self._show_status()
            if purpose in ('load', 'connect'):
                self.status = 'ERROR'
            return
        if purpose == 'load':
            self._send(f'-target-select remote {self.remote}', 'connect')
        elif purpose == 'connect':
            self._connected = True
            self.status = 'HALTED'
            self._log(f'Connected to {self.remote}; ELF: {self.elf}')
            if self._trace is None:
                try:
                    self._trace = TraceWriter(self.elf, self.remote, self.history_dir)
                    self._log(f'JSONL recording: {self._trace.path}')
                except OSError as exc:
                    self._log(f'JSONL recording unavailable: {exc}')
            self._send(f'-symbol-info-variables --max-results {MAX_GLOBAL_WATCHES + 1}',
                       'globals_discover')
            self._send('-thread-info', 'thread_info')
            helper = str(Path(__file__).with_name('gdb_returns.py').resolve())
            code = f'python exec(compile(open({helper!r}).read(), {helper!r}, "exec"))'
            self._send(f'-interpreter-exec console "{self._quoted(code)}"', 'return_observer')
            helper = str(Path(__file__).with_name('gdb_resources.py').resolve())
            code = f'python exec(compile(open({helper!r}).read(), {helper!r}, "exec"))'
            self._send(f'-interpreter-exec console "{self._quoted(code)}"', 'stack_observer')
            if self.energy_model:
                self.set_energy_model(self.energy_model)
        elif purpose == 'stack_observer':
            self._stack_ready = True
            self._request_stack()
        elif purpose == 'return_observer':
            self._log('Automatic returns: tracking debug-visible functions encountered at stops.')
        elif purpose == 'thread_info':
            self._active_thread = select_thread_id(record.payload) or self._active_thread
            if self._active_thread is None:
                self._log('GDB did not report a current thread; frame-local watches unavailable.')
            self._refresh()
        elif purpose == 'frames':
            raw = record.payload.get('stack', [])
            frames = [Frame.from_mi(item['frame']) for item in raw if isinstance(item, dict) and 'frame' in item]
            self.model.set_frames(frames)
            self._show_resources()
            self._trace_record('frames', stop=self.model.stop,
                               thread=self._active_thread, frames=[
                                   dict(level=f.level, function=f.function,
                                        filename=f.filename, line=f.line, pc=f.pc)
                                   for f in frames])
            self._show_source(reveal=True, follow_pc=True)
            self._show_scope()
            self._watches_error = ''
            self._watch_results = {}
            self._show_watches()
            if self._active_thread is None:
                self._watches_error = 'No active GDB thread ID; cannot read per-frame locals'
                self._show_watches()
            else:
                for frame in frames[:12]:
                    self._send(locals_request(self._active_thread, frame.level),
                               'vars', frame.level)
                if frames:
                    last_level = max(frame.level for frame in frames[:12])
                    token = self._send(
                        f'-stack-list-arguments --thread {self._active_thread} '
                        f'--all-values 0 {last_level}', 'args')
                    if token is not None:
                        self._argument_result_stop[token] = self.model.stop
            self._refresh_globals()
        elif purpose == 'globals_discover':
            self._globals, self._globals_truncated = discover_globals(record.payload)
            self._globals_discovered = True
            self._show_watches()
            self._refresh_globals()
        elif purpose == 'global_value' and level is not None:
            if global_result_stop == self.model.stop:
                symbol = self._globals[level]
                value = str(record.payload.get('value', '<unavailable>'))
                self.model.set_global_value(
                    symbol.key, symbol.label, symbol.name, value, symbol.type_name)
                self._trace_record('global_value', stop=self.model.stop,
                                   thread=self._active_thread,
                                   symbol=symbol.key, label=symbol.label, value=value)
                self._finish_global_display()
        elif purpose == 'args':
            if argument_result_stop == self.model.stop:
                args = parse_stack_arguments(record.payload)
                self.model.set_frame_arguments(args)
                self._trace_record('frame_arguments', stop=self.model.stop,
                                   thread=self._active_thread, arguments={
                                       str(level): list(values)
                                       for level, values in args.items()})
                self._show_scope()
                self._show_watches()
        elif purpose == 'vars' and level is not None:
            variables = record.payload.get('variables', [])
            if not isinstance(variables, list):
                self._watches_error = f'Unexpected locals response for frame {level}'
                self._log(self._watches_error)
                self._show_watches()
                return
            self._watch_results[level] = len(variables)
            self.model.set_variables(level, [v for v in variables if isinstance(v, dict)])
            self._trace_record('locals', stop=self.model.stop,
                               thread=self._active_thread, frame_level=level,
                               variables=variables)
            self._show_scope()
            self._show_watches()
        elif purpose == 'break_add':
            bp = record.payload.get('bkpt', {})
            if isinstance(bp, dict):
                file, line = self._break_pending or (self.nav_file, self.nav_line)
                self.breaks[(file, line)] = str(bp.get('number', ''))
                self._break_pending = None
                self._show_source()
        elif purpose == 'break_del':
            self._show_source()

    def _refresh_globals(self) -> None:
        """Evaluate the discovered data symbols once per debugger stop."""
        stop = self.model.stop
        if not self._globals_discovered or not self._globals or stop <= 0:
            return
        if self.status != 'HALTED' or self._global_last_requested_stop == stop:
            return
        self._global_last_requested_stop = stop
        for index, symbol in enumerate(self._globals):
            # Quote as a GDB/MI argument; the inner expression still uses
            # GDB's 'file.c'::symbol disambiguation for static variables.
            cmd = f'-data-evaluate-expression "{self._quoted(symbol.expression)}"'
            token = self._send(cmd, 'global_value', index)
            if token is not None:
                self._global_result_stop[token] = stop

    def _finish_global_display(self) -> None:
        if not any(stop == self.model.stop for stop in self._global_result_stop.values()):
            self._show_scope()
            self._show_watches()

    def _refresh(self) -> None:
        self.model.begin_stop()
        self.selected_level = 0
        frame_command = (f'-stack-list-frames --thread {self._active_thread}'
                         if self._active_thread else '-stack-list-frames')
        self._send(frame_command, 'frames')
        self._request_stack()
        self._show_status()

    def _show_status(self) -> None:
        self.query_one('#stepbar', Static).update(
            f'[{self.status}]  s:into  n:next  i:instr  I:over-instr  Space:repeat  '
            f'j/k:cursor  b:break  r:until  c:run  y:copy  W:watches  H:history  L:log  ::GDB  · Stop #{self.model.stop}'
        )

    @staticmethod
    def _contrast_ink(background: str, *, dark: bool) -> str:
        """Return legible Rich foreground color for a theme highlight.

        Textual themes may leave background/surface unset. Never interpolate
        such optional theme fields into Rich style strings.
        """
        if background.startswith('#') and len(background) in (4, 7):
            try:
                digits = background[1:]
                if len(digits) == 3:
                    digits = ''.join(c * 2 for c in digits)
                rgb = [int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4)]
                linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                          for c in rgb]
                luminance = sum(c * w for c, w in zip(linear, (0.2126, 0.7152, 0.0722)))
                return 'black' if luminance > 0.179 else 'white'
            except ValueError:
                pass
        return 'white' if dark else 'black'

    def _show_source(self, *, reveal: bool = False, follow_pc: bool = False) -> None:
        """Display every source line, scrolling without executing the firmware."""
        if not self.model.frames:
            return
        frame = next((f for f in self.model.frames if f.level == self.selected_level),
                     self.model.frames[0])
        changed_file = not self.nav_file or self.nav_file != frame.filename
        if changed_file:
            self.nav_file = frame.filename
            self.nav_line = frame.line or 1
        elif follow_pc:
            self.nav_line = frame.line or self.nav_line
        text = Text()
        theme = self.current_theme
        path = Path(self.nav_file)
        if not path.is_file():
            self._source_lines = 0
            text.append(f'Source unavailable: {self.nav_file}\nPC {frame.pc}\n')
            text.append('Check GDB source paths or rebuild with -g3.', style=theme.warning)
            self.query_one('#source', Static).update(text)
            return
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError as exc:
            self._source_lines = 0
            self.query_one('#source', Static).update(f'Cannot read {path}: {exc}')
            return
        if not lines:
            self._source_lines = 0
            self.query_one('#source', Static).update('Empty source file')
            return
        self._source_lines = len(lines)
        self.nav_line = max(1, min(len(lines), self.nav_line))
        text.append(f'{path.name} · PC {frame.pc} · line {frame.line}\n\n',
                    style=f'bold {theme.primary}')
        for i, source in enumerate(lines, start=1):
            execution = frame.filename == self.nav_file and i == frame.line
            selected = i == self.nav_line
            has_bp = (self.nav_file, i) in self.breaks
            mark = '▶' if execution else ('▸' if selected else ' ')
            bpmark = '●' if has_bp else ' '
            # Theme.background may be None (including textual-dark). A None
            # interpolated into a Rich style causes MissingStyle on startup.
            # Use the actual execution highlight color to select readable ink.
            highlight = theme.success or '#4EBF71'
            style = (f'bold {self._contrast_ink(highlight, dark=theme.dark)} on {highlight}'
                     if execution else
                     f'bold {theme.accent or theme.primary or "#7dd3fc"}' if selected
                     else (theme.foreground or 'white'))
            text.append(f'{mark}{bpmark}{i:4} │ {source}\n', style=style)
        self.query_one('#source', Static).update(text)
        if reveal or changed_file:
            self.call_after_refresh(self._reveal_source_cursor)

    def _reveal_source_cursor(self) -> None:
        pane = self.query_one('#source_scroll', VerticalScroll)
        y = max(0, self.nav_line + 1 - max(3, pane.size.height // 3))
        pane.scroll_to(y=y, animate=False)

    def _show_scope(self) -> None:
        """Keep observed returns visible even after their caller exits.

        The previous implementation removed *all* root children on every MI
        frame/locals/global reply, then attached returns only beneath frames
        still in the live call stack. When foo returned to main, bar's latest
        return row flashed once and disappeared. Scope history is not scope
        lifetime: the return branch therefore has stable node identities.
        """
        tree = self.query_one('#scope', ScopeTree)
        if self._return_branch is None:
            self._return_branch = tree.root.add('↩ observed returns (0)')
            self._stack_branch = tree.root.add('▶ active call stack')
            self._return_branch.expand()
            self._stack_branch.expand()

        # Return nodes are created ONCE per (thread, caller, callee) edge.
        # Keeping them in the tree preserves hover and selection across rapid
        # GDB frame, argument and variable result callbacks.
        self._return_branch.set_label(
            f'↩ observed returns ({len(self._returns.series)})')
        for key, series in sorted(
                self._returns.series.items(),
                key=lambda item: (item[0].thread, item[0].caller, item[0].callee)):
            caller_key = (key.thread, key.caller)
            caller = self._return_caller_nodes.get(caller_key)
            if caller is None:
                caller = self._return_branch.add(
                    f'{key.caller}()  [thread {key.thread}]')
                self._return_caller_nodes[caller_key] = caller
                caller.expand()
            node = self._return_edge_nodes.get(key)
            if node is None:
                node = caller.add_leaf(Text(series.label, style='bold'),
                                       data=key)
                self._return_edge_nodes[key] = node
            else:
                node.set_label(Text(series.label, style='bold'))

        self._stack_branch.remove_children()
        parent = self._stack_branch
        for frame in reversed(self.model.frames):
            node = parent.add(
                f'{display_call(frame)} [{frame.filename.rsplit("/", 1)[-1]}:{frame.line}]',
                data=frame.level,
            )
            for watch in sorted(self.model.active_watches(frame.level), key=lambda w: w.name):
                node.add_leaf(f'{watch.name} = {watch.value}' + (' ◆' if watch.changed else ''))
            for series in self._returns.for_caller(
                    thread=self._active_thread or 'unknown', caller=frame.function):
                node.add_leaf(Text(series.label, style='bold'), data=series.key)
            node.expand()
            parent = node

        tree.root.expand()

    def _sync_watch_rows(self, watches: list[Watch], selector: str,
                         rows: dict[str, WatchRow]) -> None:
        container = self.query_one(selector, Vertical)
        current: set[str] = set()
        for watch in watches:
            key = (f'global:{watch.symbol_id}' if watch.frame_level == -1 else
                   f'local:{watch.frame_level}:{watch.generation}:{watch.symbol_id}')
            current.add(key)
            row = rows.get(key)
            if row is None:
                row = WatchRow(watch)
                rows[key] = row
                container.mount(row)
            else:
                row.set_watch(watch)
        for key in list(rows):
            if key not in current:
                rows.pop(key).remove()

    def _show_watches(self) -> None:
        # Immediate means the executing frame, independent of source browsing.
        watches = sorted(self.model.active_watches(0), key=lambda w: w.label)
        self._sync_watch_rows(watches, '#watch_rows', self._watch_rows)
        frame = next((frame for frame in self.model.frames if frame.level == 0), None)
        self.query_one('#watch_heading', Static).update(
            f'IMMEDIATE SCOPE · {display_call(frame) if frame else "no active frame"}')
        warning = ''
        if self._watches_error:
            warning = f'GDB locals: {self._watches_error}'
        elif frame and 0 not in self._watch_results:
            warning = 'Loading debugger-stop variables…'
        elif not watches:
            warning = 'No variables currently visible at this PC'
        self.query_one('#watch_status', Static).update(warning)
        globals_now = sorted(self.model.active_globals(), key=lambda w: w.label)
        self._sync_watch_rows(globals_now, '#global_rows', self._global_rows)
        warning = ''
        if self._globals_error:
            warning = f'Global discovery: {self._globals_error}'
        elif self._globals_truncated:
            warning = f'Globals limited to {MAX_GLOBAL_WATCHES}; selection planned'
        elif not self._globals_discovered:
            warning = 'Discovering globals…'
        elif not globals_now:
            warning = 'No debug globals available'
        self.query_one('#global_status', Static).update(warning)

    def _step(self, command: str) -> None:
        if self.status != 'HALTED':
            return
        self._probe_returns_since_command.clear()
        self.last_step = command
        self.status = 'COMMANDING'
        self._show_status()
        self._send(command, 'execution')

    def action_step(self) -> None: self._step('-exec-step')
    def action_next(self) -> None: self._step('-exec-next')
    def action_instruction(self) -> None: self._step('-exec-step-instruction')
    def action_next_instruction(self) -> None: self._step('-exec-next-instruction')
    def action_finish(self) -> None: self._step('-exec-finish')
    def action_repeat(self) -> None: self._step(self.last_step)

    def action_continue_run(self) -> None:
        if self.status == 'HALTED':
            self._probe_returns_since_command.clear()
            self.status = 'COMMANDING'
            self._show_status()
            self._send('-exec-continue', 'execution')

    def action_cursor_down(self) -> None:
        self.nav_line += 1
        self._show_source(reveal=True)

    def action_cursor_up(self) -> None:
        self.nav_line = max(1, self.nav_line - 1)
        self._show_source(reveal=True)

    def action_page_down_source(self) -> None:
        self.nav_line += max(5, self.query_one('#source_scroll', VerticalScroll).size.height - 4)
        self._show_source(reveal=True)

    def action_page_up_source(self) -> None:
        self.nav_line -= max(5, self.query_one('#source_scroll', VerticalScroll).size.height - 4)
        self._show_source(reveal=True)

    def action_source_home(self) -> None:
        self.nav_line = 1
        self._show_source(reveal=True)

    def action_source_end(self) -> None:
        self.nav_line = max(1, self._source_lines)
        self._show_source(reveal=True)

    def action_breakpoint(self) -> None:
        if self.status != 'HALTED' or not self.nav_file:
            return
        key = self.nav_file, self.nav_line
        if key in self.breaks:
            number = self.breaks.pop(key)
            self._send(f'-break-delete {number}', 'break_del')
        else:
            self._break_pending = key
            self._send(f'-break-insert "{self._quoted(self.nav_file)}:{self.nav_line}"',
                       'break_add')

    def action_run_to_cursor(self) -> None:
        if self.status == 'HALTED' and self.nav_file:
            self._probe_returns_since_command.clear()
            self.status = 'COMMANDING'
            self._show_status()
            self._send(f'-exec-until "{self._quoted(self.nav_file)}:{self.nav_line}"',
                       'execution')

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, ReturnKey):
            self._copy_return_history(event.node.data)
            return
        if isinstance(event.node.data, int):
            self.selected_level = event.node.data
            self.nav_file = ''  # selecting source never executes firmware
            self._show_source(reveal=True, follow_pc=True)
            self._show_resources()

    def _copy(self, content: str, description: str) -> None:
        if not content:
            self.notify(f'Nothing to copy: {description}', severity='warning')
            return
        self.copy_to_clipboard(content)
        self.notify(f'Copied {description} to clipboard')

    def action_copy_line(self) -> None:
        """Copy source line, or selected scope if the tree has focus."""
        tree = self.query_one('#scope', Tree)
        if self.focused is tree and tree.cursor_node is not None:
            self._copy(str(tree.cursor_node.label), 'scope node')
            return
        path = Path(self.nav_file)
        if not path.is_file():
            self.notify('No source file available', severity='warning')
            return
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        if 1 <= self.nav_line <= len(lines):
            self._copy(lines[self.nav_line - 1], 'source line')

    def action_copy_source(self) -> None:
        path = Path(self.nav_file)
        if path.is_file():
            self._copy(path.read_text(encoding='utf-8', errors='replace'), 'source file')
        else:
            self.notify('No source file available', severity='warning')

    def action_copy_watches(self) -> None:
        watches = (sorted(self.model.active_globals(), key=lambda w: w.label)
                   + sorted(self.model.active_watches(), key=lambda w: (w.frame_level, w.label)))
        self._copy('\n'.join(f'{w.label}\t{w.value}\t{w.trend}' for w in watches),
                   'watch values')

    def action_copy_history(self) -> None:
        """Copy every retained sample, including out-of-scope local invocations."""
        data = self.model.export_history_tsv()
        if data.strip() == 'stop\tscope\tvalue':
            self.notify('No watch history recorded yet', severity='warning')
            return
        self._copy(data, 'full retained watch history (TSV)')

    def action_copy_log(self) -> None:
        self._copy('\n'.join(self._log_lines), 'debugger log')

    def action_focus_console(self) -> None:
        self.set_visible_views(self.visible_views | {'console'})
        self.query_one('#gdb_input', Input).focus()

    def action_focus_source(self) -> None:
        self.set_focus(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'gdb_input':
            return
        command = event.value.strip()
        if command:
            self._probe_returns_since_command.clear()
            self._log(f'(gdb) {command}')
            self._send(f'-interpreter-exec console "{self._quoted(command)}"', 'console')
            event.input.value = ''
        self.set_focus(None)

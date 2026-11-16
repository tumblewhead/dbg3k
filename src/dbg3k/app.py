"""Textual frontend: source, scope tree, sampled watches, and single-key stepping."""
from __future__ import annotations

from pathlib import Path
from collections import deque
import queue
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, RichLog, Static, Tree

from .commands import select_thread_id, locals_request

from .backend import GdbTransport
from .mi import Record
from .model import Frame, ScopeModel

class DebuggerApp(App):
    TITLE = 'dbg3k'
    SUB_TITLE = 'Scope-first Cortex-M debugger · alpha'
    CSS = """
    Screen { background: #101820; color: #dae7ee; }
    Header { background: #172b38; color: #81d9f7; }
    Footer { background: #172b38; }
    #workbench { height: 1fr; }
    #left { width: 63%; }
    #right { width: 37%; }
    #source_scroll { height: 1fr; border: round #2d596e; overflow-y: auto; overflow-x: auto; }
    #source { height: auto; padding: 1 2; }
    #stepbar { height: 3; background: #172b38; color: #7de5cb; padding: 0 1; }
    #scope { height: 45%; border: round #2d596e; background: #192733; }
    #watches { height: 1fr; border: round #2d596e; background: #192733; padding: 1; }
    #console_panel { height: 10; border: round #2d596e; background: #192733; }
    #console { height: 1fr; background: #192733; }
    #gdb_input { height: 3; background: #223746; }
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
        Binding('L', 'copy_log', 'Copy log', show=False),
        Binding('f2,colon', 'focus_console', 'GDB command'),
        Binding('escape', 'focus_source', 'Leave command', show=False),
        Binding('q', 'quit', 'Quit'),
    ]

    def __init__(self, elf: str, gdb: str, remote: str) -> None:
        super().__init__()
        self.elf, self.remote = elf, remote
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
        self._connected = False
        self._log_lines: deque[str] = deque(maxlen=500)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id='workbench'):
            with Vertical(id='left'):
                with VerticalScroll(id='source_scroll'):
                    yield Static('Connecting to GDB...', id='source')
                yield Static('s:into  n:next  i:instruction  Space:repeat  j/k:cursor  b:break', id='stepbar')
            with Vertical(id='right'):
                yield Tree('cpu0 / observed call stack', id='scope')
                yield Static('Watches appear when GDB stops.', id='watches')
        with Vertical(id='console_panel'):
            yield RichLog(id='console', highlight=True, markup=False)
            yield Input(id='gdb_input', placeholder=': GDB console command (paste and press Enter)')
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.transport.start()
            self._send(f'-file-exec-and-symbols "{self._quoted(self.elf)}"', 'load')
            self.set_interval(0.05, self._poll)
        except OSError as exc:
            self._log(f'Failed to launch GDB: {exc}')
            self.status = 'ERROR'

    def on_unmount(self) -> None:
        self.transport.close()

    @staticmethod
    def _quoted(s: str) -> str:
        return s.replace('\\', '\\\\').replace('"', '\\"')

    def _log(self, line: str) -> None:
        self._log_lines.append(line.rstrip())
        self.query_one('#console', RichLog).write(line.rstrip())

    def _send(self, command: str, purpose: str, level: int | None = None) -> None:
        try:
            token = self.transport.send(command)
            self.pending[token] = (purpose, level)
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

    def _handle(self, record: Record) -> None:
        if record.kind in ('~', '@', '&'):
            message = str(record.payload).strip()
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
            return
        if record.kind == '*' and record.cls == 'stopped':
            thread = record.payload.get('thread-id') if isinstance(record.payload, dict) else None
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
        if record.cls == 'error':
            self._log(f'{purpose}: {record.payload.get("msg", "GDB error")}')
            if purpose == 'vars':
                self._watches_error = str(record.payload.get('msg', 'GDB rejected locals request'))
                self._show_watches()
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
            self._send('-thread-info', 'thread_info')
        elif purpose == 'thread_info':
            self._active_thread = select_thread_id(record.payload) or self._active_thread
            if self._active_thread is None:
                self._log('GDB did not report a current thread; frame-local watches unavailable.')
            self._refresh()
        elif purpose == 'frames':
            raw = record.payload.get('stack', [])
            frames = [Frame.from_mi(item['frame']) for item in raw if isinstance(item, dict) and 'frame' in item]
            self.model.set_frames(frames)
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
        elif purpose == 'vars' and level is not None:
            variables = record.payload.get('variables', [])
            if not isinstance(variables, list):
                self._watches_error = f'Unexpected locals response for frame {level}'
                self._log(self._watches_error)
                self._show_watches()
                return
            self._watch_results[level] = len(variables)
            self.model.set_variables(level, [v for v in variables if isinstance(v, dict)])
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

    def _refresh(self) -> None:
        self.model.begin_stop()
        self.selected_level = 0
        frame_command = (f'-stack-list-frames --thread {self._active_thread}'
                         if self._active_thread else '-stack-list-frames')
        self._send(frame_command, 'frames')
        self._show_status()

    def _show_status(self) -> None:
        self.query_one('#stepbar', Static).update(
            f'[{self.status}]  s:into  n:next  i:instr  I:over-instr  Space:repeat  '
            f'j/k:cursor  b:break  r:until  c:run  y:copy  W:watches  L:log  ::GDB  · Stop #{self.model.stop}'
        )

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
        path = Path(self.nav_file)
        if not path.is_file():
            self._source_lines = 0
            text.append(f'Source unavailable: {self.nav_file}\nPC {frame.pc}\n')
            text.append('Check GDB source paths or rebuild with -g3.', style='yellow')
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
                    style='bold #81d9f7')
        for i, source in enumerate(lines, start=1):
            execution = frame.filename == self.nav_file and i == frame.line
            selected = i == self.nav_line
            has_bp = (self.nav_file, i) in self.breaks
            mark = '▶' if execution else ('▸' if selected else ' ')
            bpmark = '●' if has_bp else ' '
            style = ('bold black on #79c8b6' if execution else
                     'bold #7dd3fc' if selected else '#d7e4ee')
            text.append(f'{mark}{bpmark}{i:4} │ {source}\n', style=style)
        self.query_one('#source', Static).update(text)
        if reveal or changed_file:
            self.call_after_refresh(self._reveal_source_cursor)

    def _reveal_source_cursor(self) -> None:
        pane = self.query_one('#source_scroll', VerticalScroll)
        y = max(0, self.nav_line + 1 - max(3, pane.size.height // 3))
        pane.scroll_to(y=y, animate=False)

    def _show_scope(self) -> None:
        tree = self.query_one('#scope', Tree)
        tree.root.remove_children()
        parent = tree.root
        for frame in reversed(self.model.frames):
            node = parent.add(
                f'{frame.function}() [{frame.filename.rsplit("/", 1)[-1]}:{frame.line}]',
                data=frame.level,
            )
            for watch in sorted(self.model.active_watches(frame.level), key=lambda w: w.name):
                node.add_leaf(f'{watch.name} = {watch.value}' + (' ●' if watch.changed else ''))
            node.expand()
            parent = node
        tree.root.expand()

    def _show_watches(self) -> None:
        table = Table(title='Watches · sampled at debugger stops', show_edge=False, box=None, expand=True)
        table.add_column('scope.local', style='#a5cdeb', no_wrap=True)
        table.add_column('Value', style='#dae7ee')
        table.add_column('Δ', justify='center')
        table.add_column('History', style='#79c8b6')
        watches = sorted(self.model.active_watches(), key=lambda w: (w.frame_level, w.label))
        for watch in watches:
            table.add_row(watch.label, watch.value, '●' if watch.changed else '', watch.trend)
        if self._watches_error:
            self.query_one('#watches', Static).update(
                f'[GDB locals error] {self._watches_error}\nSee GDB output below.')
        elif watches:
            self.query_one('#watches', Static).update(table)
        elif not self._watch_results:
            self.query_one('#watches', Static).update('Loading locals from GDB…')
        else:
            self.query_one('#watches', Static).update(
                'No visible locals at this PC.\nStep into main()/foo() to inspect variables.')

    def _step(self, command: str) -> None:
        if self.status != 'HALTED':
            return
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
            self.status = 'COMMANDING'
            self._show_status()
            self._send(f'-exec-until "{self._quoted(self.nav_file)}:{self.nav_line}"',
                       'execution')

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if isinstance(event.node.data, int):
            self.selected_level = event.node.data
            self.nav_file = ''  # selecting source never executes firmware
            self._show_source(reveal=True, follow_pc=True)

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
        watches = sorted(self.model.active_watches(), key=lambda w: (w.frame_level, w.label))
        self._copy('\n'.join(f'{w.label}\t{w.value}\t{w.trend}' for w in watches),
                   'watch values')

    def action_copy_log(self) -> None:
        self._copy('\n'.join(self._log_lines), 'debugger log')

    def action_focus_console(self) -> None:
        self.query_one('#gdb_input', Input).focus()

    def action_focus_source(self) -> None:
        self.set_focus(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'gdb_input':
            return
        command = event.value.strip()
        if command:
            self._log(f'(gdb) {command}')
            self._send(f'-interpreter-exec console "{self._quoted(command)}"', 'console')
            event.input.value = ''
        self.set_focus(None)

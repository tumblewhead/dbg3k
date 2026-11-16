"""Nonblocking GDB/MI transport through a reader thread and event queue."""
from __future__ import annotations
import itertools
import queue
import subprocess
import threading
from .mi import Record, parse_record

class GdbTransport:
    def __init__(self, gdb: str = 'gdb') -> None:
        self.gdb = gdb
        self.events: queue.Queue[Record] = queue.Queue()
        self.proc: subprocess.Popen[str] | None = None
        self._tokens = itertools.count(1)
        self._lock = threading.Lock()

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [self.gdb, '--interpreter=mi2', '--quiet', '--nx', '--nh'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        threading.Thread(target=self._read, name='dbg3k-gdb-reader', daemon=True).start()

    def _read(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                record = parse_record(line)
            except (ValueError, TypeError) as exc:
                record = Record(None, 'error', 'parse', str(exc))
            if record is not None:
                self.events.put(record)
        self.events.put(Record(None, 'error', 'exit', 'GDB exited'))

    def send(self, command: str) -> int:
        assert self.proc is not None and self.proc.stdin is not None
        with self._lock:
            token = next(self._tokens)
            self.proc.stdin.write(f'{token}{command}\n')
            self.proc.stdin.flush()
        return token

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()

"""Append-only, versioned debugger evidence stream, one JSON object per line.

The file is dated by the local calendar and is append-only even across
multiple launches on the same day. Every record has a session ID and sequence
for deterministic parsing; a new process never truncates existing evidence.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4


SCHEMA = "dbg3k.trace.v1"


def trace_filename(elf: str | Path, timestamp: datetime) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(elf).stem).strip("._")
    if not name:
        name = "target"
    return f"{name}_{timestamp.date().isoformat()}.jsonl"


class TraceWriter:
    def __init__(self, elf: str | Path, remote: str, directory: str | Path,
                 *, now: datetime | None = None, session: str | None = None) -> None:
        stamp = now or datetime.now().astimezone()
        self.target = Path(elf).stem
        self.session = session or uuid4().hex
        self.path = Path(directory).expanduser().resolve() / trace_filename(elf, stamp)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+", encoding="utf-8")
        # A crash can leave an incomplete final JSONL line. Do not append a
        # new valid record onto that fragment and corrupt the next session.
        self._file.seek(0, 2)
        end = self._file.tell()
        if end:
            self._file.seek(end - 1)
            if self._file.read(1) != "\n":
                self._file.seek(0, 2)
                self._file.write("\n")
                self._file.flush()
        self.sequence = 0
        self.closed = False
        self.record("session_start", elf=str(Path(elf).expanduser().resolve()),
                    remote=remote, target=self.target)

    def record(self, kind: str, **fields: Any) -> None:
        if self.closed:
            return
        self.sequence += 1
        item = {
            "schema": SCHEMA,
            "kind": kind,
            "session": self.session,
            "seq": self.sequence,
            "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            **fields,
        }
        self._file.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._file.flush()

    def returns_tsv(self, *, thread: str, caller: str, callee: str) -> str:
        """Return all matching observations from this session, not a RAM sample."""
        rows = ["timestamp\tstop\tthread\tcaller\tcallee\targs\tvalue\torigin"]
        # Flush first to ensure a click sees the most recently recorded return.
        self._file.flush()
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue  # tolerate a truncated final line after abrupt shutdown
                if (record.get("session") != self.session or
                    record.get("kind") != "return" or
                    record.get("thread") != thread or
                    record.get("caller") != caller or
                    record.get("callee") != callee):
                    continue
                fields = [
                    str(record.get("timestamp", "")), str(record.get("stop", "")),
                    thread, caller, callee, str(record.get("callee_display", "")),
                    str(record.get("value")) if record.get("value") is not None else "",
                    str(record.get("origin", "")),
                ]
                rows.append("\t".join(item.replace("\t", " ").replace("\n", " ")
                                      for item in fields))
        return "\n".join(rows) + "\n"

    def close(self) -> None:
        if not self.closed:
            self.record("session_end", target=self.target)
            self.closed = True
            self._file.close()

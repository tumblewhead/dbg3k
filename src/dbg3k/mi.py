"""Parse GDB/MI2 output records; no human GDB console scraping."""
from __future__ import annotations
from dataclasses import dataclass
import ast
import re
from typing import Any

@dataclass(frozen=True)
class Record:
    token: int | None
    kind: str
    cls: str
    payload: Any

class MIParseError(ValueError):
    pass

class _Parser:
    def __init__(self, source: str):
        self.source = source
        self.i = 0

    def peek(self) -> str:
        return self.source[self.i:self.i + 1]

    def pop(self, char: str) -> None:
        if self.peek() != char:
            raise MIParseError(f"expected {char!r} at {self.i}")
        self.i += 1

    def name(self) -> str:
        start = self.i
        while self.peek() and self.peek() not in ',={}[]':
            self.i += 1
        if start == self.i:
            raise MIParseError(f"missing field at {self.i}")
        return self.source[start:self.i]

    def string(self) -> str:
        start = self.i
        self.pop('"')
        escaped = False
        while self.peek():
            c = self.peek()
            self.i += 1
            if c == '"' and not escaped:
                raw = self.source[start:self.i]
                try:
                    return ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    return raw[1:-1]
            if c == '\\':
                escaped = not escaped
            else:
                escaped = False
        raise MIParseError('unterminated C string')

    def value(self) -> Any:
        c = self.peek()
        if c == '"':
            return self.string()
        if c == '{':
            self.pop('{')
            fields: dict[str, Any] = {}
            while self.peek() != '}':
                if not self.peek():
                    raise MIParseError('unterminated tuple')
                key, value = self.result()
                if key in fields:
                    old = fields[key]
                    fields[key] = old + [value] if isinstance(old, list) else [old, value]
                else:
                    fields[key] = value
                if self.peek() == ',':
                    self.i += 1
                elif self.peek() != '}':
                    raise MIParseError('expected tuple comma')
            self.pop('}')
            return fields
        if c == '[':
            self.pop('[')
            values = []
            while self.peek() != ']':
                if not self.peek():
                    raise MIParseError('unterminated list')
                pos = self.i
                while self.peek() and self.peek() not in ',=[]{}':
                    self.i += 1
                is_result = self.peek() == '='
                self.i = pos
                if is_result:
                    key, val = self.result()
                    values.append({key: val})
                else:
                    values.append(self.value())
                if self.peek() == ',':
                    self.i += 1
                elif self.peek() != ']':
                    raise MIParseError('expected list comma')
            self.pop(']')
            return values
        start = self.i
        while self.peek() and self.peek() not in ',]}':
            self.i += 1
        if start == self.i:
            raise MIParseError('missing value')
        return self.source[start:self.i]

    def result(self) -> tuple[str, Any]:
        key = self.name()
        self.pop('=')
        return key, self.value()

    def results(self) -> dict[str, Any]:
        fields = {}
        while self.peek():
            key, value = self.result()
            fields[key] = value
            if self.peek() == ',':
                self.i += 1
            elif self.peek():
                raise MIParseError('expected result comma')
        return fields

def parse_record(line: str) -> Record | None:
    line = line.strip()
    if not line or line == '(gdb)':
        return None
    m = re.match(r'^(\d+)?([\^*+=~@&])(.*)$', line)
    if not m:
        return Record(None, 'unknown', '', line)
    token = int(m.group(1)) if m.group(1) is not None else None
    kind, rest = m.group(2), m.group(3)
    if kind in '~@&':
        return Record(token, kind, 'stream', _Parser(rest).value())
    cls, sep, fields = rest.partition(',')
    return Record(token, kind, cls, _Parser(fields).results() if sep else {})

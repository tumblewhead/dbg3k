"""Build strict GDB/MI commands for selected thread/frame scopes."""
from __future__ import annotations
import re
from typing import Any

def _thread_id(value: object) -> str | None:
    text = str(value) if value is not None else ''
    return text if re.fullmatch(r'[1-9][0-9]*', text) else None

def select_thread_id(payload: dict[str, Any]) -> str | None:
    """Prefer the reported selected thread; fall back to a stopped thread."""
    candidate = _thread_id(payload.get('current-thread-id'))
    if candidate:
        return candidate
    threads = payload.get('threads', [])
    if not isinstance(threads, list):
        return None
    for state in ('stopped', None):
        for info in threads:
            if not isinstance(info, dict):
                continue
            if state is not None and info.get('state') != state:
                continue
            candidate = _thread_id(info.get('id'))
            if candidate:
                return candidate
    return None

def locals_request(thread_id: str, frame_level: int) -> str:
    """A frame-qualified GDB/MI command must ALSO name its thread."""
    thread_id = _thread_id(thread_id)
    if thread_id is None:
        raise ValueError('A valid GDB thread ID is required for frame locals')
    if not isinstance(frame_level, int) or frame_level < 0:
        raise ValueError('frame_level must be a nonnegative integer')
    return f'-stack-list-variables --thread {thread_id} --frame {frame_level} --all-values'

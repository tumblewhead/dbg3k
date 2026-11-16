"""Discover and address file-static and global data symbols using GDB/MI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
import re
from typing import Any

# Bound UI and remote GDB work. A later watch picker can select more symbols.
MAX_GLOBAL_WATCHES = 64
_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*\\Z")


@dataclass(frozen=True)
class GlobalSymbol:
    key: str
    label: str
    name: str
    expression: str
    type_name: str


def discover_globals(payload: dict[str, Any], limit: int = MAX_GLOBAL_WATCHES) -> tuple[list[GlobalSymbol], bool]:
    """Read `-symbol-info-variables`'s debug-symbol groups.

    Return symbols plus a truncation flag. Keep a file-qualified identity for
    statics and a shared identity for externally linked globals.
    """
    result: list[GlobalSymbol] = []
    seen: set[str] = set()
    groups = payload.get("symbols", {})
    if not isinstance(groups, dict):
        return result, False
    for group in groups.get("debug", []):
        if not isinstance(group, dict):
            continue
        filename = str(group.get("fullname") or group.get("filename") or "")
        shortfile = PurePath(filename).name
        for entry in group.get("symbols", []):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not _SYMBOL.fullmatch(name):
                continue
            is_static = bool(re.search(r"\\bstatic\\b", str(entry.get("description", ""))))
            if is_static and not filename:
                continue  # Do not evaluate an ambiguous file-static name.
            key = f"static:{filename}:{name}" if is_static else f"global:{name}"
            if key in seen:
                continue
            seen.add(key)
            if is_static:
                # GDB accepts 'source.c'::name even while stopped in another TU.
                escaped = filename.replace("\\", "\\\\").replace("'", "\\'")
                expression = f"'{escaped}'::{name}"
                label = f"{shortfile}::{name}"
            else:
                expression = name
                label = f"global.{name}"
            result.append(GlobalSymbol(
                key=key, label=label, name=name, expression=expression,
                type_name=str(entry.get("type", "")),
            ))
            if len(result) > limit:
                return result[:limit], True
    return result, False

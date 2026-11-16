"""Bounded source labels for signal bits; header text is never executed."""
import ast
import hashlib
from pathlib import Path
import re

from elftools.elf.elffile import ELFFile
from elftools.common.exceptions import ELFError, DWARFError


def discover_header(elf):
    """Find the teaching header through DWARF, without assuming checkout paths."""
    candidates = set()
    try:
        with open(elf, 'rb') as stream:
            image = ELFFile(stream)
            if not image.has_dwarf_info():
                return None
            dwarf = image.get_dwarf_info()
            for cu in dwarf.iter_CUs():
                lines = dwarf.line_program_for_CU(cu)
                if lines is None:
                    continue
                comp = cu.get_top_DIE().attributes.get('DW_AT_comp_dir')
                base = Path(comp.value.decode(errors='replace')) if comp else Path('.')
                for entry in lines['file_entry']:
                    name = entry.name.decode(errors='replace')
                    if Path(name).name != 'task_config.hpp':
                        continue
                    directory = entry.dir_index
                    dirs = lines['include_directory']
                    parent = Path(dirs[directory - 1].decode(errors='replace')) if directory else base
                    path = parent / name
                    if not path.is_absolute():
                        path = base / path
                    if path.is_file():
                        candidates.add(str(path.resolve()))
    except (OSError, ValueError, KeyError, IndexError, ELFError, DWARFError):
        return None
    return next(iter(candidates)) if len(candidates) == 1 else None


def _constant(text, known):
    text = re.sub(r'\b(UINT(?:8|16|32|64)_C)\s*\(([^()]*)\)', r'(\2)', text)
    text = re.sub(r'\b(0[xX][0-9a-fA-F]+|[0-9]+)[uUlL]+\b', r'\1', text.strip())
    tree = ast.parse(text, mode='eval')
    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in known:
            return known[node.id]
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.LShift) and 0 <= b < 32:
                return a << b
            if isinstance(node.op, ast.BitOr):
                return a | b
            if isinstance(node.op, ast.Add):
                return a + b
        raise ValueError('Unsupported constant expression')
    return visit(tree)


def signal_labels(path):
    """Single-bit constants from a selected header, with explicit provenance.

    These are source labels, not an ELF attestation. Unsupported definitions
    are reported rather than run through a compiler or Python eval.
    """
    if not path:
        return dict(signals=[], path=None, status='Choose a signal header in Kodama setup')
    path = Path(path).expanduser().resolve()
    with path.open('rb') as stream:
        raw = stream.read(131073)
    if len(raw) > 131072:
        raise ValueError('Signal header exceeds 128 KiB')
    text = raw.decode('utf-8')
    text = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    declarations = []
    for match in re.finditer(r'^\s*#\s*define\s+([A-Za-z_]\w*)[ \t]+([^\n]+)', text, re.M):
        declarations.append((match.start(), match[1] + '=' + match[2]))
    for match in re.finditer(r'\b(?:constexpr|const)\s+(?:[\w:]+\s+)+([^;{}]+);', text):
        declarations.append((match.start(), match[1]))
    for match in re.finditer(r'\benum(?:\s+class)?(?:\s+\w+)?(?:\s*:\s*\w+)?\s*\{([^}]+)\}', text):
        declarations.append((match.start(), match[1]))
    known, labels, skipped = {}, {}, []
    for _, declaration in sorted(declarations):
        previous = -1
        for item in declaration.split(','):
            parts = item.strip().split('=', 1)
            name = parts[0].strip()
            if not re.fullmatch(r'[A-Za-z_]\w*', name):
                continue
            if len(name) > 80:
                skipped.append(name[:80] + '…')
                continue
            try:
                value = _constant(parts[1], known) if len(parts) == 2 else previous + 1
                previous = value
                known[name] = value
                if 0 < value <= 0x80000000 and value & (value - 1) == 0:
                    labels[name] = value
            except (ValueError, SyntaxError, RecursionError):
                skipped.append(name)
    selected = list(labels.items())[:64]
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                signals=[dict(name=n, mask=hex(v)) for n, v in selected],
                status='Header labels · not verified against ELF', skipped=skipped[:64],
                truncated=len(labels) > 64)

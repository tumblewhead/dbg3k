"""Application-agnostic observation contract; no transport or UI dependencies."""
import json
import re

PREFIX = '__dbg3k_observation_v1__'
PROVENANCE_PREFIX = '__dbg3k_provenance_v1__'
LIMITS = dict(expressions=16, expression_chars=512, depth=5, nodes=256,
              children=64, raw_chars=2048, record_bytes=131072,
              value_bytes=65536, stop_ms=750)
_NAME = r'[A-Za-z_$][A-Za-z0-9_$]*'
_ROOT = re.compile(r"(?:'[^'\n]+'::)?" + _NAME + r'(?:::' + _NAME + r')*')
_ACCESS = re.compile(r'(\.|->)(' + _NAME + r')|\[(-?[0-9]+)\]')


def expression_parts(expression):
    """Read-only C/C++ selectors, deliberately excluding calls and side effects.

    Leading * dereferences the completed selector (e.g. *slots[0].pointer).
    Member -> and pointer subscripts are also explicit dereferences.
    """
    if not isinstance(expression, str) or len(expression) > LIMITS['expression_chars']:
        raise ValueError('Expression must be a string of at most 512 characters')
    text = expression.strip()
    dereference = text.startswith('*')
    if dereference:
        text = text[1:].lstrip()
    root = _ROOT.match(text)
    if root is None:
        raise ValueError('Use a symbol, optional file/namespace scope, fields and integer subscripts')
    offset, selectors = root.end(), []
    while offset < len(text):
        match = _ACCESS.match(text, offset)
        if match is None:
            raise ValueError('Only read-only selectors are supported; calls, casts and arithmetic are excluded')
        selectors.append((match[1], match[2]) if match[1] else ('[]', int(match[3])))
        offset = match.end()
    return root[0], selectors, dereference


def select_expressions(expressions):
    selected = tuple(dict.fromkeys(expressions))
    if len(selected) > LIMITS['expressions']:
        raise ValueError('Select at most 16 observation expressions')
    for expression in selected:
        expression_parts(expression)
    return selected


def decode_message(message, prefix=PREFIX):
    if not message.startswith(prefix):
        return None
    try:
        value = json.loads(message[len(prefix):])
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None

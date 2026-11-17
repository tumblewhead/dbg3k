"""Import declared Miro wiring; no task execution or control-flow inference."""
import argparse
from collections import defaultdict
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

NAME = r'[A-Za-z_][A-Za-z_0-9]{0,63}'
OPERATORS = {'AND', 'OR', 'NOT'}


def identifier(name):
    if not isinstance(name, str) or not re.fullmatch(NAME, name) or name.upper() in OPERATORS:
        raise ValueError(f'Invalid identifier: {name!r}')
    return name


def expression(text, aliases=None):
    """Return canonical text and referenced names. AND binds more tightly than OR.

    expression ::= term ("OR" term)*
    term       ::= factor ("AND" factor)*
    factor     ::= identifier | "(" expression ")"
    """
    if not isinstance(text, str) or len(text) > 2048:
        raise ValueError('Expression must be text of at most 2048 characters')
    tokens, at = [], 0
    while at < len(text):
        if text[at].isspace():
            at += 1
            continue
        match = re.match(r'[A-Za-z_][A-Za-z_0-9]*|[()]', text[at:])
        if not match:
            raise ValueError(f'Invalid expression character at column {at + 1}: {text[at]!r}')
        token = match[0]
        tokens.append(token.upper() if token.upper() in OPERATORS else token)
        at += len(token)
    if not tokens or len(tokens) > 256:
        raise ValueError('Expression requires 1..256 tokens')
    at, names = 0, set()

    def parse(minimum=1, depth=0):
        nonlocal at
        if depth > 32 or at >= len(tokens):
            raise ValueError('Incomplete expression or nesting exceeds 32')
        token = tokens[at]
        at += 1
        if token == '(':
            node = parse(depth=depth + 1)
            if at >= len(tokens) or tokens[at] != ')':
                raise ValueError('Missing closing parenthesis')
            at += 1
        else:
            name = identifier(token)
            name = identifier((aliases or {}).get(name, name))
            names.add(name)
            node = name
        while at < len(tokens) and {'OR': 1, 'AND': 2}.get(tokens[at], 0) >= minimum:
            op = tokens[at]
            at += 1
            right = parse({'OR': 1, 'AND': 2}[op] + 1, depth + 1)
            node = (op, node, right)
        return node

    tree = parse()
    if at != len(tokens):
        raise ValueError(f'Unexpected token {tokens[at]!r}; use explicit AND/OR')

    def render(node, parent=0):
        if isinstance(node, str):
            return node
        op, left, right = node
        precedence = {'OR': 1, 'AND': 2}[op]
        result = f'{render(left, precedence)} {op} {render(right, precedence)}'
        return f'({result})' if precedence < parent else result
    return render(tree), names


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in ('p', 'br', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('p', 'div'):
            self.parts.append('\n')


def plain(html):
    if not isinstance(html, str) or len(html) > 4096:
        raise ValueError('Item/caption text must be at most 4096 characters')
    parser = _Plain()
    parser.feed(html)
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


def import_board(board, aliases=None):
    aliases = dict(aliases or {})
    for old, new in aliases.items():
        identifier(old); identifier(new)
        if new in aliases and aliases[new] != new:
            raise ValueError('Aliases must map directly to final names, without chains')
    if not isinstance(board, dict) or board.get('format') != 'miro-diagram-export/v1':
        raise ValueError('Expected miro-diagram-export/v1')
    items = board.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 2048:
        raise ValueError('Export requires 1..2048 items')
    nodes, ids, tasks, externals = {}, set(), {}, {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or item['id'] in ids:
            raise ValueError('Items require unique string IDs')
        ids.add(item['id'])
        if item.get('type') in ('connector', 'text', 'frame'):
            continue
        if item.get('type') != 'shape':
            raise ValueError(f'Unsupported item type: {item.get("type")} [{item["id"]}]')
        label = plain(item.get('content', '')).split('\n')[0]
        if label in ('Kodama::events', 'Kodama::levels'):
            nodes[item['id']] = ('occurrence' if label.endswith('events') else 'level', None)
            continue
        match = re.fullmatch(rf'(Task|External)::({NAME})(?:\(\))?', label)
        if not match:
            raise ValueError(f'Unknown wiring node {label!r} [{item["id"]}]')
        kind, name = match.groups()
        identifier(name)
        if name in tasks or name in externals:
            raise ValueError(f'Duplicate task/external name: {name}')
        target = tasks if kind == 'Task' else externals
        target[name] = dict(source_id=item['id'], spawns=[], publishes=[], updates_levels=[], sensitivities=[])
        nodes[item['id']] = ('task' if kind == 'Task' else 'external', name)
    if not tasks or len(tasks) + len(externals) > 128:
        raise ValueError('Wiring requires tasks and at most 128 task/external nodes')
    entities = {**tasks, **externals}
    produced, consumed = defaultdict(set), defaultdict(set)
    relationships = set()
    for item in items:
        if item.get('type') != 'connector':
            continue
        edge = item['id']
        try:
            if not isinstance(item.get('start'), dict) or not isinstance(item.get('end'), dict):
                raise ValueError('Connector requires start/end objects')
            start, end = item['start']['item'], item['end']['item']
            if not isinstance(start, str) or not isinstance(end, str):
                raise ValueError('Connector endpoint IDs must be strings')
            if start not in nodes or end not in nodes:
                raise ValueError('Connector endpoints must reference recognized wiring nodes')
            style = item.get('style', {})
            if not isinstance(style, dict):
                raise ValueError('Connector style must be an object')
            start_arrow = style.get('startStrokeCap', 'none') != 'none'
            end_arrow = style.get('endStrokeCap', 'none') != 'none'
            if start_arrow == end_arrow:
                raise ValueError('Connector requires exactly one arrowhead')
            if start_arrow:
                start, end = end, start
            captions = item.get('captions', [])
            if not isinstance(captions, list) or len(captions) != 1 or not isinstance(captions[0], dict):
                raise ValueError('Connector requires exactly one semantic caption')
            caption = plain(captions[0]['content'])
            (a, actor), (b, recipient) = nodes[start], nodes[end]
            if a == 'task' and b == 'task' and caption.upper() == 'KODAMA::SPAWN':
                key = ('spawn', actor, recipient)
                if actor == recipient:
                    raise ValueError('Self-spawn dependency is unsupported')
                entities[actor]['spawns'].append(recipient)
            elif a in ('task', 'external') and b in ('occurrence', 'level'):
                prefix = 'event::' if b == 'occurrence' else 'level::'
                name = caption[len(prefix):] if caption.lower().startswith(prefix) else caption
                name = identifier(name)
                name = identifier(aliases.get(name, name))
                key = (b, actor, name, 'produces')
                produced[b, name].add(actor)
                entities[actor]['publishes' if b == 'occurrence' else 'updates_levels'].append(name)
            elif a in ('occurrence', 'level') and b in ('task', 'external'):
                match = re.fullmatch(r'(?i:SUB)\[(.*)\]', caption)
                legacy = re.fullmatch(r'(?i:subAND)\[(.*)\]', caption)
                if legacy:
                    terms = [identifier(term.strip()) for term in legacy[1].split(',')]
                    if len(terms) < 2:
                        raise ValueError('subAND requires at least two identifiers')
                    condition = ' AND '.join(terms)
                elif match:
                    condition = match[1]
                else:
                    raise ValueError('Sensitivity caption requires SUB[expression]')
                condition, references = expression(condition, aliases)
                key = (a, recipient, condition, 'consumes')
                for name in references:
                    consumed[a, name].add(recipient)
                entities[recipient]['sensitivities'].append(dict(kind=a, expression=condition, source_id=edge))
            else:
                raise ValueError('Unsupported relationship; label cannot infer task behavior')
            if key in relationships:
                raise ValueError('Duplicate wiring relationship')
            relationships.add(key)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise ValueError(f'Connector {edge}: {exc}') from exc
    errors = []
    for kind, name in sorted(produced.keys() | consumed.keys()):
        if not produced[kind, name]:
            errors.append(f'{kind} {name}: consumed by {", ".join(sorted(consumed[kind, name]))}, but has no producer')
        if not consumed[kind, name]:
            errors.append(f'{kind} {name}: produced by {", ".join(sorted(produced[kind, name]))}, but has no consumer')
    for kind in ('occurrence', 'level'):
        if len({name for k, name in produced.keys() | consumed.keys() if k == kind}) > 32:
            errors.append(f'{kind} namespace exceeds 32 signals')
    if errors:
        raise ValueError('Dependency validation failed:\n' + '\n'.join(errors))
    for entity in entities.values():
        for field in ('spawns', 'publishes', 'updates_levels'):
            entity[field].sort()
        entity['sensitivities'].sort(key=lambda item: (item['kind'], item['expression']))
    return dict(schema='kodama.wiring/v1', source=dict(format=board['format'], exported_at=board.get('exportedAt')),
                aliases=dict(sorted(aliases.items())),
                occurrences=sorted(name for kind, name in produced if kind == 'occurrence'),
                levels=sorted(name for kind, name in produced if kind == 'level'),
                tasks=dict(sorted(tasks.items())), externals=dict(sorted(externals.items())))


def yaml_text(value):
    """Emit the plain mapping/list/scalar subset, quoting strings as JSON/YAML."""
    def scalar(item):
        return json.dumps(item, ensure_ascii=False)

    def lines(item, indent):
        prefix = ' ' * indent
        if isinstance(item, dict):
            for key, child in item.items():
                # Quote YAML implicit booleans/nulls even for valid C identifiers.
                reserved = {'y', 'n', 'yes', 'no', 'on', 'off', 'true', 'false', 'null'}
                key_text = key if re.fullmatch(NAME, key) and key.lower() not in reserved else scalar(key)
                if isinstance(child, (dict, list)) and child:
                    yield f'{prefix}{key_text}:'
                    yield from lines(child, indent + 2)
                else:
                    yield f'{prefix}{key_text}: {scalar(child)}'
        elif isinstance(item, list):
            for child in item:
                if isinstance(child, (dict, list)) and child:
                    yield prefix + '-'
                    yield from lines(child, indent + 2)
                else:
                    yield prefix + '- ' + scalar(child)
    return '\n'.join(lines(value, 0)) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('--output', type=Path, help='New YAML file; existing files are never overwritten')
    parser.add_argument('--alias', action='append', default=[], metavar='OLD=NEW', help='Explicit case-sensitive identifier mapping')
    args = parser.parse_args(argv)
    try:
        aliases = {}
        for entry in args.alias:
            old, new = entry.split('=', 1)
            if old in aliases:
                raise ValueError(f'Duplicate alias: {old}')
            aliases[old] = new
        with args.export.expanduser().open('rb') as stream:
            raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Export exceeds 2 MiB')
        model = import_board(json.loads(raw.decode('utf-8')), aliases)
        model['source']['sha256'] = hashlib.sha256(raw).hexdigest()
        text = yaml_text(model)
        if args.output:
            with args.output.expanduser().open('x', encoding='utf-8') as output:
                output.write(text)
        else:
            print(text, end='')
    except (ValueError, OSError, RecursionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

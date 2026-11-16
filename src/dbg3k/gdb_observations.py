"""Loaded inside GDB in an isolated namespace. Never executes target code."""
import importlib.util
import json
from pathlib import Path
import time

import gdb

_spec = importlib.util.spec_from_file_location(
    '_dbg3k_observation_contract', Path(__file__).with_name('observations.py'))
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)
LIMITS = _contract.LIMITS


def _error(path, code, message):
    return dict(path=path, code=code, message=str(message)[:LIMITS['raw_chars']])


def _dereference(value):
    if value.type.strip_typedefs().code != gdb.TYPE_CODE_PTR:
        raise ValueError('Explicit dereference requires a pointer')
    if int(value) == 0:
        raise ValueError('Null pointer: dereference skipped')
    return value.dereference()


def _evaluate(expression):
    root, selectors, dereference = _contract.expression_parts(expression)
    value = gdb.parse_and_eval(root)
    for operator, key in selectors:
        if operator == '->':
            value = _dereference(value)
        code = value.type.strip_typedefs().code
        if operator == '[]':
            if code == gdb.TYPE_CODE_PTR:
                if int(value) == 0:
                    raise ValueError('Null pointer: indexed dereference skipped')
            elif code != gdb.TYPE_CODE_ARRAY:
                raise ValueError('Subscript requires an array or pointer')
            value = value[key]
        else:
            if code not in (gdb.TYPE_CODE_STRUCT, gdb.TYPE_CODE_UNION):
                raise ValueError('Member selector requires a structure or union')
            value = value[key]
    return _dereference(value) if dereference else value


class _Encoder:
    def __init__(self, deadline):
        self.nodes = 0
        self.deadline = deadline

    def node(self, value, path='$', depth=0):
        self.nodes += 1
        node = dict(path=path, type=str(value.type), status='ok', truncated=False)
        try:
            typ = value.type.strip_typedefs()
            code = typ.code
            aggregate = code in (gdb.TYPE_CODE_ARRAY, gdb.TYPE_CODE_STRUCT, gdb.TYPE_CODE_UNION)
            # Aggregates stay lazy: expand bounded children rather than fetching
            # the whole object. Parent unavailable flags can describe only a
            # subset, so inspect each child independently.
            if not aggregate:
                if value.is_optimized_out:
                    raise LookupError('optimized-out')
                if getattr(value, 'is_unavailable', False):
                    raise LookupError('unavailable')
                value.fetch_lazy()
            raw = value.format_string(
                                   raw=True, summary=aggregate, **({'format': 'x'} if code == gdb.TYPE_CODE_PTR else {}),
                                   deref_refs=False, actual_objects=False, symbols=False,
                                   max_elements=16, max_depth=1)
            node['raw'] = dict(format='gdb.Value.format_string/raw-summary' if aggregate else
                               'gdb.Value.format_string/raw', text=raw[:LIMITS['raw_chars']],
                               truncated=len(raw) > LIMITS['raw_chars'])
            if node['raw']['truncated']:
                self.truncate(node, 'raw_chars')
            if aggregate:
                node['kind'] = 'array' if code == gdb.TYPE_CODE_ARRAY else (
                    'union' if code == gdb.TYPE_CODE_UNION else 'object')
                node['children'] = []
                if depth >= LIMITS['depth']:
                    return self.truncate(node, 'depth')
                if code == gdb.TYPE_CODE_ARRAY:
                    low, high = typ.range()
                    node['bounds'] = [str(low), str(high)]
                    total = max(0, high - low + 1)
                    members = ((str(i), i, None) for i in range(low, high + 1))
                else:
                    fields = typ.fields()
                    total = len(fields)
                    # Field ordinal disambiguates anonymous and duplicate names.
                    members = ((f.name or '@' + str(i), f, i) for i, f in enumerate(fields))
                node['total_children'] = total
                for name, key, ordinal in members:
                    if len(node['children']) >= LIMITS['children']:
                        self.truncate(node, 'children')
                        break
                    if self.nodes >= LIMITS['nodes'] or time.monotonic() >= self.deadline:
                        self.truncate(node, 'nodes' if self.nodes >= LIMITS['nodes'] else 'stop_ms')
                        break
                    child_path = path + '/' + name.replace('~', '~0').replace('/', '~1')
                    try:
                        child = self.node(value[key], child_path, depth + 1)
                    except (gdb.error, ValueError, TypeError) as exc:
                        child = dict(path=child_path, status='error', truncated=False,
                                     errors=[_error(child_path, 'read-error', exc)])
                    child['name'] = name
                    if ordinal is not None:
                        child['ordinal'] = ordinal
                    node['children'].append(child)
                    if child['status'] != 'ok':
                        node['status'] = 'partial'
                    if child.get('truncated'):
                        node['truncated'] = True
            elif code in (gdb.TYPE_CODE_INT, gdb.TYPE_CODE_CHAR, gdb.TYPE_CODE_ENUM,
                          gdb.TYPE_CODE_FLAGS, gdb.TYPE_CODE_BOOL):
                node.update(kind='enum' if code == gdb.TYPE_CODE_ENUM else 'integer',
                            encoding='decimal', value=str(int(value)))
                if typ.sizeof is not None:
                    node['bits'] = typ.sizeof * 8
            elif code == gdb.TYPE_CODE_PTR:
                node.update(kind='pointer', encoding='hex', address=hex(int(value)),
                            pointee_type=str(typ.target()), dereferenced=False)
            elif code in (gdb.TYPE_CODE_FLT, gdb.TYPE_CODE_DECFLOAT):
                # GDB's decimal text preserves target floating formatting,
                # including NaNs/Inf, without coercion to host float precision.
                node.update(kind='float', encoding='gdb-text', value=node['raw']['text'])
            else:
                node.update(kind='opaque', status='unavailable', errors=[
                    _error(path, 'unsupported-type', 'No decoder for GDB type code ' + str(code))])
        except LookupError as exc:
            node.update(status='unavailable', raw=dict(format='gdb.Value availability', text=str(exc)),
                        errors=[_error(path, str(exc), str(exc))])
        except (gdb.error, ValueError, TypeError, OverflowError) as exc:
            node.update(status='error', errors=[_error(path, 'read-error', exc)])
        return node

    @staticmethod
    def truncate(node, limit):
        node.update(status='partial', truncated=True)
        node.setdefault('errors', []).append(_error(node['path'], 'limit', limit))
        return node


def _context():
    thread = gdb.selected_thread()
    frame = gdb.selected_frame()
    sal = frame.find_sal()
    return dict(thread=str(thread.global_num) if thread else None,
                frame=dict(level=frame.level(), function=frame.name(), pc=hex(frame.pc()),
                           filename=sal.symtab.fullname() if sal.symtab else None,
                           line=sal.line or None), architecture=frame.architecture().name())


def dbg3k_provenance():
    try:
        context = _context()
    except gdb.error:
        context = {}
    gdb.write(_contract.PROVENANCE_PREFIX + json.dumps(dict(
        gdb_version=gdb.VERSION, **context), separators=(',', ':')) + '\n')


def dbg3k_observe(request, stop, expected_thread, expressions):
    deadline = time.monotonic() + LIMITS['stop_ms'] / 1000
    context = _context()
    if context['thread'] != expected_thread or context['frame']['level'] != 0:
        raise gdb.GdbError('Observation thread/frame changed before capture')
    # Defense in depth: selector grammar excludes calls/assignments, and GDB
    # also forbids inferior calls while the collector is active.
    old_calls = gdb.parameter('may-call-functions')
    old_max = gdb.parameter('max-value-size')
    try:
        gdb.execute('set may-call-functions off', to_string=True)
        gdb.execute('set max-value-size ' + str(LIMITS['value_bytes']), to_string=True)
        for expression in expressions[:LIMITS['expressions']]:
            result = dict(request=request, stop=stop, expression=expression,
                          scope=dict(thread=context['thread'], frame=context['frame'],
                                     resolution='selected-frame; explicit file scope retained in expression'),
                          thread=context['thread'], limits=LIMITS, origin='gdb-python-value',
                          observation_version=1)
            try:
                if time.monotonic() >= deadline:
                    result.update(status='unavailable', truncated=True,
                                  errors=[_error('$', 'limit', 'stop_ms')])
                else:
                    value = _evaluate(expression)
                    tree = _Encoder(deadline).node(value)
                    result.update(status=tree['status'], type=str(value.type), value=tree,
                                  raw=tree.get('raw'), truncated=tree['truncated'])
            except (gdb.error, ValueError, TypeError) as exc:
                result.update(status='error', truncated=False,
                              errors=[_error('$', 'expression-error', exc)])
            encoded = json.dumps(result, ensure_ascii=True, separators=(',', ':'))
            if len(encoded.encode('utf-8')) > LIMITS['record_bytes'] - 2048:
                result.pop('value', None)
                result.update(status='partial', truncated=True,
                              errors=[_error('$', 'limit', 'record_bytes; value tree omitted')])
                encoded = json.dumps(result, ensure_ascii=True, separators=(',', ':'))
                if len(encoded.encode('utf-8')) > LIMITS['record_bytes'] - 2048:
                    result.pop('raw', None)
                    result.pop('type', None)
                    result['scope']['frame'] = dict(level=0)
                    result['errors'].append(_error('$', 'limit', 'record_bytes; raw/type/frame details omitted'))
                    encoded = json.dumps(result, ensure_ascii=True, separators=(',', ':'))
            gdb.write(_contract.PREFIX + encoded + '\n')
    finally:
        gdb.execute('set may-call-functions ' + ('on' if old_calls else 'off'), to_string=True)
        gdb.execute('set max-value-size ' + (str(old_max) if old_max else 'unlimited'), to_string=True)

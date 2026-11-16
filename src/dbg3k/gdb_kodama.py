"""Read-only Kodama adapter inside GDB. No target calls or firmware changes.

API probes observe entry, not completion. Breakpoint callbacks only read data
and emit JSON; breakpoint installation/removal happens in explicit MI commands.
"""
import gdb
import json

PREFIX = '__dbg3k_kodama_v1__'
TASK_LIMIT = 32
POOL_LIMIT = 64
EVENT_LIMIT = 4096
ALTERNATIVE_LIMIT = 16
RECORD_LIMIT = 131072
try:
    _endian = gdb.execute('show endian', to_string=True)
    BYTE_ORDER = 'little' if 'little endian' in _endian else 'big' if 'big endian' in _endian else None
except gdb.error:
    BYTE_ORDER = None


def scalar(value):
    node = dict(type=str(value.type), status='ok')
    try:
        if value.is_optimized_out:
            return dict(node, status='unavailable', error='optimized-out')
        value.fetch_lazy()
        pointer = value.type.strip_typedefs().code == gdb.TYPE_CODE_PTR
        node.update(encoding='hex' if pointer else 'decimal',
                    value=hex(int(value)) if pointer else str(int(value)))
    except (gdb.error, ValueError, TypeError, OverflowError) as exc:
        node.update(status='unavailable', error=str(exc)[:240])
    return node


def number(node):
    return int(node['value'], 0) if node and node.get('status') == 'ok' else None


def fields(value, names):
    available = {f.name for f in value.type.strip_typedefs().fields()}
    result = {}
    for name in names:
        if name in available:
            try:
                result[name] = scalar(value[name])
            except (gdb.error, ValueError) as exc:
                result[name] = dict(status='unavailable', error=str(exc)[:240])
    return result


def read(expression):
    try:
        if expression.isidentifier():
            symbol = gdb.lookup_global_symbol(expression)
            if symbol is None:
                return None, 'Global symbol unavailable: ' + expression
            return symbol.value(), None
        return gdb.parse_and_eval(expression), None
    except gdb.error as exc:
        return None, str(exc)[:240]


def global_scalar(expression):
    value, error = read(expression)
    return dict(status='unavailable', error=error) if value is None else scalar(value)


def symbol_at(address):
    try:
        block = gdb.block_for_pc(address & ~1)
        while block:
            if block.function:
                return block.function.print_name
            block = block.superblock
    except (gdb.error, RuntimeError):
        pass
    return None


def subscription(task, values):
    active = number(values.get('active'))
    identity = number(values.get('identity'))
    if active is None and identity is not None:
        active = bool(identity & 255)
    pointer = number(values.get('subscription'))
    if not active or pointer in (None, 0) or number(values.get('waiting')) == 0:
        return None
    result = dict(address=hex(pointer), status='ok', alternatives=[])
    try:
        sub = task['subscription'].dereference()
        count = int(sub['count'])
        result['count'] = count
        if not 0 < count <= 32 or int(sub['alternatives']) == 0:
            raise ValueError('Invalid count or null alternative pointer; read skipped')
        for i in range(min(count, ALTERNATIVE_LIMIT)):
            result['alternatives'].append(fields(sub['alternatives'][i], ('inputs', 'kind')))
        if count > ALTERNATIVE_LIMIT:
            result.update(status='partial', error='alternative limit16')
    except (gdb.error, ValueError, TypeError) as exc:
        result.update(status='unavailable', error=str(exc)[:240])
    return result


def snapshot():
    result = dict(core={}, tasks=[], commands=[], pool=[], errors=[], limits=dict(
        tasks=TASK_LIMIT, pool=POOL_LIMIT, alternatives=ALTERNATIVE_LIMIT, api_events=EVENT_LIMIT))
    result['allocator'] = {name: global_scalar(name) for name in
        ('g_allocations', 'g_frees', 'g_live', 'g_peak', 'g_failed_alloc', 'g_frame_max')}
    for name in ('running', 'levels', 'urgent_levels', 'clock_ticks', 'yield_skip', 'order_head', 'destroying'):
        result['core'][name] = global_scalar("'kodama.c'::" + name)
    tasks, error = read("'kodama.c'::tasks")
    if tasks is None:
        result['errors'].append('tasks: ' + str(error))
        return result
    low, high = tasks.type.strip_typedefs().range()
    result['task_capacity'] = high - low + 1
    result['tasks_base'] = hex(int(tasks.address))
    result['task_stride'] = tasks.type.strip_typedefs().target().sizeof
    for index in range(low, min(high + 1, low + TASK_LIMIT)):
        try:
            task = tasks[index]
            values = fields(task, ('identity', 'active', 'generation', 'ready', 'priority',
                'cluster', 'job', 'promoted', 'sleeping', 'expired', 'deadline', 'context',
                'step', 'subscription', 'waiting', 'seen', 'urgent_seen', 'wake_mask', 'next'))
            step = number(values.get('step'))
            result['tasks'].append(dict(index=index, address=hex(int(task.address)), type=str(task.type),
                                        fields=values, subscription=subscription(task, values),
                                        step_symbol=symbol_at(step) if step else None))
        except (gdb.error, ValueError) as exc:
            result['tasks'].append(dict(index=index, error=str(exc)[:240]))
    if result['task_capacity'] > TASK_LIMIT:
        result['errors'].append('Task capture truncated at32 slots')
    commands, error = read('g_cmd')
    if commands is not None:
        low, high = commands.type.strip_typedefs().range()
        for index in range(low, min(high + 1, low + TASK_LIMIT)):
            try:
                command = commands[index]
                item = dict(index=index, address=hex(int(command.address)), token=scalar(command['token']))
                handle = command['handle']
                names = {f.name for f in handle.type.strip_typedefs().fields()}
                pointer = next((n for n in ('_M_fr_ptr', '__handle_', '__ptr_') if n in names), None)
                item['handle'] = scalar(handle[pointer]) if pointer else dict(status='unavailable', error='Unknown coroutine handle layout')
                result['commands'].append(item)
            except (gdb.error, ValueError, TypeError) as exc:
                result['errors'].append('Command read: ' + str(exc)[:200])
    else:
        result['errors'].append('Coroutine bindings unavailable: ' + str(error))
    pool, error = read('g_frames')
    if pool is not None:
        low, high = pool.type.strip_typedefs().range()
        result['pool_capacity'] = high - low + 1
        result['pool_reserved_bytes'] = pool.type.sizeof
        for index in range(low, min(high + 1, low + POOL_LIMIT)):
            try:
                frame = pool[index]
                item = dict(index=index, address=hex(int(frame.address)), bytes=frame.type.sizeof,
                            data_address=hex(int(frame['data'].address)), capacity=frame['data'].type.sizeof,
                            used=scalar(frame['used']))
                # Only live allocator-owned storage is inspected. This resolves
                # a compiler actor symbol, not arbitrary application pointers.
                if number(item['used']):
                    try:
                        pointer_size = gdb.lookup_type('void').pointer().sizeof
                        address = int(frame['data'].address)
                        raw = bytes(gdb.selected_inferior().read_memory(address, pointer_size))
                        # Use GDB's declared target byte order, never a guess.
                        if BYTE_ORDER and gdb.newest_frame().architecture().name().startswith('arm'):
                            item['resume_symbol'] = symbol_at(int.from_bytes(raw, BYTE_ORDER))
                    except (gdb.error, ValueError):
                        pass
                result['pool'].append(item)
            except (gdb.error, ValueError, TypeError) as exc:
                result['errors'].append('Pool read: ' + str(exc)[:200])
        if result['pool_capacity'] > POOL_LIMIT:
            result['errors'].append('Pool capture truncated at64 slots')
    else:
        result['errors'].append('Pool unavailable: ' + str(error))
    return result


class ApiProbe(gdb.Breakpoint):
    def __init__(self, owner, logical, spec):
        # Released GDBs do not all accept allow_pending. Resolve first so a
        # missing optional API never creates a pending breakpoint or prompt.
        unused, locations = gdb.decode_line(spec)
        if not locations or not any(location.pc for location in locations):
            raise gdb.GdbError('No executable debug location for ' + spec)
        super().__init__(spec, internal=True)
        self.silent = True
        self.owner, self.logical = owner, logical

    def stop(self):
        if not self.owner.enabled:
            return False
        try:
            frame = gdb.newest_frame()
            arguments = {}
            block = frame.block()
            while block and block.function is None:
                block = block.superblock
            if block:
                for symbol in block:
                    if symbol.is_argument:
                        arguments[symbol.name] = scalar(frame.read_var(symbol))
                    if len(arguments) >= 8:
                        break
            caller = frame.older()
            self.owner.emit('api', self.owner.anchor, dict(function=self.logical,
                arguments=arguments, caller=caller.name() if caller else None,
                semantics='publication-entry' if self.logical == 'signal_locked'
                else 'dispatch-entry' if self.logical == 'resume_command' else 'api-request'))
        except (gdb.error, RuntimeError, ValueError, TypeError) as exc:
            self.owner.emit_error(str(exc))
        return False


class KodamaObserver:
    def __init__(self):
        self.enabled = False
        self.probes = []
        self.sequence = 0
        self.anchor = 0
        self.capture = ''
        self.limited = False

    def emit_error(self, message):
        gdb.write(PREFIX + json.dumps(dict(capture=self.capture, diagnostic=message[:500])) + '\n')

    def emit(self, origin, stop, event=None):
        if self.sequence >= EVENT_LIMIT:
            if not self.limited:
                self.limited = True
                self.emit_error('4096 sample limit reached; pause/restart capture at a debugger stop')
            return
        self.sequence += 1
        thread = gdb.selected_thread()
        frame = gdb.newest_frame()
        sal = frame.find_sal()
        try:
            exception = str(int(frame.read_register('xpsr')) & 0x1ff)
        except (gdb.error, ValueError):
            exception = None
        data = dict(schema='dbg3k.kodama.raw.v1', capture=self.capture, sample_seq=self.sequence,
            origin=origin, stop=stop, stop_anchor='current-visible-stop' if origin == 'stop' else 'preceding-visible-stop',
            thread=str(thread.global_num) if thread else None,
            frame=dict(function=frame.name(), pc=hex(frame.pc()), filename=sal.symtab.fullname() if sal.symtab else None,
                       line=sal.line, exception=exception),
            event=event, state=snapshot())
        encoded = json.dumps(data, separators=(',', ':'))
        # Keep complete objects within the same bounded journal contract.
        while len(encoded.encode()) > RECORD_LIMIT - 2048 and data['state']['tasks']:
            data['state']['tasks'].pop()
            if 'Record size truncation' not in data['state']['errors']:
                data['state']['errors'].append('Record size truncation')
            encoded = json.dumps(data, separators=(',', ':'))
        gdb.write(PREFIX + encoded + '\n')

    def control(self, enabled, probes, capture, anchor, symbols):
        self.enabled = False
        for probe in self.probes:
            if probe.is_valid():
                probe.delete()
        self.probes = []
        if self.capture != capture:
            self.sequence, self.limited = 0, False
        self.capture, self.anchor = capture, anchor
        self.enabled = enabled
        unavailable = []
        if enabled and probes:
            for logical, spec in symbols[:24]:
                try:
                    self.probes.append(ApiProbe(self, logical, spec))
                except (gdb.error, TypeError) as exc:
                    unavailable.append(logical + ': ' + str(exc)[:120])
        gdb.write(PREFIX + json.dumps(dict(capture=capture, coverage=dict(enabled=enabled,
            probes=probes, installed=[p.logical for p in self.probes], unavailable=unavailable))) + '\n')


_observer = KodamaObserver()


def dbg3k_kodama_control(enabled, probes, capture, anchor, symbols):
    _observer.control(enabled, probes, capture, anchor, symbols)


def dbg3k_kodama_snapshot(stop):
    _observer.anchor = stop
    if _observer.enabled:
        _observer.emit('stop', stop)

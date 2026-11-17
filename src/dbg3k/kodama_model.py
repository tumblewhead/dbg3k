"""Kodama interpretation of observed data; independent of GDB and Textual.

History cells are samples, never reconstructed time intervals. Tokens include
generation; stale inactive fields cannot turn a freed slot into a waiting task.
"""
from collections import deque
from dataclasses import dataclass, field


def integer(node):
    try:
        return int(node['value'], 0) if node and node.get('status') == 'ok' else None
    except (TypeError, ValueError, KeyError):
        return None


def val(fields, name):
    return integer(fields.get(name))


@dataclass
class TaskState:
    slot: int
    generation: int | None
    token: int | None
    active: bool | None
    state: str
    name: str
    priority: int | None
    cluster: int | None
    promoted: int | None
    fields: dict
    subscription: dict | None
    address: int | None = None
    pool: int | None = None
    error: str = ''
    epoch: int = 0

    @property
    def key(self):
        return f'{self.slot}:{self.generation}' + (f'@e{self.epoch}' if self.epoch else '')

    @property
    def effective_cluster(self):
        return 0 if self.promoted == 1 else self.cluster


@dataclass
class PoolSlot:
    index: int
    address: str
    capacity: int
    extent: int
    used: bool | None
    owner: str | None
    name: str


@dataclass
class Sample:
    index: int
    sequence: int
    stop: int
    tick: int | None
    origin: str
    thread: str | None
    frame: dict
    core: dict
    tasks: list[TaskState]
    pool: list[PoolSlot]
    raw: dict
    event: dict | None
    notes: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    predicted: str | None = None
    decision: str = ''
    capture_gap: dict | None = None


def _friendly(symbol, fallback):
    if not symbol:
        return fallback
    return symbol.split('(')[0].split(' [clone')[0][:60]


def decode_sample(data, index):
    raw = data.get('state', {})
    core = {k: integer(v) for k, v in raw.get('core', {}).items()}
    notes = list(raw.get('errors', []))
    gap = data.get('capture_gap')
    if isinstance(gap, dict) and gap.get('reason') == 'api-budget':
        count = gap.get('skipped_probe_entries')
        missing = (f'{count} probe entries without state snapshots' if type(count) is int else
                   'omitted probe entry count unknown')
        notes.append(f'API capture gap after stop {gap.get("preceding_stop", "?")}: '
                     f'{missing}. Intermediate transitions are unavailable.')
    tasks = []
    for item in raw.get('tasks', []):
        slot, f = item['index'], item.get('fields', {})
        error = item.get('error', '')
        if 'identity' in f:
            identity = val(f, 'identity')
            generation = identity >> 8 if identity is not None else None
            active = bool(identity & 255) if identity is not None else None
            if active and (identity & 255 != slot + 1 or generation == 0):
                active, error = None, 'Invalid packed task identity'
            token = identity if active else None
        elif 'active' in f and 'generation' in f:
            a, generation = val(f, 'active'), val(f, 'generation')
            active = bool(a) if a in (0, 1) else None
            if active and (generation is None or not 0 < generation <= 0xffffff):
                active, error = None, 'Unavailable or invalid generation'
            token = generation << 8 | slot + 1 if active else None
        else:
            active, generation, token = None, None, None
            error = error or 'Unsupported or unavailable task identity layout'
        ready, sleeping = val(f, 'ready'), val(f, 'sleeping')
        waiting = val(f, 'waiting') if 'waiting' in f else (
            bool(val(f, 'subscription')) if val(f, 'subscription') is not None else None)
        if active is False:
            state = 'retired' if generation == 0xffffff else 'free'
        elif active is None:
            state = 'unknown'
        elif core.get('running') == token:
            exception = data.get('frame', {}).get('exception')
            state = 'interrupted' if exception is not None and int(exception) else 'running'
        elif sleeping == 1:
            state = 'sleeping'
        elif waiting:
            state = 'waiting'
        elif ready == 1:
            state = 'ready'
        elif ready == 0:
            state = 'parked'
        else:
            state = 'unknown'
        address = int(item['address'], 16) if item.get('address') else None
        tasks.append(TaskState(slot, generation, token, active, state,
            _friendly(item.get('step_symbol'), f'slot {slot}'), val(f, 'priority') if active is not False else None,
            val(f, 'cluster'), val(f, 'promoted'), f, item.get('subscription'), address=address, error=error))
    bindings = {}
    for command in raw.get('commands', []):
        token, pointer = integer(command.get('token')), integer(command.get('handle'))
        address = int(command['address'], 16)
        for task in tasks:
            if task.active and task.token == token and val(task.fields, 'context') == address and pointer:
                bindings.setdefault(pointer, []).append(task)
    pool = []
    for item in raw.get('pool', []):
        used = integer(item.get('used'))
        used = bool(used) if used in (0, 1) else None
        owners = bindings.get(int(item['data_address'], 16), []) if used else []
        owner = owners[0] if len(owners) == 1 else None
        name = _friendly(item.get('resume_symbol'), owner.name if owner else 'owner unknown')
        if owner:
            owner.pool, owner.name = item['index'], name
        pool.append(PoolSlot(item['index'], item['data_address'], item['capacity'], item['bytes'],
                             used, owner.key if owner else None, name if used else 'free' if used is False else 'unknown'))
        if len(owners) > 1:
            notes.append(f'Pool {item["index"]}: ambiguous binding ownership')
    sample = Sample(index, data['sample_seq'], data['stop'], core.get('clock_ticks'),
        data['origin'], data.get('thread'), data.get('frame', {}), core, tasks, pool, raw, data.get('event'), notes)
    sample.capture_gap = gap if isinstance(gap, dict) else None
    _decision(sample)
    return sample


def _decision(sample):
    tasks, core = sample.tasks, sample.core
    if core.get('running') is None:
        sample.decision = 'Running token unavailable; selection unknown'
        return
    if core['running']:
        task = next((t for t in tasks if t.active and t.token == core['running']), None)
        sample.decision = (f'{task.name} interrupted by exception {sample.frame.get("exception")}; dispatch deferred'
            if task and task.state == 'interrupted' else
            f'{task.name if task else "Unmatched token"} is executing; cooperative dispatch deferred')
    if core.get('destroying'):
        sample.decision = 'Destruction guard active; dispatch deferred'
    exception = sample.frame.get('exception')
    if exception is not None and int(exception) and not core.get('running'):
        sample.decision = f'Exception {exception} executing; thread-mode dispatch deferred'
    ready = [t for t in tasks if t.active and val(t.fields, 'ready') == 1]
    if (any(t.active is None or (t.active and val(t.fields, 'ready') not in (0, 1)) for t in tasks)
            or len(tasks) != sample.raw.get('task_capacity')):
        sample.decision = sample.decision or 'Incomplete task snapshot; next selection unknown'
        return
    if not ready:
        sample.decision = sample.decision or 'No ready task observed → dispatcher would return idle'
        return
    policy = any('cluster' in t.fields for t in tasks)
    if any(t.priority is None or (policy and (t.cluster not in (0, 1, 2) or t.promoted not in (0, 1))) for t in ready):
        sample.decision = sample.decision or 'Priority/rank unavailable; next selection unknown'
        return
    order = []
    head_node = sample.raw.get('core', {}).get('order_head')
    head = integer(head_node)
    lookup = {t.address: t for t in tasks} if head_node and head_node.get('encoding') == 'hex' else {t.slot: t for t in tasks}
    sentinel = 0 if head_node and head_node.get('encoding') == 'hex' else 255
    while head in lookup and head not in order:
        order.append(head)
        head = val(lookup[head].fields, 'next')
    order_known = (head == sentinel and {lookup[key].key for key in order} ==
                   {t.key for t in tasks if t.active is True})
    tie = {lookup[key].key: i for i, key in enumerate(order)}
    if not policy:
        tie = {t.key: t.slot for t in tasks}
        order_known = True
    ranked = sorted(ready, key=lambda t: (t.effective_cluster if policy else 0, t.priority, tie.get(t.key, 1000)))
    skip = core.get('yield_skip')
    if policy and skip is None:
        sample.candidates = [t.key for t in ranked]
        sample.decision = sample.decision or 'Yield deferral unavailable; ranked candidates only'
        return
    deferred = [t for t in ranked if t.token == skip]
    ranked = [t for t in ranked if t.token != skip] or deferred
    sample.candidates = [t.key for t in ranked]
    if policy and not order_known:
        sample.decision = sample.decision or 'Ready-field candidates only; stable scheduler list unavailable or transitional'
        return
    first = ranked[0]
    tied = [t for t in ranked if (t.effective_cluster if policy else 0, t.priority) ==
            (first.effective_cluster if policy else 0, first.priority)]
    if len(tied) > 1 and not order_known:
        sample.decision = sample.decision or 'Equal-rank candidates; list order unavailable'
        return
    if not sample.decision:
        sample.predicted = first.key
        sample.decision = f'Derived next candidate: {first.name} · ' + (
            'cluster/rank, priority, stable order, yield deferral' if policy else 'numeric priority, slot order (basic profile)')


class KodamaHistory:
    def __init__(self, limit=512):
        self.samples = deque(maxlen=limit)
        self.capture = None
        self.last_sequence = 0
        self.total = 0
        self.evicted = 0
        self.coverage = {}
        self.diagnostic = ''
        self.diagnostic_code = None
        self.labels = dict(signals=[], status='Signal names unavailable')
        self.names = {}
        self.epoch = 0
        self.generations = {}
        self.hidden_lanes = 0

    def reset(self, capture):
        self.samples.clear()
        self.capture, self.last_sequence = capture, 0
        self.total, self.evicted = 0, 0
        self.coverage, self.diagnostic = {}, ''
        self.diagnostic_code = None
        self.names.clear()
        self.epoch = 0
        self.generations.clear()

    def accept(self, data):
        if data.get('capture') != self.capture:
            return False
        if 'coverage' in data:
            self.coverage = data['coverage']
            budget = self.coverage.get('api_budget', {})
            if budget and not budget.get('exhausted') and self.diagnostic_code == 'api-budget':
                self.diagnostic, self.diagnostic_code = '', None
            return True
        if 'diagnostic' in data:
            self.diagnostic = data['diagnostic']
            self.diagnostic_code = data.get('diagnostic_code')
            return True
        if data.get('schema') != 'dbg3k.kodama.raw.v1':
            return False
        sequence = data.get('sample_seq')
        if type(sequence) is not int or sequence <= self.last_sequence:
            return False
        if (not isinstance(data.get('state'), dict) or
                (data.get('event') is not None and not isinstance(data['event'], dict))):
            return False
        sample = decode_sample(data, self.total + 1)
        if any(t.generation is not None and t.generation < self.generations.get(t.slot, 0) for t in sample.tasks):
            self.epoch += 1
            self.generations.clear()
            self.names.clear()
            sample.notes.append('Task generation regressed; new identity observation epoch (reset or discontinuity)')
        remap = {}
        for task in sample.tasks:
            old_key = task.key
            task.epoch = self.epoch
            remap[old_key] = task.key
            if task.generation is not None:
                self.generations[task.slot] = task.generation
        for pool in sample.pool:
            pool.owner = remap.get(pool.owner, pool.owner)
        sample.candidates = [remap[k] for k in sample.candidates]
        sample.predicted = remap.get(sample.predicted)
        if sequence > self.last_sequence + 1:
            sample.notes.append(f'{sequence - self.last_sequence - 1} collector samples unavailable before this point')
        self.last_sequence = sequence
        self.total += 1
        for task in sample.tasks:
            if task.key in self.names and (task.active is not True or task.name.startswith('resume_command')):
                task.name = self.names[task.key]
            elif task.active is True:
                self.names[task.key] = task.name
        if len(self.names) > 256:
            current = {t.key for t in sample.tasks}
            for key in list(self.names):
                if key not in current:
                    del self.names[key]
                if len(self.names) <= 256:
                    break
        if len(self.samples) == self.samples.maxlen:
            self.evicted += 1
        self.samples.append(sample)
        return True

    def mask_names(self, mask):
        if mask is None:
            return '?'
        if mask == 0:
            return '∅'
        names = []
        remaining = mask
        for bit in range(32):
            flag = 1 << bit
            if not mask & flag:
                continue
            aliases = [s['name'] for s in self.labels.get('signals', []) if int(s['mask'], 0) == flag]
            names.append('/'.join(aliases) if aliases else f'bit{bit}')
            remaining &= ~flag
        if remaining:
            names.append(hex(remaining))
        return ' + '.join(names)

    def wait_text(self, task, sample):
        if task.active is not True:
            return 'retired: generation exhausted' if task.state == 'retired' else 'inactive' if task.active is False else task.error or 'unknown'
        if task.state == 'sleeping':
            deadline = val(task.fields, 'deadline')
            return f'sleep until tick {deadline if deadline is not None else "?"} · now {sample.tick if sample.tick is not None else "?"}'
        if task.subscription and task.subscription.get('status') in ('ok', 'partial'):
            alternatives = []
            for alternative in task.subscription.get('alternatives', []):
                mask, kind = val(alternative, 'inputs'), val(alternative, 'kind')
                observed = sample.core.get('levels') if kind == 2 else val(task.fields, 'seen')
                missing = mask & ~observed if mask is not None and observed is not None else None
                label = 'level ALL' if kind == 2 else 'event ALL' if kind == 1 else 'event' if kind == 0 else '?'
                alternatives.append(f'{label}({self.mask_names(mask)}) [missing {self.mask_names(missing)}]')
            result = ' OR '.join(alternatives) or 'subscription fields unavailable'
            if task.subscription.get('status') == 'partial':
                result += f' OR … [truncated: {len(alternatives)}/{task.subscription.get("count", "?")} alternatives]'
            return result
        if task.state == 'waiting':
            return 'subscription read unavailable: ' + str((task.subscription or {}).get('error', 'missing fields'))
        wake = val(task.fields, 'wake_mask')
        return f'{task.state} · wake alternatives {hex(wake) if wake is not None else "?"} · seen {self.mask_names(val(task.fields, "seen"))}'

    def lanes(self):
        result = {}
        for sample in self.samples:
            for task in sample.tasks:
                if task.generation or task.active is None:
                    result[task.key] = task
        # Still show every currently unused slot, without a second empty lane
        # for an older pre-spawn generation0.
        if self.samples:
            for task in self.samples[-1].tasks:
                if task.key not in result:
                    result[task.key] = task
        self.hidden_lanes = 0
        if len(result) > 128:
            current = {t.key for t in self.samples[-1].tasks}
            newest, seen = [], set()
            for sample in reversed(self.samples):
                for task in sample.tasks:
                    if task.key in result and task.key not in seen:
                        newest.append(task.key)
                        seen.add(task.key)
            keep = current | set([k for k in newest if k not in current][:max(0, 128 - len(current))])
            self.hidden_lanes = len(result) - len(keep)
            result = {k: v for k, v in result.items() if k in keep}
        return sorted(result.values(), key=lambda t: (t.slot, t.epoch, t.generation or 0))

    def event_mask(self, sample):
        event = sample.event or {}
        arguments = event.get('arguments', {})
        return integer(arguments.get('occurrence')) or integer(arguments.get('level')) or 0


class KodamaJournal:
    """Rebuild one build/session/capture from the existing append-only journal."""
    def __init__(self, elf_hash, history, session=None):
        self.elf_hash, self.history, self.session = elf_hash, history, session
        self.selected = None
        self.sessions = {}
        self.configs = {}
        self.coverage = {}
        self.capture_order = {}
        self.order = 0

    def apply(self, record):
        if record.get('schema') != 'dbg3k.trace.v1':
            return False
        if type(record.get('seq')) is not int or record['seq'] <= 0:
            return False
        session, kind = record.get('session'), record.get('kind')
        if not isinstance(session, str) or (self.session and session != self.session):
            return False
        if kind == 'session_start':
            self.order += 1
            self.sessions[session] = (self.order, record.get('elf_sha256') == self.elf_hash)
            return False
        if session not in self.sessions or not self.sessions[session][1]:
            return False
        if kind == 'kodama_config':
            self.configs[(session, record.get('capture'))] = record
            self.capture_order.setdefault((session, record.get('capture')), record.get('seq', 0))
            return False
        if kind not in ('kodama_sample', 'kodama_coverage', 'kodama_diagnostic'):
            return False
        data = record.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('capture'), str):
            return False
        key = (session, data['capture'])
        self.capture_order.setdefault(key, record.get('seq', 0))
        if kind == 'kodama_coverage':
            self.coverage[key] = data.get('coverage', {})
        if self.selected and self.sessions[session][0] < self.sessions[self.selected][0]:
            return False
        if self.selected == session and self.history.capture and self.capture_order[key] < self.capture_order.get((session, self.history.capture), 0):
            return False
        if self.selected != session or self.history.capture != data['capture']:
            if kind != 'kodama_sample':
                return False
            self.selected = session
            self.history.reset(data['capture'])
            config = self.configs.get((session, data['capture']), {})
            self.history.labels = config.get('signal_labels', dict(signals=[], status='Recorded signal labels unavailable'))
            self.history.coverage = self.coverage.get(key, dict(enabled=False, probes=config.get('probes', False), installed=[]))
        try:
            return self.history.accept(data)
        except (KeyError, ValueError, TypeError, AttributeError):
            self.history.diagnostic = 'Malformed Kodama record skipped'
            return False

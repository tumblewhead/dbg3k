/* Pure evidence decoding. Shared by the file worker and Node regression tests. */
(function (root) {
  'use strict';
  function parse(text) {
    // JSON.parse would round full-width counters before a reviver could see them.
    // Quote only unsafe integral tokens, leaving quoted strings and floats intact.
    let out = '', at = 0;
    while (at < text.length) {
      const start = at, ch = text[at];
      if (ch === '"') {
        at++;
        while (at < text.length) {
          if (text[at++] === '\\') at++;
          else if (text[at - 1] === '"') break;
        }
        out += text.slice(start, at);
      } else if (ch === '-' || /[0-9]/.test(ch)) {
        const match = text.slice(at).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
        if (!match) throw Error('Invalid JSON number');
        const token = match[0]; at += token.length;
        out += !/[.eE]/.test(token) && !Number.isSafeInteger(Number(token)) ? JSON.stringify(token) : token;
      } else { out += ch; at++; }
    }
    return JSON.parse(out);
  }
  function integer(value) {
    if (typeof value === 'bigint') return value;
    if (typeof value === 'number') return Number.isSafeInteger(value) ? BigInt(value) : null;
    if (typeof value === 'string' && /^(?:-?\d+|0x[\da-f]+)$/i.test(value)) {
      try { return BigInt(value); } catch (_) { return null; }
    }
    return null;
  }
  function scalar(node) { return node && node.status === 'ok' ? integer(node.value) : null; }
  function small(node) { const v = scalar(node); return v !== null && v <= BigInt(Number.MAX_SAFE_INTEGER) && v >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(v) : null; }
  function friendly(value, fallback) { return typeof value === 'string' && value ? value.split('(')[0].split(' [clone')[0].slice(0, 120) : fallback; }
  function identity(item) {
    const f = item.fields || {}, slot = item.index;
    let active = null, generation = null, token = null;
    if (f.identity) {
      const v = small(f.identity);
      if (v !== null && v >= 0 && v <= 0xffffffff) {
        generation = Math.floor(v / 256); active = (v % 256) !== 0;
        if (active && (v % 256 !== slot + 1 || generation === 0)) active = null;
      }
    } else {
      const a = small(f.active); generation = small(f.generation);
      active = a === 0 ? false : a === 1 ? true : null;
      if (active && (generation === null || generation < 1 || generation > 0xffffff)) active = null;
    }
    if (active === true) token = BigInt(generation) * 256n + BigInt(slot + 1);
    return {active, generation, token};
  }
  function decode(data, epoch = 0, names = new Map()) {
    if (!data || data.schema !== 'dbg3k.kodama.raw.v1' || !data.state || !Array.isArray(data.state.tasks)) throw Error('Invalid Kodama sample');
    const raw = data.state, core = raw.core || {}, running = scalar(core.running);
    if (raw.tasks.length > 32 || (Array.isArray(raw.pool) && raw.pool.length > 64)) throw Error('Snapshot exceeds task/pool bounds');
    const taskSlots = new Set(), poolSlots = new Set();
    const tasks = raw.tasks.slice(0, 32).map(item => {
      if (!Number.isInteger(item.index) || item.index < 0 || item.index >= 32) throw Error('Invalid task slot');
      if (taskSlots.has(item.index)) throw Error('Duplicate task slot');
      taskSlots.add(item.index);
      const f = item.fields || {}, id = identity(item);
      const key = `${item.index}:${id.generation === null ? '?' : id.generation}@e${epoch}`;
      let state = 'unknown';
      if (id.active === false) state = id.generation === 0xffffff ? 'retired' : 'free';
      else if (id.active === true) {
        const waiting = f.waiting ? small(f.waiting) : (scalar(f.subscription) === null ? null : scalar(f.subscription) !== 0n);
        if (running === id.token) state = Number(data.frame?.exception || 0) ? 'interrupted' : 'running';
        else if (small(f.sleeping) === 1) state = 'sleeping';
        else if (waiting) state = 'waiting';
        else if (small(f.ready) === 1) state = 'ready';
        else if (small(f.ready) === 0) state = 'parked';
      }
      const name = friendly(item.step_symbol, names.get(key) || `slot ${item.index}`);
      return {slot: item.index, key, name, state, active: id.active, generation: id.generation,
        token: id.token?.toString() || null, priority: small(f.priority), cluster: small(f.cluster),
        promoted: small(f.promoted), seen: scalar(f.seen)?.toString() ?? null,
        wake: scalar(f.wake_mask)?.toString() ?? null, deadline: scalar(f.deadline)?.toString() ?? null,
        context: scalar(f.context)?.toString() ?? null, fields: f, subscription: item.subscription || null};
    });
    const commands = Array.isArray(raw.commands) ? raw.commands : [];
    const pool = (Array.isArray(raw.pool) ? raw.pool : []).slice(0, 64).map(item => {
      if (!Number.isInteger(item.index) || item.index < 0 || item.index >= 64 || poolSlots.has(item.index)) throw Error('Invalid/duplicate pool slot');
      poolSlots.add(item.index);
      const u = small(item.used), used = u === 1 ? true : u === 0 ? false : null;
      const matches = used ? tasks.filter(t => t.active === true && commands.some(c =>
        scalar(c.token)?.toString() === t.token && integer(c.address)?.toString() === t.context &&
        scalar(c.handle) === integer(item.data_address))) : [];
      const owner = matches.length === 1 ? matches[0] : null;
      if (owner) owner.name = friendly(item.resume_symbol, owner.name);
      return {slot: item.index, address: item.data_address, capacity: item.capacity, extent: item.bytes,
        used, owner: owner?.key || null, name: owner?.name || (used ? 'owner unavailable' : used === false ? 'free' : 'unavailable'),
        state: owner?.state || (used === false ? 'free' : used ? 'unattributed' : 'unknown')};
    });
    for (const task of tasks) {
      if (task.active === true && !task.name.startsWith('slot ')) names.set(task.key, task.name);
      else if (names.has(task.key)) task.name = names.get(task.key);
    }
    // Names aid snapshots; they must never become an unbounded second history.
    while (names.size > 4096) names.delete(names.keys().next().value);
    const levels = scalar(core.levels);
    return {sequence: data.sample_seq, stop: data.stop, origin: data.origin, frame: data.frame || {},
      tick: scalar(core.clock_ticks)?.toString() ?? null, levels: levels?.toString() ?? null,
      tasks, pool, event: data.event || null, gap: data.capture_gap || null,
      notes: Array.isArray(raw.errors) ? raw.errors : [], core,
      poolReserved: raw.pool_reserved_bytes ?? null, taskCapacity: raw.task_capacity ?? null};
  }
  function positiveModel(record) {
    return record && ['ua_per_mhz', 'mips_per_mhz', 'voltage'].every(k =>
      typeof record[k] === 'number' && Number.isFinite(record[k]) && record[k] > 0);
  }
  function validateProfile(record, hash, previous = null) {
    if (!hash || record.elf_sha256 !== hash || typeof record.run !== 'string' || !record.run ||
        !Number.isSafeInteger(record.profile_seq) || record.profile_seq < 0 || typeof record.complete !== 'boolean') throw Error('Invalid profile identity');
    const total = integer(record.total), unknown = integer(record.unknown);
    if (total === null || unknown === null || total < 0n || unknown < 0n || !record.functions ||
        Array.isArray(record.functions) || typeof record.functions !== 'object') throw Error('Invalid profile counters');
    let sum = unknown;
    for (const value of Object.values(record.functions)) {
      const count = integer(value); if (count === null || count < 0n) throw Error('Invalid function count'); sum += count;
    }
    if (sum !== total) throw Error('Profile totals do not reconcile');
    if (record.entry_hits !== undefined) {
      if (!record.entry_hits || Array.isArray(record.entry_hits) || typeof record.entry_hits !== 'object') throw Error('Invalid entry hits');
      for (const [key, value] of Object.entries(record.entry_hits)) {
        const count = integer(value);
        if (count === null || count < 0n || count > (integer(record.functions[key]) ?? 0n)) throw Error('Entry hits exceed dispatches');
      }
    }
    if (previous && previous.run === record.run && (record.profile_seq <= previous.profile_seq || total < integer(previous.total))) throw Error('Duplicate or regressed profile');
    return true;
  }
  function profileRows(record, catalog = new Map(), model = null, duration = null) {
    const total = integer(record.total), entriesAvailable = record.entry_hits !== undefined;
    const keys = new Set([...catalog.keys(), ...Object.keys(record.functions)]);
    const rows = [...keys].map(key => {
      const raw = Object.hasOwn(record.functions, key) ? record.functions[key] : 0;
      const meta = catalog.get(key), count = integer(raw);
      const match = key.match(/:0x[\da-f]+:(\d+)$/i);
      const inferred = match ? Number(match[1]) : null;
      const size = meta?.size ?? (Number.isSafeInteger(inferred) ? inferred : null);
      const entries = entriesAvailable ? integer(record.entry_hits[key] ?? 0) : null;
      return {key, name: meta?.names?.join(' / ') || key, size, count: count.toString(),
        entries: entries?.toString() ?? null,
        share: total > 0n ? Number(count * 1000000n / total) / 10000 : 0,
        density: size > 0 ? Number(count) / size : null,
        perEntry: entries > 0n ? Number(count) / Number(entries) : null,
        perMillion: entries !== null && total > 0n ? Number(entries * 1000000n) / Number(total) : null,
        hz: entries !== null && duration > 0 ? Number(entries) / duration : null,
        cycles: model ? Number(count) / model.mips_per_mhz : null,
        charge: model ? Number(count) * model.ua_per_mhz / model.mips_per_mhz : null,
        energy: model ? Number(count) * model.ua_per_mhz / model.mips_per_mhz * model.voltage : null};
    });
    const unknown = integer(record.unknown);
    if (unknown > 0n) rows.push({key: '?', name: 'Unattributed dispatches', count: unknown.toString(), entries: null,
      size: null, share: Number(unknown * 1000000n / total) / 10000,
      cycles: model ? Number(unknown) / model.mips_per_mhz : null,
      energy: model ? Number(unknown) * model.ua_per_mhz / model.mips_per_mhz * model.voltage : null,
      charge: model ? Number(unknown) * model.ua_per_mhz / model.mips_per_mhz : null});
    return rows;
  }
  function waitText(task, labels, sample) {
    const maskNames = raw => {
      const mask = integer(raw); if (mask === null) return '?'; if (!mask) return '∅';
      const result = [];
      for (let bit = 0; bit < 32; bit++) if (mask & (1n << BigInt(bit))) {
        const found = labels.filter(s => integer(s.mask) === (1n << BigInt(bit))).map(s => s.name);
        result.push(found.join('/') || `bit${bit}`);
      }
      return result.join(' + ');
    };
    if (task.state === 'sleeping') return `until tick ${task.deadline ?? '?'} (observed ${sample.tick ?? '?'})`;
    if (task.subscription && ['ok', 'partial'].includes(task.subscription.status)) {
      const text = (task.subscription.alternatives || []).slice(0, 16).map(a => {
        const mask = scalar(a.inputs), kind = small(a.kind), seen = integer(kind === 2 ? sample.levels : task.seen);
        const missing = mask !== null && seen !== null ? mask & ~seen : null;
        return `${kind === 2 ? 'level ALL' : kind === 1 ? 'event ALL' : 'event'}(${maskNames(mask)}) missing ${maskNames(missing)}`;
      }).join(' OR ');
      return text + (task.subscription.status === 'partial' ? ' … truncated' : '');
    }
    return task.state === 'waiting' ? 'subscription unavailable' : task.state;
  }
  const api = {parse, integer, scalar, small, identity, decode, positiveModel, validateProfile, profileRows, waitText};
  root.TraceModel = api;
  if (typeof module !== 'undefined') module.exports = api;
})(globalThis);

/* Streaming byte index. Raw snapshots stay in the selected File, not in RAM. */
if (typeof importScripts === 'function') importScripts('model.js');
const M = typeof TraceModel !== 'undefined' ? TraceModel : require('./model.js');
const MAX_LINE = 8 * 1024 * 1024, MAX_RECORDS = 2000000, MAX_SAMPLES = 1000000;
class TraceIndex {
  constructor(file) {
    this.file = file; this.sessions = new Map(); this.errors = []; this.errorCount = 0;
    this.lines = 0; this.indexed = 0; this.finished = false;
    this.cache = new Map(); this.cacheBytes = 0; this.fileReads = 0;
  }
  issue(message) { this.errorCount++; if (this.errors.length < 100) this.errors.push(message); }
  async read(ref) {
    const cached = this.cache.get(ref.start);
    if (cached) {
      this.cache.delete(ref.start); this.cache.set(ref.start, cached);
      return cached.record;
    }
    const record = M.parse(await this.file.slice(ref.start, ref.end).text());
    this.fileReads++;
    const bytes = ref.end - ref.start;
    // Repeated cursor/nearby-window reads are common during a trackpad gesture.
    // Bound this acceleration cache independently of the durable file index.
    const previous = this.cache.get(ref.start);
    if (previous) this.cacheBytes -= previous.bytes;
    this.cache.set(ref.start, {record, bytes}); this.cacheBytes += bytes;
    while (this.cache.size > 1024 || this.cacheBytes > 16 * 1024 * 1024) {
      const key = this.cache.keys().next().value;
      this.cacheBytes -= this.cache.get(key).bytes; this.cache.delete(key);
    }
    return record;
  }
  async scan(progress = () => {}) {
    const reader = this.file.stream().getReader();
    let pending = new Uint8Array(), base = 0, oversized = false, bytes = 0, lastProgress = 0;
    const decoder = new TextDecoder('utf-8', {fatal: true});
    const line = (array, start, end, final = false) => {
      this.lines++;
      if (!array.length || array.every(c => c === 13 || c === 32 || c === 9)) return;
      try {
        const record = M.parse(decoder.decode(array));
        this.accept(record, {start, end});
        if (final) this.issue('Final JSON object has no newline; indexed, but file may still be growing.');
      } catch (error) {
        if (error.message === 'INDEX_LIMIT' || error.message === 'SAMPLE_LIMIT') {
          throw Error('Recording exceeds the explicit index limit; import stopped. No partial history is presented as complete.');
        }
        this.issue(`Line ${this.lines}: ${error.message}${final ? ' (interrupted tail)' : ''}`);
      }
    };
    try {
      while (true) {
        const {value, done} = await reader.read(); if (done) break;
        const chunk = new Uint8Array(pending.length + value.length);
        chunk.set(pending); chunk.set(value, pending.length); bytes += value.length;
        let start = 0;
        for (let i = 0; i < chunk.length; i++) if (chunk[i] === 10) {
          if (oversized || i - start > MAX_LINE) {
            this.lines++; this.issue(`Line ${this.lines} exceeds 8 MiB; omitted explicitly.`);
          } else line(chunk.subarray(start, i), base + start, base + i);
          oversized = false; start = i + 1;
        }
        base += start;
        pending = chunk.slice(start);
        if (pending.length > MAX_LINE) { oversized = true; base += pending.length; pending = new Uint8Array(); }
        if (bytes - lastProgress > 4 * 1024 * 1024) {
          progress({bytes, size: this.file.size, indexed: this.indexed}); lastProgress = bytes;
        }
      }
      if (oversized) this.issue('Oversized interrupted final line omitted.');
      else if (pending.length) line(pending, base, base + pending.length, true);
      this.finished = true;
    } finally { reader.releaseLock(); }
    return this.summary();
  }
  session(id) {
    if (!this.sessions.has(id)) this.sessions.set(id, {id, meta: null, last: 0, records: [], captures: new Map(),
      profiles: [], runs: new Map(), models: [], catalog: new Map(), catalogChunks: new Set(),
      catalogExpected: null, stacks: [], observed: [], stops: [], errors: [], hash: null});
    return this.sessions.get(id);
  }
  accept(r, location) {
    if (!r || Array.isArray(r) || r.schema !== 'dbg3k.trace.v1') { this.issue(`Line ${this.lines}: unsupported schema`); return; }
    if (typeof r.session !== 'string' || !r.session || r.session.length > 256 ||
        !Number.isSafeInteger(r.seq) || r.seq <= 0 || typeof r.kind !== 'string') throw Error('Invalid journal envelope');
    if (++this.indexed > MAX_RECORDS) throw Error('INDEX_LIMIT');
    const s = this.session(r.session);
    if (r.seq <= s.last) { this.issue(`Session ${s.id.slice(0, 8)}: duplicate/regressed seq ${r.seq} omitted`); return; }
    if (s.last && r.seq > s.last + 1) this.issue(`Session ${s.id.slice(0, 8)}: journal seq gap ${s.last} → ${r.seq}`);
    s.last = r.seq;
    const ref = {...location, seq: r.seq, kind: r.kind, stop: r.stop ?? null};
    s.records.push(ref);
    if (r.kind === 'session_start') {
      const hash = r.elf_sha256 || r.executable?.sha256 || null;
      if (s.meta) { s.hash = null; s.errors.push('Repeated session start; build identity ambiguous.'); }
      else { s.meta = r; s.hash = typeof hash === 'string' ? hash : null; }
    } else if (r.kind === 'code_catalog') {
      if (r.catalog_version !== 1 || !s.hash || r.elf_sha256 !== s.hash || !Array.isArray(r.functions) || r.functions.length > 128 ||
          !Number.isInteger(r.chunk_index) || r.chunk_index < 0 || !Number.isInteger(r.chunk_count) || r.chunk_count < 1 ||
          r.chunk_count > 4096 || r.chunk_index >= r.chunk_count) throw Error('Invalid catalog chunk/build');
      if (s.catalogExpected !== null && s.catalogExpected !== r.chunk_count) throw Error('Conflicting catalog chunk count');
      if (s.catalogChunks.has(r.chunk_index)) throw Error('Duplicate catalog chunk');
      const chunkKeys = new Set();
      const functions = r.functions.map(f => {
        if (typeof f.key !== 'string' || !Array.isArray(f.names) || !f.names.length || !f.names.every(n => typeof n === 'string') ||
            !Number.isSafeInteger(f.size) || f.size <= 0 || typeof f.start !== 'string' || M.integer(f.start) === null ||
            f.key !== `${f.section}:${f.start}:${f.size}` || s.catalog.has(f.key) || chunkKeys.has(f.key)) throw Error('Invalid emitted body');
        chunkKeys.add(f.key);
        return [f.key, f];
      });
      s.catalogExpected = r.chunk_count; s.catalogChunks.add(r.chunk_index);
      for (const [key, f] of functions) s.catalog.set(key, f);
    } else if (r.kind === 'instruction_profile') {
      M.validateProfile(r, s.hash, s.runs.get(r.run));
      s.runs.set(r.run, {run: r.run, profile_seq: r.profile_seq, total: r.total});
      s.profiles.push({...ref, run: r.run, profileSeq: r.profile_seq, total: String(r.total), complete: r.complete});
    } else if (r.kind === 'energy_model') {
      if (!M.positiveModel(r) || (r.elf_sha256 != null && r.elf_sha256 !== s.hash) || !s.hash) throw Error('Invalid energy model/build');
      s.models.push({seq: r.seq, ua_per_mhz: r.ua_per_mhz, mips_per_mhz: r.mips_per_mhz,
        voltage: r.voltage, source: r.source || 'Recorded assumptions'});
    } else if (r.kind.startsWith('kodama_')) {
      const d = r.data, capture = r.kind === 'kodama_config' ? r.capture : d?.capture;
      if (typeof capture !== 'string' || capture.length > 256) throw Error('Missing capture identity');
      if (!s.captures.has(capture)) s.captures.set(capture, {id: capture, samples: [], labels: [], labelStatus: 'No recorded labels',
        coverage: null, diagnostics: [], epochs: 0, generations: new Map(), names: new Map(), slots: new Map(), last: 0, gaps: 0});
      const c = s.captures.get(capture);
      if (r.kind === 'kodama_config') {
        c.labels = Array.isArray(r.signal_labels?.signals) ? r.signal_labels.signals.slice(0, 64).filter(v =>
          typeof v.name === 'string' && M.integer(v.mask) !== null && M.integer(v.mask) > 0n && M.integer(v.mask) <= 0x80000000n) : [];
        c.labelStatus = r.signal_labels?.status || 'No recorded labels';
      } else if (r.kind === 'kodama_coverage') c.coverage = d.coverage;
      else if (r.kind === 'kodama_diagnostic') {
        if (c.diagnostics.length < 100) c.diagnostics.push(String(d.diagnostic));
      } else if (r.kind === 'kodama_sample') {
        if (!Number.isSafeInteger(d.sample_seq) || d.sample_seq <= c.last || !Number.isSafeInteger(d.stop)) throw Error('Duplicate/invalid sample sequence');
        if (c.samples.length >= MAX_SAMPLES) throw Error('SAMPLE_LIMIT');
        const decoded = M.decode(d, c.epochs, c.names);
        if (decoded.tasks.some(t => t.generation !== null && t.generation < (c.generations.get(t.slot) || 0))) {
          c.epochs++; c.generations.clear(); c.names.clear();
        }
        for (const t of decoded.tasks) {
          if (t.generation !== null) c.generations.set(t.slot, t.generation);
          if (t.active === true) c.slots.set(t.slot, t.name);
        }
        const gap = !!d.capture_gap || d.sample_seq > c.last + 1;
        if (gap) c.gaps++;
        c.samples.push({...ref, sampleSeq: d.sample_seq, tick: decoded.tick, epoch: c.epochs,
          origin: d.origin, gap, stop: d.stop}); c.last = d.sample_seq;
      }
    } else if (r.kind === 'stack_sample') s.stacks.push(ref);
    else if (r.kind === 'stop') s.stops.push(ref);
    else if (['observation', 'locals', 'global_value', 'return', 'frames'].includes(r.kind)) s.observed.push(ref);
  }
  summary() {
    return {name: this.file.name || 'recording.jsonl', size: this.file.size, lines: this.lines,
      indexed: this.indexed, errors: this.errors, errorCount: this.errorCount,
      sessions: [...this.sessions.values()].map(s => ({id: s.id, meta: s.meta, hash: s.hash,
        recordCount: s.records.length, profiles: s.profiles.map(({start, end, ...r}) => r),
        models: s.models, errors: s.errors, catalogBodies: s.catalog.size,
        catalogComplete: s.catalogExpected !== null && s.catalogChunks.size === s.catalogExpected,
        captures: [...s.captures.values()].map(c => ({id: c.id, count: c.samples.length,
          gaps: c.gaps, labels: c.labels, labelStatus: c.labelStatus, coverage: c.coverage,
          diagnostics: c.diagnostics, slots: [...c.slots],
          stops: c.samples.map((r, i) => ({index: i, stop: r.stop, origin: r.origin})).filter((r, i, a) => !i || r.stop !== a[i - 1].stop),
          overview: Array.from({length: Math.min(500, c.samples.length)}, (_, n) => {
            const a = Math.floor(n * c.samples.length / Math.min(500, c.samples.length));
            const b = Math.floor((n + 1) * c.samples.length / Math.min(500, c.samples.length));
            return {api: c.samples.slice(a, b).filter(r => r.origin === 'api').length, gap: c.samples.slice(a, b).some(r => r.gap)};
          })}))}))};
  }
  async view(session, capture, start, count, selected, cancelled = () => false) {
    const s = this.sessions.get(session), c = s?.captures.get(capture);
    if (!c) throw Error('Capture unavailable');
    start = Math.max(0, Math.min(c.samples.length - 1, Math.trunc(start) || 0));
    count = Math.max(1, Math.min(512, Math.trunc(count) || 128));
    const refs = c.samples.slice(start, start + count), names = new Map();
    const samples = [];
    for (let offset = 0; offset < refs.length; offset += 16) {
      if (cancelled()) throw Error('Superseded viewport');
      const batch = await Promise.all(refs.slice(offset, offset + 16).map(r => this.read(r)));
      for (let i = 0; i < batch.length; i++) {
        const ref = refs[offset + i], d = M.decode(batch[i].data, ref.epoch, names);
        d.journalSeq = ref.seq; d.gap = batch[i].data.capture_gap || (ref.gap ? {reason: 'sample-sequence-gap'} : null);
        samples.push(d);
      }
    }
    const selectedIndex = Math.max(0, Math.min(c.samples.length - 1, Math.trunc(selected) || 0));
    const ref = c.samples[selectedIndex];
    let detail = null, stack = null;
    if (ref) {
      const r = await this.read(ref); detail = M.decode(r.data, ref.epoch, names); detail.journalSeq = ref.seq;
      detail.gap = r.data.capture_gap || (ref.gap ? {reason: 'sample-sequence-gap'} : null);
      const stackRef = s.stacks.findLast(r => r.seq <= ref.seq);
      if (stackRef) stack = await this.read(stackRef);
    }
    return {start, selected: selectedIndex, count: c.samples.length, samples, detail, stack};
  }
  async profile(session, index) {
    const s = this.sessions.get(session), ref = s?.profiles[index];
    if (!ref) return null;
    const record = await this.read(ref); M.validateProfile(record, s.hash);
    const model = s.models.findLast(m => m.seq <= ref.seq) || null;
    return {record, catalog: [...s.catalog], model};
  }
  async record(session, seq, direction = 0, kind = '') {
    const s = this.sessions.get(session);
    const records = s?.records.filter(r => !kind || r.kind === kind) || [];
    const ref = direction < 0 ? records.findLast(r => r.seq < seq) :
      direction > 0 ? records.find(r => r.seq > seq) : s?.records.find(r => r.seq === seq);
    if (!ref) throw Error('Record not found');
    return this.read(ref);
  }
}
if (typeof module !== 'undefined') module.exports = {TraceIndex};
if (typeof self !== 'undefined' && typeof self.postMessage === 'function') {
  let index = null, latestView = 0;
  self.onmessage = async ({data}) => {
    const {id, type} = data;
    try {
      let result;
      if (type === 'load') { index = new TraceIndex(data.file); result = await index.scan(p => self.postMessage({type: 'progress', ...p})); }
      else if (!index?.finished) throw Error('Select a complete file first');
      else if (type === 'view') {
        latestView = id;
        result = await index.view(data.session, data.capture, data.start, data.count, data.selected, () => latestView !== id);
      }
      else if (type === 'profile') result = await index.profile(data.session, data.index);
      else if (type === 'record') {
        const record = await index.record(data.session, data.seq, data.direction, data.kind);
        const ref = index.sessions.get(data.session).records.find(r => r.seq === record.seq);
        result = {record, raw: await index.file.slice(ref.start, ref.end).text()};
      }
      else throw Error('Unknown request');
      self.postMessage({id, type, result});
    } catch (error) { self.postMessage({id, type: 'error', error: error.message}); }
  };
}

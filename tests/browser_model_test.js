'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const M = require('../src/dbg3k/browser/model.js');
const {TraceIndex} = require('../src/dbg3k/browser/worker.js');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
(async () => {
  assert.equal(M.parse('{"n":9007199254740993123,"quoted":"9007199254740993123","f":1.25,"neg":-9007199254740993123}').n, '9007199254740993123');
  assert.equal(M.parse('{"n":-9007199254740993123}').n, '-9007199254740993123');
  assert.equal(M.integer(M.parse('{"p":"0xffffffffffffffff"}').p), 18446744073709551615n);
  assert.equal(M.scalar({status: 'unavailable', value: '0'}), null);
  assert.deepEqual(M.estimates(100, {mips_per_mhz: 2}), {cycles: 50, charge: null, energy: null, power: null});
  assert.deepEqual(M.estimates(100, {mips_per_mhz: 0}), {cycles: null, charge: null, energy: null, power: null});
  assert.equal(M.estimates(100, {mips_per_mhz: 2, ua_per_mhz: 48, voltage: 1.8}, 2).power, .00216);
  let seq = 0;
  const lines = [];
  const add = (kind, fields = {}, session = 'one') => lines.push(JSON.stringify({schema: 'dbg3k.trace.v1', session, seq: ++seq, kind, ...fields}) + '\n');
  add('session_start', {elf_sha256: 'hash', target: '<img src=x onerror=alert(1)>'});
  add('code_catalog', {catalog_version: 1, elf_sha256: 'hash', chunk_index: 0, chunk_count: 1,
    functions: [{key: '.text:0x10000000:10', section: '.text', start: '0x10000000', size: 10, names: ['worker<script>']}]});
  add('energy_model', {ua_per_mhz: 48, mips_per_mhz: 1, voltage: 1.8, elf_sha256: 'hash', source: 'Illustrative test inputs'});
  add('kodama_config', {capture: 'fixture', signal_labels: {status: 'Fixture labels', signals: [{name: 'A', mask: '0x1'}]}});
  for (let i = 1; i <= 6200; i++) {
    const d = JSON.parse(JSON.stringify(fixture)); d.sample_seq = i; d.stop = Math.floor((i - 1) / 1000) + 1;
    d.origin = i % 1000 ? 'api' : 'stop'; d.state.core.clock_ticks.value = String(i);
    if (i === 5000) d.capture_gap = {reason: 'api-budget', skipped_probe_entries: 80};
    add('kodama_sample', {data: d});
  }
  const profile = {elf_sha256: 'hash', run: 'qemu-one', profile_seq: 1, total: '9007199254740993123', unknown: '3', complete: false,
    functions: {'.text:0x10000000:10': '9007199254740993120'}, entry_hits: {'.text:0x10000000:10': 2}};
  add('instruction_profile', profile);
  // Exercise an original JSON numeric token beyond Number's exact range.
  lines[lines.length - 1] = lines.at(-1).replace('"total":"9007199254740993123"', '"total":9007199254740993123');
  add('instruction_profile', profile); // Duplicate cumulative snapshot must not be added again.
  add('instruction_profile', {...profile, profile_seq: 2, total: 2, unknown: 0}); // Invalid total.
  add('instruction_profile', {...profile, elf_sha256: 'other', profile_seq: 3});
  add('stack_sample', {stop: 7, frames: [{level: 0, function: 'worker', pc: 0x10000000, sp: 0x3800ffe0, kind: 'normal'}]});
  add('observation', {stop: 7, status: 'error', expression: 'missing', errors: [{message: 'not found'}]});
  const reset = JSON.parse(JSON.stringify(fixture)); reset.sample_seq = 6201; reset.stop = 7;
  reset.state.tasks[0].fields.generation.value = '0'; reset.state.tasks[0].fields.active.value = '0';
  add('kodama_sample', {data: reset});
  add('kodama_config', {capture: 'second', signal_labels: {signals: []}});
  add('kodama_sample', {data: {...fixture, capture: 'second'}});
  // A separate session can use the same local seqs without borrowing any model.
  let twoSeq = 1;
  lines.push(JSON.stringify({schema: 'dbg3k.trace.v1', kind: 'session_start', session: 'two', seq: twoSeq++, elf_sha256: 'other'}) + '\n');
  lines.push(JSON.stringify({schema: 'dbg3k.trace.v1', kind: 'instruction_profile', session: 'two', seq: twoSeq++, ...profile, elf_sha256: 'other', total: 10, unknown: 0, functions: {'.text:0x10000000:10': 10}}) + '\n');
  lines.push('not-json\n{"interrupted":');
  const file = new Blob(lines); file.name = 'large-fixture.jsonl';
  const index = new TraceIndex(file); const summary = await index.scan();
  assert.equal(summary.sessions.length, 2);
  assert.equal(summary.sessions[0].captures[0].count, 6201);
  assert.equal(summary.sessions[0].profiles.length, 1);
  assert.equal(summary.sessions[0].catalogComplete, true);
  assert.equal(summary.sessions[1].models.length, 0);
  assert.ok(summary.errorCount >= 5);
  const first = await index.view('one', 'fixture', 0, 32, 0);
  const reads = index.fileReads;
  await index.view('one', 'fixture', 1, 32, 1);
  assert.equal(index.fileReads - reads, 1, 'Adjacent pan rereads only the entering record');
  assert.ok(index.cache.size <= 1024 && index.cacheBytes <= 16 * 1024 * 1024);
  const last = await index.view('one', 'fixture', 6199, 32, 6200);
  const middle = await index.view('one', 'fixture', 4990, 32, 4999);
  assert.equal(first.detail.sequence, 1); assert.equal(last.detail.sequence, 6201);
  assert.equal(last.detail.tasks[0].key, '0:0@e1');
  assert.equal(middle.detail.gap.skipped_probe_entries, 80);
  assert.equal(first.detail.tasks[1].state, 'waiting');
  assert.equal(first.detail.pool[0].owner, '1:1@e0');
  assert.match(M.waitText(first.detail.tasks[1], [{name: 'A', mask: '1'}, {name: 'B', mask: '2'}], first.detail), /missing B/);
  const p = await index.profile('one', 0), rows = M.profileRows(p.record, new Map(p.catalog), p.model, 2);
  assert.equal(rows[0].name, 'worker<script>');
  assert.equal(rows[0].count, '9007199254740993120');
  assert.equal(rows[0].entries, '2'); assert.equal(rows[0].hz, 1);
  assert.equal(rows[0].energy, Number(9007199254740993120n) * 48 * 1.8);
  assert.equal(rows[1].name, 'Unattributed dispatches');
  assert.equal(M.profileRows({...p.record, entry_hits: undefined})[0].entries, null);
  assert.equal((await index.profile('two', 0)).model, null);
  assert.equal((await index.record('one', 1, 1, 'observation')).kind, 'observation');
  assert.equal((await index.record('one', 1)).kind, 'session_start');
  // Chunk boundaries may divide a multibyte UTF-8 name or any JSON token.
  const unicode = JSON.stringify({schema: 'dbg3k.trace.v1', session: 'utf', seq: 1, kind: 'session_start', target: '木霊'}) + '\n';
  const bytes = new TextEncoder().encode(unicode);
  const chunked = {size: bytes.length, name: 'unicode', slice: (a, b) => new Blob([bytes.slice(a, b)]),
    stream: () => new ReadableStream({start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close(); }})};
  assert.equal((await new TraceIndex(chunked).scan()).sessions[0].meta.target, '木霊');
  const oversized = new Blob([' '.repeat(8 * 1024 * 1024 + 1), '\n', unicode]);
  const oversizedSummary = await new TraceIndex(oversized).scan();
  assert.equal(oversizedSummary.sessions[0].meta.target, '木霊'); assert.equal(oversizedSummary.errorCount, 1);
  if (process.env.DBG3K_BROWSER_FIXTURE) fs.writeFileSync(process.env.DBG3K_BROWSER_FIXTURE, Buffer.concat(lines.slice(0, -1).map(v => Buffer.from(v))));
  console.log('Browser model/index checks passed: 6201 samples, full-width counters, generations, gaps, sessions, errors and profiles.');
})().catch(error => { console.error(error); process.exitCode = 1; });

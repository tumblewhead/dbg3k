/* Browser frontend. Trace text is always rendered as text, never HTML. */
'use strict';
const $ = id => document.getElementById(id), M = TraceModel;
let worker = null, requestId = 0, pending = new Map(), summary = null;
let session = null, capture = null, view = null, cursor = 0, start = 0, columns = 128;
let profile = null, profileIndex = -1, rows = [], functionPage = 0, override = false, localModel = null;
let modelDuration = null, rawRecord = null, rawText = '', viewGeneration = 0, profileGeneration = 0, recordGeneration = 0;
const PAGE = 75, LABEL_WIDTH = 215, ROW = 25;
function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
function element(tag, text, className) { const e = document.createElement(tag); if (text !== undefined) e.textContent = String(text); if (className) e.className = className; return e; }
function option(text, value) { const e = element('option', text); e.value = String(value); return e; }
function pretty(value) { return JSON.stringify(value, (_, v) => typeof v === 'bigint' ? v.toString() : v, 2); }
function count(value) { return value === null || value === undefined ? '—' : String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
function number(value) { return value === null || value === undefined || !Number.isFinite(value) ? '—' : value.toLocaleString(undefined, {maximumFractionDigits: 2}); }
function scaled(value, unit) {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'Unavailable';
  const groups = [[1e12, ''], [1e9, 'm'], [1e6, 'µ'], [1e3, 'n'], [1, 'p']];
  const [scale, prefix] = groups.find(([scale]) => Math.abs(value) >= scale) || groups[4];
  return `${number(value / scale)} ${prefix}${unit}`;
}
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim(); }
function stateColor(state) { return css(['running', 'ready', 'waiting', 'sleeping', 'parked', 'free'].includes(state) ? state : state === 'retired' ? 'free' : 'unknown'); }
function rpc(type, args = {}) {
  const id = ++requestId;
  return new Promise((resolve, reject) => { pending.set(id, {resolve, reject}); worker.postMessage({id, type, ...args}); });
}
function tab(name) {
  document.querySelectorAll('.tab-panel').forEach(e => { e.hidden = e.id !== name; });
  document.querySelectorAll('[data-tab]').forEach(e => e.setAttribute('aria-selected', String(e.dataset.tab === name)));
  if (name === 'timeline') requestAnimationFrame(drawTimeline);
}
async function openFile(file) {
  if (!file) return;
  if (worker) worker.terminate();
  for (const p of pending.values()) p.reject(Error('Recording changed'));
  pending = new Map(); viewGeneration++; profileGeneration++; recordGeneration++;
  summary = session = capture = view = profile = rawRecord = null; rawText = ''; rows = [];
  $('workspace').hidden = true; $('intro').hidden = false; $('progress').hidden = false;
  $('progress').value = 0; status(`Indexing ${file.name} locally…`);
  worker = new Worker('worker.js');
  worker.onmessage = ({data}) => {
    if (data.type === 'progress') {
      $('progress').value = data.size ? data.bytes * 100 / data.size : 0;
      status(`Indexing locally · ${number(data.bytes / 1048576)} / ${number(data.size / 1048576)} MiB · ${count(data.indexed)} records`);
      return;
    }
    const p = pending.get(data.id); if (!p) return; pending.delete(data.id);
    if (data.type === 'error') p.reject(Error(data.error)); else p.resolve(data.result);
  };
  worker.onerror = error => {
    for (const p of pending.values()) p.reject(Error(error.message || 'File worker failed'));
    pending.clear(); status('File worker failed. Reopen the recording to retry.', true);
  };
  try {
    summary = await rpc('load', {file});
    if (!summary.sessions.length) throw Error('No dbg3k.trace.v1 sessions found. See the file format in the capture guide.');
    $('session').replaceChildren(...summary.sessions.map(s => option(`${s.meta?.target || 'Unknown target'} · ${s.id.slice(0, 12)} · ${count(s.recordCount)} records`, s.id)));
    $('session').value = summary.sessions.at(-1).id;
    $('workspace').hidden = false; $('intro').hidden = true; $('progress').hidden = true;
    status(`${summary.name} · ${number(summary.size / 1048576)} MiB · ${count(summary.indexed)} journal records indexed${summary.errorCount ? ` · ${count(summary.errorCount)} diagnostics (Coverage tab)` : ''}`);
    await changeSession();
  } catch (error) { $('progress').hidden = true; status(`Cannot open recording: ${error.message}`, true); }
}
async function changeSession() {
  viewGeneration++; profileGeneration++; recordGeneration++;
  session = summary.sessions.find(s => s.id === $('session').value);
  override = false; localModel = null; modelDuration = null; $('duration').value = '';
  $('identity').textContent = `${session.meta?.elf || 'Executable path unavailable'}\nSHA256 ${session.hash || 'unavailable'} · ${session.catalogBodies} named bodies`;
  $('capture').replaceChildren(...session.captures.map(c => option(`${c.id.slice(0, 12)} · ${count(c.count)} samples`, c.id)));
  if (!session.captures.length) $('capture').append(option('No scheduler samples recorded', ''));
  else $('capture').value = session.captures.at(-1).id;
  $('profile-snapshot').replaceChildren(...session.profiles.map((p, i) => option(`Run ${p.run.slice(0, 8)} · snapshot ${p.profileSeq} · ${count(p.total)} dispatches${p.complete ? ' · complete' : ''}`, i)));
  $('profile-snapshot').prepend(option(session.profiles.length ? 'No profile received before cursor' : 'No instruction profile recorded', -1));
  profileIndex = session.profiles.length - 1; $('profile-snapshot').value = profileIndex;
  $('record-kind').replaceChildren(option('All record kinds', ''));
  // These are filters, not executable handlers. The inspector can still open any seq.
  for (const kind of ['kodama_sample', 'stop', 'stack_sample', 'instruction_profile', 'energy_model', 'code_catalog', 'observation', 'global_value', 'locals', 'return', 'frames', 'gdb_error']) $('record-kind').append(option(kind, kind));
  $('raw').textContent = 'Select a record.'; $('record-label').textContent = ''; rawRecord = null; rawText = '';
  await Promise.all([changeCapture(), loadProfile()]);
}
async function changeCapture() {
  capture = session.captures.find(c => c.id === $('capture').value) || null;
  cursor = 0; start = 0; view = null;
  $('sample-count').textContent = capture ? count(capture.count) : '0';
  $('profile-cursor').disabled = !capture?.count;
  $('pan').max = Math.max(0, (capture?.count || 0) - 1); $('pan').value = 0;
  $('jump').max = Math.max(1, capture?.count || 0); $('jump').value = 1;
  coverage();
  if (capture?.count) await loadView();
  else {
    $('range-label').textContent = 'No scheduler observations'; $('tasks').replaceChildren(); $('pool').replaceChildren();
    $('sample-detail').textContent = 'This file may contain profiling only. For lanes, enable Kodama capture in dbg3k. For intermediate activity, enable API probes.';
    $('cursor-label').textContent = 'Unavailable'; $('pool-total').textContent = 'Unavailable'; $('pool-note').textContent = '';
    drawTimeline(); drawStack(null);
  }
}
async function loadView() {
  if (!capture?.count) return;
  const generation = ++viewGeneration;
  try {
    const result = await rpc('view', {session: session.id, capture: capture.id, start, count: columns, selected: cursor});
    if (generation !== viewGeneration) return;
    view = result; start = result.start; cursor = result.selected;
    $('pan').value = start; $('jump').value = cursor + 1;
    $('range-label').textContent = `${count(start + 1)}–${count(start + result.samples.length)} of ${count(capture.count)}`;
    $('cursor-label').textContent = `Sample ${count(cursor + 1)} / collector #${view.detail.sequence} · stop ${view.detail.stop} · journal #${view.detail.journalSeq} · tick ${view.detail.tick ?? '?'}`;
    details(); drawTimeline(); drawStack(result.stack);
  } catch (error) { if (generation === viewGeneration) status(`Cannot read viewport: ${error.message}`, true); }
}
function go(index, panOnly = false) {
  if (!capture?.count) return;
  index = Math.max(0, Math.min(capture.count - 1, Math.round(index)));
  cursor = index;
  if (panOnly || index < start || index >= start + columns) start = Math.max(0, index - (panOnly ? 0 : Math.floor(columns / 2)));
  loadView();
}
function details() {
  const d = view.detail, event = d.event;
  const lines = [`${d.origin === 'api' ? 'API entry observation' : 'Debugger-stop observation'} · ${d.frame.function || 'function unavailable'}`];
  const running = M.scalar(d.core.running);
  const active = d.tasks.find(t => M.integer(t.token) === running && t.active === true);
  lines.push(`Running token: ${running === null ? 'unavailable' : running === 0n ? 'none' : `${running}${active ? ' · ' + active.name : ' · owner unavailable'}`} · levels: ${d.levels === null ? 'unavailable' : '0x' + BigInt(d.levels).toString(16)}`);
  lines.push(`Observed ready states: ${d.tasks.filter(t => t.state === 'ready').map(t => t.name).join(', ') || 'none'}. This is a snapshot, not a prediction of the next dispatch.`);
  if (event) lines.push(`${event.semantics || 'API request'}: ${event.function || '?'}\n${Object.entries(event.arguments || {}).map(([k, v]) => {
    const pointer = M.scalar(v);
    const matches = pointer ? d.tasks.filter(t => t.active === true && (
      (k === 'context' && M.integer(t.context) === pointer) ||
      (k === 'sub' && M.scalar(t.fields.subscription) === pointer))) : [];
    const alias = matches.length === 1 ? ` · ${matches[0].name} [${matches[0].key}]` : '';
    return `${k}=${v.status === 'ok' ? v.value : `[${v.status || 'unavailable'}]`}${alias}`;
  }).join(' · ')}`);
  if (d.frame.exception && Number(d.frame.exception)) lines.push(`Exception ${d.frame.exception}; tasks remain cooperative.`);
  if (d.gap) lines.push(`CAPTURE GAP: ${pretty(d.gap)}`);
  if (d.notes.length) lines.push(...d.notes.map(String));
  $('sample-detail').textContent = lines.join('\n');
  $('tasks').replaceChildren(...d.tasks.filter(t => t.active !== false).map(t => {
    const tr = element('tr'), name = element('td', t.name); name.append(element('small', t.key));
    const state = element('td', t.state); state.style.color = stateColor(t.state);
    tr.append(name, state, element('td', `${t.priority ?? '?'} / ${t.cluster ?? '?'}${t.promoted === 1 ? ' · promoted' : ''}`), element('td', M.waitText(t, capture.labels, d))); return tr;
  }));
  $('pool').replaceChildren(...d.pool.map(p => {
    const box = element('div', undefined, 'pool-slot'); box.style.setProperty('--slot-color', stateColor(p.state));
    box.append(element('strong', `#${p.slot} · ${p.name}`), element('small', `${p.state} · capacity ${p.capacity ?? '?'} B`));
    let end = '?'; const address = M.integer(p.address), extent = M.integer(p.extent);
    if (address !== null && extent !== null) end = '0x' + (address + extent).toString(16);
    box.append(element('small', `${p.address || '?'} – ${end} (slot extent)`), element('small', p.owner || 'No validated owner'));
    return box;
  }));
  $('pool-total').textContent = `${d.pool.filter(p => p.used === true).length} occupied / ${d.pool.length} observed slots`;
  $('pool-note').textContent = `Recorded reservation ${d.poolReserved ?? '?'} B. Payload capacity differs from requested coroutine-frame size. Shared stack is shown separately.`;
}
function surface(canvas, height) {
  const width = Math.max(canvas.id === 'lanes' ? 600 : 100, canvas.getBoundingClientRect().width || 900), ratio = devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio); canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio); ctx.fillStyle = css('inset'); ctx.fillRect(0, 0, width, height);
  ctx.font = '11px -apple-system, BlinkMacSystemFont, sans-serif'; ctx.textBaseline = 'middle'; return {ctx, width};
}
function signals() {
  const grouped = new Map();
  for (const label of capture?.labels || []) {
    const key = String(label.mask); if (!grouped.has(key)) grouped.set(key, []); grouped.get(key).push(label.name);
  }
  if (!grouped.size && view) for (let bit = 0; bit < 32; bit++) {
    const mask = 1n << BigInt(bit);
    if (view.samples.some(s => ((M.integer(s.levels) || 0n) & mask) || ((M.scalar(s.event?.arguments?.occurrence) || M.scalar(s.event?.arguments?.level) || 0n) & mask))) grouped.set('0x' + mask.toString(16), [`bit${bit}`]);
  }
  return [...grouped].map(([mask, names]) => ({mask: M.integer(mask), name: names.join(' / ')}));
}
function drawTimeline() {
  const canvas = $('lanes');
  if (!view || !capture) { const {ctx} = surface(canvas, 100); ctx.fillStyle = css('muted'); ctx.fillText('No scheduler samples in this selection.', 20, 35); surface($('overview'), 40); return; }
  const slots = [...new Set([...capture.slots.map(([slot]) => slot), ...view.samples.flatMap(s => s.tasks.map(t => t.slot))])].sort((a, b) => a - b);
  const labels = new Map(capture.slots), sig = signals();
  const signalTop = 66 + slots.length * ROW + 65, height = signalTop + sig.length * ROW + 28;
  const {ctx, width} = surface(canvas, height), cell = (width - LABEL_WIDTH - 12) / Math.max(1, view.samples.length);
  ctx.fillStyle = css('muted'); ctx.fillText('TASK SLOT / LIFETIME AT CURSOR', 14, 20); ctx.fillText('OBSERVATION INDEX', LABEL_WIDTH, 20);
  const taskTop = 65;
  for (let row = 0; row < slots.length; row++) {
    const slot = slots[row], y = taskTop + row * ROW;
    ctx.fillStyle = css('text');
    const selectedTask = view.detail.tasks.find(t => t.slot === slot);
    const name = `${slot} · ${selectedTask?.name || labels.get(slot) || 'slot'}`;
    ctx.save(); ctx.beginPath(); ctx.rect(8, y - 10, LABEL_WIDTH - 18, 22); ctx.clip(); ctx.fillText(name, 14, y + 1); ctx.restore();
    view.samples.forEach((s, i) => {
      const t = s.tasks.find(t => t.slot === slot), x = LABEL_WIDTH + i * cell;
      ctx.fillStyle = stateColor(t?.state || 'unknown');
      ctx.globalAlpha = t?.active === false ? .2 : .9; ctx.fillRect(x + .25, y - 5, Math.max(.5, cell - .5), 12); ctx.globalAlpha = 1;
      const prior = i ? view.samples[i - 1].tasks.find(v => v.slot === slot) : null;
      if (t && prior && t.key !== prior.key) { ctx.fillStyle = css('text'); ctx.fillRect(x, y - 8, 1, 18); }
    });
  }
  const poolY = taskTop + slots.length * ROW + 5;
  ctx.fillStyle = css('muted'); ctx.fillText('Pool slots occupied', 14, poolY);
  view.samples.forEach((s, i) => {
    const used = s.pool.filter(p => p.used === true).length;
    ctx.fillStyle = css('accent'); ctx.fillRect(LABEL_WIDTH + i * cell, poolY + 6 - 15 * used / Math.max(1, s.pool.length), Math.max(.5, cell - .5), 15 * used / Math.max(1, s.pool.length));
  });
  ctx.fillStyle = css('muted'); ctx.fillText('SIGNALS · LEVEL BITS + API ENTRIES', 14, signalTop - 24);
  sig.forEach((signal, row) => {
    const y = signalTop + row * ROW;
    ctx.fillStyle = css('text'); ctx.save(); ctx.beginPath(); ctx.rect(8, y - 10, LABEL_WIDTH - 18, 24); ctx.clip(); ctx.fillText(signal.name, 14, y); ctx.restore();
    view.samples.forEach((s, i) => {
      const x = LABEL_WIDTH + i * cell, level = M.integer(s.levels);
      ctx.strokeStyle = level === null ? css('muted') : css('blue'); ctx.lineWidth = 1;
      const yy = y + (level !== null && (level & signal.mask) ? -5 : 5);
      ctx.setLineDash(level === null ? [2, 2] : []); ctx.beginPath(); ctx.moveTo(x, yy); ctx.lineTo(x + cell, yy); ctx.stroke(); ctx.setLineDash([]);
      const args = s.event?.arguments || {}, mask = M.scalar(args.occurrence) || M.scalar(args.level) || 0n;
      if (!(mask & signal.mask)) return;
      const mid = x + cell / 2, radius = Math.min(4, Math.max(1.2, cell / 2));
      ctx.fillStyle = css('accent'); ctx.strokeStyle = css('accent');
      if (s.event.semantics === 'publication-entry') { ctx.beginPath(); ctx.arc(mid, y, radius, 0, Math.PI * 2); ctx.fill(); }
      else { ctx.beginPath(); ctx.moveTo(mid, y - radius - 2); ctx.lineTo(mid - radius, y + radius); ctx.lineTo(mid + radius, y + radius); ctx.closePath(); ctx.stroke(); }
      if (args.level && cell > 13) { const high = M.small(args.high); ctx.fillText(high === 1 ? '↑' : high === 0 ? '↓' : '?', mid, y - 10); }
    });
  });
  view.samples.forEach((s, i) => {
    const x = LABEL_WIDTH + i * cell;
    if (s.gap) { ctx.fillStyle = css('danger'); ctx.globalAlpha = .2; ctx.fillRect(x, 34, Math.max(cell, 2), height - 45); ctx.globalAlpha = 1; }
    if (!i || s.stop !== view.samples[i - 1].stop) {
      ctx.strokeStyle = css('line'); ctx.beginPath(); ctx.moveTo(x, 35); ctx.lineTo(x, height - 10); ctx.stroke();
      ctx.fillStyle = css('muted'); if (i % Math.max(1, Math.ceil(65 / cell)) === 0 || !i) ctx.fillText(`S${s.stop}`, x + 3, 43);
    }
  });
  const selectedX = LABEL_WIDTH + (cursor - start + .5) * cell;
  if (cursor >= start && cursor < start + view.samples.length) {
    ctx.strokeStyle = css('accent'); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(selectedX, 33); ctx.lineTo(selectedX, height - 8); ctx.stroke();
  }
  const overview = surface($('overview'), 40), buckets = capture.overview;
  buckets.forEach((b, i) => { const x = i * overview.width / buckets.length; overview.ctx.fillStyle = b.gap ? css('danger') : css('blue'); overview.ctx.globalAlpha = .55;
    overview.ctx.fillRect(x, b.api ? 9 : 25, Math.max(1, overview.width / buckets.length), b.api ? 22 : 6); });
  overview.ctx.globalAlpha = 1; overview.ctx.strokeStyle = css('accent');
  overview.ctx.strokeRect(start / capture.count * overview.width, 3, Math.max(4, view.samples.length / capture.count * overview.width), 33);
}
async function loadProfile() {
  const generation = ++profileGeneration;
  const oldRun = profile?.record.run;
  try {
    const result = profileIndex >= 0 ? await rpc('profile', {session: session.id, index: profileIndex}) : null;
    if (generation !== profileGeneration) return;
    profile = result;
    if (oldRun && oldRun !== result?.record.run) { modelDuration = null; $('duration').value = ''; }
    if (!override) {
      for (const [id, key] of [['current', 'ua_per_mhz'], ['throughput', 'mips_per_mhz'], ['voltage', 'voltage']]) $(id).value = result?.model?.[key] ?? '';
    }
    functionPage = 0; renderProfile();
  } catch (error) { if (generation === profileGeneration) { profile = null; renderProfile(); status(`Profile unavailable: ${error.message}`, true); } }
}
function renderProfile() {
  const model = override ? localModel : profile?.model;
  if (!profile) {
    $('instruction-count').textContent = '—'; $('entry-count').textContent = '—'; $('energy-total').textContent = '—';
    $('instruction-caption').textContent = 'No instruction profile recorded'; $('energy-caption').textContent = 'Enable plugin and record electrical assumptions';
    $('profile-provenance').textContent = session?.profiles.length ? 'No profile received before the selected cursor. Choose a later recorded snapshot; profile polling is independent of target stops.' : 'No validated instruction profile in this session. Task snapshots cannot reconstruct instruction or call counts.';
    $('profile-summary').textContent = ''; $('model-status').textContent = 'No recorded profile/model selected.';
    rows = []; $('functions').replaceChildren(); $('pareto').textContent = 'Unavailable'; $('energy-bars').textContent = 'Unavailable'; $('functions-range').textContent = '0 functions'; return;
  }
  const r = profile.record, catalog = new Map(profile.catalog);
  rows = M.profileRows(r, catalog, model, modelDuration);
  $('instruction-count').textContent = count(r.total);
  $('instruction-caption').textContent = `QEMU ${r.run.slice(0, 8)} · snapshot ${r.profile_seq}`;
  $('entry-count').textContent = r.entry_hits === undefined ? '—' : count(Object.values(r.entry_hits).reduce((sum, n) => sum + M.integer(n), 0n));
  const energy = model ? Number(M.integer(r.total)) * model.ua_per_mhz / model.mips_per_mhz * model.voltage : null;
  $('energy-total').textContent = scaled(energy, 'J');
  $('energy-caption').textContent = model ? `${override ? 'Local' : 'Recorded'} assumptions · ${model.ua_per_mhz} µA/MHz · ${model.voltage} V` : 'No electrical assumptions recorded';
  $('profile-provenance').textContent = `Journal #${r.seq} · QEMU run ${r.run} · ${r.complete ? 'collector final snapshot' : 'partial cumulative run snapshot'} · ${session.catalogComplete ? 'recorded ELF symbol catalog' : 'catalog missing/partial; emitted-body keys remain inspectable'}. Profiles are independently polled; “at cursor” means received before that journal record, not exact target-stop synchronization.`;
  $('model-status').textContent = model ? `${override ? 'Local override; derived values only' : 'Recorded: ' + (profile.model?.source || 'explicit assumptions')} · throughput ${model.mips_per_mhz} MIPS/MHz. ${modelDuration ? `User-supplied cumulative target duration ${modelDuration} s.` : 'No target duration: entries/s and average power unavailable.'}` : 'No model: energy and estimated cycles unavailable. Enter all three positive assumptions to calculate estimates.';
  const cycles = model ? Number(M.integer(r.total)) / model.mips_per_mhz : null;
  $('profile-summary').replaceChildren(element('span', `Unattributed: ${count(r.unknown)} dispatches`), element('span', `Estimated cycles: ${number(cycles)}`), element('span', `Estimated average active-core power: ${energy !== null && modelDuration ? number(energy * 1e-6 / modelDuration) + ' µW' : 'unavailable'}`));
  renderFunctions();
}
function compareRows(a, b, key) {
  if (key === 'count' || key === 'entries') {
    const av = M.integer(a[key]), bv = M.integer(b[key]);
    if (av === null) return bv === null ? a.name.localeCompare(b.name) : 1;
    if (bv === null) return -1;
    return av === bv ? a.name.localeCompare(b.name) : av > bv ? -1 : 1;
  }
  return (b[key] ?? -Infinity) - (a[key] ?? -Infinity) || a.name.localeCompare(b.name);
}
function filteredRows() { const filter = $('function-filter').value.trim().toLowerCase(); return rows.filter(r => `${r.name} ${r.key}`.toLowerCase().includes(filter)).sort((a, b) => compareRows(a, b, $('sort').value)); }
function bars(target, sorted, key, energy = false) {
  target.replaceChildren();
  const first = sorted.find(r => r[key] !== null && r[key] !== undefined && Number(r[key]) > 0);
  if (!first) { target.textContent = 'Unavailable for this metric / model.'; return; }
  const max = Number(first[key]);
  for (const row of sorted.slice(0, 12)) {
    if (row[key] === null || row[key] === undefined) continue;
    const e = element('div', undefined, 'bar-row'), name = element('span', row.name, 'bar-name'); name.title = row.name;
    const track = element('div', undefined, 'bar-track'), fill = element('div', undefined, energy ? 'bar-fill energy-fill' : 'bar-fill');
    fill.style.width = `${Math.max(0, Math.min(100, Number(row[key]) / max * 100))}%`; track.append(fill);
    e.append(name, track, element('span', energy ? scaled(row[key], 'J') : number(Number(row[key])), 'bar-value')); target.append(e);
  }
}
function renderFunctions() {
  const filtered = filteredRows(); functionPage = Math.max(0, Math.min(functionPage, Math.max(0, Math.ceil(filtered.length / PAGE) - 1)));
  const from = functionPage * PAGE;
  $('functions').replaceChildren(...filtered.slice(from, from + PAGE).map(r => {
    const tr = element('tr'), name = element('td', r.name); name.append(element('small', r.key));
    tr.append(name, ...[count(r.count), number(r.share) + '%', count(r.entries), number(r.perMillion), number(r.hz), number(r.size), number(r.perEntry), number(r.cycles), number(r.charge), number(r.energy)].map(v => element('td', v)));
    return tr;
  }));
  $('functions-range').textContent = filtered.length ? `${from + 1}–${Math.min(from + PAGE, filtered.length)} of ${filtered.length} functions` : '0 functions';
  $('functions-back').disabled = functionPage === 0; $('functions-forward').disabled = from + PAGE >= filtered.length;
  bars($('pareto'), filtered, $('sort').value);
  bars($('energy-bars'), [...filtered].sort((a, b) => compareRows(a, b, 'energy')), 'energy', true);
}
function drawStack(record) {
  $('stack-map').replaceChildren(); $('stack-frames').replaceChildren(); $('stack-memory').textContent = 'Unavailable';
  if (!record) { $('stack-caption').textContent = 'No stack sample recorded before this scheduler observation.'; return; }
  $('stack-caption').textContent = `Recorded at stop ${record.stop}, journal #${record.seq}. Origin: ${record.origin || 'unavailable'}.`;
  const frames = Array.isArray(record.frames) ? record.frames.slice(0, 64) : [];
  if (record.frames?.length > 64) $('stack-caption').textContent += ' Display limited to first 64 frames; inspect the raw record for the remainder.';
  $('stack-frames').replaceChildren(...frames.map((f, i) => {
    const next = frames[i + 1], sp = M.integer(f.sp), caller = M.integer(next?.sp);
    const own = f.kind === 'normal' && next?.kind === 'normal' && sp !== null && caller !== null && caller >= sp ? caller - sp : null;
    const tr = element('tr'); tr.append(...[f.level, f.function, sp === null ? '—' : '0x' + sp.toString(16), own === null ? '—' : own.toString()].map(v => element('td', v)));
    const block = element('div', undefined, 'stack-block'); block.append(element('strong', f.function || 'unavailable'), element('small', `${sp === null ? '?' : '0x' + sp.toString(16)} · ${own === null ? 'own bytes unavailable' : own + ' sampled own B'}`));
    block.style.minHeight = Math.min(130, 40 + (own === null ? 0 : Math.sqrt(Number(own)) * 2)) + 'px'; $('stack-map').append(block);
    return tr;
  }));
  const memory = record.memory;
  if (memory && typeof memory.hex === 'string') {
    const base = M.integer(memory.start), bytes = memory.hex.match(/.{1,2}/g) || [], lines = [];
    for (let i = 0; i < Math.min(bytes.length, 256); i += 16) lines.push(`${base === null ? '?' : '0x' + (base + BigInt(i)).toString(16)}  ${bytes.slice(i, i + 16).join(' ')}`);
    $('stack-memory').textContent = lines.join('\n') + (bytes.length > 256 ? '\n… first 256 recorded bytes shown; inspect the raw record for the remainder.' : '');
  } else $('stack-memory').textContent = record.memory_error || 'No memory bytes recorded.';
}
function coverage() {
  const target = $('coverage-detail'); target.replaceChildren();
  for (const [title, text] of [
    ['Recording', `${summary.name} · ${summary.lines} lines · ${session.recordCount} session records indexed. Selected capture: ${capture?.count || 0} samples, ${capture?.gaps || 0} explicit gap boundaries.`],
    ['Session & build', `${session.id}\n${session.hash || 'Build hash unavailable; profile/model association unavailable.'}\n${session.meta?.timestamp || 'Session start missing'}`],
    ['Capture coverage', pretty(capture?.coverage || {status: 'No recorded coverage metadata'})],
    ['Signal labels', `${capture?.labelStatus || 'Unavailable'}. Source header labels do not attest firmware semantics.`],
    ['Trace semantics', 'Each column is a recorded observation, not equal elapsed time. API requests/publication entries do not prove successful return. State changes between samples and gaps are not reconstructed. Task identities include slot, generation and an observation epoch after generation regression.'],
    ['Profile semantics', 'Guest dispatches and entry-PC hits are observed counters, not silicon cycles or exact invocations. Profiles are cumulative for one QEMU run and are not summed across snapshots. The cursor uses journal arrival order, not exact target synchronization.'],
    ['Energy & power', 'Recorded or locally supplied assumptions drive derived active-core estimates. No target duration is inferred from host timestamps. Measured power/cycles, peripherals, sleep and leakage are unavailable.'],
    ['Capture diagnostics', (capture?.diagnostics || []).join('\n') || 'None recorded.'],
    ['Session diagnostics', session.errors.join('\n') || 'None recorded.']]) {
    const row = element('div', undefined, 'coverage-row'); row.append(element('strong', title), element('span', text)); row.style.whiteSpace = 'pre-wrap'; target.append(row);
  }
  $('diagnostics').textContent = summary.errorCount ? `${summary.errorCount} import diagnostics; first ${summary.errors.length}:\n${summary.errors.join('\n')}` : 'No malformed, duplicate, unsupported or oversized records detected.';
}
async function inspectRecord(seq, direction = 0) {
  if (!session) return;
  const generation = ++recordGeneration, sessionId = session.id;
  try {
    const payload = await rpc('record', {session: session.id, seq: Math.max(1, Number(seq) || 1), direction, kind: $('record-kind').value});
    if (generation !== recordGeneration || sessionId !== session?.id) return;
    const result = payload.record; rawText = payload.raw;
    rawRecord = result; $('record-seq').value = result.seq;
    const text = pretty(result); $('raw').textContent = text.length > 160000 ? text.slice(0, 160000) + '\n… display truncated; Save selected record retains the complete record.' : text;
    $('record-label').textContent = `${result.kind} · journal #${result.seq} · stop ${result.stop ?? 'not stop-indexed'} · ${result.timestamp || 'timestamp unavailable'}`;
  } catch (error) {
    if (generation === recordGeneration && sessionId === session?.id) $('record-label').textContent = error.message + (rawRecord ? '; previous record remains shown.' : '');
  }
}
function download(text, name, type) { const link = element('a'); link.href = URL.createObjectURL(new Blob([text], {type})); link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000); }
$('file').addEventListener('change', e => openFile(e.target.files[0]));
$('session').addEventListener('change', changeSession); $('capture').addEventListener('change', changeCapture);
$('columns').addEventListener('change', () => { columns = Number($('columns').value); start = Math.max(0, cursor - Math.floor(columns / 2)); loadView(); });
$('pan').addEventListener('input', () => go(Number($('pan').value), true));
$('jump-button').onclick = () => go(Number($('jump').value) - 1);
$('jump').addEventListener('keydown', e => { if (e.key === 'Enter') go(Number(e.target.value) - 1); });
$('oldest').onclick = () => go(0, true); $('latest').onclick = () => go((capture?.count || 1) - 1);
$('page-back').onclick = () => go(Math.max(0, start - columns), true); $('page-forward').onclick = () => go(start + columns, true);
$('previous-stop').onclick = () => { const p = capture?.stops.findLast(s => s.index < cursor); if (p) go(p.index); };
$('next-stop').onclick = () => { const p = capture?.stops.find(s => s.index > cursor); if (p) go(p.index); };
$('lanes').addEventListener('click', e => { if (!view) return; const rect = e.target.getBoundingClientRect(), x = e.clientX - rect.left; if (x >= LABEL_WIDTH) go(start + Math.min(view.samples.length - 1, Math.floor((x - LABEL_WIDTH) / (rect.width - LABEL_WIDTH - 12) * view.samples.length))); });
$('lanes').addEventListener('keydown', e => {
  const moves = {ArrowRight: cursor + 1, ArrowLeft: cursor - 1, Home: 0, End: (capture?.count || 1) - 1, PageDown: cursor + columns, PageUp: cursor - columns};
  if (e.key in moves) { e.preventDefault(); go(moves[e.key]); }
});
$('overview').onclick = e => { if (capture) go((e.clientX - e.target.getBoundingClientRect().left) / e.target.getBoundingClientRect().width * (capture.count - 1)); };
$('profile-snapshot').onchange = () => { profileIndex = Number($('profile-snapshot').value); loadProfile(); };
$('profile-cursor').onclick = () => {
  if (!view || !session) return; profileIndex = session.profiles.findLastIndex(p => p.seq <= view.detail.journalSeq);
  $('profile-snapshot').value = profileIndex; loadProfile();
};
$('function-filter').oninput = () => { functionPage = 0; renderFunctions(); };
$('sort').onchange = () => { functionPage = 0; renderFunctions(); };
$('functions-back').onclick = () => { functionPage--; renderFunctions(); }; $('functions-forward').onclick = () => { functionPage++; renderFunctions(); };
$('apply-model').onclick = () => {
  const values = ['current', 'throughput', 'voltage'].map(id => $(id).value.trim());
  const model = {ua_per_mhz: Number(values[0]), mips_per_mhz: Number(values[1]), voltage: Number(values[2])};
  const duration = $('duration').value.trim();
  if ((values.some(Boolean) && !M.positiveModel(model)) || (duration && (!Number.isFinite(Number(duration)) || Number(duration) <= 0))) { $('model-status').textContent = 'Enter all three positive finite model values, or leave all three blank. Duration must be positive if supplied.'; return; }
  override = true; localModel = values.some(Boolean) ? model : null; modelDuration = duration ? Number(duration) : null; renderProfile();
};
$('reset-model').onclick = () => { override = false; localModel = null; modelDuration = null; $('duration').value = ''; loadProfile(); };
$('export-profile').onclick = () => {
  if (!profile) return;
  const keys = ['key', 'name', 'count', 'share', 'entries', 'perMillion', 'hz', 'size', 'perEntry', 'cycles', 'charge', 'energy'];
  const csv = v => { const text = String(v ?? ''); return '"' + (/^[=+\-@\t\r]/.test(text) ? "'" : '') + text.replaceAll('"', '""') + '"'; };
  const model = override ? localModel : profile.model;
  const info = `# Session ${session.id}; run ${profile.record.run}; snapshot ${profile.record.profile_seq}; source journal ${profile.record.seq}; ${override ? 'local model override' : 'recorded model'} ${JSON.stringify(model)}; duration ${modelDuration ?? 'unavailable'} seconds; counts=guest dispatches; entries=entry-PC proxy; cycles/charge/energy=estimated\n`;
  download(info + [keys.map(csv).join(','), ...filteredRows().map(r => keys.map(k => csv(r[k])).join(','))].join('\n'), 'dbg3k-profile.csv', 'text/csv');
};
$('inspect-sample').onclick = () => { if (view) { tab('stack'); inspectRecord(view.detail.journalSeq); } };
$('record-open').onclick = () => inspectRecord($('record-seq').value);
$('record-prev').onclick = () => inspectRecord($('record-seq').value, -1);
$('record-next').onclick = () => inspectRecord($('record-seq').value, 1);
$('record-download').onclick = () => { if (rawRecord) download(rawText + '\n', `dbg3k-record-${rawRecord.seq}.json`, 'application/json'); };
$('record-seq').addEventListener('keydown', e => { if (e.key === 'Enter') inspectRecord(e.target.value); });
for (const button of document.querySelectorAll('[data-tab]')) button.onclick = () => tab(button.dataset.tab);
$('theme').onclick = () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'; requestAnimationFrame(drawTimeline); };
new ResizeObserver(() => { if (!$('timeline').hidden) drawTimeline(); }).observe($('timeline'));

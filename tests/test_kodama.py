"""Domain boundaries and the graphical task/signal interactions."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from dbg3k.app import DebuggerApp
from dbg3k.kodama_model import KodamaHistory, KodamaJournal, decode_sample
from dbg3k.kodama_symbols import signal_labels
from dbg3k.kodama_ui import KodamaCanvas, KodamaHistoryBar, KodamaScreen, KodamaSetup, event_arguments


def node(value, pointer=False):
    return dict(status='ok', type='void *' if pointer else 'unsigned int',
                encoding='hex' if pointer else 'decimal', value=hex(value) if pointer else str(value))


def sample(sequence=1, *, packed=False, capture='fixture', running=0):
    tasks = []
    for index, priority in enumerate((30, 10, 20)):
        fields = {k: node(v) for k, v in dict(active=1, generation=1, ready=1, priority=priority,
                  cluster=1, promoted=0, sleeping=0, waiting=0, seen=0, wake_mask=0, deadline=4,
                  next=index + 1 if index < 2 else 255).items()}
        fields.update(context=node(0x38002000 + index * 8, True), subscription=node(0, True))
        if packed:
            fields.pop('active'); fields.pop('generation'); fields.pop('waiting')
            fields['identity'] = node(0x100 | index + 1)
        tasks.append(dict(index=index, address=hex(0x38003000 + 64 * index), fields=fields))
    tasks[1]['fields'].update(ready=node(0), subscription=node(0x38004000, True), seen=node(1))
    if not packed:
        tasks[1]['fields']['waiting'] = node(1)
    tasks[1]['subscription'] = dict(status='ok', address='0x38004000', count=2, alternatives=[
        dict(inputs=node(3), kind=node(1)), dict(inputs=node(4), kind=node(0))])
    raw = dict(core={k: node(v) for k, v in dict(running=running, levels=8, clock_ticks=2,
               yield_skip=0, order_head=0, destroying=0).items()}, tasks=tasks,
        task_capacity=3, commands=[dict(index=1, address='0x38002008', token=node(258), handle=node(0x38001000, True))],
        pool=[dict(index=0, address='0x38001000', data_address='0x38001000', capacity=512,
                   bytes=520, used=node(1), resume_symbol='worker(_Z6workerv.Frame *)'),
              dict(index=1, address='0x38001208', data_address='0x38001208', capacity=512, bytes=520, used=node(0))],
        pool_capacity=2, pool_reserved_bytes=1040, errors=[])
    return dict(schema='dbg3k.kodama.raw.v1', capture=capture, sample_seq=sequence, stop=sequence,
                origin='stop', thread='1', frame=dict(function='checkpoint', filename='task.cpp', line=10),
                event=None, state=raw)


def history():
    h = KodamaHistory()
    h.capture = 'fixture'
    h.labels = dict(status='Illustrative fixture header mapping', signals=[
        dict(name='A', mask='0x1'), dict(name='B', mask='0x2'), dict(name='ACK', mask='0x4')])
    h.accept(sample())
    data = sample(2)
    data['origin'] = 'api'
    data['event'] = dict(function='signal_locked', semantics='publication-entry', arguments={'occurrence': node(1)})
    h.accept(data)
    return h


class KodamaModelTests(unittest.TestCase):
    def test_event_aliases_require_unique_live_binding(self):
        h = history()
        data = sample()
        data['event'] = dict(arguments={'context': node(0x38002008, True), 'sub': node(0x38004000, True)})
        s = decode_sample(data, 1)
        text = event_arguments(s, h)
        self.assertIn('worker [1:1]', text)
        self.assertIn('missing B', text)
        self.assertIn('0x38002008', text)
        s.tasks[1].active = False
        self.assertEqual(event_arguments(s, h), 'context=0x38002008, sub=0x38004000')

    def test_old_and_packed_layout_waits_identity_and_pool_ownership(self):
        for packed in (False, True):
            h = KodamaHistory(); h.capture = 'fixture'
            h.labels = history().labels
            h.accept(sample(packed=packed))
            s = h.samples[-1]; task = s.tasks[1]
            self.assertEqual((task.name, task.key, task.state, task.pool), ('worker', '1:1', 'waiting', 0))
            self.assertIn('event ALL(A + B) [missing B]', h.wait_text(task, s))
            self.assertIn('OR event(ACK)', h.wait_text(task, s))
            self.assertEqual(s.pool[0].owner, task.key)
            self.assertEqual(s.pool[0].capacity, 512)
            self.assertEqual(s.raw['pool_reserved_bytes'], 1040)
            stale = sample(2, packed=packed)
            stale['state']['commands'][0]['token'] = node(0x202)
            h.accept(stale)
            self.assertIsNone(h.samples[-1].pool[0].owner)

    def test_priority_promotion_yield_ties_and_running_guard(self):
        data = sample()
        s = decode_sample(data, 1)
        self.assertEqual(s.predicted, '2:1')  # p20 beats p30; p10 is waiting
        data['state']['tasks'][0]['fields']['promoted'] = node(1)
        self.assertEqual(decode_sample(data, 1).predicted, '0:1')
        data['state']['core']['yield_skip'] = node(257)
        self.assertEqual(decode_sample(data, 1).predicted, '2:1')
        data['state']['core']['running'] = node(259)
        self.assertIsNone(decode_sample(data, 1).predicted)
        self.assertIn('executing', decode_sample(data, 1).decision)
        data = sample()
        data['state']['tasks'][0]['fields']['priority'] = node(20)
        data['state']['core']['order_head'] = dict(status='unavailable')
        self.assertIsNone(decode_sample(data, 1).predicted)

    def test_free_stale_fields_reuse_and_bounded_history(self):
        h = KodamaHistory(limit=2); h.capture = 'fixture'
        h.accept(sample(1))
        dead = sample(2)
        dead['state']['tasks'][1]['fields']['active'] = node(0)
        h.accept(dead)
        self.assertEqual(h.samples[-1].tasks[1].state, 'free')
        self.assertEqual(h.samples[-1].tasks[1].name, 'worker')
        reused = sample(3)
        reused['state']['tasks'][1]['fields']['generation'] = node(2)
        h.accept(reused)
        self.assertEqual(h.samples[-1].tasks[1].key, '1:2')
        self.assertEqual(h.evicted, 1)
        self.assertFalse(h.accept(sample(3)))
        self.assertFalse(h.accept(sample(4, capture='foreign')))
        unavailable = sample(4, packed=True)
        unavailable['state']['tasks'][0]['fields']['identity'] = node(0x102)  # Wrong low slot byte
        h.accept(unavailable)
        self.assertEqual(h.samples[-1].tasks[0].state, 'unknown')

    def test_header_labels_safe_bounded_and_explicitly_unverified(self):
        with TemporaryDirectory() as folder:
            p = Path(folder) / 'signals.hpp'
            p.write_text('''#define RX (1U << 0)
#define TX UINT32_C(2)
constexpr uint32_t A=4, B=8, BOTH=A|B;
enum Signals { ALARM=0x10u, NEXT, BIG=(1 << 31) };
#define BAD __import__("os").system("false")
''')
            labels = signal_labels(p)
            names = {s['name']: int(s['mask'], 0) for s in labels['signals']}
            self.assertEqual(names, dict(RX=1, TX=2, A=4, B=8, ALARM=16, BIG=0x80000000))
            self.assertIn('BAD', labels['skipped'])
            self.assertIn('not verified', labels['status'])
            self.assertEqual(len(labels['sha256']), 64)

    def test_journal_build_session_capture_and_late_records(self):
        h = KodamaHistory(); replay = KodamaJournal('elfhash', h)
        def record(kind, session, seq, **payload):
            return dict(schema='dbg3k.trace.v1', kind=kind, session=session, seq=seq, **payload)
        replay.apply(record('session_start', 'old', 1, elf_sha256='wrong'))
        self.assertFalse(replay.apply(record('kodama_sample', 'old', 2, data=sample())))
        replay.apply(record('session_start', 'one', 1, elf_sha256='elfhash'))
        replay.apply(record('kodama_config', 'one', 2, capture='fixture', signal_labels=history().labels))
        self.assertTrue(replay.apply(record('kodama_sample', 'one', 3, data=sample())))
        self.assertEqual(h.labels, history().labels)
        replay.apply(record('session_start', 'two', 1, elf_sha256='elfhash'))
        self.assertTrue(replay.apply(record('kodama_sample', 'two', 3, data=sample(1, capture='new'))))
        self.assertFalse(replay.apply(record('kodama_sample', 'one', 4, data=sample(2))))
        self.assertEqual(replay.selected, 'two')
        self.assertEqual(len(h.samples), 1)

    def test_generation_discontinuity_retirement_and_exception_context(self):
        h = KodamaHistory(); h.capture = 'fixture'
        h.accept(sample(1))
        reset = sample(2)
        reset['state']['tasks'][1]['fields']['generation'] = node(0)
        reset['state']['tasks'][1]['fields']['active'] = node(0)
        h.accept(reset)
        self.assertEqual(h.samples[-1].tasks[0].key, '0:1@e1')
        self.assertTrue(any('regressed' in n for n in h.samples[-1].notes))
        self.assertEqual(h.samples[-1].pool[0].owner, None)
        retired = sample(3)
        retired['state']['tasks'][1]['fields'].update(generation=node(0xffffff), active=node(0))
        h.accept(retired)
        self.assertEqual(h.samples[-1].tasks[1].state, 'retired')
        interrupt = sample(1, running=259)
        interrupt['frame']['exception'] = '15'
        s = decode_sample(interrupt, 1)
        self.assertEqual(s.tasks[2].state, 'interrupted')
        self.assertIn('exception 15', s.decision)
        self.assertIsNone(s.predicted)


class KodamaWidgetTests(unittest.IsolatedAsyncioTestCase):
    def app(self):
        app = DebuggerApp('demo.elf', 'gdb', 'localhost:1234', kodama=True)
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app._send = lambda *a, **kw: None
        app.kodama_history = history()
        return app

    async def test_history_scrollbar_drag_page_alignment_and_live_arrivals(self):
        app = self.app()
        for sequence in range(3, 601):
            app.kodama_history.accept(sample(sequence))
        async with app.run_test(size=(140, 55)) as pilot:
            app.set_visible_views({'kodama'})
            app._show_kodama()
            await pilot.pause()
            canvas = app.query_one(KodamaCanvas)
            bar = app.query_one(KodamaHistoryBar)
            self.assertTrue(bar.visible)
            self.assertFalse(bar.disabled)
            self.assertEqual(canvas.visible_samples[-1].index, 600)
            newest_start = canvas.visible_samples[0].index
            # A native track click pages, rather than moving one cell at a time.
            await pilot.click(bar, offset=(0, 0))
            await pilot.pause()
            self.assertLess(canvas.visible_samples[0].index, newest_start)
            self.assertIsNotNone(canvas.cursor)
            canvas.focus()
            await pilot.press('home')
            self.assertEqual(canvas.cursor, app.kodama_history.samples[0].index)
            self.assertEqual(bar.position, 0)
            # Drag the actual native thumb through mouse capture.
            await pilot.mouse_down(bar, offset=(1, 0))
            self.assertIsNotNone(bar.grabbed)
            await pilot.hover(bar, offset=(bar.size.width // 2, 0))
            await pilot.mouse_up(bar, offset=(bar.size.width // 2, 0))
            await pilot.pause()
            self.assertGreater(canvas.window_start, 100)
            self.assertEqual(canvas.parent.scroll_x, 0)  # Lane names stay fixed.
            first = canvas.visible_samples[0].index
            signal_row = next(y for y, signal in canvas.signal_hits.items() if signal['name'] == 'A')
            target = canvas.visible_samples[5].index
            await pilot.click(canvas, offset=(canvas.lane_gutter + 10, signal_row))
            self.assertEqual(canvas.cursor, target)
            self.assertEqual(canvas.selected_signal['name'], 'A')
            self.assertEqual(canvas.visible_samples[0].index, first)
            task_row = next(iter(canvas.hits))
            target = canvas.visible_samples[7].index
            await pilot.click(canvas, offset=(canvas.lane_gutter + 14, task_row))
            self.assertEqual(canvas.cursor, target)
            # New samples evict the oldest retained entries without shifting our
            # absolute sample window or resuming live mode.
            for sequence in range(601, 611):
                app.kodama_history.accept(sample(sequence))
            app._show_kodama()
            await pilot.pause()
            self.assertEqual(canvas.cursor, target)
            self.assertEqual(canvas.visible_samples[0].index, first)
            self.assertEqual(bar.position, canvas.window_start * 2)
            app._send = Mock()
            await pilot.click('.kodama-live')
            self.assertIsNone(canvas.cursor)
            self.assertEqual(canvas.visible_samples[-1].index, 610)
            app._send.assert_not_called()  # History browsing never runs GDB.

    async def test_history_scrollbar_expanded_resize_eviction_and_capture_reset(self):
        app = self.app()
        app.kodama_history = KodamaHistory(limit=60)
        app.kodama_history.reset('fixture')
        async with app.run_test(size=(110, 46)) as pilot:
            app.set_visible_views({'kodama'})
            app._show_kodama()
            await pilot.pause()
            self.assertTrue(app.query_one(KodamaHistoryBar).disabled)
            for sequence in range(1, 81):
                app.kodama_history.accept(sample(sequence))
            app._show_kodama()
            await pilot.click('.kodama-expand')
            await pilot.pause()
            canvas = app.screen.query_one(KodamaCanvas)
            bar = app.screen.query_one(KodamaHistoryBar)
            canvas.focus()
            await pilot.press('home')
            self.assertEqual(canvas.cursor, 21)
            await pilot.press('pagedown')
            self.assertGreater(canvas.window_start, 0)
            await pilot.press('pageup')
            self.assertEqual(canvas.window_start, 0)
            for sequence in range(81, 151):
                app.kodama_history.accept(sample(sequence))
            app._show_kodama()
            await pilot.pause()
            self.assertEqual(canvas.cursor, 91)
            self.assertEqual(canvas.visible_samples[0].index, 91)
            self.assertEqual(bar.position, 0)
            await pilot.resize_terminal(80, 40)
            await pilot.pause()
            self.assertEqual(canvas.cursor, 91)
            self.assertEqual(bar.window_size, canvas.window_size * 2)
            bar_y = bar.region.y
            canvas.parent.scroll_end(animate=False)
            await pilot.pause()
            self.assertEqual(bar.region.y, bar_y)  # Control stays above vertical content.
            await pilot.press('end')
            self.assertIsNone(canvas.cursor)
            self.assertEqual(canvas.visible_samples[-1].index, 150)
            app.kodama_history.reset('new-capture')
            app.kodama_history.accept(sample(1, capture='new-capture'))
            app._show_kodama()
            await pilot.pause()
            self.assertEqual(canvas.visible_samples[0].index, 1)
            self.assertEqual(bar.position, 0)
            self.assertTrue(bar.disabled)

    async def test_level_requests_keep_api_marker_and_observed_waveform_separate(self):
        app = self.app()
        h = app.kodama_history
        h.reset('fixture')
        # Entry probes see pre-operation values. Requests may repeat or fail;
        # only subsequent observations establish the persistent level.
        cases = [
            (8, None, '· '),
            (8, dict(function='signal_locked', semantics='publication-entry',
                     arguments={'occurrence': node(1)}), '● '),
            (8, dict(function='kodama_level_set', semantics='api-request',
                     arguments={'level': node(1), 'high': node(1)}), '△↑'),
            (9, None, '━ '),
            (9, dict(function='kodama_level_set', semantics='api-request',
                     arguments={'level': node(1), 'high': node(1)}), '△↑'),
            (9, dict(function='kodama_level_set', semantics='api-request',
                     arguments={'level': node(1), 'high': node(0)}), '△↓'),
            (8, None, '· '),
            (8, dict(function='kodama_level_set', semantics='api-request',
                     arguments={'level': node(1), 'high': {'status': 'unavailable'}}), '△?'),
            (None, None, '? '),
        ]
        for sequence, (levels, event, _) in enumerate(cases, 1):
            data = sample(sequence)
            data['state']['core']['levels'] = node(levels) if levels is not None else {'status': 'unavailable'}
            data['event'] = event
            data['origin'] = 'api' if event else 'stop'
            self.assertTrue(h.accept(data))
        async with app.run_test(size=(140, 55)) as pilot:
            app.set_visible_views({'kodama'})
            app._show_kodama()
            await pilot.pause()
            canvas = app.query_one(KodamaCanvas)
            row = next(y for y, signal in canvas.signal_hits.items() if signal['name'] == 'A')
            lane = str(canvas.render()).splitlines()[row][canvas.lane_gutter:]
            self.assertEqual(lane, ''.join(cell for _, _, cell in cases))
            # Two symbols still occupy one sample cell, preserving mouse alignment.
            await pilot.click(canvas, offset=(canvas.lane_gutter + 2 * 2 + 1, row))
            self.assertEqual(canvas.cursor, 3)
            self.assertEqual(canvas.selected_signal['name'], 'A')
            self.assertIn('level LOW observed', str(canvas.render()))
            self.assertIn('1 retained publication entries', str(canvas.render()))
            await pilot.press('right')
            self.assertEqual(canvas.cursor, 4)
            self.assertIn('level HIGH observed', str(canvas.render()))
            app.copy_to_clipboard = Mock()
            await pilot.click('.kodama-copy')
            app.copy_to_clipboard.assert_called_once()
            self.assertIn('SIGNALS', app.copy_to_clipboard.call_args.args[0])

    async def test_wide_lanes_selection_scrub_expand_and_theme(self):
        app = self.app()
        async with app.run_test(size=(140, 55)) as pilot:
            app.set_visible_views({'source', 'kodama', 'console'})
            app._show_kodama()
            await pilot.pause()

            canvas = app.query_one(KodamaCanvas)
            self.assertEqual(app.query_one('#kodama_panel').region.width, app.size.width)
            text = str(canvas.render())
            for expected in ('worker', 'missing B', 'SIGNALS', 'COROUTINE POOL', 'publication', '512', '1040'):
                self.assertIn(expected, text)
            row = next(y for y, key in canvas.hits.items() if key == '1:1')
            await pilot.click(canvas, offset=(canvas.lane_gutter, row))
            self.assertEqual(canvas.selected, '1:1')
            self.assertEqual(canvas.cursor, 1)
            app.kodama_history.accept(sample(3))
            app._show_kodama()
            self.assertEqual(canvas.cursor, 1)  # frozen inspection while live capture advances
            canvas.focus()
            await pilot.press('end')
            self.assertIsNone(canvas.cursor)
            await pilot.click('.kodama-expand')
            await pilot.pause()
            self.assertIsInstance(app.screen, KodamaScreen)
            expanded = app.screen.query_one(KodamaCanvas)
            row = next(y for y, signal in expanded.signal_hits.items() if signal['name'] == 'A')
            await pilot.click(expanded, offset=(expanded.lane_gutter + 2, row))
            self.assertEqual(expanded.selected_signal['name'], 'A')
            self.assertEqual(expanded.cursor, 2)
            app.theme = 'textual-light'
            app._show_kodama()
            await pilot.pause()
            self.assertIn('worker', str(app.screen.query_one(KodamaCanvas).render()))
            await pilot.press('escape')
            app.action_kodama_setup()
            await pilot.pause()
            self.assertIsInstance(app.screen, KodamaSetup)
            await pilot.press('escape')
            await pilot.pause()

    async def test_recorded_file_does_not_start_gdb_and_live_config_defers(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'replay.jsonl'
            start = dict(schema='dbg3k.trace.v1', kind='session_start', session='recorded', seq=1,
                         elf_sha256='fixture-hash')
            snapshot = dict(schema='dbg3k.trace.v1', kind='kodama_sample', session='recorded', seq=2, data=sample())
            path.write_text(json.dumps(start) + '\n' + json.dumps(snapshot) + '\n')
            app = DebuggerApp('missing.elf', 'gdb', 'localhost:1234', kodama_log=str(path))
            from test_resources import catalog
            app.catalog = catalog()
            app._kodama_journal = KodamaJournal(app.catalog.sha256, app.kodama_history)
            app.transport.start = Mock(side_effect=AssertionError('Replay must not launch GDB'))
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                app.transport.start.assert_not_called()
                self.assertEqual(app.status, 'REPLAY')
                self.assertEqual(app.visible_views, {'kodama'})
                self.assertEqual(len(app.kodama_history.samples), 1)
                self.assertIn('RECORDED', str(app.query_one(KodamaCanvas).render()))
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            app._connected = True
            app.status = 'RUNNING'
            app._send = Mock()
            app.configure_kodama(False, None, False)
            app._send.assert_not_called()
            self.assertTrue(app._kodama_config_pending)
            await pilot.pause()

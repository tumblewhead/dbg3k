import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dbg3k.resources import CodeCatalog, EnergyModel, FunctionCode, InstructionProfile, StackProfile, decode_stack
from dbg3k.resource_ui import resource_text


def catalog():
    # Deliberate fixture mapping: disjoint executable bodies, exact alias group.
    code = CodeCatalog.__new__(CodeCatalog)
    code.machine, code.sha256 = 'EM_ARM', 'fixture-hash'
    code.functions = [FunctionCode('.text', 0x1000, 10, ('foo', 'foo_alias')),
                      FunctionCode('.text', 0x1010, 8, ('bar',))]
    code.starts = [0x1000, 0x1010]
    code.max_ends = [0x100a, 0x1018]
    return code


class ResourceModelTests(unittest.TestCase):
    def test_dispatch_attribution_alias_unknown_and_new_run(self):
        code = catalog()
        self.assertEqual(code.lookup(0x1001).names, ('foo', 'foo_alias'))
        profile = InstructionProfile()
        data = dict(schema='dbg3k.qemu-counts.v1', metric='instruction-dispatch', elf_sha256=code.sha256,
                    run='one', seq=1, total=12, overflow=1, complete=False,
                    pcs=[['0x1000', 5], ['0x1010', 4], ['0x2000', 2]])
        self.assertTrue(profile.update(data, code))
        self.assertEqual(profile.by_function[code.functions[0].key], 5)
        self.assertEqual(profile.unknown, 3)
        self.assertFalse(profile.update(data, code))
        with self.assertRaises(ValueError):
            profile.update(dict(data, elf_sha256='different-build'), code)
        with self.assertRaises(ValueError):
            profile.update(dict(data, seq=2, total=99), code)
        self.assertEqual(profile.total, 12)  # malformed data never partly applies
        profile.update(dict(data, run='two', seq=1, total=0, overflow=0, pcs=[]), code)
        self.assertEqual(profile.total, 0)
        self.assertEqual(profile.by_function, {})

    def test_stack_frame_estimates_recursion_and_unknown_boundaries(self):
        frames = [dict(level=i, function='foo', pc=0x1000, sp=0x38000000 + 16 * i, kind='normal')
                  for i in range(3)]
        stack = StackProfile()
        sample = dict(schema='dbg3k.stack.v1', stop=4, thread='1', frames=frames, registers={'sp': frames[0]['sp']})
        self.assertIsNotNone(decode_stack('__dbg3k_stack_v1__' + json.dumps(sample)))
        stack.update(sample, catalog())
        self.assertEqual(stack.own_bytes(frames, 0), 16)
        self.assertEqual(stack.inclusive_bytes(frames, 1), 32)
        self.assertIsNone(stack.own_bytes(frames, 2))
        text, code, energy = resource_text(stack, catalog(), InstructionProfile(), 1, 4, None, 'no plugin')
        self.assertIn('3 active frame(s)', text)
        self.assertIn('~32 B', text)
        self.assertIn('ELF code bytes: 10 B', code)
        self.assertIn('unavailable', energy)
        frames[0]['kind'] = 'inline'
        self.assertIsNone(stack.own_bytes(frames, 0))
        self.assertIsNone(stack.inclusive_bytes(frames, 1))
        stale, _, _ = resource_text(stack, catalog(), InstructionProfile(), 1, 5, None, 'no plugin')
        self.assertNotIn('~32 B', stale)

    def test_energy_units_and_invalid_assumptions(self):
        model = EnergyModel(100, 2, 3.3)
        self.assertEqual(model.charge_pc(20), 1000)
        self.assertEqual(model.energy_pj(20), 3300)
        for values in ((0, 1, 3), (-1, 1, 3), (1, float('nan'), 3), (1, 1, float('inf'))):
            with self.assertRaises(ValueError):
                EnergyModel(*values)


class ResourceViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_resource_panes_palette_energy_and_stale_stack(self):
        from dbg3k.app import DebuggerApp
        from dbg3k.mi import Record
        from dbg3k.views import EnergyScreen
        from textual.widgets import Input, Static
        app = DebuggerApp('fixture.elf', 'gdb', 'localhost:1234')
        app.transport.start = lambda: None
        app.transport.close = lambda: None
        app._send = lambda *a, **k: None
        app.catalog = catalog()
        async with app.run_test(size=(120, 45)) as pilot:
            app._active_thread, app.status = '1', 'HALTED'
            app.model.begin_stop()
            data = dict(schema='dbg3k.stack.v1', stop=1, thread='1', registers={'sp': 0x38000000}, frames=[
                dict(level=0, function='foo', pc=0x1000, sp=0x38000000, kind='normal'),
                dict(level=1, function='main', pc=0x1010, sp=0x38000020, kind='normal')])
            app._handle(Record(None, '~', 'stream', '__dbg3k_stack_v1__' + json.dumps(data)))
            self.assertIn('~32 B', str(app.query_one('#stack_content', Static).render()))
            app.set_visible_views({'stack', 'instructions', 'energy'})
            self.assertTrue(app.query_one('#right').display)
            self.assertFalse(app.query_one('#left').display)
            app.push_screen(EnergyScreen())
            await pilot.pause()
            for key, value in [('ua_per_mhz', '100'), ('mips_per_mhz', '2'), ('voltage', '3.3')]:
                app.screen.query_one('#' + key, Input).value = value
            await pilot.click('#energy_apply')
            await pilot.pause()
            self.assertEqual(app.energy_model.energy_pj(20), 3300)
            app.model.begin_stop()
            app._handle(Record(None, '~', 'stream', '__dbg3k_stack_v1__' + json.dumps(data)))
            app._show_resources()
            self.assertNotIn('~32 B', str(app.query_one('#stack_content', Static).render()))

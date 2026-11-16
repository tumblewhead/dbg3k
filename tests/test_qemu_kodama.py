"""Real GDB protocol fixture plus optional real Kodama qualification."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import unittest

from dbg3k.app import DebuggerApp
from dbg3k.kodama_model import val
from dbg3k.kodama_ui import KodamaCanvas


@unittest.skipUnless(os.environ.get('DBG3K_QEMU_TEST') == '1', 'opt-in real GDB/QEMU test')
class KodamaQemuTests(unittest.IsolatedAsyncioTestCase):
    async def run_capture(self, elf, folder, *, sram, header=None, actual=False):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        image = ['-device', f'loader,file={elf},cpu-num=0'] if sram else ['-kernel', str(elf)]
        qemu = subprocess.Popen(['qemu-system-arm', '-M', 'mps2-an505', '-display', 'none',
            '-serial', 'none', '-monitor', 'none', '-semihosting-config', 'enable=on,target=native',
            *image, '-S', '-gdb', f'tcp:127.0.0.1:{port}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            await asyncio.sleep(.2)
            self.assertIsNone(qemu.poll())
            app = DebuggerApp(str(elf), os.environ.get('DBG3K_GDB', 'gdb'), f'127.0.0.1:{port}',
                              history_dir=folder, kodama=True, kodama_header=header)
            async with app.run_test(size=(150, 58)) as pilot:
                async def ready():
                    for _ in range(350):
                        await pilot.pause(.025)
                        if app.status == 'HALTED' and app.model.frames and not app.pending:
                            return
                    self.fail(f'Not ready: {app.status}, {app.pending}, {list(app._log_lines)[-10:]}')
                await ready()
                self.assertTrue(app._kodama_ready)
                self.assertIn('kodama_signal', app.kodama_history.coverage.get('installed', []))
                signal_symbol = next(n for f in app.catalog.functions for n in f.names
                                     if n == 'kodama_signal' or n.startswith('kodama_signal__'))
                app._send(f'-break-insert {signal_symbol}', 'test_break')
                app._send('-break-insert app_frames_reclaimed' if actual else '-break-insert done', 'test_break')
                await ready()
                app.action_continue_run(); await ready()
                self.assertTrue(app.kodama_history.samples)
                first = app.kodama_history.samples[-1]
                self.assertEqual(first.origin, 'stop')
                worker = next(t for t in first.tasks if t.name == 'worker') if actual else first.tasks[0]
                self.assertEqual(worker.state, 'waiting')
                self.assertIsNotNone(worker.generation)
                # Independent MI reads verify decoded field and occupied flags.
                oracle = []
                handle = app._handle
                def receive(record):
                    if record.kind == '^' and app.pending.get(record.token, (None,))[0] == 'oracle':
                        oracle.append(record.payload)
                    handle(record)
                app._handle = receive
                app._send(f'-data-evaluate-expression "\'kodama.c\'::tasks[{worker.slot}].seen"', 'oracle')
                self.assertIsNotNone(worker.pool)
                app._send(f'-data-evaluate-expression "(unsigned int)g_frames[{worker.pool}].used"', 'oracle')
                await ready()
                self.assertEqual(int(oracle[0]['value'], 0), val(worker.fields, 'seen'))
                self.assertEqual(oracle[1]['value'], '1')
                app._handle = handle
                self.assertTrue(any(p.owner == worker.key for p in first.pool))
                app.action_continue_run(); await ready()
                final = app.kodama_history.samples[-1]
                if actual:
                    self.assertTrue(all(t.active is False for t in final.tasks))
                    self.assertTrue(all(p.used is False for p in final.pool))
                    self.assertTrue(any(t.name == 'worker' for t in final.tasks))
                    self.assertTrue(any(t.name == 'producer' for t in final.tasks))
                    self.assertTrue(any(t.state == 'sleeping' for s in app.kodama_history.samples for t in s.tasks))
                publications = [s for s in app.kodama_history.samples if (s.event or {}).get('semantics') == 'publication-entry']
                self.assertTrue(publications)
                self.assertEqual(next(app.kodama_history.event_mask(s) for s in publications if app.kodama_history.event_mask(s)), 1)
                self.assertEqual(first.raw['pool_reserved_bytes'], sum(p.extent for p in first.pool))
                path = app._trace.path
                records = [json.loads(line) for line in path.read_bytes().splitlines()]
                self.assertTrue(all(r['schema'] == 'dbg3k.trace.v1' for r in records))
                raw = [r['data'] for r in records if r['kind'] == 'kodama_sample']
                self.assertTrue(all(r['capture'] == app._kodama_capture for r in raw))
                self.assertEqual([r['sample_seq'] for r in raw], list(range(1, len(raw) + 1)))
                self.assertTrue(all(r['stop_anchor'] == 'preceding-visible-stop' for r in raw if r['origin'] == 'api'))
                self.assertIn('COROUTINE POOL', str(app.query_one(KodamaCanvas).render()))
                receipt = os.environ.get('DBG3K_KODAMA_RECEIPT')
                if receipt:
                    destination = Path(receipt); destination.mkdir(exist_ok=True, parents=True)
                    with (destination / f'{elf.stem}-{app._trace.session}.jsonl').open('xb') as output:
                        output.write(path.read_bytes())
                    app.set_visible_views({'kodama'})
                    # Current source/status stays identifiable in exported views.
                    await pilot.pause()
                    app.save_screenshot(filename=f'{elf.stem}-{app._trace.session}.svg', path=str(destination))
                if actual:
                    app.action_continue_run()
                    for _ in range(200):
                        await pilot.pause(.025)
                        if qemu.poll() is not None:
                            break
                    self.assertEqual(qemu.poll(), 0)
                    output, error = qemu.communicate(timeout=3)
                    self.assertIn(b'PASS C main / coroutine tasks: all frames reclaimed', output)
        finally:
            if qemu.poll() is None:
                qemu.terminate()
            qemu.communicate(timeout=5)

    async def test_collector_with_public_arm_protocol_fixture(self):
        """Not a Kodama scheduler implementation or production qualification."""
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'kodama.c'
            header = Path(folder) / 'signals.h'; header.write_text('#define A 1u\n#define B 2u\n')
            source.write_text('''#include <stdint.h>
typedef struct { uint32_t inputs; unsigned char kind; } Alternative;
typedef struct { const Alternative *alternatives; unsigned char count; } Subscription;
typedef struct { unsigned identity; unsigned char priority,ready,cluster,promoted,sleeping;
  void *context; const Subscription *subscription; uint32_t seen,wake_mask,deadline; unsigned char next; } Task;
struct Handle { void *_M_fr_ptr; };
struct Command { struct Handle handle; unsigned token; } g_cmd[1];
struct FrameSlot { unsigned char data[64]; unsigned char used; } g_frames[1];
static const Alternative alternatives[]={{3,1}};
static const Subscription sub={alternatives,1};
static Task tasks[1];
static unsigned running,levels,clock_ticks,yield_skip,order_head,destroying;
__attribute__((noinline)) static void signal_locked(unsigned occurrence,int isr) { tasks[0].seen |= occurrence; }
__attribute__((noinline)) int kodama_signal(unsigned occurrence) { signal_locked(occurrence,0); return 1; }
__attribute__((noinline)) int kodama_run_one(void) { return 0; }
__attribute__((noinline)) void done(void) { __asm volatile("nop"); }
int main(void) {
 tasks[0].identity=257; tasks[0].priority=10; tasks[0].cluster=1; tasks[0].next=255;
 tasks[0].context=&g_cmd[0]; tasks[0].subscription=&sub;
 g_frames[0].used=1;g_cmd[0].token=257;g_cmd[0].handle._M_fr_ptr=g_frames[0].data;
 kodama_signal(1);tasks[0].ready=1;tasks[0].subscription=0;done();for(;;){}
}
''')
            elf = Path(folder) / 'protocol.elf'
            subprocess.run(['arm-none-eabi-gcc', '-mcpu=cortex-m33', '-mthumb', '-O0', '-g3',
                '-ffreestanding', '-fno-builtin', '-nostdlib', '-T', str(root / 'examples/an505/linker.ld'),
                str(root / 'examples/an505/startup.c'), str(source), '-o', str(elf)], check=True, capture_output=True)
            await self.run_capture(elf, folder, sram=False, header=str(header))

    @unittest.skipUnless(os.environ.get('DBG3K_KODAMA_ELF'), 'set DBG3K_KODAMA_ELF for real pinned Kodama')
    async def test_actual_kodama_separate_identity_layout(self):
        with TemporaryDirectory() as folder:
            await self.run_capture(Path(os.environ['DBG3K_KODAMA_ELF']).resolve(), folder, sram=True, actual=True)

    @unittest.skipUnless(os.environ.get('DBG3K_KODAMA_CURRENT_ELF'), 'set DBG3K_KODAMA_CURRENT_ELF for packed layout')
    async def test_actual_kodama_packed_identity_layout(self):
        with TemporaryDirectory() as folder:
            await self.run_capture(Path(os.environ['DBG3K_KODAMA_CURRENT_ELF']).resolve(), folder, sram=True, actual=True)

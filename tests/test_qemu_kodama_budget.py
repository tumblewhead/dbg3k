"""Actual GDB/QEMU budget exhaustion and repeated-continue regression."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
from tempfile import TemporaryDirectory
import unittest

from dbg3k.app import DebuggerApp
from dbg3k.kodama_ui import KodamaCanvas


@unittest.skipUnless(os.environ.get('DBG3K_QEMU_TEST') == '1', 'opt-in actual QEMU/GDB')
class KodamaBudgetQemuTests(unittest.IsolatedAsyncioTestCase):
    async def capture_two_runs(self, elf, folder, *, actual=False):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        image = ['-device', f'loader,file={elf},cpu-num=0'] if actual else ['-kernel', str(elf)]
        with (folder / 'console.log').open('w+') as console:
            qemu = subprocess.Popen(['qemu-system-arm', '-M', 'mps2-an505', '-display', 'none',
                '-serial', 'none', '-monitor', 'none', '-semihosting-config', 'enable=on,target=native',
                *image, '-S', '-gdb', f'tcp:127.0.0.1:{port}'],
                stdout=console, stderr=console)
            try:
                await asyncio.sleep(.2)
                self.assertIsNone(qemu.poll())
                app = DebuggerApp(str(elf), os.environ.get('DBG3K_GDB', 'gdb'), f'127.0.0.1:{port}',
                                  history_dir=folder, kodama=True)
                async with app.run_test(size=(140, 55)) as pilot:
                    async def ready():
                        for _ in range(500):
                            await pilot.pause(.025)
                            if app.status == 'HALTED' and app.model.frames and not app.pending:
                                return
                        latest = app.kodama_history.samples[-1] if app.kodama_history.samples else None
                        self.fail(f'Not ready: {app.status}, {app.pending}, '
                                  f'coverage={app.kodama_history.coverage}, '
                                  f'last={(latest.sequence, latest.tick, latest.event) if latest else None}, '
                                  f'log={list(app._log_lines)[-8:]}')
                    await ready()
                    # Lower only the debugger-side budget to exercise exhaustion
                    # quickly. Firmware/timebase are never patched or called.
                    code = "python _dbg3k_kodama_ns['EVENT_LIMIT']=16"
                    app._send(f'-interpreter-exec console "{code}"', 'test_budget')
                    app._send('-break-insert ' + ('demo_checkpoint' if actual else 'budget_checkpoint'), 'test_break')
                    await ready()
                    capture = app._kodama_capture
                    anchors = []
                    for _ in range(2):
                        preceding_stop = app.model.stop
                        app.action_continue_run(); await ready()
                        latest = app.kodama_history.samples[-1]
                        self.assertEqual(latest.origin, 'stop')
                        self.assertEqual(latest.stop, app.model.stop)
                        self.assertEqual(latest.capture_gap['reason'], 'api-budget')
                        self.assertEqual(latest.capture_gap['preceding_stop'], preceding_stop)
                        self.assertGreater(latest.capture_gap['skipped_probe_entries'], 0)
                        budget = app.kodama_history.coverage['api_budget']
                        self.assertFalse(budget['exhausted'])
                        self.assertEqual(budget['used'], 0)
                        self.assertEqual(budget['stop'], app.model.stop)
                        self.assertEqual(app.kodama_history.diagnostic, '')
                        self.assertEqual(app._kodama_capture, capture)
                        anchors.append((preceding_stop, latest.tick))
                    records = [json.loads(line) for line in app._trace.path.read_bytes().splitlines()]
                    raw = [r['data'] for r in records if r['kind'] == 'kodama_sample']
                    self.assertEqual([r['sample_seq'] for r in raw], list(range(1, len(raw) + 1)))
                    self.assertTrue(all(r['capture'] == capture for r in raw))
                    for anchor, _ in anchors:
                        api = [r for r in raw if r['origin'] == 'api' and r['stop'] == anchor]
                        self.assertEqual(len(api), 16)
                        self.assertTrue(all(r['stop_anchor'] == 'preceding-visible-stop' for r in api))
                    ticks = [tick for _, tick in anchors]
                    if actual:
                        # The real clock starts before Init completes. Startup
                        # can consume ticks, so checkpoint time has an offset.
                        self.assertGreaterEqual(ticks[0], 1000)
                        self.assertEqual(ticks[1] - ticks[0], 1000)
                    else:
                        self.assertEqual(ticks, [1, 2])
                    self.assertIn('⋮ capture gap', str(app.query_one(KodamaCanvas).render()))
                    self.assertIsNone(qemu.poll())
                    receipt = os.environ.get('DBG3K_BUDGET_RECEIPT')
                    if receipt:
                        destination = Path(receipt); destination.mkdir(exist_ok=True, parents=True)
                        (destination / f'{elf.stem}-trace.jsonl').write_bytes(app._trace.path.read_bytes())
                        (destination / f'{elf.stem}-oracle.json').write_text(json.dumps(dict(
                            actual_kodama=actual, api_budget=16, anchors=anchors, samples=len(raw),
                            capture=capture, gap_samples=sum('capture_gap' in r for r in raw))) + '\n')
            finally:
                if qemu.poll() is None:
                    qemu.terminate()
                qemu.wait(timeout=5)

    async def test_public_arm_fixture_continues_recording_after_exhaustion(self):
        """Protocol fixture only; not a replacement Kodama implementation."""
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as directory:
            folder = Path(directory); source = folder / 'kodama.c'
            source.write_text('''#include <stdint.h>
typedef struct { unsigned inputs; unsigned char kind; } Alternative;
typedef struct { const Alternative *alternatives; unsigned char count; } Subscription;
typedef struct { unsigned active,generation,ready,priority,cluster,promoted,sleeping,waiting;
 void *context; const Subscription *subscription; unsigned seen,wake_mask,deadline,next; } Task;
struct Handle { void *_M_fr_ptr; };
struct Command { struct Handle handle; unsigned token; } g_cmd[1];
struct FrameSlot { unsigned char data[16]; unsigned char used; } g_frames[1];
static Task tasks[1];
static unsigned running,levels,clock_ticks,yield_skip,order_head,destroying;
__attribute__((noinline)) static void signal_locked(unsigned occurrence,int isr) { tasks[0].seen|=occurrence; }
__attribute__((noinline)) int kodama_signal(unsigned occurrence) { signal_locked(occurrence,0); return 1; }
__attribute__((noinline)) int kodama_run_one(void) { return 0; }
__attribute__((noinline)) void budget_checkpoint(void) { __asm volatile("nop"); }
int main(void) {
 tasks[0].active=1;tasks[0].generation=1;tasks[0].ready=1;tasks[0].priority=10;
 tasks[0].cluster=1;tasks[0].next=255;
 for(;;){for(unsigned i=0;i<32;++i)kodama_signal(1);++clock_ticks;budget_checkpoint();}
}
''')
            elf = folder / 'budget.elf'
            subprocess.run(['arm-none-eabi-gcc', '-mcpu=cortex-m33', '-mthumb', '-O0', '-g3',
                '-ffreestanding', '-fno-builtin', '-nostdlib', '-T', str(root / 'examples/an505/linker.ld'),
                str(root / 'examples/an505/startup.c'), str(source), '-o', str(elf)], check=True, capture_output=True)
            await self.capture_two_runs(elf, folder)

    @unittest.skipUnless(os.environ.get('DBG3K_KODAMA_DEMO_ELF'), 'requires actual continuous Kodama demo ELF')
    async def test_actual_kodama_demo_second_continue_records_new_activity(self):
        with TemporaryDirectory() as directory:
            await self.capture_two_runs(Path(os.environ['DBG3K_KODAMA_DEMO_ELF']).resolve(),
                                        Path(directory), actual=True)

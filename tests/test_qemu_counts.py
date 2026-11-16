"""Real plugin oracle: five loop iterations dispatch exactly 13 instructions.

DBG3K_QEMU_PLUGIN_TEST=1 PYTHONPATH=src python -m unittest discover -s tests -p test_qemu_counts.py -v
Build plugins/libdbg3k-counts.so first; requires a matching QEMU plugin header.
"""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from dbg3k.resources import CodeCatalog, InstructionProfile


@unittest.skipUnless(os.environ.get('DBG3K_QEMU_PLUGIN_TEST') == '1', 'opt-in real QEMU plugin test')
class QemuCountTests(unittest.TestCase):
    def test_exact_loop_count_elf_size_and_unseen_instruction_exclusion(self):
        root = Path(__file__).resolve().parents[1]
        plugin = Path(os.environ.get('DBG3K_PLUGIN', root / 'plugins/libdbg3k-counts.so')).resolve()
        with TemporaryDirectory() as folder:
            folder = Path(folder)
            assembly, elf, output = folder / 'fixture.s', folder / 'fixture.elf', folder / 'counts.json'
            assembly.write_text('''
.syntax unified
.cpu cortex-m33
.thumb
.section .vectors,"a",%progbits
.word _stack_top
.word Reset_Handler
.text
.global Reset_Handler
.type Reset_Handler,%function
.thumb_func
Reset_Handler:
    bl counted
    bl counted
    movs r0,#0x20
    ldr r1,=exit_block
    bkpt #0xab
    b .
.size Reset_Handler,.-Reset_Handler
.align 2
exit_block: .word 0x20026,0
.global counted
.type counted,%function
.thumb_func
counted:
    push {r4,lr}
    movs r4,#5
1:  subs r4,#1
    bne 1b
    pop {r4,pc}
.size counted,.-counted
.global never_called
.type never_called,%function
.thumb_func
never_called:
    nop
    bx lr
.size never_called,.-never_called
''')
            subprocess.run(['arm-none-eabi-gcc', '-mcpu=cortex-m33', '-mthumb', '-nostdlib',
                            '-T', str(root / 'examples/an505/linker.ld'), str(assembly), '-o', str(elf)],
                           check=True, capture_output=True)
            run = subprocess.run(['qemu-system-arm', '-M', 'mps2-an505', '-display', 'none',
                                  '-monitor', 'none', '-serial', 'none', '-semihosting-config',
                                  'enable=on,target=native', '-kernel', str(elf),
                                  '-plugin', f'{plugin},out={output},elf={elf}'],
                                 capture_output=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            data = json.loads(output.read_text())
            self.assertTrue(data['complete'])
            code, profile = CodeCatalog(str(elf)), InstructionProfile()
            profile.update(data, code)
            counted = next(f for f in code.functions if 'counted' in f.names)
            unused = next(f for f in code.functions if 'never_called' in f.names)
            self.assertEqual(counted.size, 10)
            self.assertEqual(unused.size, 4)
            self.assertEqual(profile.by_function[counted.key], 26)  # two calls * (push+mov+5*(subs+bne)+pop)
            self.assertEqual(profile.by_function.get(unused.key, 0), 0)
            self.assertEqual(profile.total, sum(profile.by_function.values()) + profile.unknown)
            pcs = dict(data['pcs'])
            self.assertEqual(pcs[f'0x{counted.start + 4:x}'], 10)
            self.assertEqual(pcs[f'0x{counted.start + 6:x}'], 10)

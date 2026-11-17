"""Pair the actual ELF/plugin/profile paths without starting a debugger or target."""
import importlib.util
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('demo_launcher', ROOT / 'examples/kodama-demo/run.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class DemoLauncherTests(unittest.TestCase):
    def test_quoted_paths_profile_pairing_and_unique_run_directories(self):
        with TemporaryDirectory(prefix='demo paths ') as directory, redirect_stdout(io.StringIO()):
            root = Path(directory); demo = root / 'kodama/experiments/diagram_yaml'
            demo.mkdir(parents=True)
            (demo / 'build_demo.py').touch(); (demo / 'debug_signals.h').touch()
            elf = root / 'demo with spaces.elf'; elf.write_bytes(b'fixture ELF identity')
            plugin = root / 'test counts.so'; plugin.touch()
            argv = ['--kodama-dir', str(root / 'kodama'), '--elf', str(elf), '--plugin', str(plugin),
                    '--dbg3k', '/path with spaces/dbg3k', '--output-dir', str(root / 'runs'), '--dry-run']
            self.assertEqual(launcher.main(argv), 0)
            self.assertEqual(launcher.main(argv), 0)
            manifests = list((root / 'runs').glob('*/launch.json'))
            self.assertEqual(len(manifests), 2)
            data = [json.loads(path.read_text()) for path in manifests]
            self.assertNotEqual(data[0]['instruction_profile'], data[1]['instruction_profile'])
            for run in data:
                qemu, dbg = run['qemu_command'], run['dbg3k_command']
                self.assertIn(str(elf), qemu[qemu.index('-device') + 1])
                option = qemu[qemu.index('-plugin') + 1]
                self.assertEqual(option, f'{plugin},out={run["instruction_profile"]},elf={elf}')
                self.assertEqual(dbg[dbg.index('--instruction-profile') + 1], run['instruction_profile'])
                self.assertEqual(dbg[1], str(elf))
                self.assertIn('--kodama-no-probes', dbg)
                self.assertEqual(shlex.split(shlex.join(dbg)), dbg)
            self.assertEqual(launcher.main([*argv, '--no-profile', '--api-probes']), 0)
            latest = next(json.loads(p.read_text()) for p in (root / 'runs').glob('*/launch.json')
                          if json.loads(p.read_text())['instruction_profile'] is None)
            self.assertNotIn('-plugin', latest['qemu_command'])
            self.assertNotIn('--instruction-profile', latest['dbg3k_command'])
            self.assertNotIn('--kodama-no-probes', latest['dbg3k_command'])

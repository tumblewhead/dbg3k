"""Launch the Kodama diagram demo with a matching instruction profile and dbg3k command."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def prepare(args):
    kodama = args.kodama_dir.expanduser().resolve()
    demo = kodama / 'experiments/diagram_yaml'
    if not (demo / 'build_demo.py').is_file() or not (demo / 'debug_signals.h').is_file():
        raise ValueError('Use the Kodama experiment/diagram-yaml-001 checkout/worktree; see docs/KODAMA_DEMO_HANDOFF.md')
    if not 1 <= args.port <= 65535:
        raise ValueError('Port must be 1..65535')
    elf = args.elf.expanduser().resolve() if args.elf else kodama / 'build/diagram-demo/demo.elf'
    plugin = args.plugin.expanduser().resolve() if args.plugin else ROOT / 'plugins/libdbg3k-counts.so'
    output = args.output_dir.expanduser().resolve()
    if ',' in str(elf) or (not args.no_profile and any(',' in str(path) for path in (plugin, output))):
        raise ValueError('Plugin/ELF/output paths must not contain commas (QEMU plugin option separator)')
    if args.elf is None:
        subprocess.run([sys.executable, str(demo / 'build_demo.py')], cwd=kodama, check=True)
    if not elf.is_file():
        raise ValueError(f'ELF does not exist: {elf}')
    if not args.no_profile:
        if args.plugin is None:
            # Rebuild against the installed matching header, rather than reusing
            # an old binary after a QEMU upgrade. QEMU_INCLUDE is honored by make.
            subprocess.run(['make', '-B', '-C', str(ROOT / 'plugins')], check=True)
        if not plugin.is_file():
            raise ValueError(f'Plugin does not exist: {plugin}')
    executable = args.dbg3k
    if executable is None:
        local = ROOT / '.venv/bin/dbg3k'
        executable = str(local) if local.is_file() else shutil.which('dbg3k')
    if not executable:
        raise ValueError('Install dbg3k in .venv or pass --dbg3k /path/to/dbg3k')
    run_dir = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    counts = run_dir / 'counts.json'
    qemu = [args.qemu, '-M', 'mps2-an505', '-display', 'none', '-serial', 'none', '-monitor', 'none',
            '-semihosting-config', 'enable=on,target=native', '-device', f'loader,file={elf},cpu-num=0',
            '-S', '-gdb', f'tcp:127.0.0.1:{args.port}']
    if not args.no_profile:
        qemu += ['-plugin', f'{plugin},out={counts},elf={elf}']
    debugger = [executable, str(elf), '--gdb', args.gdb, '--remote', f'127.0.0.1:{args.port}',
                '--kodama', '--kodama-header', str(demo / 'debug_signals.h'),
                '--history-dir', str(run_dir / 'history'), '--observe', 'g_demo_shared.hfe_result',
                '--observe', 'g_demo_shared.scratchpad.entries[0]']
    if not args.api_probes:
        debugger.append('--kodama-no-probes')
    if not args.no_profile:
        debugger += ['--instruction-profile', str(counts)]
    manifest = dict(schema='dbg3k.kodama-demo-run/v1', elf=str(elf),
        elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(), kodama_dir=str(kodama),
        instruction_profile=None if args.no_profile else str(counts),
        api_probes=args.api_probes, qemu_command=qemu, dbg3k_command=debugger)
    (run_dir / 'launch.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return qemu, debugger, run_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kodama-dir', type=Path, required=True, help='Kodama experiment checkout/worktree')
    parser.add_argument('--elf', type=Path, help='Use an existing ELF instead of rebuilding')
    parser.add_argument('--port', type=int, default=3333)
    parser.add_argument('--qemu', default='qemu-system-arm')
    parser.add_argument('--gdb', default='gdb')
    parser.add_argument('--dbg3k', help='Override dbg3k executable; defaults to this checkout .venv/bin/dbg3k')
    parser.add_argument('--plugin', type=Path, help='Use a prebuilt compatible plugin instead of rebuilding it')
    parser.add_argument('--no-profile', action='store_true', help='Disable instruction profiling for a lighter run')
    parser.add_argument('--api-probes', action='store_true', help='Start with detailed scheduler API probes (slower)')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/kodama-demo-runs')
    parser.add_argument('--dry-run', action='store_true', help='Build/prepare and print commands without starting QEMU')
    args = parser.parse_args(argv)
    try:
        qemu, debugger, run_dir = prepare(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(2, f'Demo setup failed: {exc}\nSee docs/KODAMA_DEMO_HANDOFF.md\n')
    print(f'Run directory: {run_dir}', flush=True)
    print('Instruction plugin: ' + ('OFF' if args.no_profile else 'ON (profiling, not acceleration)'), flush=True)
    print('Scheduler API probes: ' + ('ON' if args.api_probes else 'OFF initially; enable in Kodama Setup for short traces'), flush=True)
    print('QEMU command:\n' + shlex.join(qemu), flush=True)
    print('SECOND TERMINAL — paste this exact command:\n' + shlex.join(debugger), flush=True)
    if args.dry_run:
        return 0
    try:
        process = subprocess.Popen(qemu)
    except OSError as exc:
        parser.exit(2, f'Cannot start QEMU: {exc}\n')
    try:
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())

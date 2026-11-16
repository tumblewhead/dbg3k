"""CLI: dbg3k ELF --gdb gdb --remote localhost:1234."""
import argparse
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description="dbg3k: Cortex-M source debugger")
    p.add_argument("elf", type=Path, help="ELF with debug symbols")
    p.add_argument("--gdb", default="gdb", help="GDB binary (ARM target support needed)")
    p.add_argument("--remote", default="localhost:1234", help="QEMU GDB endpoint")
    p.add_argument("--history-dir", type=Path, default=Path("dbg3k-history"),
                   help="Append-only JSONL output directory (default ./dbg3k-history)")
    profiles = p.add_mutually_exclusive_group()
    profiles.add_argument('--instruction-profile', type=Path, help='Atomic JSON snapshot written by QEMU counts plugin')
    profiles.add_argument('--profile-history', type=Path, help='Read and follow recorded instruction/energy JSONL events')
    p.add_argument('--profile-session', help='Pin --profile-history to one debugger session UUID (default: newest matching profile session)')
    p.add_argument('--observe', action='append', default=[], metavar='EXPRESSION',
                   help='Capture this read-only selector at each stop (repeatable; up to 16) in the existing JSONL trace')
    kodama = p.add_mutually_exclusive_group()
    kodama.add_argument('--kodama', action='store_true', default=None, help='Enable graphical Kodama view (default: detect ELF)')
    kodama.add_argument('--no-kodama', action='store_false', dest='kodama', help='Disable automatic Kodama view')
    p.add_argument('--kodama-header', type=Path, help='Application header containing signal bit names')
    p.add_argument('--kodama-no-probes', action='store_false', dest='kodama_probes', help='Collect only manual-stop Kodama snapshots')
    p.add_argument('--kodama-history', type=Path, help='View/follow a Kodama JSONL journal without starting GDB')
    p.add_argument('--kodama-session', help='Pin --kodama-history to one debugger session UUID')
    p.add_argument('--ua-per-mhz', type=float, help='Assumed active current slope (µA/MHz)')
    p.add_argument('--mips-per-mhz', type=float, help='Assumed instruction throughput (MIPS/MHz)')
    p.add_argument('--voltage', type=float, help='Assumed supply voltage (V)')
    args = p.parse_args()
    if args.profile_session and not args.profile_history:
        p.error('--profile-session requires --profile-history')
    if args.kodama_session and not args.kodama_history:
        p.error('--kodama-session requires --kodama-history')
    if not args.elf.is_file():
        p.error(f"ELF not found: {args.elf}")
    from .app import DebuggerApp
    from .resources import EnergyModel
    from .observations import select_expressions
    try:
        select_expressions(args.observe)
    except ValueError as exc:
        p.error(str(exc))
    energy = None
    values = (args.ua_per_mhz, args.mips_per_mhz, args.voltage)
    if any(value is not None for value in values):
        if any(value is None for value in values):
            p.error('Energy estimates require --ua-per-mhz, --mips-per-mhz and --voltage together')
        try:
            energy = EnergyModel(*values)
        except ValueError as exc:
            p.error(str(exc))
    DebuggerApp(str(args.elf.resolve()), args.gdb, args.remote,
                history_dir=str(args.history_dir),
                instruction_profile=str(args.instruction_profile) if args.instruction_profile else None,
                energy_model=energy,
                profile_history=str(args.profile_history) if args.profile_history else None,
                profile_session=args.profile_session, observations=args.observe,
                kodama=args.kodama if args.kodama is not None else (True if args.kodama_header else None),
                kodama_header=str(args.kodama_header) if args.kodama_header else None,
                kodama_probes=args.kodama_probes,
                kodama_log=str(args.kodama_history) if args.kodama_history else None,
                kodama_session=args.kodama_session).run()

if __name__ == "__main__":
    main()

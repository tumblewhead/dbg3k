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
    p.add_argument('--ua-per-mhz', type=float, help='Assumed active current slope (µA/MHz)')
    p.add_argument('--mips-per-mhz', type=float, help='Assumed instruction throughput (MIPS/MHz)')
    p.add_argument('--voltage', type=float, help='Assumed supply voltage (V)')
    args = p.parse_args()
    if args.profile_session and not args.profile_history:
        p.error('--profile-session requires --profile-history')
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
                profile_session=args.profile_session, observations=args.observe).run()

if __name__ == "__main__":
    main()

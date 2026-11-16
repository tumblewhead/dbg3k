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
    p.add_argument('--instruction-profile', type=Path, help='Atomic JSON snapshot written by QEMU counts plugin')
    p.add_argument('--ua-per-mhz', type=float, help='Assumed active current slope (µA/MHz)')
    p.add_argument('--mips-per-mhz', type=float, help='Assumed instruction throughput (MIPS/MHz)')
    p.add_argument('--voltage', type=float, help='Assumed supply voltage (V)')
    args = p.parse_args()
    if not args.elf.is_file():
        p.error(f"ELF not found: {args.elf}")
    from .app import DebuggerApp
    from .resources import EnergyModel
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
                energy_model=energy).run()

if __name__ == "__main__":
    main()

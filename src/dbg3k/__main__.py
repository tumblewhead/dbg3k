"""CLI: dbg3k ELF --gdb gdb --remote localhost:1234."""
import argparse
from pathlib import Path

def main():
    p = argparse.ArgumentParser(description="dbg3k: Cortex-M source debugger")
    p.add_argument("elf", type=Path, help="ELF with debug symbols")
    p.add_argument("--gdb", default="gdb", help="GDB binary (ARM target support needed)")
    p.add_argument("--remote", default="localhost:1234", help="QEMU GDB endpoint")
    args = p.parse_args()
    if not args.elf.is_file():
        p.error(f"ELF not found: {args.elf}")
    from .app import DebuggerApp
    DebuggerApp(str(args.elf.resolve()), args.gdb, args.remote).run()

if __name__ == "__main__":
    main()

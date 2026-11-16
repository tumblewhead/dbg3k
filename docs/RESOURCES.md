# Stack, code/instruction and energy views

Three independently selectable panes follow the active stack frame selected in
the existing tree. Ctrl+P → View entries → Left/Right, or use the Views dialog.

| Pane | Evidence and scope |
| --- | --- |
| Stack frames and stack watch | GDB-visible frame count, active instances of the selected emitted function, available SP/MSP/PSP registers, unwound-SP frame contribution and inclusive estimates, sampled peaks |
| Code and instruction counts | ELF sized executable function body (normally `.text`), exclusive guest instruction dispatches since QEMU launch, share of all dispatches, unknown/ambiguous PC bucket |
| Energy estimate | User-supplied active-current slope, throughput and voltage applied to the selected body's exclusive instruction count |

## Start QEMU with instruction counting

Requirements: a plugin-enabled QEMU system emulator, C compiler, `pkg-config`,
GLib development headers and the **matching QEMU public `qemu-plugin.h`**.
The header is often `/usr/include/qemu-plugin.h`. If it is missing, get it from
the source release matching your QEMU binary, and set `QEMU_INCLUDE` to its
directory. QEMU rejects incompatible plugin API versions. No target firmware
instrumentation is added.

From the dbg3k repository:

```sh
. .venv/bin/activate
python -m pip install -e .
make -C plugins
# Or: make -C plugins QEMU_INCLUDE=/path/to/matching/header-directory
make -C examples/an505
```

Terminal 1, from the dbg3k repository:

```sh
qemu-system-arm -M mps2-an505 -display none -monitor none -serial none \
  -semihosting-config enable=on,target=native \
  -kernel "$PWD/examples/an505/firmware.elf" -S -gdb tcp:127.0.0.1:1234 \
  -plugin "$PWD/plugins/libdbg3k-counts.so,out=/tmp/dbg3k-counts.json,elf=$PWD/examples/an505/firmware.elf"
```

Terminal 2:

```sh
dbg3k examples/an505/firmware.elf --instruction-profile /tmp/dbg3k-counts.json
```

For Kodama, append the same `-plugin` argument to its QEMU launch, using the
actual Kodama ELF in both the plugin's `elf=` option and dbg3k. Preserve its
existing loader, SRAM layout and startup flags. The `elf=` option fingerprints
the supplied ELF; it does not load firmware. Use a distinct output path for each
QEMU process, and paths without commas (QEMU's plugin-option separator).
Instruction collection requires restarting QEMU with the plugin enabled.

The Stack pane works without the plugin, with Python-enabled GDB. Missing
registers, symbols or plugin data display **unavailable**, rather than zero.

## Stack interpretation

Frame contribution is `caller unwound SP - frame unwound SP` for adjacent normal
frames on a downward-growing stack. Inclusive usage adds active callees down to
the executing frame. These are **estimates** based on GDB's unwinder at a stop,
including save areas/alignment where reflected in SP; they are not compiler
frame-size guarantees. The oldest frame has no caller SP, so its contribution
is unavailable. Inline/other frame boundaries, negative deltas and active ARM
exceptions do not produce byte estimates.

Peaks are maxima of these sampled estimates, aggregated by thread and emitted
body. They can miss deeper use between stops. Frame count is debugger-visible
call depth, not stack bytes or coroutine storage. Kodama coroutine frames live
outside the active C stack and are not counted as dedicated task stacks. MSP/PSP
values are separate and may be unavailable with a given GDB stub. No verified
stack origin or universal stack bound is inferred.

## Instruction interpretation and provenance

The collector registers an execution callback for every translated instruction.
Translation itself does not increment counts. Retranslations of the same virtual
PC reuse one counter. This first collector supports single-vCPU system emulation.
It takes a lock per dispatch and writes an atomic cumulative JSON snapshot about
every 100 ms; it adds emulator overhead. A snapshot is not synchronized to a GDB
stop and may lag the displayed stack. Snapshot `run` UUID and sequence distinguish
QEMU launches, and `complete=true` marks a clean final snapshot.

The ELF SHA256 must match dbg3k's ELF before counts can be used. This checks the
build, not the identity of a separately attached target: use the output from the
same QEMU process. New UUIDs reset displayed cumulative counts. Counts include
startup/handlers where attributed; they are exclusive by emitted ELF body,
aggregated across calls/recursion/tasks. The displayed denominator is **all
recorded guest dispatches since QEMU launch**. No inclusive or per-invocation
instruction count is claimed.

ELF aliases with identical section/start/size share a body and are not counted
twice. Unsized/stripped functions, unequal overlapping ranges, ROM and other
unmapped PCs remain in an unknown bucket. The plugin bounds tracked PCs to
262144; further executed addresses increment an overflow bucket included in the
unknown total. Inline functions are attributed to their containing emitted body,
which is named in the pane. Code size is ELF symbol extent inside an executable
section; it is not an estimate from source lines or Thumb instruction width.

QEMU's instruction callbacks occur before completion, so **dispatches may include
faulting instructions**. They are not retired instructions, silicon cycles,
elapsed target time or CPU utilization. See the primary
[QEMU plugin documentation](https://www.qemu.org/docs/master/devel/tcg-plugins.html)
and [GDB frame API](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Frames-In-Python.html).

## Energy assumptions

Ctrl+P → **Energy model** opens fields for current slope (µA/MHz), throughput
(MIPS/MHz), and supply voltage. Values must all be finite and positive. No chip
parameters are silently assumed. CLI equivalents:

```text
--ua-per-mhz VALUE --mips-per-mhz VALUE --voltage VALUE
```

```text
charge per instruction [pC] = (µA/MHz) / (MIPS/MHz)
estimated charge [pC] = dispatch count × charge per instruction
estimated energy [pJ] = estimated charge × voltage [V]
```

These are user-configured constant active-core estimates for the same cumulative
exclusive work as the count pane. Idle, leakage, peripherals, memory effects,
faults and actual target throughput may invalidate the simple model. **Average
power remains unavailable without target execution duration**; host/QEMU time
and debugger pauses must not be substituted for it.

## Reproduce qualification

```sh
make -C plugins
DBG3K_QEMU_TEST=1 DBG3K_QEMU_PLUGIN_TEST=1 PYTHONPATH=src \
  python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Set `DBG3K_GDB=gdb-multiarch` as needed. The assembly oracle executes a five-iteration
loop twice: 13 dispatches per call, 26 total, 10 ELF body bytes. An uncalled
4-byte function counts zero. The mounted Textual/GDB/QEMU test checks actual
stack snapshots, ELF mapping and live plugin ingestion while retaining return
observations. This is AN505 M33 emulator evidence; physical M23, ISR-stack and
current Kodama-specific profiling remain unqualified.

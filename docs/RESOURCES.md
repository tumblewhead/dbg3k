# Stack, code/instruction and energy views

Three independently selectable panes follow the active stack frame selected in
the existing tree. Ctrl+P → View entries → Left/Right, or use the Views dialog.

Three additional graphical panes reuse the same evidence. The original textual
panes remain available:

| Graphical pane | Display and controls |
| --- | --- |
| Graphical stack map and contents | Vertical colored frame-gap bar, exact sampled address boundaries, selected-frame marker, SP/MSP/PSP values, and up to 256 actual raw stack bytes |
| Run statistics and Pareto ranking | All emitted functions, total/exclusive dispatch counts, current-function count/rank, entry-hit call proxy, code bytes, instructions per entry/byte, share and cumulative share |
| Graphical energy ranking | Ranked exclusive estimated charge/energy for all emitted bodies, estimated run total and unattributed energy under the same user model |

Choose the sort metric in each ranking pane, click a table heading, or use the
ascending/descending button. The bars show the top eight rows and the current
function even if it ranks lower; the table contains all bodies and can scroll in
both directions. Cursor selection is retained across live count updates.
`▶` marks the currently stopped function (`Last stopped` while running); `▸`
marks another frame selected in the stack tree. Ties use stable name/address
order. Cumulative percentages always divide by **all** recorded dispatches,
including unknown PCs; consequently attributed functions may sum to less than
100%. Default descending instruction/energy order is Pareto-style; other sort
orders are ranked bars with cumulative instruction shares.

**Calls† means function-entry dispatch hits**, taken directly from the existing
PC histogram at each sized ELF body's normalized start address. It is a call-count
proxy, not an exact invocation trace: tail entries, resets, loops back to entry,
faulting entry instructions, and jumps into the middle of a body affect the
interpretation. Aliases share one entry counter. `Instr/entry` stays unavailable
if no entry was observed; it is never inferred by dividing by zero. Entry counts
reset with the QEMU run UUID. No plugin rebuild/schema change is needed for this
derived metric, so existing compatible profile files can be ranked.

The stack bar covers only adjacent normal-frame unwound-SP gaps, ordered from
higher to lower addresses. Heights scale to estimated bytes with a minimum one
row per gap; exact boundaries and sizes are labeled. Unknown/discontinuous or
overlapping ranges are not silently joined. It does not draw invented free space,
the oldest frame's unknown allocation, or coroutine storage. The raw hex dump
shows bytes actually read by GDB at the same halted stop, from SP toward the
highest sampled SP, bounded to 256 bytes. Bytes are not labeled as specific local
variables without corresponding location evidence. Unsupported reads show
unavailable, and samples from earlier stops are not displayed as current.

Energy bars represent **estimated energy, not measured power**. With one common
charge-per-instruction model for all functions, energy ordering is necessarily
the same as instruction ordering. Peripheral/idle contributions remain excluded.

## Reliable energy updates and recorded profiles

Live profile snapshots are validated, appended as cumulative `instruction_profile`
events, then consumed incrementally from the active session's JSONL stream for
the rankings. A temporary missing/partial snapshot file or unavailable history
read retains the last validated result with a source/status message. A failed
history write falls back to validated live data and closes the failed writer.
Wrong-build or inconsistent live data is still rejected.

On a normal live launch, explicit energy assumptions previously recorded for the
**same ELF SHA256** are restored from matching history files. CLI values and new
choices made through **Model…** or the Energy model palette command take
precedence. Restored values and their source session are displayed; review them
when changing hardware. No chip defaults are invented. If assumptions have never
been recorded, measured work still populates the energy table while energy cells
remain unavailable; the Model button opens the assumption editor.

You can instead follow an existing or growing JSONL file:

```sh
dbg3k examples/an505/firmware.elf \
  --profile-history dbg3k-history/firmware_YYYY-MM-DD.jsonl \
  --profile-session SESSION_UUID
```

Use a real path/date and a session UUID from a `session_start` record. Omit
`--profile-session` to follow the newest matching session **with a valid profile**;
late writes from older sessions cannot supersede it. This selects the profiling
source; GDB attachment retains its normal behavior. `--profile-history` and
`--instruction-profile` are mutually exclusive. The display labels recorded run
data separately from live GDB state. Replaying a session uses that session's
recorded assumptions unless you explicitly override them via CLI or Model…;
assumptions from another recorded session are not silently attached during replay.

The reader processes appended bytes in bounded batches (~4 polls/sec), buffers
partial UTF-8/JSON lines until newline, skips malformed records, and detects file
replacement/truncation. Large files catch up progressively with a queued-byte
indicator. Cumulative snapshots **replace** prior totals; they are never summed.
Session/build/run identity and monotone sequence validation prevent mixing runs
or double-counting repeated events. A QEMU run UUID change resets counters.

Older logs without `entry_hits` show unavailable Calls/Instr-per-entry rather
than invented zeroes. Logs containing only debugger stops or return observations
cannot supply guest instruction counts or energy estimates; valid recorded
instruction profiles are required.

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
The graphical stack pane also works without the plugin; rankings need matching
QEMU count data and energy rankings additionally need configured assumptions.

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

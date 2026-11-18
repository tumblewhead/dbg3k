# Run and present the Kodama demo with dbg3k

For full-file history inspection, see the [browser workflow](BROWSER_HISTORY.md):
run `python -m dbg3k.history_browser`, open its local URL and select the JSONL.
It adds task/signal/pool, stack, instruction and electrical-model history views
without launching GDB/QEMU or requiring the original ELF.

This guide is for someone receiving the demo for the first time. It covers
setup, both terminals, the UI, the GDB commands, profiling, saving a session,
and recovery from the problems encountered during development.

The application stays alive in a superloop. Init releases nine services after
their startup waits. Synthetic ADC inputs feed Pipeline at 1 Hz, HFE at 500 Hz
while it exists, and Mellow at 35 Hz. Prime Pipeline samples start at most one
two-second HFE instance. Logging, telemetry, scripted commands, scratchpad
request/reply, and coroutine frame reclamation make the scheduler observable.

Use **dbg3k branch `feature/kodama-demo-handoff`** and **Kodama branch
`experiment/diagram-yaml-001`** for this guide. They are experimental branches
with draft reviews. Record the exact commits when handing over a run.

Quick index: [setup](#1-prepare-the-checkouts-and-tools),
[QEMU/plugin](#2-start-terminal-a-firmware-qemu-and-the-plugin),
[dbg3k](#3-start-terminal-b-dbg3k), [UI layout](#4-arrange-the-ui),
[overview](#5-overview-initialization-first-result-and-application-output),
[detailed timeline](#6-detailed-timeline-capture-real-waits-and-task-handoffs),
[profiling](#7-instructions-code-size-stack-and-energy),
[saved runs](#8-structured-observations-and-saved-history),
[CLI exercise](#9-scripted-cli-scratchpad-and-logging-exercises),
[command reference](#10-gdb-and-keyboard-reference),
[recovery](#11-recovery-and-repeatability).

## 1. Prepare the checkouts and tools

For the existing development machine, open a shell and set:

```sh
export DBG3K_DIR=/home/easy/proj/qemu-learn/dbg3k
export KODAMA_DIR=/tmp/kodama-diagram-yaml
```

The Kodama demo is in that separate worktree. The original
`/home/easy/proj/kodama` checkout contains optimization work and is a different
branch. If Git says a branch is already used by a worktree, run
`git -C /home/easy/proj/kodama worktree list`, then use the listed demo directory
as `KODAMA_DIR`. Do not set the optimization branch's upstream to the demo branch.

Update the existing dbg3k checkout:

```sh
cd "$DBG3K_DIR"
git fetch origin
git switch feature/kodama-demo-handoff
git pull --ff-only
git -C "$KODAMA_DIR" pull --ff-only
```

For a new recipient, use fresh directories instead. Access to both GitHub
repositories is required:

```sh
mkdir -p "$HOME/kodama-workshop"
cd "$HOME/kodama-workshop"
git clone --branch feature/kodama-demo-handoff https://github.com/tumblewhead/dbg3k.git dbg3k
git clone --branch experiment/diagram-yaml-001 https://github.com/tumblewhead/kodama.git kodama
export DBG3K_DIR="$HOME/kodama-workshop/dbg3k"
export KODAMA_DIR="$HOME/kodama-workshop/kodama"
```

Required host tools:

| Tool | Purpose |
| --- | --- |
| Python 3.11+ and venv/pip | dbg3k and the build/launch scripts |
| ARM GCC/G++ with C++20 headers and newlib | Build the M23-targeted firmware |
| `qemu-system-arm` with plugin support | Run the AN505 model |
| ARM-capable GDB (`gdb` or `gdb-multiarch`) | Debug the target |
| C compiler, make, pkg-config, GLib development headers | Build the counting plugin |
| Matching QEMU `qemu-plugin.h` | Compile a compatible plugin |

The Ubuntu 24.04 target CI uses these packages:

```sh
sudo apt-get update
sudo apt-get install -y python3-venv build-essential pkg-config libglib2.0-dev \
  gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-dev \
  qemu-system-arm gdb-multiarch
```

The plugin header is often `/usr/include/qemu-plugin.h`. If absent, obtain it
from the source release matching your QEMU binary. See [plugin setup](RESOURCES.md#start-qemu-with-instruction-counting).
For a nonstandard location, set `QEMU_INCLUDE` to the directory containing it
before running the launcher. A header from an arbitrary QEMU release can fail.

Install the Python requirements in dbg3k's environment. Include the Kodama
requirements so its YAML generators work in this same environment:

```sh
cd "$DBG3K_DIR"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e . -r "$KODAMA_DIR/experiments/diagram_yaml/requirements.txt"
```

On an existing installation, activate its existing `.venv` and run the pip
command; creating it again is unnecessary. `dbg3k` is installed in
`$DBG3K_DIR/.venv/bin`, so activation or that executable's absolute path is needed.

## 2. Start Terminal A: firmware, QEMU and the plugin

Use this launcher in the **dbg3k repository**, rather than Kodama's older
`experiments/diagram_yaml/run_demo.py`. The older launcher does not load the
instruction-counting plugin.

```sh
cd "$DBG3K_DIR"
. .venv/bin/activate
python examples/kodama-demo/run.py --kodama-dir "$KODAMA_DIR"
```

If the ARM-capable debugger is `gdb-multiarch`, append `--gdb gdb-multiarch`.
The launcher:

1. Builds `build/diagram-demo/demo.elf` in the Kodama checkout.
2. Rebuilds `plugins/libdbg3k-counts.so` against the configured QEMU header.
3. Creates a unique local run directory under `dbg3k/build/kodama-demo-runs/`.
4. Starts QEMU **paused**, using the Secure SRAM loader and GDB port 3333.
5. Prints the exact command to paste into Terminal B, including absolute ELF,
   plugin profile, signal header and history paths.

Look for **Instruction plugin: ON** and a QEMU command containing `-plugin`.
Leave this terminal open: application messages appear here as execution proceeds.

Record the printed **Run directory** as `RUN_DIR` for later commands. Each run
has its own `counts.json`, `launch.json` and `history/`; a prior profile is not
silently reused. `launch.json` records the ELF SHA256 and both command argument
lists. Paths used in QEMU options must not contain commas.

Useful launcher options:

| Option | When to use it |
| --- | --- |
| `--port 3334` | Another QEMU already owns port 3333; printed debugger command changes too |
| `--elf /absolute/path/demo.elf` | Reuse a built ELF without rebuilding firmware |
| `--api-probes` | Start detailed scheduler capture immediately; slower and bounded |
| `--no-profile` | Run without instruction profiling; a lighter emulator workload |
| `--plugin /path/libdbg3k-counts.so` | Use a known compatible prebuilt plugin |
| `--dry-run` | Build/prepare the run and print commands without starting QEMU |

### What the plugin does, and what makes the demo slow

`libdbg3k-counts.so` is an **instruction profiling plugin**. It counts guest
instruction dispatches within QEMU and supplies Code/Run statistics/Energy views.
It avoids using GDB to single-step every instruction for counting. It does not
accelerate QEMU; this implementation adds a callback and lock per instruction.
QEMU describes plugins as execution instrumentation in its
[TCG plugin documentation](https://www.qemu.org/docs/master/devel/tcg-plugins.html).

The detailed Kodama timelines use **separate GDB API-entry probes**. They read
scheduler state at many breakpoints and can be much slower. The counting plugin
does not replace those probes or provide task/signal timelines. Start with the
overview below, then enable probes for a short teaching interval. `-icount` is
not a speed plugin; the demonstrated interactive launch uses the normal QEMU
clock rather than the slow icount/software-probe combination encountered in tests.

## 3. Start Terminal B: dbg3k

Open another terminal and paste the **SECOND TERMINAL** command printed by the
launcher. It uses the dbg3k executable inside this checkout's `.venv`, so it
does not depend on the second shell already being activated.

That command supplies these settings:

| Setting | Value |
| --- | --- |
| ELF | The exact ELF loaded by Terminal A |
| Remote | `127.0.0.1:3333`, or the selected port |
| Signal names | Kodama's `experiments/diagram_yaml/debug_signals.h` |
| Instruction profile | This run's `counts.json` |
| JSONL history | This run's `history/` |
| Structured observations | `g_demo_shared.hfe_result`, `g_demo_shared.scratchpad.entries[0]` |
| Scheduler API probes | Initially off for the overview; enabled explicitly in section 6 |

dbg3k should report a halted target. Source initially can be in Reset_Handler;
the first command sequence below takes it to `main`.

### How to enter GDB commands

For every GDB command block in this guide:

1. Press **F2** to focus the GDB console input.
2. Enter **one command**, then press **Enter**. Repeat for additional lines.
3. Press **Esc** to leave the command input and focus Source.
4. Press **c** to continue, or **s/n** to step when instructed.

Shell commands belong in terminals, not the GDB input. Commands such as
`CLI:status` are application messages in the serial script, not GDB commands.
This version uses breakpoints to stop a run; do not rely on Ctrl+C as a universal
pause shortcut because it also copies text in the Kodama canvas.

## 4. Arrange the UI

1. Press **Ctrl+P**, search **Views**, select it and press Enter.
2. Keep **Source**, **Stack tree and observed returns**, **Immediate scope watch**,
   **GDB console**, and **Kodama graphical scheduler and timelines** checked.
3. Uncheck other panes for the scheduler lesson. Highlight a choice and use
   **Left/Right**, **Space**, or click its checkbox. Click **Done**.
4. The palette's individual **View:** entries also toggle with Left/Right
   without closing the palette. A checkmark means visible.
5. In the Kodama pane, click **Expand** for a full-width lesson view. **Esc** or
   **Close** returns to the source workspace.
6. Optional: Ctrl+P and choose a theme. The pool key follows the active theme.

Hiding a pane does not stop collection. Click Source before using source-step
keys; click the timeline before its navigation keys.

## 5. Overview: initialization, first result and application output

Keep API probes off for this section; the instruction plugin remains on.

At the initial halt, enter:

```gdb
tbreak main
```

Press Esc, then **c**. Source should stop in `main` in `arm_main.cpp`. It starts
the root task and configures the application timebase. To reach the first
one-second checkpoint, enter:

```gdb
tbreak demo_checkpoint
```

Press Esc, then **c**. `tbreak` removes itself when hit, so it will not interrupt
the later six-second exercise. Inspect these commands one at a time:

```gdb
print g_demo_shared.runtime
print/x g_demo_shared.runtime.startup_mask
print g_demo_shared.notes.init
print g_live
print g_frees
```

Expected for the supplied configuration: initialized is true, failed is zero,
startup_mask is `0x3fe`, Init's completion note is present, and its frame has been
released. There are nine permanent services. The pool can later rise to ten
occupied slots while HFE exists; eleven slots are configured.

Now set a temporary breakpoint at or after six logical seconds:

```gdb
tbreak demo_checkpoint if g_demo_shared.runtime.elapsed_ticks >= 6000
```

Press Esc, then **c**. Inspect:

```gdb
print g_demo_shared.hfe_result
print g_demo_shared.hfe_launches
print g_demo_shared.hfe_busy_skips
print g_demo_shared.adc_readers
print g_demo_shared.mellow
print g_demo_shared.telemetry
print g_demo_shared.scratchpad.entries[0]
```

Normally the first HFE result has 1,000 samples. The supplied ramp starts with
values 0, 1, 2, ... at 1 Hz: prime2 starts HFE around3s; prime3 around4s finds it
busy; the first two-second burst completes around5s. Check the recorded sample
and missed/coalesced counters rather than assuming exact delivery under every
debugger/emulator load. Results persist after HFE's frame is freed. The raw
kernel clock includes startup ticks; `runtime.elapsed_ticks` is the demo epoch.

Terminal A should show tagged `[Mellow]`, `[Pipeline]`, `[PerfTelemetry]`, `[HFE]`,
`[CLI]`, `[SP]`, and `[LOG/source]` messages. The first scratch entry should have
key `demo`, value `7`. Mellow is a small battery-shaped teaching workload, not a
validated Mumble/SCM integration or battery estimator.

## 6. Detailed timeline: capture real waits and task handoffs

The overview's few columns are stop snapshots. Enable API probes explicitly:

1. While halted, click **Setup** in the Kodama pane, or Ctrl+P → **Kodama setup**.
2. Confirm the header ends in `experiments/diagram_yaml/debug_signals.h`.
3. Turn on **Observe API entries between visible debugger stops**.
4. Click **Start / restart**. **Close** does not apply that change.
5. Confirm **API probes ON** with installed probes in the pane.

Start/restart creates a fresh capture segment and resets the displayed history.
Older segments remain in JSONL. It does not restart the firmware.

For a very short interval, enter:

```gdb
tbreak kodama_pend
```

Press Esc, then **c**. It stops at an actual wait call. Inspect the **Activity**
and **Inspect** areas; a verified live subscription/context can show its task
alias beside the raw address. Click the task lane for the wait explanation,
matched/missing inputs, priority, generation and pool slot. Another `tbreak
kodama_pend` followed by c gives another short interval.

For repeated one-second intervals instead, enter:

```gdb
break demo_checkpoint
```

Press Esc and **c**, then **c** again after the first stop. Both runs should
append API activity and current stop snapshots. Record this persistent
breakpoint's number from the console or `info breakpoints`. Disable it when
moving on, for example `disable 3` if its actual number is3.

Each run has a 4,096-API-sample budget. Exhaustion displays **API CAPTURE GAP**;
the next stop records a fresh snapshot, marks the unrecorded interval with **⋮**,
and automatically re-arms. Each cell is one observation, not equal elapsed time.
The gap is not proof that no task ran. Installed probes still add overhead after
their read budget is exhausted. Use shorter intervals for a more complete view
of the operation being taught.

### Navigate and interpret the lanes

| Control or mark | Meaning |
| --- | --- |
| Drag History thumb / click track | Pan tasks and signals together; names stay fixed |
| Page Up/Down | Page through retained samples when canvas has focus |
| Home | Oldest retained sample |
| End / Follow live | Newest samples; resume following incoming data |
| Left/Right | Inspect one sample older/newer |
| Up/Down | Select another task lane |
| Click task/signal cell | Inspect that sample; execution is unchanged |
| Vertical scrolling | Reach remaining signal rows, pool, inspector and diagnostics |
| ▶ / ◆ / ▒ / z | Running / ready / waiting / sleeping |
| ◇ / ! / · / × / ? | Parked / interrupted / free / retired / unavailable |
| △ / ● | API request / observed publication entry; neither proves successful return |
| △↑ / △↓ | Requested level-high/level-low change |
| Solid/dotted level waveform | Observed high/low level |
| ⋮ | Capture gap; intermediate activity was not recorded |

The UI retains512 samples; JSONL keeps older recorded samples. Browsing holds
your selection while capture continues. Press End if the view seems frozen.
Slot/generation/epoch distinguish observed task identities; slot number alone
does not establish that two HFE instances are the same task.

### Read the coroutine pool

Pool color follows the verified owning task's state. Read the **Owner state**
key and per-row label: typically green running, primary/blue ready, yellow
waiting/interrupted, purple sleeping and accent parked. Unknown state uses the
error color. **Other slots** explains dim free, warning-colored unattributed
ownership, and unavailable occupancy. Color mappings vary by theme.

`█` is occupied capacity, `░` free, and `?` unavailable. A sleeping/waiting task
still owns its coroutine frame. Capacity is not an observed per-allocation byte
request or a per-task stack; the hardware call stack is shared MSP storage.

After the short trace, use Setup → turn the probe switch **off** → **Start /
restart** to return to stop-snapshot mode while keeping the Kodama view active.
**Pause capture** instead stops Kodama collection until explicitly enabled.

## 7. Instructions, code size, stack and energy

1. Ctrl+P → Views: enable **Code and instruction counts** and **Run statistics
   and Pareto ranking**. You can hide Source/Kodama temporarily for space.
2. Continue to a checkpoint, then inspect the whole-run total and ranked bars.
   Counts should increase as QEMU executes. A just-started paused target may
   initially show zero/no executed rows.
3. In the ranking, select a sort metric or click a column heading. Compare
   Instructions, Calls†, code size, instructions/entry and share; reverse the
   order with the ascending/descending control.
4. Enable **Stack frames and stack watch** and **Graphical stack map and
   contents** for a halted call-stack snapshot. Select frames in the stack tree.
   Adjacent unwound-SP gaps are estimates; displayed raw bytes are stopped reads.
5. Enable **Energy estimate** and **Graphical energy ranking**. Choose **Model…**
   or Ctrl+P → **Energy model**. Enter current slope (µA/MHz), throughput
   (MIPS/MHz) and voltage, then **Apply assumptions**.

For a teaching calculation only, 48 µA/MHz, 1 MIPS/MHz and1.8V give48pC and86.4pJ
per instruction. These are illustrative assumptions, not measured properties of
AN505 or a selected MCU. Review any restored assumptions before presenting them.
With a common per-instruction factor, energy rank follows instruction rank.

Counts are exclusive guest instruction **dispatches** by emitted ELF function,
including startup and handlers. Calls† is entry-address hits, a call-count proxy.
They are not silicon cycles, retired-instruction guarantees, per-coroutine totals,
CPU occupancy or measured power. Shared adapter/core functions aggregate work
from multiple tasks. The plugin histogram does not supply per-task causal traces.

### Explain the ranking columns

For the presentation, introduce the view with:

> “This view shows where the observed instruction work goes over the whole QEMU
> run. We can distinguish a small operation executed frequently from a larger
> amount of work per entry. These are guest instruction counts, not MCU cycles.”

Dynamic counters accumulate **since QEMU launch**, including startup and interrupt
handlers. They do not reset at each breakpoint or describe only the current call.
Instructions are attributed to the compiler-emitted body containing their PC;
called functions receive their own counts separately.

| Column | What to tell the audience |
| --- | --- |
| **Function** | Compiler-emitted function body. Names that alias the same body share one row. |
| **Dispatches** | Guest instructions dispatched inside that body. This excludes instructions charged to its callees. |
| **Calls†** | Times execution reached the body's entry instruction. A call-count proxy, not exact invocations or calls per second. |
| **Code B** | Bytes occupied by the emitted body. This is code footprint, separate from shared stack or coroutine-frame storage. |
| **Instr/entry** | `Dispatches / Calls†`: average instructions in the body per observed entry, not total work including callees. |
| **Instr/B** | `Dispatches / Code B`: execution activity relative to code footprint. A small hot loop can score highly. |
| **Share %** | The body's dispatches divided by all recorded run dispatches, multiplied by 100. |
| **Cumul %** | Running sum of instruction shares down the current table order. Sort by descending dispatches to show the leading contributors together. |

**Worked example (illustrative, not a captured result):** a body with 12,000
Dispatches, 100 Calls† and 80 Code B has `Instr/entry = 120` and `Instr/B = 150`.
If the whole run has 100,000 dispatches, its Share is 12%. If preceding rows account
for 30%, its Cumul value is 42%.

A short live walkthrough:

1. Sort **Dispatches** descending. Point to the leading bars, then scroll the
   table. The chart shows the top eight plus the currently stopped function;
   the table contains all emitted bodies. Cumul shows how many leading bodies
   account for a chosen fraction of the observed instruction work.
2. Compare **Calls†** with **Instr/entry**. Many entries with little work per
   entry identify frequent small operations; fewer entries with more work per
   entry identify larger processing segments. Different paths and inputs can
   change these ratios, so a high value alone does not establish inefficiency.
3. For Kodama, point out that a coroutine resume body can be entered repeatedly
   during **one task lifetime**. Its entry count is not the number of task
   instances spawned. Use task generation and pool ownership to discuss lifetime.

`▶` marks the current stopped body (last stopped while running); `▸` marks a body
selected through another stack frame. `—` means unavailable, such as an average
with no observed entry; it does not mean zero. Tail entries, jumps and loops back
to the entry address can affect Calls†. Optimized/inlined functions may share a
containing emitted body rather than appear as independent source functions.

Share and Cumul include **unattributed dispatches in their denominator**. Those
instructions remain in the run's unknown bucket, so the listed rows may total
less than 100%. Cumul always follows instruction shares in the current table
order, even when the rows are sorted by code size or another metric.

The energy ranking adds **Energy pJ** and **Charge pC**, derived from the explicit
current/throughput/voltage model. A common per-instruction factor makes its energy
order match instruction order. These are active-core estimates, not measured
power. Average power additionally requires target duration. QEMU dispatches are
not silicon cycles or a guarantee that each instruction retired successfully.

### Confirm that this run's plugin is actually feeding dbg3k

Set `RUN_DIR` to the launcher's printed absolute directory, then in a separate
shell inspect the latest snapshot:

```sh
export RUN_DIR=/absolute/path/printed/by/the/launcher
python - "$RUN_DIR/counts.json" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
print({k:d.get(k) for k in ('schema','metric','elf_sha256','run','seq','total','complete')})
PY
```

Expect schema `dbg3k.qemu-counts.v1`, metric `instruction-dispatch` and a positive
total after execution. Re-run while the target runs to see progress. The plugin
writes cumulative atomic snapshots about every100ms; they can lag a GDB stop.
The launch manifest and dbg3k must use the same ELF hash/profile path. A profile
from another QEMU process must not be mixed into this session.

## 8. Structured observations and saved history

The launch already selects two expressions. To change them:

1. Ctrl+P → **Observation capture**.
2. Put one selector per line in the text area, for example:

```text
g_demo_shared.hfe_result
g_demo_shared.scratchpad.entries[0]
g_demo_shared.cli
```

3. Click **Start / apply**. Close only dismisses; **Stop capture** stops these
   selected observations. This is independent of Kodama API probes.
4. Continue to another breakpoint to record changed values at a new stop.

JSONL stores typed fields, original expressions, errors, truncation, stop/session
and build identity. Full-width integer/pointer encodings preserve precision.
Unavailable or partial reads stay explicit. This is a stop-indexed observation
history, not a continuous application-event log. See [query examples](OBSERVATIONS.md).

To copy displayed information, use the Kodama **Copy** button or focus its canvas
and press Ctrl+C. Other keys: `y` current source line/selected scope node, `Y`
source file, `W` current watches, `H` watch histories, `L` recent console log.
Clipboard delivery depends on terminal OSC52 support; Shift+drag plus the
terminal's copy shortcut is another option.

To hand over a captured run after closing dbg3k:

```sh
cp "$KODAMA_DIR/build/diagram-demo/demo.elf" "$RUN_DIR/demo.elf"
git -C "$DBG3K_DIR" rev-parse HEAD > "$RUN_DIR/dbg3k-commit.txt"
git -C "$KODAMA_DIR" rev-parse HEAD > "$RUN_DIR/kodama-commit.txt"
tar -czf "$RUN_DIR.tar.gz" -C "$RUN_DIR" .
```

Keep the matching source checkout/edits too if the recipient will step source.
The bundle includes local application values and paths; choose which captures to
share. It is not uploaded automatically. Reopen a recorded Kodama journal with:

```sh
"$DBG3K_DIR/.venv/bin/dbg3k" "$RUN_DIR/demo.elf" \
  --kodama-history "$RUN_DIR/history/demo_YYYY-MM-DD.jsonl"
```

Replace the dated filename with the actual file in `history/`. Replay launches
no GDB/QEMU and selects the newest matching capture segment unless pinned with
`--kodama-session SESSION_UUID`. To revisit an earlier segment, use a separately
saved run/journal; restarting a capture selects its new segment by default.
Recorded instruction rankings can also be followed through `--profile-history`
as described in [the resource guide](RESOURCES.md#reliable-energy-updates-and-recorded-profiles).

## 9. Scripted CLI, scratchpad and logging exercises

The QEMU terminal is output. Application input comes from
`experiments/diagram_yaml/rx_script.yaml`, repeating every10 seconds. Existing
traffic includes `CLI:status`, `SP:SET demo 7`, `SP:GET demo`, and
`CLI:scratch get demo`, plus malformed/oversized traffic and recovery.

| Exercise | Inspect with GDB |
| --- | --- |
| CLI forwards and pends for correlated reply | `print g_demo_shared.cli`, `print g_demo_shared.scratch_reply` |
| Scratch storage and limits | `print g_demo_shared.scratchpad` |
| Three-message log batching | `print g_demo_shared.log.head`, `.published`, `.tail`, `.dropped` |
| Simulated transmission and coalescing | `print g_demo_shared.comms_write` |
| Malformed input, overflow and recovery | `print g_demo_shared.comms_read` |
| Per-task work totals/window deltas | `print g_demo_shared.telemetry` |

CLI scratch replies go through `[CLI]`; direct SP replies through `[SP]`.
Scratchpad has8 entries,15-character keys and47-character string values. Updating
an existing key works when full; invalid requests return errors without altering
data. Log buffers6 immutable queued records, publishes after3 and counts drops.
Direct output is latest-value with skipped counters; it is not lossless queuing.

For a quick what-if, stop the run, edit the YAML script and regenerate it:

```sh
cd "$KODAMA_DIR"
python experiments/diagram_yaml/generate_rx_script.py
```

Then rerun the new dbg3k launcher, which rebuilds firmware and creates a fresh
profile/history. For signal bits, rates, priorities or frame settings, edit
`application.yaml` and run `generate_sensitivities.py` before rebuilding.
Changes need a new QEMU process and matching ELF. GDB commands in this guide read
the target; they do not call target methods or inject application commands.

## 10. GDB and keyboard reference

| Command/key | Use |
| --- | --- |
| `tbreak main` | One-time startup stop |
| `tbreak demo_checkpoint` | One-time next one-second checkpoint |
| `break demo_checkpoint` | Repeat checkpoint stop; remember its number |
| `tbreak demo_checkpoint if g_demo_shared.runtime.elapsed_ticks >= 6000` | One-time stop at/after chosen demo time |
| `tbreak kodama_pend` | One-time actual wait call |
| `tbreak kodama_signal_and_pend` | One-time request/reply publish-and-wait call |
| `info breakpoints` | List actual numbers and conditions |
| `disable N` / `enable N` / `delete N` | Manage the actual breakpoint number |
| `bt` / `frame N` / `info locals` | Inspect the stopped C call stack |
| `print g_demo_shared.FIELD` | Inspect named shared state |
| `print g_live` / `print g_peak` / `print g_failed_alloc` | Allocator gauges |
| `print/x 'kodama.c'::levels` | Observed persistent level bits |
| `print 'kodama.c'::tasks` | Raw scheduler slots; include generation when reasoning about identity |
| `info files` / `info sources` / `info line main` | Check ELF and source provenance |
| `s` / `n` / `o` | Into / next source / finish observed function |
| `i` / `I` | One instruction / step over instruction; use sparingly for teaching |
| Space | Repeat last stepping action |
| `c` | Continue to a breakpoint |
| `j/k`, `b`, `r` in Source | Browse line, toggle breakpoint, run to cursor |
| F2 / Esc | Enter GDB input / return to Source |
| Ctrl+P | Palette: views, theme, Kodama setup, observation capture, energy model |
| `q` outside text input | Quit dbg3k |

Enter each GDB table command separately; replace FIELD and N with actual values.
The log table's `.published` shorthand means `print g_demo_shared.log.published`,
and similarly for its other fields. Avoid blanket `delete` during a lesson;
identify your own breakpoints in `info breakpoints`.

## 11. Recovery and repeatability

| Symptom | Action |
| --- | --- |
| `dbg3k: command not found` | Paste the printed absolute executable command, or activate `$DBG3K_DIR/.venv/bin/activate` |
| Wrong directory / demo script missing | Use the demo worktree as `KODAMA_DIR`; inspect `git worktree list` |
| Python cannot import yaml | Activate the same venv and install Kodama's requirements from section1 |
| Port3333 already in use | Stop the older run in its own terminal, or launch with `--port 3334` and use the newly printed command |
| Plugin header/API error | Obtain the matching header and set QEMU_INCLUDE; rebuild. The launcher never silently falls back without profiling |
| Rankings unavailable | Verify `-plugin`, the same ELF/profile in both commands, and counts.json total after execution |
| Energy numbers absent | Set/review all three model assumptions; the plugin alone cannot supply them |
| Only a few timeline columns | Overview mode has probes off. Use Setup → switch on → **Start / restart** |
| New capture looks empty | Start/restart begins a segment; continue to collect it |
| History seems frozen | Click Follow live or focus canvas and press End |
| API CAPTURE GAP | Per-run budget was reached. Next visible stop re-arms; use shorter intervals for detailed tracing |
| Target slow | Disable API probes for overview; `--no-profile` also removes counting overhead on a fresh QEMU run |
| Source unavailable / cannot find function bounds | Verify matching ELF with `info files`, `info line main`; rebuild locally and restart QEMU/debugger with the new paired command |
| Unexpected early exit | Use this continuous diagram-demo ELF, not the older finite C-main example |
| Breaks every second when trying to reach6s | Disable the persistent checkpoint breakpoint by its actual number, then use the conditional temporary breakpoint |
| Keys scroll Source instead of history | Click/focus the Kodama canvas first |
| `DEMO ERROR` in Terminal A | Inspect `g_demo_shared.runtime.failed` and task error flags; preserve the run before changing it |

If a copied ELF embeds another machine's source prefix, while halted use GDB's
source mapping with the actual paths:

```gdb
set substitute-path /old/build/path/kodama /your/current/path/kodama
directory /your/current/path/kodama/experiments/diagram_yaml
```

For a clean repeat: quit dbg3k with q, stop the launcher's QEMU with Ctrl+C in
Terminal A, rerun the launcher and paste its **new** Terminal B command. Keeping
an old counts path after restarting QEMU mixes evidence from different runs.

## Suggested one-hour presentation

| Minutes | Demonstration |
| --- | --- |
| 0–10 | Two terminals, source at main, Init barrier and pool ownership |
| 10–25 | Pipeline prime input, busy rejection, HFE result and frame lifetime |
| 25–35 | Short API trace: pends, ready/running transitions, signal request/publication markers |
| 35–45 | Scripted CLI/scratchpad request/reply, logging batches and error counters |
| 45–55 | Plugin-backed code/instruction ranking, stack estimates, explicit energy assumptions |
| 55–60 | Change script, save run, replay, questions |

Local qualification is Linux/GNU Arm GCC16.2/GDB17.2/QEMU11.1 with AN505 M33
executing an M23 instruction target. The ordinary app tests include a virtual
native hour; this does not establish a wall-clock-hour QEMU soak, physical M23
behavior, measured power, silicon cycles, complete scheduler trace or a shared
stack bound. Check `handoff/kodama-demo-handoff-validation.json` for this launch
and guide's actual validation. The older top-level Kodama `make qemu-test` has a
retained GCC16 memset link failure; the isolated diagram demo supplies newlib.

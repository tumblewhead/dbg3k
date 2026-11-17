# dbg3k: a scope-first Cortex-M debugger

A keyboard-first terminal source debugger for embedded C/C++, with scoped watches, value-change highlighting, sparklines, and eventual per-function memory/instruction/energy profiling. Born from a working QEMU `mps2-an505` bare-metal experiment. The conceptual name is **qscope**; the canonical repository name is **dbg3k**.

**Status:** Alpha. Textual/GDB source and watches, retained returns, sampled stack
estimates, ELF function sizes, and optional QEMU instruction dispatch profiling.
Local watches are user-confirmed; the resource collector has real AN505 emulator
tests. Stack bounds, silicon cycles and measured power remain unavailable.

**Structured observation capture:** use Ctrl+P → Observation capture to select
expressions and start/stop typed snapshots in the existing JSONL trace. Or pass
repeated `--observe "'kodama.c'::tasks"` flags. Scalars, fields, array elements,
pointer addresses, read failures and capture limits retain stop/build provenance.
See [the schema, queries and real Kodama/QEMU demonstration](docs/OBSERVATIONS.md).

**Graphical Kodama view:** Kodama ELFs automatically open a full-width panel
with task/signal timelines, decoded waits, priorities, scheduler decision boxes
and coroutine-pool ownership. Click cells to inspect history; expand for a
lesson view. Configure a signal header and optional API probes in **Kodama setup**.
The **History** scrollbar pans task and signal lanes together while names stay
fixed. Drag or use Page Up/Down; Home selects the oldest retained sample and End
resumes following live activity. The visible/retained range is shown above it.
Saved sessions can be viewed with `--kodama-history FILE` without starting GDB.
See [the graphical guide and screenshot](docs/KODAMA_VIEW.md).

For a repeating lesson that stays alive under the debugger, see the
[Kodama live superloop](examples/kodama-live/README.md). Its application-owned
SysTick requests a new run every emulated second; main never returns.

**Diagram wiring:** the [Miro-to-YAML importer](docs/KODAMA_WIRING.md) accepts
explicit AND/OR sensitivities and checks producer/consumer dependencies before
writing a reviewed wiring specification. It does not infer task behavior.

## Getting started on Arch Linux

Install Python 3.11+, make, arm-none-eabi-gcc, qemu-system-arm, GDB with ARM support.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e .
make -C examples/an505
```

Terminal 1:

```sh
make -C examples/an505 debug
```

Terminal 2:

```sh
dbg3k examples/an505/firmware.elf --gdb gdb --remote localhost:1234
```

Change `--gdb` if only `gdb-multiarch` or `arm-none-eabi-gdb` supports the ARM target.

Key bindings: `s` source step into, `n` next, `i` instruction, `I` next instruction, `o` finish, `c` continue, `Space` repeat last step, `j/k` source cursor, `b` breakpoint, `r` run to cursor, `q` quit.

Run standalone tests:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

## Components

**Stack, instruction and energy profiling:** three selectable panes now show
GDB stack snapshots/estimates, ELF function body sizes, QEMU plugin instruction
dispatch counts, and user-configured energy estimates. See
[setup, launch commands and measurement limits](docs/RESOURCES.md).

Energy rankings now follow recorded JSONL profile/model events as they grow,
restore prior explicit assumptions for the same ELF, and retain validated data
through transient read failures. The energy pane's **Model…** button edits
assumptions directly. Use `--profile-history FILE [--profile-session UUID]` to
follow a recorded profile instead of the live plugin file; see the resource guide.

- `src/dbg3k/mi.py`: GDB/MI record parser, no CLI scraping
- `src/dbg3k/backend.py`: subprocess, tokenized MI transport and event queue
- `src/dbg3k/model.py`: frame-aware locals and globals, bounded histories, numeric sparklines
- `src/dbg3k/globals.py`: GDB/MI global and file-static symbol discovery with disambiguation
- `src/dbg3k/app.py`: Textual source pane, scope tree, watch display, keyboard stepping
- `src/dbg3k/views.py`: palette view choices and checkbox dialog
- `src/dbg3k/resources.py`: ELF, stack, instruction and energy evidence model
- `plugins/counts.c`: actual QEMU per-PC instruction dispatch collector
- `examples/an505/`: sample with the Secure RAM mapping verified in the precursor QEMU experiment
- `docs/DESIGN.md`: product and measurement contracts
- `docs/CONVERSATION_NOTES.md`: preserved design discussion
- `handoff/CONTINUE.json`: machine-readable next checkpoint

**No fabricated measurements.** Instruction counts are not cycles, debugger-stop histories are not time series, and stack estimates are not guarantees.

## Choose your views

Press **Ctrl+P**, search **Views**, and press Enter. Click checkboxes or use
Up/Down and Space to show or hide Source, Stack tree and observed returns,
Immediate scope watch, Globals, GDB console, Stack frames and stack watch,
Code and instruction counts, and Energy estimate. Esc or Done closes the dialog.
Additional views provide a **Graphical stack map and contents**, **Run statistics
and Pareto ranking**, and **Graphical energy ranking**. These add graphical
projections while retaining the original resource panes. Ranking selectors and
clickable headings sort instructions, Calls† (entry hits), code size, density,
and instructions per entry; energy views also sort estimated charge/energy.
Individual **View:** commands in the palette also show a checkmark when enabled.
Highlight a View command and press **Left or Right** to toggle it while keeping
the palette, search text and selection open. Left/Right also toggle checkboxes
in the Views dialog. For other palette commands the arrows edit the search text.
Choices apply for the current session; all views start enabled on launch.

The **immediate scope watch** shows only the executing frame (frame 0), including
debug-visible arguments and locals. Browsing another frame's source leaves this
watch on the executing frame. The **stack tree** retains locals for all queried
active frames and observed return histories. **Globals** has its own pane.
Hidden views retain histories and continue receiving debugger-stop updates.
Remaining panes expand into available space; on short terminals the right column
scrolls. F2 reveals the console if hidden and focuses its command input.

## Development journal and continuation

Read [`CONTINUE.md`](CONTINUE.md) for project history, live user feedback, open defects, and exact next steps. [`handoff/CONTINUE.json`](handoff/CONTINUE.json) carries the machine-readable checkpoint.

## Copying text and running GDB commands

Textual supports mouse drag-selection with Ctrl+C on many widgets. On some terminals Shift+drag lets the terminal handle the selection directly.

In the debugger's source/scope views, `y` copies the current source line (or a selected scope tree node), `Y` copies the current source file, `W` copies all visible watches as tab-separated rows, and `L` copies the last 500 console lines. Copy uses Textual's OSC 52 clipboard integration; terminal/remote clipboard support varies. If copy does not reach the desktop clipboard, use Shift+drag and the terminal's copy shortcut.

Press `F2` (or `:`, where supported) to focus the GDB console-command input. Paste a GDB CLI command such as `info registers` and press Enter; Esc returns keyboard focus to debugger controls. This is an interactive CLI command line, not an automatic GDB/MI scripting mode.

The watch backend first discovers a GDB thread via `-thread-info` or stop events, then issues frame-local requests with **both** `--thread ID` and `--frame N`. Locals are only available where GDB reports their scope.

## Global and file-static watches (new, pending Arch verification)

GDB's `-stack-list-variables` reports frame locals only. dbg3k now uses
`-symbol-info-variables` once per connection, then evaluates the discovered
data symbols at each stopped PC using `-data-evaluate-expression`.
The Globals pane is independent of the stack tree and immediate scope watch,
with shared change detection and sparklines.

- External variable `ticks` is labeled `global.ticks`.
- File-static variable `total` in `main.c` is labeled `main.c::total`, and
  evaluated with GDB's qualified expression `'path/main.c'::total`.
- At most 64 debug globals are displayed initially to bound GDB traffic; there
  is not yet a search/pin control for selecting more. Optimized-out, unavailable,
  stripped, or unsupported symbols may not be readable.
- Global history is sampled at debugger stops, not continuously in real time.

Try the bundled AN505 example: `main.c::total` should appear even while
stepping through `foo()` and `bar()`, and its value/history should change.

## Theme, call-tree and watch-history experience (M0.1 UI refinement)

**Theme:** The command palette's themes now drive the entire application
via Textual CSS theme variables, including the source pane, call tree,
watch rows, GDB input, headers, borders, and console. The source view's
Rich text markup uses the active theme as well. Open Textual's palette
(`Ctrl+P`) and try `textual-light`, `nord`, or `dracula`.

**Call tree:** GDB/MI `-stack-list-arguments` supplies argument values
for active frames. For example, the scope tree can display `foo(2)`
rather than `foo()` when symbols are available. With Python-enabled GDB,
dbg3k arms an internal return probe for the debug-visible executing function at
each stop. After stepping into `bar` with `s`, keep using `s`/`n`, or continue:
when that invocation returns, GDB supplies its actual result to the tree without
an extra visible stop. `o` / finish remains supported and is counted only once.
Functions called entirely between debugger stops are not automatically observed.
GDB builds without Python retain the `o` / finish fallback and log a diagnostic.
Unavailable or void return values stay unreported; no register-based guesses.

**Watch histories:** Each watch has its own line and hoverable history
cell. The first two numeric samples appear as a short number list; once
three numeric observations exist, they become a 24-column sparkline.
Hover over that history cell for its **last ten debugger-stop values**.
Click a watch row to copy all of that watch's retained history (TSV);
press `H` to copy the retained histories of **all** watches, including
locals that have gone out of scope. `W` still copies the current watch
values. Host-side history retention is bounded to **4096 observations
per watch** rather than the previous 128. The oldest values are evicted
past that capacity and are not recoverable. The count is samples at
GDB stops, not time-series data collected while firmware runs.

**Verification:** Automated Python/model, GDB/MI parsing, Textual
headless theme tests, and headless pane tests run in GitHub Actions.
A real GDB/QEMU AN505 regression now checks ordinary stepping, continuation,
finish deduplication and retained return rows in the mounted Textual app:

~~~sh
DBG3K_QEMU_TEST=1 PYTHONPATH=src python -m unittest discover -s tests -p test_qemu_returns.py -v
~~~

Use `DBG3K_GDB=gdb-multiarch` if needed. This test also requires
`arm-none-eabi-gcc` and `qemu-system-arm`. Actual terminal hover/clipboard behavior
and the latest changes against Kodama remain to be reviewed by the user.

## Persistent caller-return histories and JSONL trace

The scope tree keeps a **single, persistent return row per thread/caller/callee pair**
in its **observed returns** section, including after the caller leaves the stack.
The latest observed return also appears under an active caller. For example,
after finishing bar from inside foo, the active stack can show:

~~~text
foo(2)
  ↳ bar(4) ⟵ 12 · 5×
~~~

Subsequent observed returns from bar into foo replace the displayed value, increment the count, and remain available as history. Hover the return row for the last ten observed returns; **click/select the row to copy all of its current-session returns as TSV**, streaming from the JSONL file rather than the limited in-memory UI cache.

To observe a return value, **step into bar with s, then keep stepping normally**.
The GDB Python return observer supplies the result when bar returns. `o` is an
alternative. A `next` that skips an entire previously unseen call does not reveal
that callee's result. Missing return values are shown as unreported, never zero.

dbg3k also starts an **append-only JSONL trace** after connecting to GDB. Default path (relative to the directory where you launched dbg3k):

**dbg3k-history/targetname_YYYY-MM-DD.jsonl**

Here targetname is the ELF basename without extension, so debugging Kodama's demo.elf on 2026-11-15 creates **dbg3k-history/demo_2026-11-15.jsonl**. Multiple launches on the same day append into the same file under separate session IDs. All records are flushed immediately, including stop events, frames, arguments, local and global observations, GDB-reported returns and errors.

Choose a different directory:

~~~sh
dbg3k ~/proj/kodama/build/c-main-arm/demo.elf --history-dir ~/proj/kodama/debug-traces
~~~

The GDB output pane prints the chosen file location. See [docs/TRACE_JSONL.md](docs/TRACE_JSONL.md) for schema, provenance, retention, and limitations. This captures debugger-observed stops and values, **not every instruction or unobserved call**.

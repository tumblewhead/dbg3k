# dbg3k: a scope-first Cortex-M debugger

A keyboard-first terminal source debugger for embedded C/C++, with scoped watches, value-change highlighting, sparklines, and eventual per-function memory/instruction/energy profiling. Born from a working QEMU `mps2-an505` bare-metal experiment. The conceptual name is **qscope**; the canonical repository name is **dbg3k**.

**Status:** M0.1 alpha. Textual, GDB/MI, local and global watches, unit tests, and AN505 example are on this branch. The user confirmed local watches work on Arch; global watches still need a live QEMU/GDB retest. No stack-byte or instruction profiling is implemented yet.

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

- `src/dbg3k/mi.py`: GDB/MI record parser, no CLI scraping
- `src/dbg3k/backend.py`: subprocess, tokenized MI transport and event queue
- `src/dbg3k/model.py`: frame-aware locals and globals, bounded histories, numeric sparklines
- `src/dbg3k/globals.py`: GDB/MI global and file-static symbol discovery with disambiguation
- `src/dbg3k/app.py`: Textual source pane, scope tree, watch display, keyboard stepping
- `examples/an505/`: sample with the Secure RAM mapping verified in the precursor QEMU experiment
- `docs/DESIGN.md`: product and measurement contracts
- `docs/CONVERSATION_NOTES.md`: preserved design discussion
- `handoff/CONTINUE.json`: machine-readable next checkpoint

**No fabricated measurements.** Instruction counts are not cycles, debugger-stop histories are not time series, and stack estimates are not guarantees.

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
The scope tree has a separate `globals` group and the watch table includes
both local and global values, with shared change detection and sparklines.

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
rather than `foo()` when symbols are available. A GDB
`function-finished` stop (typically the `o` key / `finish`) adds
an observed return under the caller, such as `↳ foo(2) ⟵ 4`.
If GDB does not report the result, the UI says so. Ordinary stepping
over a call does **not** reveal a return value automatically: those
values require an observable GDB finish event, not inference.

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
A real GDB/QEMU/Arch smoke test is still needed to confirm that
argument values and finish notifications look right for AN505.

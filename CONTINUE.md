# dbg3k: development history and continuation

**Repository:** https://github.com/tumblewhead/dbg3k
**Working branch:** `feature/selectable-debugger-views` (based on `feature/m0-1-mi-textual-scope-001`)
**Review:** https://github.com/tumblewhead/dbg3k/pull/2 (draft, based on the M0.1 branch; original work in PR #1)
**Current stage:** Palette Left/Right toggles and automatic return capture during ordinary stepping; 43 local checks pass including real GDB/QEMU AN505.

> **Handoff protocol:** Read this file first, followed by `AGENTS.md`, `docs/DESIGN.md`, `docs/CONVERSATION_NOTES.md`, `README.md`, and `handoff/CONTINUE.json`. The GitHub repo is canonical. Update this human-readable journal and the JSON checkpoint after meaningful work, and leave the next exact action for a new agent.

## Chronological development record

### 2026-11-15: normal stepping returns and palette arrow toggles

User confirmed the missing return values occur while using ordinary `s/n`.
The local existing firmware JSONL corroborated this: 84 source-step commands,
9 instruction steps, 94 end-stepping-range stops, zero function-finished stops
and zero return records, despite bar frames being observed. The previous fixes
retained rows correctly but only populated them after `o`/finish.

Added a GDB Python observer using internal FinishBreakpoints for normal
debug-visible executing frames encountered at stops. GDB supplies actual return
values; structured JSON passes over MI console records to the existing return
ledger/tree/JSONL. Probes auto-resume without visible stops; normal `s/n` and
continue now capture returns from observed functions. `o` and probe evidence
are deduplicated. Missing Python logs a diagnostic and retains MI finish fallback.
Unseen calls entirely between stops, unsupported frames and unavailable/void
values remain explicitly unobserved/unreported. Probes are bounded to 128 and
out-of-scope unwinds do not invent normal returns. No timing or task identity
claims were added. GDB subprocess shutdown now closes its pipes (real-test
ResourceWarnings exposed the omission).

The actual command palette now accepts Left/Right on highlighted View entries
without closing, losing search text or moving selection. Checkmarks update in
place. Arrows continue editing search text for non-view commands. The checkbox
dialog also supports both arrows.

Validation: 43 checks pass including the opt-in mounted Textual + real GDB 17.2,
QEMU 11.1 AN505 and GNU Arm GCC 16.2 test. Actual bar returns 6 via `s`, 9 via
continue, and 12 via `n`; foo returns 8 via `o` exactly once. Historical row
identity survives caller exit and subsequent returns; JSONL has real probe
provenance. Dedicated CI job added for the real GDB/QEMU test. Compileall and
diff whitespace checks pass. See handoff/returns-validation.json for reproduction
and earlier sandbox socket failure. Current Kodama/terminal behavior remains for
user retest. Updates stay on feature/selectable-debugger-views and PR #2.

### 2026-11-15: selectable panes and immediate scope watches

Added Ctrl+P > Views checkbox dialog (Space/click, Esc/Done), plus individual
palette View commands with checked/unchecked labels. Source, stack tree with
returns, immediate scope watch, globals and console can be hidden independently.
Choices last for the current session. Hidden panes retain observation histories;
remaining panes fill space. The right column scrolls on short terminals. F2
reveals a hidden console before focusing input.

Globals now have their own pane and are absent from the stack tree. Immediate
watches show executing frame 0 locals/arguments; browsing source from another
frame does not redirect them. The tree retains locals for all queried frames.
The prior durable observed-returns branch already exists in this checkout;
preserved it and added latest-return summaries beneath active callers. Historical
node identity survives caller exit, empty stacks and hide/show. Collapsing the
historical section is now respected across redraws. GDB finish observations only;
ordinary next still cannot supply unobserved callee return values.

Validation: 38 unit/headless Textual tests pass with Python 3.14/Textual 7.5.0;
compileall and diff whitespace checks pass. New tests drive the real palette,
checkbox keyboard controls, F2, layout expansion, scope isolation and retained
returns. One initial test failed because Textual normalizes width to `100w`;
corrected it to assert actual rendered width. See handoff/views-validation.json.
Live Kodama/QEMU retest and terminal clipboard review remain pending.

Next: review the view-selection PR, run dbg3k on the new branch, use Ctrl+P >
Views, and finish a callee with `o`; confirm its return remains in observed
returns after its caller exits. No merge into main performed.

### 2026-11-15: QEMU learning experiment

The Cortex-M33 `mps2-an505` bare-metal example initially failed with a HardFault lockup. GDB showed the Secure vector table and the reset handler were correctly loaded at `0x10000000`, but the original stack location around `0x30400000` was invalid. Secure SRAM at **`0x38000000`** with a 64-KiB linker allocation fixed the boot; the user confirmed it works. Stepping through `Reset_Handler` and exception handlers led to the idea of a source-aware TUI.

### 2026-11-15: dbg3k vision

CGDB was close to the desired interaction, but the user wanted more: always-visible `function.local` watches, numeric history sparklines, value-change highlighting, independent source navigation, and modern Rich/Textual styling with optional Nerd Fonts.

The **scope tree** is the central structure. Scope identities distinguish same-name locals in different functions, lexical blocks, invocations, and eventually tasks. A scope owns local variables, frame stack usage, dynamic instruction work, and a rough electrical estimate. The source browser must NOT control execution.

Keyboard control should be low-friction: `s` step into, `n` next, `i/I` instructions, `o` out, `c` continue and Space repeat. Later: count prefixes, auto-stepping, run to cursor, split assembly, watches/plots, source function navigator.

Profiling plans: attribute own/inclusive stack frame contribution, cumulative stack depth and high-water marks; static function `.text` bytes beside actually executed QEMU guest-instruction counts; estimate energy only from clearly labeled silicon assumptions (µA/MHz, MIPS/MHz, voltage). Instruction share is **not** CPU-time utilization. See `docs/DESIGN.md`.

### 2026-11-15: M0.1 implemented, PR #1

Feature branch `feature/m0-1-mi-textual-scope-001` created. Python GDB/MI parser, transport, Textual TUI, source view, active call tree, bounded stop-sampled watches/sparklines, keyboard stepping, and AN505 demo were committed. Initial model/parser tests (10) and `compileall` passed in the builder, but no QEMU or Textual end-to-end execution was available there.

### 2026-11-15: first real user feedback

**User confirmed:** dbg3k TUI launches and looks great; clicking a function in the scope tree successfully loads its source.

**User observed bugs:**
1. Source pane only displays roughly lines 20–33, without scrolling. The initial implementation rendered only a centered excerpt into a non-scrollable Static.
2. Watches never appear. The cause is **not yet confirmed** by GDB/MI output. Do not claim the culprit has been proven.

**Clarification:** The user wants to naturally step through startup until `main()`, not an automatic jump to main. Keep source navigation separate from execution.

### 2026-11-15: feedback patch (pending user retest)

- Render the **whole file** in a Textual `VerticalScroll` container; preserve execution arrow `▶` and independent navigation cursor `▸`. Mouse wheel, `j/k`, arrow keys, PageUp/Down, Home/End scroll/browse without changing CPU PC.
- Fetch locals using `-stack-list-variables --frame N --all-values`. Differentiate *loading*, *no visible locals*, and *GDB query errors* in the watch pane/console. This is a **diagnostic and UX improvement**, NOT verified resolution of missing watches.
- Preserve selecting source via the active call tree.
- Pure-Python tests/compileall pass locally; Textual/GDB/QEMU runtime was unavailable in the builder and must be retested on SaltyPond.

### 2026-11-15: GDB thread ID and copy/paste bugfix (pending Arch retest)

**Live user error, root cause confirmed:** Watches displayed `Cannot specify --frame without --thread`. GDB/MI requires a thread context for any command using `--frame`. Earlier request `-stack-list-variables --frame N --all-values` was rejected; this is not evidence that the function has no locals. The patch now discovers the selected/stopped GDB thread using `-thread-info` and `*stopped.thread-id`, and requests `-stack-list-variables --thread T --frame N --all-values`. A small pure helper module validates these arguments; 15 unit tests (including 5 new thread/command tests) passed locally. Actual GDB+QEMU retest is still required.

**Live user complaint:** Cannot copy/paste any text from TUI. Textual supports drag-selection + Ctrl+C in many widgets, though terminal mouse interception differs. The patch adds `y` for selected source line/scope node, `Y` for source file, `W` for watches, `L` for GDB log (bounded to 500 lines); all use Textual OSC52 clipboard copy. Adds an editable GDB command input, focused by `F2` (or `:` if supported), accepting pasted GDB commands and executing via `-interpreter-exec console`. Esc leaves the input. Requires user test for keyboard focus and terminal clipboard support. Fallback is Shift+drag with the terminal's selection/copy.

**Test on SaltyPond:** restart QEMU in debug mode; pull branch, reinstall editable package if necessary, start dbg3k, step naturally from Reset_Handler to main and into foo/bar. Verify watches update when in scope and keyboard copy actions. Use `F2`, enter `info registers`, confirm output appears and `L` copies it. If Clipboard OSC52 fails, report terminal emulator and whether `wl-paste` gets data.


### 2026-11-15: local watches confirmed; global watches added (CI-passed, Arch retest pending)

**User confirmed:** the thread-qualified GDB/MI fix worked and local variables now populate the watches pane. **Remaining nit:** global variables, including the AN505 demo's `static volatile uint32_t total`, did not appear. This was a scope-coverage omission, not a regression in the frame-local code.

**Implementation:** `src/dbg3k/globals.py` discovers DWARF global/file-static data via `-symbol-info-variables --max-results 65`. Externally linked symbols are labeled `global.name`; file-static symbols are labeled `file.c::name` and evaluated via quoted GDB file context `'file.c'::name`. The Textual scope tree gains a sibling `globals` group and the watch table includes both kinds of watches. Persistent globals reuse the same 128-stop numeric history and change glyphs; replies from earlier stops are discarded by token/stop tracking. A limit of 64 symbols bounds the initial remote-query workload.

**Validation:** GitHub Actions unit tests, TUI import check and compileall passed at commit `bd9aeac`; further event-flow tests and docs are being added. Actual global value retrieval on Arch/QEMU remains unverified. Do not claim globals work on the target without a run receipt.

**Known limitations:** first 64 enumerated debug globals, no pin/search or pagination; no continuously sampled watch values while running; optimized-out/unreadable symbols may show `<unavailable>`; GDB expression qualification on full source paths and nontrivial C++ globals needs real-target checks. Static source symbols absent from DWARF cannot be discovered.


### 2026-11-15: whole-app themes, call signatures/returns, and watch trace UX

**User request:** The palette changed theme but almost all application panels stayed blue; function nodes should display actual argument values such as `foo(2)`, and the caller should show a return arrow `↳ foo(2) ⟵ 4`; histories should start as raw numbers, transform into a sparkline from three numeric samples onward, provide ten recent values on hover, and make the complete retained history copyable.

**Implementation:** `src/dbg3k/app.py` is now theme-token-based for the entire Textual layout (background/surface/panel/foreground/accent/borders/tooltip). The Rich source pane derives colors from `current_theme` and redraws if the selected theme changes. GDB `-stack-list-arguments --thread T --all-values 0 N` populates argument tuples on active `Frame` objects; call-tree labels are formatted by `src/dbg3k/calltree.py`. On a genuine `*stopped,reason="function-finished"` event, the caller's node gets the returned function and GDB-reported value. This return marker is stop-scoped and MUST NOT be inferred from ordinary `next` / unknown return values.

**Watch UX:** `src/dbg3k/watch_ui.py` displays independent theme-aware `WatchRow` widgets. One or two numeric readings show `[1]` / `[1, 2]`; at three readings, display a 24-character sparkline. Hover the history cell for ten most recent (stop-number, raw value) observations. Click a watch row to copy that watch's complete retained history; `H` exports TSV for all watches including expired stack scopes; `W` remains current snapshot copy. Host-side history is now 4096 samples per watch (capped, not unbounded). Local and global watchers share this infrastructure.

**Tests:** `tests/test_ux.py` checks argument parsing, return provenance, missing-return behavior, number-to-sparkline threshold, tooltip content, including expired watch data and an actual Textual dark/light theme switch. `tests/test_visual_smoke.py` mounts a real row and caller tree in a headless Textual session. GitHub CI green at `503adc544691` with these tests (prior to the README update); verify later commits too. The implementation has not yet been exercised on the user's Arch/QEMU system.

**Next Arch smoke test:** Pull feature branch, verify Ctrl+P changes source/call/watches/footer/console colors; step into `foo` and `bar` to see `foo(2)`-style argument signatures; press `o` from `foo()`/ `bar()` and observe the return marker under the caller frame; step three times in a function and hover the watch-history cell; click the row and press `H`, then inspect pasted TSV. Also retest `main.c::total` global, local watches, source scrolling and clipboard behavior.

**Known bounds:** GDB must have meaningful debug arguments; optimized-out parameters show `?` or GDB unavailable values. Returns are only shown when GDB reports `function-finished`, not for arbitrary called functions. Clipboard depends on the terminal OSC52 integration. 4096 observations per symbol is a host UI cap, not an embedded RAM budget; earlier values are evicted.

### 2026-11-15: Arch crash report: Rich MissingStyle on source PC highlight

**User-provided traceback:** Opening dbg3k against `~/proj/kodama/build/c-main-arm/demo.elf` halted in `Reset_Handler` at `0x380000dc`. GDB returned a valid stack frame for `/home/easy/proj/kodama/examples/c-main/arm/startup.c:22`. During `_show_source()`, the highlighted execution line was styled using `f'bold {theme.background} on {theme.success}'`, but the built-in `textual-dark` theme reports `theme.background=None`. Rich therefore raised `MissingStyle: Failed to get style 'bold None on #4EBF71'`. This is a theme-rendering bug, not an ARM/GDB or Kodama startup failure.

**Fix:** Use only a defined highlight color (`theme.success` or a defensive fallback), and compute a WCAG-luminance-based contrasting black/white foreground for the Rich execution-line span. Do not interpolate optional theme color fields into Rich styles. The regression test constructs an actual 28-line `startup.c` in a temporary directory, feeds a `frames` MI result at line 22 through the `DebuggerApp._handle()` path, and verifies dark and light themes render without crashing. The earlier headless theme test missed this because no source frame had been loaded.

**Validation:** GitHub CI must be green at the latest commit (check post-documentation). A live retest against the user's Kodama QEMU session remains to be done. Keep the frame/scope/watch features unchanged in this hotfix.


### 2026-11-15: persistent bar → foo returns and append-only simulation evidence

**User request:** The previous GDB function-finished return annotation vanished after a stop. Keep one row under the caller (e.g., foo) showing the latest callee (e.g., bar) return value as the function is invoked repeatedly; hover for a short return history; click to copy the entire return history; record the simulation's debugger-observable history to a targetname_date.jsonl file.

**Implementation:** Added src/dbg3k/trace.py (TraceWriter), calltree.py ReturnLedger/ReturnSeries/ReturnKey, scope_ui.py ScopeTree hover handling, GDB/MI event wiring in app.py, and --history-dir CLI support. A real GDB *stopped,reason=function-finished* event is recorded as a return record with its stop/thread/caller/callee signature/value and provenance. Ledger aggregation is by thread + caller function + callee function, one visible return row per pair under the active caller. Every newly reported return overwrites the row value and increments its observed count. Hover shows the last ten events and their stop indices; clicking the row copies *every* matching observed return in the **current session** from the JSONL disk file as TSV. The per-row memory cache is only ten events, independent of the log's unbounded append history.

**Evidence store:** Default working-directory-relative dbg3k-history/<ELF-stem>_<local-YYYY-MM-DD>.jsonl, e.g. dbg3k-history/demo_2026-11-15.jsonl, overridden by --history-dir. File is append-only across same-day sessions, each session has an ID, event sequence and timestamp. Writes are flushed after every record. Events cover session start/end, commands, debugger stops, frame stacks, argument batches, locals, global variable readings, function return observations, and GDB errors. A newline separator is inserted when reopening after an interrupted partial final record. See docs/TRACE_JSONL.md for versioned schema and provenance.

**Behavior contract:** Only GDB-reported returns are observed. Normal 'next' / stepping over bar does **not** expose its return value. The reproducible way to get a row is to step into bar with 's', then finish with 'o' to emit 'function-finished', returning to foo. Calls entirely between stops, calls run past by continue, and returns GDB does not report are **not reconstructed**. The ledger currently groups by function name and thread, not exact invocation/call site; recursion or multiple same-name call sites may aggregate, which is explicitly a pending refinement.

**Validation:** Added tests/test_returns_trace.py for replacement of latest values, hover ten, append session isolation and full-session TSV reads; tests/test_visual_smoke.py replays two function-finished MI events from bar into foo, checking persistent tree, hover and disk-based copy. CI is passing after fixes to pre-existing one-stop visual expectations. Live Kodama AN505/QEMU GDB UI still needs user verification.

**Next actions:** Pull latest feature branch on Arch; debug Kodama; enter bar from foo with 's' and finish with 'o' twice, observing one return line under foo with count 2. Hover shows both returns; clicking copies full TSV. Check JSONL path printed in GDB pane, and inspect the file. Then progress to per-invocation/call-site IDs and automatic return interception (requiring actual trace instrumentation), plus previously planned stack/.text/energy profiling.

### 2026-11-15: live user feedback: return line flashes then disappears

**Observed:** On the user's Arch/QEMU session the GDB-reported bar return briefly appeared then was overwritten. Root cause from code inspection: `_show_scope` used `tree.root.remove_children()` for every frame/locals/args/global response and reinserted a return node only under an **active caller frame**. When execution exited foo or the set of active frames changed, the return ledger still contained the event but the UI had no node for it. The whole-tree clear also destroyed hover/selection identity.

**Fix:** `app.py` now establishes three stable root branches: `↩ observed returns` (first and always visible), `▶ active call stack`, `◆ globals`. Return groups are stable per (thread, caller) and return leaves per (thread, caller, callee); new observations call `set_label` to update the *same leaf* and retain tooltip/click identity. Only the active stack and global-variable branches are rebuilt on asynchronous MI results; return nodes are never cleared by frame exit. This meets the user's request that bar's latest return into foo remain visible through later iterations while the tooltip and JSONL hold the history.

**Regression test:** `test_return_line_survives_caller_exit_and_repeated_async_redraw` creates foo+main frames, records bar→foo, transitions to main-only, redraws five times, then observes a new bar return. It asserts exact return-node object identity, same single row, new value/count, tooltip and copy data after caller exit. The existing visual smoke test was updated to find return leaves in historical caller groups. CI passed on `2f4a3a6`; live user retest still needed.

**Next:** Pull feature branch, show foo's bar return, leave foo to main, then step more: verify return row remains in `↩ observed returns > foo() [thread 1]` and updates without blinking, with hover/click and JSONL untouched.

## Resuming on the user's Arch Linux workstation

```sh
git fetch origin
git switch feature/m0-1-mi-textual-scope-001
git pull --ff-only
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
make -C examples/an505 clean all
```

Terminal 1: `make -C examples/an505 debug`

Terminal 2: `dbg3k examples/an505/firmware.elf`

## Immediate smoke test

- [ ] Halt at `Reset_Handler`; source shown, CPU stays stopped.
- [ ] Mouse wheel and PageUp/Down can reach beginning/end of file and do **not** advance PC.
- [ ] Click function in call tree to view source without running firmware.
- [ ] Step through startup loops and into `main()`, then `foo()` and `bar()` using `n/s/Space`; no automatic skip.
- [x] User confirmed that thread-qualified local watches now work.
- [ ] Confirm `main.c::total` global in the new `globals` group from startup through `main`, `foo`, and `bar`, with value-change glyph and history.
- [ ] If not, capture watch-pane error and GDB MI response to `-thread-info` and `-stack-list-variables --thread T --frame 0 --all-values`, GDB/Textual versions, PC and console log.
- [ ] Verify y/Y/W/L copy commands, F2 input, paste and Enter, Escape to resume key stepping.

## Next engineering steps

1. **Retest global watches on SaltyPond**; capture GDB `-symbol-info-variables` / evaluated static `total` if unavailable. Retest local watches for regression.
2. Add repeatable fake-GDB event-flow tests, including stale responses, and source-scroller navigation tests. Improve focus handling if tree consumes `j/k`.
3. Add a separate source-function navigator (functions not currently executing), assembly/register pane and interactive GDB console, while retaining natural startup stepping.
4. Measure static function `.text` sizes, then introduce a QEMU TCG guest-instruction histogram; preserve unknown/unattributed ranges.
5. Add frame stack contribution and per-scope inclusive/self instruction attribution with provenance labels; implement optional electrical energy model only when assumptions are explicit.

## Verified versus unverified

**Verified:** User-confirmed original AN505 program boot; user-confirmed dbg3k TUI startup and source selection; Python parser/model unit tests and compileall in builder.

**User confirmed:** frame-local watch query now succeeds. **Patched but unverified on user's machine:** globals and file-static watch discovery/evaluation; source scrolling and clipboard behavior.

**Not implemented:** Global watch selection/pinning, function navigator, actual per-function instruction profiling, frame-stack peak calculation, energy accounting, numeric stepping prefixes, robust invocation identities.

**Do not regress:** Visible startup and handler source; separation of navigation and execution; accurate labels distinguishing measurement from estimate; GitHub + `CONTINUE.md` + JSON handoff continuity.

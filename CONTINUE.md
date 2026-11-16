# dbg3k: development history and continuation

**Repository:** https://github.com/tumblewhead/dbg3k
**Working branch:** `feature/m0-1-mi-textual-scope-001`
**Review:** https://github.com/tumblewhead/dbg3k/pull/1 (draft)
**Current stage:** M0.1 user-feedback fixes, pending live retest on Arch Linux.

> **Handoff protocol:** Read this file first, followed by `AGENTS.md`, `docs/DESIGN.md`, `docs/CONVERSATION_NOTES.md`, `README.md`, and `handoff/CONTINUE.json`. The GitHub repo is canonical. Update this human-readable journal and the JSON checkpoint after meaningful work, and leave the next exact action for a new agent.

## Chronological development record

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
- [ ] Check locals populate watches once symbols are in scope, including `main.n`, `foo.n`, `bar.result`; histories update across stops.
- [ ] If not, capture watch-pane message, GDB MI response to `-stack-list-variables --frame 0 --all-values`, GDB/Textual versions, current PC/function and console log.

## Next engineering steps

1. **Retest on SaltyPond** and collect real MI evidence for the missing watches if unresolved.
2. Add repeatable fake-GDB event-flow tests, including stale responses, and source-scroller navigation tests. Improve focus handling if tree consumes `j/k`.
3. Add a separate source-function navigator (functions not currently executing), assembly/register pane and interactive GDB console, while retaining natural startup stepping.
4. Measure static function `.text` sizes, then introduce a QEMU TCG guest-instruction histogram; preserve unknown/unattributed ranges.
5. Add frame stack contribution and per-scope inclusive/self instruction attribution with provenance labels; implement optional electrical energy model only when assumptions are explicit.

## Verified versus unverified

**Verified:** User-confirmed original AN505 program boot; user-confirmed dbg3k TUI startup and source selection; Python parser/model unit tests and compileall in builder.

**Patched but unverified on user's machine:** Source scrolling and MI watch diagnostics/command adjustment.

**Not implemented:** Function navigator, advanced console, actual per-function instruction profiling, frame-stack peak calculation, energy accounting, numeric stepping prefixes, robust invocation identities.

**Do not regress:** Visible startup and handler source; separation of navigation and execution; accurate labels distinguishing measurement from estimate; GitHub + `CONTINUE.md` + JSON handoff continuity.

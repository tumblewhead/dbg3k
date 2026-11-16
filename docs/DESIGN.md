# dbg3k architecture and measurement contracts

## Product

A stylish, fast, keyboard-first source debugger for Cortex-M firmware in QEMU. Concept name qscope. CGDB-like navigation into startup, handlers and assembly. Source pane, scope tree, locals with change highlighting and sparklines, compact stepping bar and GDB console. Nerd Font optional; Unicode fallback. Execution `▶` and browsing `▸` cursors separate. Stack/variable stop-state updates only while halted; independent QEMU count snapshots can update while running.

## Canonical scope graph

The palette offers checkmarked view toggles and a multi-select Views dialog.
Source, stack tree with persistent observed returns, immediate scope watches
(executing frame 0), globals and console are independently visible for a session.
Source browsing does not change the immediate watch's scope. View visibility
does not control debugger execution or history collection.

Left/Right toggles the highlighted View entry without dismissing the palette.
An optional GDB Python helper is installed automatically on connection; internal
finish breakpoints observe returns from normal debug-visible frames encountered
at stops. Structured JSON arrives over MI console records, separate from target
output. This supports normal source stepping and continuing from observed
functions. Missing GDB Python falls back to MI finish events. No return is
inferred for calls entirely skipped between visible stops. These observations
are aggregated caller/callee histories, not exact invocation traces.

CPU -> thread/task/exception context -> call invocation -> lexical scope -> symbol. Two projections: active call tree and aggregate call tree. Symbol identity should incorporate build ID, compilation unit, DWARF DIE or code ranges; locals add lexical declaration identity; instances add task/thread and invocation. Human display defaults to `function.local`. Recursion and shadowed names must be distinguishable. Frame number is *not* a permanent identity. Calls between debugger stops cannot always be observed without trace.

Watches retain a bounded (initially 128) sample history, time axis by stop sequence, not clock time. Show value delta and optional Unicode sparklines. Later: pin expressions, expand struct/array, snapshot review, and globals.

## Low-friction execution

`s` into source, `n` next source, `i` instruction, `I` over instruction, `o` out, `c` continue, `Space` repeat, `j/k` source cursor, `b` breakpoint, `r` until cursor. Future: count prefixes like `5s`, auto-step mode with rate control, break/exception abort, assembly split, GDB command line. Serialize GDB commands and synchronize running vs stopped state; never queue overlapping execution.

## Stack attribution

The first resource implementation uses three selectable panes: Stack, Code &
Instructions, and Energy. GDB Python supplies stopped frame/register snapshots;
ELF symbols supply emitted body extents; a single-vCPU QEMU plugin supplies
exclusive instruction dispatch counts. Stack bytes remain sampled unwind
estimates, inclusive instruction counts are unavailable, and energy requires
explicit user assumptions. Average power remains unavailable without target
duration. See [RESOURCES.md](RESOURCES.md) for the evidence and launch contract.

Additional graphical projections retain the textual panes: a vertical sampled
stack map with bounded real memory bytes; a sortable whole-QEMU-run Pareto/table
ranking; and a matching estimated energy ranking. Function-entry PC dispatches
are labeled as a call-count proxy, never exact invocation identities. Current
and selected frames use emitted-body identities; aliases are folded. Percentages
include unknown dispatches in the denominator and energy remains explicitly
estimated under a common per-instruction model.

The energy/ranking update path is backed by session-scoped JSONL snapshots. Live
plugin input is validated before recording; incremental replay rebuilds the
profile and model without summing cumulative counters. Transient I/O failures
retain last validated data with source diagnostics. Previous explicit model
assumptions can be restored for a proven matching ELF on live startup. Recorded
profile replay keeps session identity, uses that session's assumptions or an
explicit user override, and never derives instruction counts from stop samples.

Per invocation: physical frame contribution, cumulative depth from an identified stack origin, inclusive maximum including callees, and observed maximum stack pointer displacement. Separate call-stack depth (frames) from bytes. Track MSP vs PSP independently, consider interrupts/hardware exception frames, dynamic allocation, recursion, tail calls, inlining, and compiler optimizations. GDB SP differences are estimates; exact maxima require SP tracing, instrumentation, or carefully qualified stack coloring. Mark evidence quality.

## Instruction attribution and static footprint

Use ELF/DWARF/linker maps for `.text` bytes per emitted body and address mapping. Thumb instruction width can be 16 or 32 bits. Inlining, veneers, aliases and unknown code ranges need explicit buckets, not invented ownership. The first QEMU TCG plugin counts **guest instruction dispatches** by PC (exclusive, potentially faulting; not necessarily retired). Inclusive call-tree totals require call/return and exception-context tracking. Future profiles can add call counts, per-invocation work and density. Current share uses all-code dispatches since QEMU launch as denominator. Instruction share is NOT measured CPU time or energy. QEMU host execution time is not a useful MCU CPU measurement.

## Energy model

Under a constant active current slope and fixed workload throughput:
`charge_per_instruction[pC] = active_current[µA/MHz] / performance[MIPS/MHz]`
`energy_per_instruction[pJ] = charge_per_instruction[pC] * supply_voltage[V]`.
Alternatively `estimated_cycles = instructions / (MIPS/MHz)`, then `energy[pJ] = estimated_cycles * active_current[µA/MHz] * voltage[V]`. Later add leakage/idle/peripheral current, wait states, frequency/voltage choices, cache/memory effects and sleep. Always label estimated vs measured and list assumptions.

## Profiles and build diffs

Sort by `.text` bytes, exclusive/inclusive instructions, stack own vs peak, approximate energy. Build A/B compares matched stimuli, compiler flags, run window and assumptions. Export versioned data: ELF hash, build ID, hardware model, provenance, measurement engine, electrical assumptions.

## Separation of concerns

- GDB/MI: source, frames, locals, breakpoints, registers, halt and exception events.
- QEMU plugin (later): executed instruction and optionally SP/call trace with low overhead.
- Scope model: identifiers, histories, attribution and provenance.
- Textual/Rich: keyboard workflow and panels.
- Data format: versioned profiles and sampled stop state.

## Milestones

**M0.1 alpha:** GDB/MI parser, GDB subprocess, source/stack/watch panes, single-key stepping, breakpoint support, stop sparklines, unit tests, AN505 example. Implemented but *not end-to-end-qualified* in this builder.

**M0.2:** verify real Arch/QEMU/GDB/Textual integration; add fake-GDB tests, assembly pane, editable command console, MSP/PSP registers, robust MI dispatch, invocation tracking, numeric prefixes and auto-step.

**M0.3 first slice implemented:** ELF function body sizes, QEMU TCG dispatch-PC histogram, three resource panes, unknown-PC accounting and sampled unwound-SP estimates. Inclusive/invocation instruction attribution and proven stack bounds remain unavailable.

**M0.4+:** complete self/inclusive attribution through call/exception trace, stack-frame contributions, energy model, build comparison, runtime task context, history drill-down.

Do not show illustrative numbers as live measurements. No claim of silicon-accurate timing from QEMU or guaranteed stack bounds without evidence.

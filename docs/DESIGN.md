# dbg3k architecture and measurement contracts

## Product

A stylish, fast, keyboard-first source debugger for Cortex-M firmware in QEMU. Concept name qscope. CGDB-like navigation into startup, handlers and assembly. Source pane, scope tree, locals with change highlighting and sparklines, compact stepping bar, GDB console (later). Nerd Font optional; Unicode fallback. Execution `▶` and browsing `▸` cursors separate. Stop-state updates only while halted.

## Canonical scope graph

CPU -> thread/task/exception context -> call invocation -> lexical scope -> symbol. Two projections: active call tree and aggregate call tree. Symbol identity should incorporate build ID, compilation unit, DWARF DIE or code ranges; locals add lexical declaration identity; instances add task/thread and invocation. Human display defaults to `function.local`. Recursion and shadowed names must be distinguishable. Frame number is *not* a permanent identity. Calls between debugger stops cannot always be observed without trace.

Watches retain a bounded (initially 128) sample history, time axis by stop sequence, not clock time. Show value delta and optional Unicode sparklines. Later: pin expressions, expand struct/array, snapshot review, and globals.

## Low-friction execution

`s` into source, `n` next source, `i` instruction, `I` over instruction, `o` out, `c` continue, `Space` repeat, `j/k` source cursor, `b` breakpoint, `r` until cursor. Future: count prefixes like `5s`, auto-step mode with rate control, break/exception abort, assembly split, GDB command line. Serialize GDB commands and synchronize running vs stopped state; never queue overlapping execution.

## Stack attribution

Per invocation: physical frame contribution, cumulative depth from an identified stack origin, inclusive maximum including callees, and observed maximum stack pointer displacement. Separate call-stack depth (frames) from bytes. Track MSP vs PSP independently, consider interrupts/hardware exception frames, dynamic allocation, recursion, tail calls, inlining, and compiler optimizations. GDB SP differences are estimates; exact maxima require SP tracing, instrumentation, or carefully qualified stack coloring. Mark evidence quality.

## Instruction attribution and static footprint

Use ELF/DWARF/linker maps for `.text` bytes per emitted body and address mapping. Thumb instruction width can be 16 or 32 bits. Inlining, veneers, aliases and unknown code ranges need explicit buckets, not invented ownership. QEMU TCG plugin is planned to count **executed guest instructions** by PC (initially exclusive). Inclusive call-tree totals require call/return and exception-context tracking. Include call counts, per-invocation work, instruction share with a stated denominator and time/window selection, and density = executed instructions/static bytes. Instruction share is NOT measured CPU time or energy. QEMU host execution time is not a useful MCU CPU measurement.

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

**M0.3:** ELF function `.text` sizes, QEMU TCG instruction-PC histogram, resource panel, unowned-PC accounting; start stack observation with explicit precision.

**M0.4+:** complete self/inclusive attribution through call/exception trace, stack-frame contributions, energy model, build comparison, runtime task context, history drill-down.

Do not show illustrative numbers as live measurements. No claim of silicon-accurate timing from QEMU or guaranteed stack bounds without evidence.

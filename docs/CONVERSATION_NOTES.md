# Design-conversation checkpoint, 2026-11-15

This document **preserves the content and decisions of the discussion**, not a verbatim message-by-message transcript. The original conversation remains in ChatGPT.

## Precursor: QEMU AN505

The user wanted a fast bare-metal Cortex-M33 learning example under Arch Linux, using QEMU `mps2-an505`. The first firmware crashed with `Lockup: can't escalate 3 to HardFault`. The debugging path established:

1. QEMU initially loaded reset SP and PC as zero, and a fault referenced the Secure vector table at `0x1000000c`.
2. The firmware was relinked to `0x10000000` (Secure code alias). GDB confirmed execution at `Reset_Handler` and a correct Thumb reset vector `0x10000011`.
3. Stack at `0x30400000` remained invalid, faulting on exception entry.
4. Placing RAM at `0x38000000` with a 64 KiB allocation fixed the problem. User confirmed: **it works**.
5. The ability to single-step into startup and exception handlers prompted the debugger idea.

## Product direction

CGDB was close to ideal for source navigation, but lacked the desired always-visible local-variable watches and histories. The user loves modern Rich/Textual TUI design, Nerd Fonts, stylish but restrained colors, and sparklines. Keep an integrated source view, scope explorer, watches, compact command/help strip, and GDB console. A console should be an escape hatch, not required for normal debugging.

The requested label is `scope.local`: `foo.n` must never collide with `bar.n`. Recursion, lexical shadowing, and concurrent Kodama tasks need additional invocation/scope/thread identities. Historical values are sampled at debugger stops, highlighting changes and optionally showing inline sparklines or expanded plots. Historical snapshot inspection is distinct from true reverse execution.

The user objected to repeatedly typing `s s s s si si s s n n n`. Support single keys: `s/n/i/I/o/c`, `Space` repeat, numeric prefixes such as `5s`, auto-step rate control, breakpoint/run-to-navigation-cursor, and separate source browse and execution cursors. Execution commands must be serialized.

## Scope tree and measurements

User strongly preferred a single canonical **scope tree** underpinning all the UI views. Scope nodes own locals, call relationships, stack contribution, dynamic instruction work, and eventual energy estimates. Active invocation and aggregated call trees share the same identity model.

Stack requirements: current usage, maximum, call depth, and explicitly the incremental contribution of each function frame to cumulative depth, plus peak including callees. MSP, PSP, interrupts, recursion, alloca, inlining and compiler behaviors require accurate provenance labels.

Execution metric: **executed guest instructions**, not elapsed time or silicon cycles. Display emitted function `.text` bytes alongside lifetime dynamic instruction counts, exclusive/inclusive shares, and execution density. A small hot function matters as much as a large cold function, for different reasons.

Energy: use configurable active current `µA/MHz`, performance `MIPS/MHz`, and voltage. Ratio is `µA/MIPS`, equivalent to picoCoulombs per instruction under the model; voltage yields picoJoules/instruction. An optional CPI-based estimated cycle model is not a silicon measurement. Future profiles compare two builds using the *same* stimulus and assumptions.

## Build commitment

Canonical GitHub repository: https://github.com/tumblewhead/dbg3k. Python Textual/Rich frontend; GDB/MI control plane; independent scope model; future QEMU TCG plugin for guest instruction profiling. Start with an actual AN505 debugger MVP before sophisticated resource attribution.

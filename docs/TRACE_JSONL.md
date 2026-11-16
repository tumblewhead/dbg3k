# dbg3k JSONL evidence stream (v1)

**Goal:** retain debugger-observable execution, stack, variable, and function-return evidence so UI histories can be explored without losing older values. This is a debugger observation stream (visible stops plus automatic return probes), not an instruction-accurate QEMU trace or continuous sample stream.

## File and lifecycle

Default path: **./dbg3k-history/targetname_YYYY-MM-DD.jsonl**.

The target name is the sanitized ELF basename without its extension. For example, a Kodama target stored as /path/c-main-arm/demo.elf on November 15, 2026 writes **dbg3k-history/demo_2026-11-15.jsonl**, relative to the process working directory. Set **--history-dir PATH** to override the directory.

- File opens in **append** mode; multiple launches on the same date use the same file, without overwriting it.
- Each launch has a unique session ID and monotone per-session sequence numbers. Each record has an ISO 8601 timestamp in the host's local timezone.
- Each record is compact UTF-8 JSON, one object per line, immediately flushed. If a previous crash leaves an incomplete last line, a new session starts on a fresh line.
- Recording starts upon a successful GDB remote connection. The debugger console prints the absolute filename.
- A write failure disables recording and reports a diagnostic, without aborting target debugging.

## Schema

Every object includes: **schema="dbg3k.trace.v1"**, **kind**, **session**, **seq**, and **timestamp**.

| Kind | Fields beyond the envelope |
| --- | --- |
| session_start | target, elf, remote |
| command | stop, gdb_command, purpose (for execution, console, breakpoints) |
| stop | stop, reason, thread, frame, origin |
| frames | stop, thread, frames (level, function, filename, line, PC) |
| frame_arguments | stop, thread, arguments by stack level |
| locals | stop, thread, frame_level, variables from GDB/MI |
| global_value | stop, thread, symbol, label, value |
| return | stop, thread, caller, callee, callee_display, value, optional caller_frame, origin, optional stop_anchor |
| gdb_error | stop, purpose, message |
| session_end | target |
| stack_sample | stop, thread, registers (unavailable values null), frames (level/function/PC/SP/kind), optional memory (start, hex; cap 256 bytes), memory_error, origin=gdb-unwound-registers |
| instruction_profile | ELF SHA256, QEMU run UUID, profile_seq (separate from JSONL envelope seq), total, unknown, complete, exclusive counts and entry_hits by emitted body, origin=qemu-plugin-instruction-dispatch |
| energy_model | ua_per_mhz, mips_per_mhz, voltage, origin=user-configured-active-core-model |
| debugger_metadata | GDB version, architecture, connection and available frame/thread metadata |
| observation_config | stop, enabled, selected expressions, expansion limits |
| observation | observation_version=1, stop, thread, expression, scope, status, type/value/raw when available, errors, truncated, limits, request, origin |
| kodama_config | capture, enabled, probes, source-header label mapping/fingerprint |
| kodama_coverage | data: installed/unavailable API probes |
| kodama_sample | data: dbg3k.kodama.raw.v1 sample, typed state/event, thread/frame/exception, visible-stop anchor |
| kodama_diagnostic | data: explicit collector read/limit diagnostic |

Kodama samples drive a domain projection with task/signal timelines, decoded
waits, derived policy explanations and pool mapping. API entries anchor to the
preceding visible stop; they do not invent a stop or claim API success. Signal
names are source mappings, not build-verified values. Scalar nodes use tagged
strings. See [KODAMA_VIEW.md](KODAMA_VIEW.md) for graphical/replay workflows,
encoding, coverage and bounds. Existing kinds/readers remain compatible.

`session_start` additionally carries `executable` (path, SHA256, GNU build ID when
present) and dbg3k version. These additions preserve `dbg3k.trace.v1` and all old
kinds. Ignore unknown fields/kinds. Opt-in observations use GDB typed values,
ordered fields/elements, decimal integer strings and hex pointer addresses.
They do not parse existing watch strings. See [OBSERVATIONS.md](OBSERVATIONS.md)
for the complete versioned encoding, CLI/palette selection, limits, query and
reproducible real Kodama qualification.

New session-start and energy-model records also include `elf_sha256` where the
ELF is available; energy-model `source` describes CLI/user/restored provenance.
The profiling views incrementally consume active-session profile/model records
and can explicitly follow a recorded file/session. Old records without entry-hit
data retain unavailable call metrics. Partial lines, malformed records and
rotated/truncated files are handled without adding cumulative totals twice.
Recorded sessions/builds are kept distinct. See the JSONL replay section in
[RESOURCES.md](RESOURCES.md).

Instruction snapshots are periodic cumulative QEMU-run dispatch counts, not
stop-synchronized instruction traces. Stack samples are accepted only for the
current halted stop/thread. Energy model entries record assumptions, not power
measurements. See [RESOURCES.md](RESOURCES.md).

Illustrative return record (not actual simulation data):

~~~json
{"schema":"dbg3k.trace.v1","kind":"return","session":"abc123","seq":30,"timestamp":"2026-11-15T21:22:00-08:00","stop":12,"thread":"1","caller":"foo","callee":"bar","callee_display":"bar(2)","value":"6","caller_frame":{"func":"foo","line":"17"},"origin":"gdb-mi-function-finished"}
~~~

## Live return UI

A GDB Python internal finish breakpoint observes a return from a debug-visible
function encountered at a stop, including when returning through ordinary `s`,
`n` or continue. It emits a versioned JSON message on the MI console stream and
automatically resumes without adding a visible debugger stop. Return records
have `origin="gdb-python-finish-breakpoint"`, and `stop` anchors to the preceding
visible stop (`stop_anchor="preceding-debugger-stop"`). MI `function-finished`
events from `o` remain supported as `origin="gdb-mi-function-finished"`, with the
new stop index. The two sources are deduplicated when they describe the same
finish command. dbg3k groups observations by (thread, caller function, callee
function) and keeps one persistent row per edge under the historical caller.

~~~text
cpu0 / observed call stack
  ↩ observed returns (1)
    foo() [thread 1]
      ↳ bar(4) ⟵ 12 · 5×
  ▶ active call stack
    main()
      foo(2)
~~~

Globals are displayed in a separate pane. The active caller also shows its latest
observed callee returns; those summaries use the same ledger and copy behavior.

The return-history group is independent of the active stack. Its rows and tree-node identities **survive the caller leaving the stack** and subsequent asynchronous GDB replies. The displayed value is overwritten on subsequent returns, without recreating the node. Hover for the **last ten** observed returns, with debugger-stop numbers and original callee signatures. Select/click to copy the **entire current-session history** for that caller/callee edge, read from the JSONL file as TSV rather than the 10-event in-memory cache.

Step into a callee with **s**, then keep using **s/n** or continue to observe its
return automatically. The observer tracks up to 128 pending normal frames with
debug symbols and an identifiable caller. Unsupported/inline/optimized frames
may be unavailable. Exception unwinds do not manufacture return values. Without
GDB Python, use **o** as a fallback. A `next` over a wholly unseen call still
does not observe that callee's result. These host debugger breakpoints change
debug execution overhead; no timing or silicon measurements are implied.

## Provenance and bounds

- A debugger-stop trace cannot reconstruct calls that started and finished entirely between GDB halts.
- A missing reported return value is encoded as JSON null, not zero.
- Caller/callee aggregation is keyed by function and thread, not unique invocation or call site; recursion and multiple call sites can share a UI row, but JSONL retains every observed event.
- JSONL is the durable source; the in-memory return ledger stores only the most recent 10 for each edge.
- A file may contain multiple sessions; readers must filter by session ID.
- Source paths, variable values and debugger command contents may be sensitive. Treat traces as developer data.

Future: invocation-precise identities, QEMU guest-instruction events, additional stack/profiling data with distinct provenance, and offline rehydration of the UI from a selected session.

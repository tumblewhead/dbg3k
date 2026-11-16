# dbg3k JSONL evidence stream (v1)

**Goal:** retain debugger-observable execution, stack, variable, and function-return evidence so UI histories can be explored without losing older values. This is a *debugger-stop trace*, not an instruction-accurate QEMU trace or continuous sample stream.

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
| return | stop, thread, caller, callee, callee_display, value, caller_frame, origin |
| gdb_error | stop, purpose, message |
| session_end | target |

Illustrative return record (not actual simulation data):

~~~json
{"schema":"dbg3k.trace.v1","kind":"return","session":"abc123","seq":30,"timestamp":"2026-11-15T21:22:00-08:00","stop":12,"thread":"1","caller":"foo","callee":"bar","callee_display":"bar(2)","value":"6","caller_frame":{"func":"foo","line":"17"},"origin":"gdb-mi-function-finished"}
~~~

## Live return UI

A GDB/MI **function-finished** stop contains a return value if GDB can observe one; this commonly follows **o** (finish) from inside the callee. dbg3k groups these observations by (thread, caller function, callee function) and keeps exactly one active row per edge under the caller.

~~~text
foo(2) [main.c:17]
  result = 12
  ↳ bar(4) ⟵ 12 · 5×
~~~

The row is persistent while the caller is visible, and its value is overwritten on subsequent returns. Hover for the **last ten** observed returns, with debugger-stop numbers and original callee signatures. Select/click to copy the **entire current-session history** for that caller/callee edge, read from the JSONL file as TSV rather than the 10-event in-memory cache.

Ordinary source **next/step over** does not report each callee's return value. To record a return now, step into the callee (**s**) and finish it (**o**). Unobserved calls require separate trace instrumentation; do not invent values.

## Provenance and bounds

- A debugger-stop trace cannot reconstruct calls that started and finished entirely between GDB halts.
- A missing reported return value is encoded as JSON null, not zero.
- Caller/callee aggregation is keyed by function and thread, not unique invocation or call site; recursion and multiple call sites can share a UI row, but JSONL retains every observed event.
- JSONL is the durable source; the in-memory return ledger stores only the most recent 10 for each edge.
- A file may contain multiple sessions; readers must filter by session ID.
- Source paths, variable values and debugger command contents may be sensitive. Treat traces as developer data.

Future: invocation-precise identities, QEMU guest-instruction events, additional stack/profiling data with distinct provenance, and offline rehydration of the UI from a selected session.

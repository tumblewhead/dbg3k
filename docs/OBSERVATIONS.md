# Selected structured observations in dbg3k.trace.v1

This is the application-agnostic data foundation for a future Kodama view. It
extends the existing append-only evidence stream. It does not add a second
exporter, a Kodama decoder, or a continuous scheduler event trace.

## Capture and locate

Select **Ctrl+P → Observation capture**, enter one expression per line, and choose
**Start / apply**. **Stop capture** prevents new requests; a request already
issued may finish. Selection lasts for this launch. Changing the selection while
halted requests the new selection at the current stop. Reopening the dialog shows
the capture status, most recent result and absolute JSONL path. Individual
partial/error results also appear in the GDB console. GDB Python is required;
missing collectors are recorded as unavailable rather than silently omitted.

Alternatively, start with explicitly selected values:

```sh
dbg3k /path/to/kodama/build/c-main-arm/demo.elf --remote localhost:1234 \
  --observe "'kodama.c'::tasks" \
  --observe "'kodama.c'::running" \
  --observe "'kodama.c'::levels" \
  --observe "'kodama.c'::clock_ticks" \
  --observe g_cmd --history-dir ./kodama-capture
```

The existing file is `./kodama-capture/demo_YYYY-MM-DD.jsonl`. It is appended,
never replaced, and each session has its own UUID. Copy the file directly with
`cp` to export it. Complete records flush immediately. A crash can leave an
incomplete last line: skip that fragment; reopening starts on a fresh line.
Write failures disable recording and print the failure in the GDB console.
Values, expressions and source paths stay local; there is no upload. The normal
legacy watch trace still runs independently of selected observation capture.

Selectors support a symbol (including `'file.c'::name` and C++ namespace scope),
`.field`, `->field` and integer `[index]`. A leading `*` explicitly reads the
pointee of the completed selector, e.g. `*tasks[0].subscription`. Parenthesized
expressions, casts, arithmetic, assignments, increments and calls are excluded
in this slice. The original requested expression is retained verbatim in each
record, including the leading `*`. Null dereferences are skipped with an error;
non-null addresses can still be stale and fail. Pointer values alone never
cause a pointee read, including character pointers. GDB inferior function calls
are disabled during collection, and Python pretty printers are bypassed.

## Additive contract

Every record keeps `schema="dbg3k.trace.v1"`, `kind`, `session`, monotonic `seq`,
and the host-local ISO `timestamp`. Existing kinds retain their meanings. Readers
must ignore unknown kinds and fields; future incompatible observation encodings
will increment `observation_version`. Unknown metadata is null or omitted and
is not evidence of a zero target value. See [TRACE_JSONL.md](TRACE_JSONL.md).

- `session_start` adds `executable: {path, sha256, build_id}` and
  `tool_versions: {dbg3k}`. The legacy `elf` and `elf_sha256` remain. Missing GNU
  build IDs are null. The hash identifies the readable ELF file, not an attestation
  that target memory equals that image.
- `debugger_metadata` provides `gdb_version`, `architecture`, `remote`, and
  thread/frame context when available. It supplements the session after GDB
  connects; it is not itself a stop snapshot.
- `observation_config` records `enabled`, selected `expressions`, fixed `limits`,
  and the `stop` at which configuration changed.
- `observation` has `observation_version=1`, `stop`, `thread`, `expression`,
  `scope`, `status`, `truncated`, `limits`, `origin`, and, when available, `type`,
  `value`, `raw`, `errors` and a collector `request` identifier. A diagnostic can
  lack `request` when the collector could not load.

`scope.frame` contains level (currently 0), function, PC as hex text, source file
and line when supplied by GDB. File/static scope remains explicit in the original
expression; expressions without it resolve in the executing frame. Capture does
not follow the source-browsing frame. Thread, frame and stop are checked against
the issued request. Stale or missing replies generate capture errors anchored to
the original stop, never successful values assigned to a later stop. Existing
asynchronous frames/locals/arguments/globals now also reject stale replies. Each
actual MI stop advances the stop index; redisplaying frames does not create a
new stop. The attach snapshot has an explicit initial `stop` record.

`status` is `ok`, `partial`, `unavailable` or `error`. An aggregate with failing
children is partial; each child preserves its own status/error. Optimized-out
and unavailable scalar fields are unavailable. Expression and memory read
failures are errors. Bounds produce partial aggregates or unavailable unstarted
expressions with `truncated=true` and an explicit limit reason. No missing or
failed value is replaced by zero or a successful JSON null.

### Value nodes

All nodes include a logical `path` rooted at `$`, type when known, status and
truncation. Nodes can carry `errors: [{path, code, message}]`.

| kind | Encoding |
| --- | --- |
| integer / enum | `encoding="decimal"`, `value` is a decimal string; `bits` when known |
| pointer | `encoding="hex"`, `address` is hex text, `pointee_type`, `dereferenced=false`; no implicit child |
| float | `encoding="gdb-text"`, `value` is GDB decimal text, including nonfinite forms |
| array | `bounds` as decimal strings, `total_children`, ordered `children` with integer-string `name` |
| object / union | ordered `children`, each with field `name` and `ordinal`; unions expose alternative interpretations, not a claim of the active member |
| opaque | raw rendering when possible and explicit unsupported/unavailable status |

Array/field children remain independent nodes, rather than a parsed aggregate
string. Field ordinals disambiguate duplicate names; unnamed fields use `@N`.
Logical paths escape `~` and `/` as `~0` and `~1`; duplicate field names must also
be distinguished using ordinal. Integers and pointer addresses never pass through
a JSON floating number. Use `int(value, 10)` or `int(address, 16)` in a consumer.

`raw` is `{format, text, truncated}`. Scalar text uses
`gdb.Value.format_string/raw`; pointers use hexadecimal formatting to avoid
reading character strings. Aggregate raw text uses GDB's **summary** rendering
(`gdb.Value.format_string/raw-summary`), not a fabricated full printout; the
structured tree carries the fields. Unavailable values can instead carry a GDB
availability label. Rendering is evidence for display only, never the decoding
source. GDB representations vary by version. See the primary
[GDB value API](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Values-From-Inferior.html)
and [inferior-call permission](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Calling.html).

### Work bounds

The recorded limits are: 16 expressions, 512 characters per expression, depth 5,
256 nodes per expression, 64 children per aggregate, 2048 raw characters per node,
64 KiB GDB `max-value-size`, 128 KiB per observation record (with envelope reserve),
and a shared 750 ms cooperative expansion budget per stop. A huge tree can be
omitted with an explicit record-size error. Depth/node/child/time cutoffs retain
partial children and label the omission. The time budget is checked between
reads; it cannot interrupt one blocking remote-memory operation. This is a
bounded expansion policy, not a hard wall-clock deadline. Existing automatic
legacy watches have separate work costs. There is no firmware code/RAM cost;
host debug reads and halted-time overhead remain.

## Query

[examples/observations.jsonl](examples/observations.jsonl) is a small **illustrative**
compatible stream, not target qualification evidence. Query actual files by
session and successful/partial observation, then use named children:

```python
import json

def field(node, name):
    return next(c for c in node['children'] if c['name'] == str(name))

session = 'YOUR_SESSION_UUID'
with open('kodama-capture/demo_YYYY-MM-DD.jsonl', 'rb') as stream:
    for line in stream:
        try:
            r = json.loads(line)
        except (ValueError, UnicodeError):
            continue  # interrupted last line
        if (r.get('session') == session and r.get('kind') == 'observation'
                and r.get('expression') == "'kodama.c'::tasks"
                and r.get('status') in ('ok', 'partial') and 'value' in r):
            for slot in r['value'].get('children', []):
                # Example layout only: check each field's status before use.
                fields = {c['name']: c for c in slot.get('children', [])}
                observed = {k: fields[k].get('value') for k in
                            ('active', 'generation', 'waiting', 'seen')
                            if k in fields and fields[k]['status'] == 'ok'}
                print(r['stop'], slot['name'], observed)
```

Kodama layouts differ across builds. Generation + validity matter; slot number
alone is not task identity. Newer optimized layouts may expose `identity` rather
than `active`/`generation`, or a subscription pointer instead of `waiting`. The
exporter does not translate these. Event/task names and wake causes remain
unknown unless observed explicitly. Subscription pointers can be stale after a
wake; explicit dereferences require their own checked observation.

A difference between two snapshots establishes endpoint differences only. It
does not establish intermediate event order, complete transitions, CPU occupancy,
physical time or exact invocation history. Derived comparisons belong in distinct
consumer data, not in observed nodes.

## Reproduce real Kodama qualification

Use the requested branch's pinned source independently of any dirty checkout:

```sh
git clone https://github.com/tumblewhead/kodama.git /tmp/kodama-observation-demo
git -C /tmp/kodama-observation-demo checkout 2679a470eb982aee76e75950f0e117edf02767fd
(cd /tmp/kodama-observation-demo && make c-main-arm)
# From dbg3k, with dependencies installed in the active Python environment:
DBG3K_QEMU_TEST=1 \
DBG3K_KODAMA_ELF=/tmp/kodama-observation-demo/build/c-main-arm/demo.elf \
DBG3K_OBSERVATION_RECEIPT=/tmp/kodama-capture-receipt \
PYTHONPATH=src python -m unittest discover -s tests -p test_qemu_observations.py -v
```

Requires ARM-capable Python-enabled GDB (`DBG3K_GDB=gdb-multiarch` if needed),
`qemu-system-arm`, GNU Arm C/C++ compiler with newlib and C++ headers, and dbg3k's
Python dependencies. The tests launch their own AN505/GDB session on an ephemeral
loopback port, validate the complete JSONL, compare values/types with independent
MI queries, and copy the Kodama journal to the requested receipt directory. Use
an empty/new receipt directory to preserve older qualification copies.

The real Kodama test stops at `kodama_signal` and `kodama_signal_and_pend` and
checks the worker active=1, generation=1, waiting=1, seen=0 then seen=1; it also
captures `running`, `levels`, `clock_ticks`, `g_cmd`, and an invalid expression.
The generic ARM fixture verifies UINT64_MAX, nested arrays, a changing scalar,
null vs bad pointers, failed explicit reads, GNU build ID and truncation. CI runs
both against the pinned real source. The example is an SRAM-only M23-instruction
image at `0x38000000` running on QEMU's AN505 M33 proxy. No physical M23, physical
timing/power or target UI qualification is implied. Local versions/results and
retained failures are in `handoff/observations-validation.json`.

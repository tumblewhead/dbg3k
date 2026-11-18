# Browser history inspector

Record with dbg3k, open the local browser inspector, choose the JSONL, and inspect
the recorded history. The inspector starts no GDB or QEMU and needs no ELF file.
The selected trace is read by a browser worker; it is not uploaded to the server.
All assets are local, with no external fonts, analytics or network services.

Screenshots: [task/signal/pool history](images/browser-history.png) and
[function/energy profile](images/browser-profile.png). These use an actual
Kodama/QEMU capture; the electrical inputs48/1/1.8 are illustrative test
assumptions, with a6-second illustrative target-duration input for the power
preview; none are measured device properties.

## Start the viewer

From the dbg3k checkout, using its installed environment:

```sh
python -m dbg3k.history_browser
```

Open **http://127.0.0.1:8767** in a browser on the same machine. Click **Open JSONL**
and select the recording. Keep this terminal open; Ctrl+C stops the asset server.
If the port is busy, append `--port 8768` and use the printed URL.

After reinstalling the package, `dbg3k-history` is an equivalent command. The
server itself uses only Python's standard library. In the Kodama demo repository
with the updated submodule, this also works without a package installation:

```sh
python3 tools/dbg3k/src/dbg3k/history_browser.py
```

The server exposes only its five fixed UI assets. There is no upload, debugger,
compiler, shell or filesystem-browsing endpoint. JSONL values are rendered as
text, never HTML. The file remains in the browser's selected File object;
closing/reloading the page clears the selection. To refresh a growing recording,
select it again. For a transferable capture, close dbg3k before copying the file.

## Record the evidence you need

Use the paired demo launcher so QEMU's instruction plugin and dbg3k refer to the
same ELF and profile file. In the Kodama demo root, with its venv active:

```sh
python tools/dbg3k/examples/kodama-demo/run.py --kodama-dir . \
  --dbg3k "$PWD/.venv/bin/dbg3k"
```

Use the platform settings in the operator guide if the debugger is named
`arm-none-eabi-gdb`/`gdb-multiarch` or the plugin header is outside `/usr/include`.
Paste the printed second-terminal command to launch dbg3k.

The launcher prints its unique run directory. Captures are under its `history/`
directory, typically `demo_YYYY-MM-DD.jsonl`. In the demo layout, locate them with:

```sh
find tools/dbg3k/build/kodama-demo-runs -name '*.jsonl'
```

Collection is independent of which panes are visible:

- **Task/signal lanes and pool:** enable Kodama capture. Visible stops supply
  snapshots. For intermediate observations, enable API probes in **Ctrl+P →
  Kodama setup**, then **Start / restart** while halted. Close alone does not
  apply changes. API probes are slower and bounded, so use focused intervals.
- **Instructions and entry hits:** run QEMU with the counting plugin and pass
  the paired `--instruction-profile` path to dbg3k. The launcher does both.
- **Recorded electrical assumptions:** set the energy model through **Model…**
  in the energy pane, or supply all three CLI options `--ua-per-mhz`,
  `--mips-per-mhz` and `--voltage`. Do not copy a teaching example's numbers as
  a device specification. Browser-only assumptions are also possible later.
- **Stack, watches and typed observations:** normal debugger stops collect stack
  samples; use **Observation capture** to select additional structured values.

New captures include `code_catalog` records with emitted-body keys, names,
aliases, addresses, sizes and the ELF hash. Older files remain readable, but
function names may be unavailable; their body keys and recorded counters remain
inspectable. No matching ELF has to be supplied to the browser.

## Browse task and signal history

Choose a **Session** and **Scheduler capture**. Sessions may share a file; captures
within a session may have different labels or a reset sequence. Each remains
selectable. They are never silently merged into one apparent task lifetime.

The browser indexes every accepted sample in the selected capture, rather than
keeping only the last512 displayed by the live TUI. The overview and history
slider span that entire capture. On desktop-width windows the coroutine pool sits
beside the lanes and stays visible while browsing; narrower windows stack the
panels. The pool and long lane area scroll independently. **First**, **Last**, page buttons, stop buttons
and **Go to sample** provide direct navigation. **Columns** controls zoom from
32 to512 observations. Click a column to inspect it; focus the canvas and use
Left/Right, Home/End or Page Up/Down for keyboard navigation. Horizontal trackpad
scrolling or Shift+wheel pans history. Movement is coalesced to the latest
requested viewport, and a bounded recent-record cache avoids rereading the full
window for a small pan. The cache holds at most1024 parsed records or16 MiB of
input bytes, independently of the full file index.

Each column is an observation, not an equal time interval. Stop boundaries are
marked S1, S2, etc. Task rows group scheduler slots; the selected inspector shows
slot/generation/epoch identities, state, priority, cluster and decoded waits.
Generation regression starts a new observation epoch. An undetected reset can
still leave identity uncertain. A shared slot row is not an exact invocation
trace. A vertical lifetime boundary prevents connecting changed identities as
one continuous task.

Signal rows combine observed level bits with API-entry markers: a triangle is
a request, a filled dot is a publication entry, and arrows identify level
requests when space permits. An entry does not prove successful return. Header
names are source mappings recorded by dbg3k, not build-attested semantics.
Names for event and level namespaces may share a mask in older recordings.

Select a sample to see coroutine slot ownership, addresses and slot extents.
Ownership requires matching live task/context/token/handle evidence. Unknown
owners remain unknown. Occupied payload capacity is not actual requested frame
size and is separate from the shared hardware execution stack. A compact lane
also shows the observed occupied-slot count across the viewport.

Capture gaps are shaded and explained at the selected observation. The browser
cannot recover activity omitted by the collector. The current API budget is
4096 samples between visible stops, automatically re-armed at the next stop.
Stop snapshots alone do not reveal all activity during a continue.

## Inspect instructions, calls and electrical estimates

**Instructions & energy** defaults to the latest validated cumulative profile in
the selected debugger session. The snapshot selector identifies its QEMU run and
sequence. Snapshots are replacements, not values to add together. Different
QEMU runs remain separate choices. **Use latest profile received before cursor**
chooses by journal arrival sequence; profile polling is not target-stop
synchronized. If none was received before that observation, the view says so.

Search function names/body keys, change the ranking metric, and page through
all functions. The table includes:

| Metric | Evidence |
| --- | --- |
| Dispatches and share | Exclusive guest instruction dispatch counters; denominator includes unattributed work |
| Entry hits † | Dispatches at the emitted body's entry PC; a call-count proxy |
| Entries / million dispatches | Normalized activity ratio; not a time frequency |
| Entries / s † | Entry hits divided by an explicitly supplied target-duration assumption |
| Code bytes | ELF emitted-body size, with exact aliases folded |
| Instructions / entry | Ratio of recorded counters; unavailable with no entry hits |
| Estimated cycles | Dispatches / assumed MIPS per MHz |
| Estimated charge and energy | Active-current/throughput/voltage model |

The charts show a sorted top12 ranking; all functions remain in the paged table.
Unattributed dispatches have their own row rather than disappearing. Known catalog
bodies with no attributed dispatches appear with zero counts. Inlined source
functions need not have distinct emitted bodies. Calls, recursion, coroutine
resumes, tail calls and interrupts are not reconstructed into exact invocations.

The summary has separate **Estimated cycles** and **Average active-core power**
cards, with a reason when a value is unavailable. **Configure estimates** opens
the profiling tab and focuses the next missing input. Open **Cycle, electrical
and duration assumptions** to inspect the recorded model or apply local
overrides. Each supplied input must be positive and finite. Throughput alone
enables estimated cycles; current plus throughput enables estimated charge;
adding voltage enables energy. Average power also needs target duration. Blank
inputs remain unavailable, rather than becoming zero. Leaving all three model
inputs blank disables the local model. Reset restores the recorded model,
without borrowing one from another session. No target duration is inferred from wall-clock timestamps or debugger
delays. The optional duration must correspond to the selected cumulative QEMU
counter window. Changing the selected cumulative snapshot or QEMU run clears that duration,
so an assumption for one counter window does not silently carry into another.

```text
estimated_cycles = dispatches / (MIPS/MHz)
charge[pC] = dispatches × (µA/MHz) / (MIPS/MHz)
energy[pJ] = charge[pC] × voltage[V]
average_active_core_power[µW] = energy[pJ] × 10^-6 / target_duration[s]
```

Measured silicon cycles and measured power are unavailable. Peripheral current,
sleep, leakage, frequency changes, memory effects and workload-dependent
throughput are excluded. Derived floating-point values are approximate;
recorded integral counters and addresses retain full precision.

**Export displayed profile CSV** exports all filtered rows, including rows on
other pages, plus session/run/snapshot/model/duration provenance. It does not
rewrite the source capture. Electrical model values remain assumptions.

## Inspect stacks and arbitrary records

**Stack & records** shows the latest stack sample received before the selected
scheduler observation, identifying its debugger stop. Adjacent normal-frame SP
differences are sampled own-frame estimates, not guaranteed maxima. Recorded
memory bytes show only what GDB actually supplied; unavailable reads stay absent.

The record inspector can open any session-local journal sequence. Filter a kind
and use Previous/Next to inspect typed observations, global/local watches,
returns, frames, diagnostics or other records throughout the file. **Raw record**
from the selected task observation jumps directly to its scheduler record.
Large display text is explicitly truncated; **Save selected record** preserves
the original complete JSON line, including full-width numeric tokens.

## Input bounds, validation and platforms

Files are scanned incrementally as UTF-8. The index stores byte offsets and
compact metadata; viewport snapshots are read on demand. It supports up to
2 million journal records,1 million samples per capture and8 MiB per line.
Index limits abort import with a visible error. Oversized or malformed lines,
interrupted tails, sequence gaps and duplicate/regressed records are reported
under **Coverage & provenance**. Nothing is silently dropped to fit a512-sample
window. A valid final object without a newline is indexed with a diagnostic.

Trace contents are user-supplied data, not independently authenticated evidence.
The viewer checks schemas, counter reconciliation and recorded build/session
relationships; it cannot prove where the file originated.

The automated checks exercise the actual streaming index/domain code in Node,
and an optional real Chromium test opens files and navigates the UI. The real
Kodama/QEMU recording is tested separately from the6201-sample synthetic fixture.
Linux Chromium, dark/light and narrow layouts are qualified by the current
receipt. Native macOS/Safari and physical hardware are not yet qualified.
Modern browsers need Worker, File/Blob streams, BigInt, ResizeObserver and
`findLast`; Node is only needed for development tests, not to use the inspector.

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_browser_history.py -v
# With Playwright/Chromium installed in a development environment:
DBG3K_BROWSER_TEST=1 PYTHONPATH=src python -m unittest discover -s tests -p test_browser_ui.py -v
```

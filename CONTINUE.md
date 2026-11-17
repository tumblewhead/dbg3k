# dbg3k: development history and continuation

**Repository:** https://github.com/tumblewhead/dbg3k
**Working branch:** `fix/kodama-capture-rearm` (based on PR #14)
**Review:** https://github.com/tumblewhead/dbg3k/pull/15 (draft, stacked on PR #14)
**Current stage:** Re-arm bounded API capture at each visible stop; preserve fresh snapshots and explicit capture gaps.101 tests:91 pass/10 opt-in skips; five real QEMU checks pass; compileall/whitespace pass.

> **Handoff protocol:** Read this file first, followed by `AGENTS.md`, `docs/DESIGN.md`, `docs/CONVERSATION_NOTES.md`, `README.md`, and `handoff/CONTINUE.json`. The GitHub repo is canonical. Update this human-readable journal and the JSON checkpoint after meaningful work, and leave the next exact action for a new agent.

## Chronological development record

### 2026-11-17: API capture resumes after budget exhaustion

User sees no new task/signal activity on the second continue. Read-only tail
inspection of the local journal confirms sequence4096 and the old session-wide
limit diagnostic. Replaced that lifetime cap with4096 API samples per interval
between visible stops. Every enabled visible stop emits a current snapshot and
re-arms the next interval without changing capture ID or resetting sample IDs.
Duplicate same-stop refreshes cannot refill the budget; paused capture stays
paused. Exhausted probes skip argument/frame/state reads, although installed
breakpoint traps still have overhead. No hidden interrupts or execution added.

Coverage carries budget scope/usage/exhaustion. A prominent banner identifies
exhaustion during a run. The following snapshot retains a capture_gap with
preceding stop, cutoff sequence and counted probe entries without state reads;
the timeline shows a separate gap row/legend without overwriting axis numbers.
Missing scheduler transitions are never reconstructed. Journal replay retains
gaps, and only the budget-specific diagnostic clears when re-armed. UI retention
remains512; JSONL appends across intervals. Per-run quotas do not bound total
session-file size. Existing source/capture histories remain untouched.

Validation:101 ordinary checks in23.317s:91 pass/10 opt-in skips. Five actual
QEMU/GDB checks pass in10.343s: old/current identity layouts, public collector
fixture, real continuous demo second-continue and public budget fixture. Budget
target tests use16 API samples/run to force exhaustion; unit tests exercise the
production4096 budget across two intervals. Real demo emits fresh stop snapshots,
16 API entries in each run, two gaps and monotonic sample IDs in one capture;
observed checkpoints are1000 ticks apart with an actual startup offset.

Retained failed attempts: sandbox socket denial; slow icount/probe combination
replaced by the launcher's normal QEMU clock; GDB rejected deferred breakpoint
disable while running, so that approach was removed; test's zero-start clock
assumption corrected; gap marker/long numeric axis overlap fixed with its own
row. No physical/terminal qualification. Receipt:
handoff/kodama-capture-rearm-validation.json; local evidence/preview in
/tmp/dbg3k-budget-receipt. Review PR#15; source7ed740c locally validated. Next: check CI, pull this branch
and restart dbg3k; continue twice and use End to follow new activity.

### 2026-11-17: draggable Kodama history scrollbar

User needs fast navigation through rapidly accumulated task/signal observations.
Added a native horizontal scrollbar, pinned above vertically scrolling content,
which pans both lane groups together while names stay fixed. Visible/retained
sample ranges are explicit. Drag the thumb or click its track to page; canvas
Page Up/Down page, Home selects oldest and End/Follow live resumes following.
Browsing anchors an absolute sample window while incoming data continues; if
its selected sample is evicted, clamp to the oldest retained sample. Resizing,
empty/short captures and capture restart update the range/thumb. Normal and
expanded panes both provide the control. UI retention remains512; older JSONL
records are not silently represented as scrollable live history.

Two headless interaction tests exercise actual thumb dragging, track clicks,
task/signal hit alignment after pan, fixed labels, incoming appends/evictions,
frozen inspection, live resumption, expanded paging, resize, pinned controls and
capture reset. No GDB execution commands are sent by browsing. Full suite95 in
22.503s:87 pass/8 opt-in skips; compileall and whitespace pass. Dark/light preview
PNGs visually inspected using explicitly illustrative fixture data, retained in
/tmp/dbg3k-history-scrollbar-preview. GDB collector, firmware and physical hardware
were not rerun/changed for this frontend update. User histories remain untouched.
Receipt: handoff/kodama-scrollbar-validation.json. Review PR#14; source bc7ea50 locally validated. Next: check CI, pull this
dbg3k branch and restart the existing venv application.

### 2026-11-17: validated wiring import and explicit Boolean sensitivities

Owner wants only wiring/dependencies in the diagram, with explicit A AND B
rather than implicit AB and no produced-but-unconsumed or consumed-without-
producer signals. Added pure offline kodama_wiring module/CLI and guide. Bounded
BNF-defined AND/OR/parenthesis parser, separate occurrence/level namespaces,
explicit External endpoints, producer/consumer coverage for every expression atom,
recognized spawn relations and item/edge provenance. Separate edges stay separate;
task body SUPERLOOP/PEND annotations never supply sequencing or Boolean grouping.
AB is an identifier. Legacy subAND[A,B] normalizes to A AND B. Case sensitivity
is preserved; aliases require explicit flags and remain in YAML. Unsupported,
ambiguous, dangling, duplicate and malformed wiring fails before output creation;
existing YAML is never overwritten. No new runtime dependencies/firmware changes.

Actual clean user export kodama-diagram(2).json (5 shapes/12 connectors) correctly
fails with four unmatched b/B,c/C dependency diagnostics. Explicit --alias b=B
--alias c=C passes; local review artifact build/wiring/kodama.yaml retains source
hash/item IDs and independent sensitivities. System PyYAML6.0.3 readback matches
the normalized model, including ambiguous YAML key quoting. Raw export/user
artifacts are not committed or transmitted. Added11 grammar/graph/CLI tests;
full suite93 in18.887s:85 pass/8 opt-in skips. Compileall/whitespace pass. QEMU not
rerun for this offline importer; header generation and post-edit YAML validation
remain explicit later work. Receipt: handoff/kodama-wiring-validation.json.
Review PR#13; pull feature/kodama-wiring-import. Source738fcc5 is locally
validated; remote CI status should be checked before review/merge.


### 2026-11-17: continuous Kodama superloop

User requests a one-second trigger and main that cannot return and finish QEMU.
Added examples/kodama-live: separate C main/startup with real100Hz AN505 SysTick,
reusing the actual Kodama C-main tasks and linker. A run starts immediately then
on100-tick triggers; one pending run retained, excess triggers counted/coalesced,
no overlapping task sets. Main dispatches cooperatively and uses WFE when idle;
IRQ publishes ticks and SEV, never executes coroutine tasks. Clears INIT_READY
before each run; checks frame reclamation at completion. Startup also parks if
main accidentally returns. Existing finite example, kernel, source checkout and
user histories untouched. Exact live.elf launch pairing is in the example guide.

Real QEMU/GDB regression passed1 test in3.760s: source at main, break at third
completion, live/pool0, allocations=frees9, trigger/tick counts, and fourth full
run after detach with QEMU still alive. Starts at ticks0/100/200/300. Sandbox
socket-denied attempt retained; approved rerun passes. Full ordinary suite82 in
18.666s:74 passed/8 opt-in skips. Compileall/whitespace pass. CI can run the new
real test when its existing optional Kodama checkout token is available.
Source hashes, ELF hash, tool versions/oracle: handoff/kodama-live-validation.json.
PR#12 source e52c864 CI44018276909 queued at handoff. Pull the live branch and
use its paired launch commands; owner review remains before merging.
Physical M23, actual terminal and integrated stack/latency unqualified. One second
is emulated time; debugger stops can stretch/coalesce timer delivery. Existing
4096 capture/512 display limits remain; timer probes consume budget. Application
error loop stays alive; original task assertion exits remain fault behavior.


### Readable inspector and explicit copying

Unique live subscription/context bindings now show task name and generation beside
raw addresses; subscription aliases include decoded waits. Unbound/new/ambiguous
pointers remain raw, without stale historical ownership guesses. Copy button and
focused Ctrl+C copy Textual selection or the whole canvas. Clipboard delivery uses
Textual's terminal clipboard mechanism and depends on terminal support. Activity
has its own spaced heading, long calls wrap, and navigation hints are shorter.
This is a modest spacing/readability pass, not a complete visual redesign.
Validation: 81 tests in 19.130s, 74 passed/7 opt-in QEMU skipped; compileall and
whitespace pass. Tests cover live/stale aliases, retained addresses and Copy button.
Actual terminal clipboard, firmware and physical hardware not rerun. Review PR
pending against fix/kodama-level-request-markers. User captures untouched.


### 2026-11-16: retain level API request triangles

User noticed occurrence publication entries had an API triangle, but level
changes did not. The level-request rendering branch replaced the triangle with
the direction arrow. Render `△↑`/`△↓` (or `△?` for unavailable direction) in the
same two-column sample cell. The following waveform remains based on observed
levels, not an assumed successful request. Updated the legend and view guide.

Headless regression covers rising/falling/repeated/unknown requests, unknown
levels, occurrence publication counts, and clicking the second symbol to scrub
to the correct sample. The inspector still reports LOW at a high-request entry
until a later observation reports HIGH. First test attempt incorrectly cleared
the fixture deque without resetting its sequence counter (one failure); fixed
the fixture using the model's reset API. Full suite: 80 tests in 18.939s, 73 pass
and 7 opt-in real-QEMU tests skipped. Compileall and whitespace pass. No collector
changes; real QEMU and physical hardware were not rerun for this display fix.
Existing user capture directories remain untouched and untracked.
Review PR#10; source1a892a3 CI run43981210297 was queued at handoff. To try:
`git fetch origin`, `git switch fix/kodama-level-request-markers`, then
`git pull --ff-only` and restart the existing editable-venv application.

### 2026-11-16: graphical Kodama scheduler view

Owner requests a full-width graphical task/signal timeline, scheduler explanation
and pool ownership, rather than another dense table. Added a pure domain model,
read-only GDB adapter and wide Textual panel/expanded view. Recognizes separate
active/generation/waiting and packed identity/subscription layouts; task lanes
include generation. Reads bounded active subscriptions, maps compiler coroutine
handles to live allocator slots only after token/context validation, and labels
occupied capacity separately from requested bytes/shared MSP stack. Header signal
names are explicitly source mappings, not build attestation. Optional API entry
and validated publication-entry probes supply samples between manual stops;
request markers never claim successful return or physical time. Raw records stay
in dbg3k.trace.v1, separate from derived policy explanations. Auto-detect Kodama
ELF; palette controls preserve existing views and allow a full-width expanded
canvas. Model/UI/real old and current-layout qualification still in progress.

Validation milestone: all79 local checks pass with actual GDB/QEMU/plugin and
both real Kodama identity layouts. Both examples reach their normal PASS and an
explicit final user stop proves all tasks inactive/pool slots free. Independent
MI validates worker seen bits and its mapped pool occupancy. The current dirty
sources were copied/hash-pinned to /tmp before build; original checkout untouched.
Public ARM protocol fixture is mandatory for CI independently of private-repo
access. Header names remain explicitly source mappings. Replay follows matching
ELF/session/capture data without launching GDB. Actual-color preview inspected in
docs/images/kodama-view.png; click/scrub/freeze/follow/expanded/theme flows pass.

Retained prototype failures: reserved Textual visible property (19 errors), a
GDB allow_pending keyword unsupported by installed17.2, wrong mouse-event API,
fixture assumptions about ABI symbols/pool0/char renders/zero-event reevaluation,
and an exit-time polling race. All corrected; full/local targeted reruns pass.
Compileall/whitespace pass. Receipt: handoff/kodama-view-validation.json.
Source28350b3 passes both CI jobs43958923440, including the mandatory public ARM
protocol collector on Ubuntu/GDB15/QEMU8.2. Real old/current Kodama builds passed
locally; private cross-repository CI is explicitly skipped without its read
token. Review PR#9. User fetch/switch feature/kodama-visual-state, reinstall
editable from its venv and restart. The horizontal pane auto-detects known Kodama
ELFs; Ctrl+P provides setup/expanded view. Original histories/worktree untouched.

### 2026-11-16: structured stop observations for Kodama tooling

Final source `e178475` passed both Python and actual ARM/QEMU CI jobs in run
43945295595. Real Kodama CI is explicitly skipped without KODAMA_READ_TOKEN;
its actual pinned ELF passed locally. All68 local tests, compileall and whitespace
checks pass. Review PR#8; pull feature/structured-observations and use Ctrl+P >
Observation capture or repeated --observe flags. Schema/demo/receipt links below.

Extended the existing dbg3k.trace.v1 journal rather than adding a parallel
exporter. Opt-in --observe selectors and Ctrl+P > Observation capture select
expressions/start/stop collection. A generic isolated GDB Python helper exports
typed ordered fields/arrays, exact expressions, GDB raw summaries, decimal-string
integers, hex pointers and field/expression errors. Pointers are not implicitly
followed; explicitly selected dereferences guard null and preserve read failures.
Calls/assignments/arithmetic are excluded; inferior calls are disabled during
capture. Node/child/depth/raw/value-size/record-size/cooperative time limits are
recorded. Missing Python produces unavailable records. No Kodama semantics or
target firmware changes were introduced.

Session provenance adds ELF SHA256/build ID and dbg3k/GDB versions/architecture.
Each actual MI stop advances the stop index; refreshes no longer invent stops.
Capture request identity and stop/thread checks prevent late results from being
assigned to newer stops. Existing frames/locals/args/globals also reject stale
replies. Attach has an explicit initial stop even when MI emits no stopped event.

Local Kodama checkout contains uncommitted layout changes; it was left untouched.
Built a clean git-archive of requested branch revision2679a470 in /tmp. Actual
AN505 capture observed worker slot1 active1/generation1/waiting1 and seen0->1 at
kodama_signal then kodama_signal_and_pend; captured tasks/running/levels/ticks/
g_cmd plus explicit invalid-expression errors. Independent MI queries agree on
seen and task-array type. Generic ARM tests cover UINT64_MAX, nested fields,
changing scalar, null vs stale pointers, guarded failures and truncated arrays.
The 66-test full local suite passed with real GDB/QEMU/plugin enabled; an added
missing-collector test passes too. Final full rerun passes all67 checks; compileall/whitespace pass. PR#8 open. Initial CI Python passed; QEMU job could not access Kodama with the default repository token. Cross-repository qualification is now conditional on KODAMA_READ_TOKEN; generic ARM checks always run. Second CI exposed a missing math dependency in GDB helper imports and a generic flash fixture incorrectly using the SRAM loader. Collector imports were minimized; generic fixture now uses the proven -kernel boot path while Kodama retains its explicit-MSP SRAM loader. Focused local real-ARM rerun passes; Third CI confirmed helper loads, but PC0x14 exposed a GNU build-ID note ahead of the reset vectors on Ubuntu's linker. Fixture now explicitly places the note after .text and verifies vector base/MSP/reset entry; local focused capture passes, CI pending.

Retained issues during work: sandbox denied localhost socket creation (approved
rerun passed); first regression run exposed a synthetic catalog without build_id
(getattr fallback fixed); one documentation patch context mismatch was corrected.

Final local suite passes all68 checks, including capture replies drained after a
step is queued but before GDB reports running. Those remain valid at the issuing
stop; truly stale replies still fail explicitly. Both CI jobs passed checkpoint
fe1c5c4 in run43944773286 (Ubuntu QEMU8.2/GDB15; real Kodama CI explicitly skipped
without cross-repository token, independently qualified locally). Final ordering
checkpoint CI pending. User histories and dirty Kodama work remain untouched.

Schema/query/example/demo: docs/OBSERVATIONS.md. No physical hardware, continuous
event reconstruction, arbitrary C++ expression decoder or Kodama-specific pane
is claimed. Machine receipt: handoff/observations-validation.json.

### 2026-11-16: energy ranking reliability and JSONL updates

User reports unreliable energy ranking and suggests JSONL as the update source.
Read-only inspection of the local history confirmed a missing configuration in
the latest session: recorded instruction profiles were present, but no energy
model. A preceding matching-build session contained the explicit assumptions
48 µA/MHz, 1 MIPS/MHz, 1.8 V. The previous UI cleared its table when assumptions
were missing, and also cleared valid data after transient profile reads failed.

Live snapshots now validate through a separate collector, append cumulative
profile events, and drive rankings via an incremental current-session JSONL
reader. Startup restores only explicit recorded assumptions bound to the same
ELF hash; CLI and Model… changes override recovery/replay. The energy pane has a
Model button, keeps measured rows visible without a model, and labels numeric
energy unavailable until assumptions exist. Temporary missing/partial profile
files and failed reads retain last validated data with provenance/status. Wrong
build/counter data is rejected. Recording failure closes its writer and falls
back to validated live data.

Added --profile-history/--profile-session for explicitly following recorded or
growing profile logs. Reader buffers partial UTF-8/JSON, skips malformed lines,
detects rotation/truncation (including same-inode rewrites), and consumes bounded
appended batches. Session/build/run/sequence checks and cumulative replacement
avoid mixed sessions and double counts. Replay does not silently borrow another
session's assumptions. Legacy profiles without entry hits show unavailable call
counts. Session/model events now carry build hashes and source provenance.
Trace reopening/export also tolerates interrupted UTF-8 fragments; failed closes
release the file handle.

Read-only replay of the earlier real session populated six rows from 1152
recorded dispatches and restored its explicit model, without any plugin snapshot
or debugger connection in the harness. Estimated run energy under that model was
99532.8 pJ (a calculation, not a physical measurement). New tests cover growing
files, partial lines, model restoration/CLI precedence, session changes, invalid
hash/counters, legacy entry data, transient IO and simulated disk-full fallback.
An old test's expectation that missing models erase all rows was updated for the
new behavior; a headless test exited before its UI settled and was corrected to
await the pilot. All 61 checks pass including actual GDB/QEMU; compileall and
whitespace checks pass. Results are recorded in handoff/energy-history-validation.json.

PR #7 checkpoint `bab868c` passed both Python and real QEMU/GDB CI jobs in run
43917749694. Next: pull the fix branch and restart using the existing
live launch command. Recorded assumptions restore automatically when build-bound
evidence exists. Optional --profile-history follows saved sessions with explicit
provenance. User terminal/latest Kodama and long-duration catch-up remain pending.

### 2026-11-16: graphical resource projections

Added three palette-selectable graphical panes while retaining all textual
resource views. Stack map draws normal unwound-SP gaps vertically with exact
address labels, approximate byte-scaled heights, selected frame marker and
unknown boundaries. GDB now reads at most 256 raw bytes from the sampled normal
stack slice while halted; graphical hex contents are observed bytes, not guesses
about local-variable ownership. No free stack extent/oldest allocation/coroutine
storage is invented. Stale/unsupported memory stays unavailable.

Whole-run instruction and energy panes provide ranked bars (top eight plus
current function), scrollable full DataTables, selectors and clickable headings,
ascending/descending order and stable cursor selection across updates. Include
dispatch count, entry-hit Calls† proxy, ELF bytes, instructions per entry/byte,
all-code share/cumulative share and current function rank. Entry counters derive
from existing per-PC histograms at normalized ELF body starts, with aliases folded
and reset by QEMU UUID; no plugin binary/schema change. Tail entries, entry loops,
reset/faults and mid-body jumps prevent labeling these exact invocation counts.
Energy ranking uses existing user assumptions, includes attributed/unattributed
estimated run energy, and states that a common factor preserves instruction
ordering. Average power remains unavailable without target duration.

Validation: all 53 tests pass with actual QEMU/plugin/GDB enabled. Real fixture
has two observed entries and 26 dispatches for the counted loop. New GDB raw
memory snapshot matches an independent MI memory read exactly. Headless tests
exercise header clicks, sort selector, reverse order, current rank, cursor
retention, cumulative 95% with 5% unknown, energy unavailable states, address
ordering, bytes and stale-sample rejection. Preview PNGs/SVGs were generated and
visually inspected in /tmp/dbg3k-graph-previews using explicitly marked synthetic
fixtures; they are not target evidence. Compileall and whitespace checks pass.
No local test failures. Source checkpoint `59be199` passed both CI jobs in run
43834476319, including actual QEMU8.2/GDB. See compact handoff/graphical-validation.json.

Review: PR #6 is open against feature/stack-instruction-energy. Next: check CI,
restart dbg3k on the graphical branch,
enable the graphical views in Ctrl+P, review narrow-terminal ergonomics and test
the latest Kodama firmware independently.

### 2026-11-16: stack, code/instruction and energy panes

User chose a QEMU plugin as the instruction-count source. Added independently
selectable Stack, Code & Instructions, and Energy panes following the selected
active tree frame. Stack snapshots are versioned GDB Python messages containing
available CPU/stack registers and unwound frames. Stop/thread freshness is
checked. Own and inclusive active bytes are explicitly SP-delta estimates;
sampled peaks aggregate by thread/body. Oldest/inline/exception boundaries and
unavailable registers remain unknown. Frame count/recursion is separate from
bytes; Kodama coroutine frame storage is not attributed as task stacks.

`plugins/counts.c` counts per-instruction execution callbacks on single-vCPU QEMU
system emulation, not translations. Atomic cumulative snapshots every ~100 ms
carry run UUID, ELF SHA256, sequence, completion and overflow. PC counters are
reused across translations, capped at 262144; overflow counts remain unknown.
`resources.py` reads ELF executable STT_FUNC extents with pyelftools, folds exact
aliases, and preserves ambiguous/unmapped PC counts. No inclusive/invocation or
cycle claim. QEMU dispatch callbacks run before completion, so counts may include
faulting instructions. Users restart QEMU with the collector and provide the
snapshot path to `--instruction-profile`. Snapshot boundaries are not GDB stops.

Energy model accepts explicit finite positive µA/MHz, MIPS/MHz and voltage through
the palette or CLI. Their ratio is pC/instruction; multiplying by count and voltage
gives estimated pJ. Power stays unavailable without target duration; peripheral,
idle, leakage and memory effects are excluded. No chip defaults were fabricated.
New trace kinds preserve the original envelope schema/sequence. `RESOURCES.md`
contains the complete build/launch instructions and measurement contract.

Validation: 48 tests pass with both real QEMU flags enabled. Assembly oracle:
10-byte counted body, exactly 13 dispatches/call (26 for two calls); an uncalled
4-byte body has zero dispatches. Mounted Textual/GDB/QEMU validates live stack,
ELF mapping, plugin ingestion and retained returns. `make -C plugins` builds with
warnings as errors using installed API7/QEMU11.1 headers; CI also builds API1 for
Ubuntu24.04's QEMU8.2. Compileall and whitespace checks pass. See compact
handoff/resource-validation.json. PyPI DNS was sandbox-blocked; approved venv
installation of pyelftools0.33 succeeded. The matching QEMU header was already
installed; no downloaded header was needed locally. Physical silicon, interrupt
stack precision, latest Kodama profiling and terminal ergonomics remain pending.

CI source `bc803db` passed both Python and actual QEMU8.2/API1 tests in run
43828640310; local QEMU11.1/API7 also passes. Latest checkpoint CI remains a
separate commit check. Next: launch QEMU with the collector following RESOURCES.md,
choose the resource panes and select active tree frames. Enter actual chip
assumptions in Energy model; compare unknown counts and sampled stack peaks.

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
user retest. Updates stay on feature/selectable-debugger-views. PR #2 was already
merged by the owner; follow-up changes need a new review PR. An added non-view
arrow test initially used Ctrl+A as select-all (Textual uses it as Home); corrected
the setup to an exact Theme query, and verified normal Left search editing.
Follow-up review is PR #4 against main. Main's tree was verified identical to
the previous feature tip before merging its ancestry into the current branch;
existing users can still pull --ff-only.

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

**Not implemented:** Global watch selection/pinning, function navigator, inclusive/invocation instruction attribution, proven stack bounds, measured energy/power, numeric stepping prefixes and robust invocation/task identities. First exclusive dispatch profiles, sampled SP estimates/peaks and explicit-assumption energy estimates now exist; see RESOURCES.md.

**Do not regress:** Visible startup and handler source; separation of navigation and execution; accurate labels distinguishing measurement from estimate; GitHub + `CONTINUE.md` + JSON handoff continuity.

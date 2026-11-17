# Miro wiring to reviewed YAML

The diagram describes declared wiring and dependencies. Task code chooses when
to pend, publish, yield, complete a job, sleep or return. This importer generates
neither task control flow nor firmware. It does not edit Miro or transmit files.

## Import

From an installed checkout (or with PYTHONPATH=src):

```sh
.venv/bin/python -m dbg3k.kodama_wiring ~/Downloads/kodama-diagram.json \
  --output build/application.yaml
```

The output's parent directory must exist. Without --output the validated YAML
goes to stdout. Existing output files are never overwritten. Invalid wiring
returns1, prints diagnostics on stderr and produces no YAML. Raw JSON remains
untouched. The importer uses the standard library; a YAML package is not needed.

Names are case sensitive. For the reviewed diagram whose producer labels use
lowercase b/c and consumer labels uppercase B/C, explicitly reconcile them:

```sh
.venv/bin/python -m dbg3k.kodama_wiring 'board.json' \
  --alias b=B --alias c=C --output build/application.yaml
```

Aliases are recorded in the YAML and apply across both namespaces. Fixing the
labels in Miro instead removes the need for aliases. They are exact identifier
mappings, not substring replacements. Chains/conflicting duplicate flags fail.

## Diagram notation

Only the first line of a task shape identifies it. Remaining annotations such
as SUPERLOOP or PEND[AB,C] are never interpreted as behavior or dependencies.

| Shape/edge | Meaning |
|---|---|
| Task::consume() | Declared task named consume |
| External::timer | Explicit external endpoint, such as application IRQ port |
| Kodama::events | Occurrence namespace; not a queue or persistent state |
| Kodama::levels | Persistent-level namespace |
| Task/external → events, caption event::A or A | Declared publication of A |
| Task/external → levels, caption level::READY or READY | Declared update of READY; no raise/lower sequence inferred |
| events → task/external, caption SUB[A AND B] | Occurrence sensitivity to A and B |
| levels → task/external, caption SUB[READY] | Level sensitivity to READY |
| task → task, caption KODAMA::SPAWN | Declared spawn relationship, without ordering |

Connectors need recognized attached endpoints, exactly one arrowhead and exactly
one semantic caption. Reverse arrowheads are interpreted by their direction.
Unsupported shapes, cards, unlabeled/bidirectional lines and unknown relations
are errors. Text/frame items may serve as annotations, but cannot be endpoints
of semantic edges. Task/external names must be unique. Self-spawn is unsupported.

## Sensitivity grammar

BNF defines the expression syntax; YAML stores expressions as readable strings.

```bnf
<expression> ::= <term> | <expression> "OR" <term>
<term>       ::= <factor> | <term> "AND" <factor>
<factor>     ::= <identifier> | "(" <expression> ")"
```

An identifier matches [A-Za-z_][A-Za-z_0-9]*, with a64-character limit.
AND and OR are case-insensitive keywords, emitted uppercase. AND takes precedence
over OR; parentheses change grouping. NOT is reserved and unsupported. No eval,
implicit concatenation, comma operator, negation or arbitrary code is accepted.
**AB is one identifier**, not shorthand for A AND B. The explicit legacy caption
subAND[A,B] remains accepted and is emitted as A AND B.

Examples:

```yaml
sensitivities:
  - kind: occurrence
    expression: "(A OR B) AND C"
  - kind: level
    expression: "INIT_COMPLETE"
```

Occurrence AND means observations accumulated in the same armed wait, in either
order. Level AND means currently overlapping levels. OR describes alternatives
within one declared sensitivity. Separate edges remain separate sensitivities;
the importer never ORs them together or infers an ordered sequence of pends.
One edge belongs to one namespace; mixed occurrence/level conditions are outside
this slice. Later header lowering must respect configured alternative/mask limits.

## Dependency checks

Every occurrence/level referenced by a sensitivity must have at least one
declared producer. Every produced occurrence/updated level must have at least
one declared consumer. Every atom in an AND or OR expression is checked, including
all OR branches. An occurrence cannot satisfy a level dependency of the same
spelling, or vice versa. Multiple producers and multiple consumers are permitted.
External producers/sinks must be explicit External nodes with real labeled edges;
there is no implicit exemption for an unconnected output or missing input.

Checks also reject duplicate item IDs, duplicate entity names, duplicate
relationships, dangling endpoints, invalid expressions and namespace overflow.
Bounds:2 MiB input,2048 items,128 task/external nodes,32 signals per namespace,
4096 characters/item text,2048 characters/expression,256 tokens and32 nesting
levels. These import bounds do not configure firmware capacities.

This validates the **declared graph**. It does not prove the implementation
publishes an event, arms a subscription, avoids missed occurrences, supplies a
buffer, makes progress or is deadlock-free. Feedback loops such as request/ACK
are valid and are not rejected merely for forming a graph cycle. No application
or target code runs during import.

## YAML and provenance

Schema kodama.wiring/v1 stores source format/export timestamp/SHA256, explicit
aliases, occurrence/level names, task/external endpoints, spawn/publication/level
relationships and each independent sensitivity's kind/expression. Source IDs
identify original task shapes and sensitivity connectors for review. It is an
editable application specification, not a dump of board coordinates/styles.
Names are sorted for deterministic review; sorting does not assign bit numbers.
No bit assignment, runtime identity, priority or task lifetime is invented.

The writer emits the plain YAML mapping/list/scalar subset, quoting strings and
ambiguous YAML keys. Repeated imports require a new destination, allowing manual
changes to be reviewed rather than silently overwritten. This first slice has
no YAML reader/header generator: validation after manual YAML edits must also
be implemented before that later generation stage can rely on those edits.

## Validation

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_kodama_wiring.py -v
```

Tests cover grammar/precedence, limits, explicit names/aliases, every dependency
branch, unused publications, namespace separation, external producers, reverse
arrows, malformed/duplicate/dangling relations, annotation independence and
validate-before-write/no-overwrite behavior. No QEMU is required for this offline
importer. The user export is intentionally kept outside Git; local generated
review copies belong under ignored build/.

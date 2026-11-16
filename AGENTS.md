# Agent contract

1. Read `handoff/CONTINUE.json`, `README.md`, and `docs/DESIGN.md` at start.
2. `tumblewhead/dbg3k` GitHub repository is canonical. Work on a named branch, open a PR, keep main protected from unreviewed experiments.
3. Update the handoff JSON at each significant milestone. Machine-to-machine notes must remain compact machine-readable JSON.
4. Tests: `PYTHONPATH=src python -m unittest discover -s tests -v` and `python -m compileall -q src tests`; record failures.
5. Do not pretend QEMU guest instruction counts are silicon cycles, or guessed stack sizes are verified. Annotate observed vs estimated vs unavailable.
6. Preserve separation of MI transport, scope model, and Textual frontend.
7. Target AN505 Secure flash-like memory `0x10000000` and Secure RAM `0x38000000` for demo, as verified in original user environment.
8. Reconcile GDB frame reuse, lexical shadowing, recursion and task identity before labeling histories exact invocation traces.
9. Serialize debugger commands, honor running/stopped, stop queued stepping on unexpected breaks and faults.
10. Favor working code/tests and a reproducible run receipt over speculative future features.

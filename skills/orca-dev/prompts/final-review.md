# Final review of the branch

Repository: `<REPO>`. Spec: `<SPEC>`. Plan: `<PLAN>`. Read-only: do not edit any file, do not commit.

Run this to see the whole change:

<DIFF>

For every acceptance criterion of the spec decide whether the branch closes it: find the code and the test, and run the test. Then check that the phases fit together: no broken integration, no leftover duplicate or dead code between phases.

Report through the Orca worker preamble: worker_done subject `PASS` when every criterion is closed and there is no `blocking` integration problem, otherwise `FINDINGS`. Body: a table with one row per criterion, `| AC{n} | closed | {test or file} |` or `| AC{n} | not closed | {why} |`; then integration problems, one per line, `I{n} blocking|minor {file}:{line} — {problem} → {fix}`.

Outcome: `--outcome failed` only with a `BLOCKED` subject, when you could not do the job; every other report, `FINDINGS` and `not fixed` lines included, uses `--outcome succeeded`.

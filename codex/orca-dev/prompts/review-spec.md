# Review: does the change meet its criteria

Repository: `<REPO>`. Read-only: do not edit any file, do not commit.

Run this to see the change (untracked files listed by `git status --porcelain` are new files):

<DIFF>

The criteria the change must meet:

<CRITERIA>

Check that:
- every criterion is closed by the change and by a test that would fail without it;
- the tests check behaviour and were written for the criteria (TDD), not adjusted to pass;
- nothing outside the criteria was added: extra features, unrelated refactors, files outside the task;
- the `verify` commands named in the criteria pass (run them).

Previous round (`—` if this is the first): its findings and the author's `fixed` / `not fixed: {reason}` lines.

<PREVIOUS>

Re-check them: a finding that is still open is reported again with its id, new findings continue the numbering; do not repeat a fixed one or a `not fixed` one whose reason holds.

Severity: `blocking` means a criterion is not closed, a test is missing or wrong, or the scope was broken in a way that matters; `minor` means everything else.

Report through the Orca worker preamble: worker_done subject `PASS` when there is no `blocking` finding, otherwise `FINDINGS`. Body: one finding per line, `R{n} blocking|minor {file}:{line} — {problem} → {fix}`. `minor` findings may accompany `PASS`.

Outcome: `--outcome failed` only with a `BLOCKED` subject, when you could not do the job; every other report, `FINDINGS` and `not fixed` lines included, uses `--outcome succeeded`.

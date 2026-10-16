# Review: code quality

Repository: `<REPO>`. Read-only: do not edit any file, do not commit.

The task behind the change:

<TASK>

Run this to see the change (untracked files listed by `git status --porcelain` are new files):

<DIFF>

Look for bugs, unhandled edge cases and errors, races, security problems, broken behaviour on Windows or Linux, dead code, unclear names, and missing or weak tests. Read the surrounding code, but judge the change, not the old code.

Severity: `blocking` means a bug, data loss, a security hole or risky logic without a test; `minor` means readability, naming and style.

Report through the Orca worker preamble: worker_done subject `PASS` when there is no `blocking` finding, otherwise `FINDINGS`. Body: one finding per line, `Q{n} blocking|minor {file}:{line} — {problem} → {fix}`. `minor` findings may accompany `PASS`.

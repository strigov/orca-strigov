# Spec review

Repository: `<REPO>`. Review the spec `<SPEC>` written for this task:

<TASK>

Read-only: do not edit any file, do not commit.

Check that:
- the spec solves the task and nothing else, and the scope boundaries are explicit;
- every `AC` has the form «КОГДА ..., ТОГДА ...» and is observable through a command, a test or a file;
- the criteria together cover the task;
- the design names real paths, commands and APIs of this repository (verify them) and contradicts neither the code nor itself.

Previous round (`—` if this is the first): its findings and the author's `fixed` / `not fixed: {reason}` lines.

<PREVIOUS>

Re-check them: a finding that is still open is reported again with its id, new findings continue the numbering; do not repeat a fixed one or a `not fixed` one whose reason holds.

Severity: `blocking` means the spec is wrong, incomplete or cannot be implemented as written; `minor` means wording, clarity or a small gap that does not change the work.

Report through the Orca worker preamble: worker_done subject `PASS` when there is no `blocking` finding, otherwise `FINDINGS`. Body: one finding per line, `S{n} blocking|minor {section} — {problem} → {fix}`. `minor` findings may accompany `PASS`.

Outcome: `--outcome failed` only with a `BLOCKED` subject, when you could not do the job; every other report, `FINDINGS` and `not fixed` lines included, uses `--outcome succeeded`.

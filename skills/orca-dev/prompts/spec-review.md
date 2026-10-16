# Spec review

Repository: `<REPO>`. Review the spec `<SPEC>` written for this task:

<TASK>

Read-only: do not edit any file, do not commit.

Check that:
- the spec solves the task and nothing else, and the scope boundaries are explicit;
- every `AC` has the form «КОГДА ..., ТОГДА ...» and is observable through a command, a test or a file;
- the criteria together cover the task;
- the design names real paths, commands and APIs of this repository (verify them) and contradicts neither the code nor itself.

Severity: `blocking` means the spec is wrong, incomplete or cannot be implemented as written; `minor` means wording, clarity or a small gap that does not change the work.

Report through the Orca worker preamble: worker_done subject `PASS` when there is no `blocking` finding, otherwise `FINDINGS`. Body: one finding per line, `S{n} blocking|minor {section} — {problem} → {fix}`. `minor` findings may accompany `PASS`. Do not repeat findings that were fixed in an earlier round.

# Plan review

Repository: `<REPO>`. Review the plan `<PLAN>` against the spec `<SPEC>`.

Read-only: do not edit any file, do not commit.

Check that:
- the frontmatter has `spec`, `orca_run`, `status` and, for every phase, `id`, `title`, `risk`, `area`, `hard`, `covers`, `verify` and `status: pending`;
- every `AC` of the spec is in the `covers` of some phase, and no phase lacks `covers`;
- every `verify` command exists in this repository and proves its phase;
- each phase body says what to do, which files and which tests come first (TDD);
- the phases are ordered so that each builds on the previous ones, and nothing outside the spec is planned;
- `hard: true` and `risk: risky` are justified.

Previous round (`—` if this is the first): its findings and the author's `fixed` / `not fixed: {reason}` lines.

<PREVIOUS>

Re-check them: a finding that is still open is reported again with its id, new findings continue the numbering; do not repeat a fixed one or a `not fixed` one whose reason holds.

Severity: `blocking` means the plan cannot be executed as written or misses a criterion; `minor` means clarity or a small gap.

Report through the Orca worker preamble: worker_done subject `PASS` when there is no `blocking` finding, otherwise `FINDINGS`. Body: one finding per line, `P{n} blocking|minor {phase} — {problem} → {fix}`. `minor` findings may accompany `PASS`.

Outcome: `--outcome failed` only with a `BLOCKED` subject, when you could not do the job; every other report, `FINDINGS` and `not fixed` lines included, uses `--outcome succeeded`.

# Plan writer

Write the implementation plan `<PLAN>` for the approved spec `<SPEC>` in the repository `<REPO>`. Write only this file: no code, no other files, no commits.

Read the spec and the code it touches; verify every path, command and API you name.

The file starts with this YAML frontmatter (fill the values, keep the keys and their order):

```yaml
---
spec: docs/specs/{date}-{slug}.md   # repo-relative path of the spec
orca_run:                           # leave empty: the coordinator fills it
status: active
phases:
  - id: F1
    title: {short title}
    risk: none        # none | risky (security, data, migrations, concurrency)
    area: backend     # backend | frontend
    hard: false       # true only if the phase is obviously hard
    covers: [AC1, AC2]
    verify:
      - {command that exits 0 when the phase is done}
    status: pending
---
```

Do not add `implementer`: the coordinator sets it.

Body: one section per phase, headed like `## F1: {title}`, with what to do, which files, which tests to write first (TDD: the test for each criterion before the code) and which criteria it closes.

Rules: every acceptance criterion of the spec is covered by at least one phase; no phase without `covers`; usually 1 to 5 phases, each small enough for one implementer run; `verify` holds concrete commands of this repository.

When done, report through the Orca worker preamble: worker_done subject `DONE`, body: number of phases, their titles, and the criteria each covers. If the spec cannot be planned as written, subject `BLOCKED` and the reason.

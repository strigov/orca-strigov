# Path B consolidation: one launch path, one model source, owned terminals

Standalone maintenance plan for this repository (AGENTS.md "repository
maintenance exception"). It is not a C6 pipeline plan: no `orca_run`, no
`protocol_version` frontmatter, no Orca dispatch of phases. Design:
`docs/architecture-runtime.md`. Incident record:
`docs/tasks/2026-09-26-claude-model-evidence.md`.

Created: 2026-09-28. Base: `main` at the commit that adds this file.
Branch for the work: `feat/path-b-consolidation`. One commit per phase, subject
`<type>(<scope>): <what>`, body with the why, trailer
`Co-Authored-By: <model> <noreply@anthropic.com>`. No push.

## Goal

The coordinator launches every worker one way, C6 verifies a worker's model from
one admissible source per agent, terminals the coordinator created are closed by
a helper instead of a prose rule, and the coordinator instruction set states each
rule once. The next live run should hit no C6 false positive that this plan's
fixtures could have caught.

## Acceptance criteria

1. `skills/orca-dev/` contains no launch instruction other than
   `terminal create` + `wait-agent-ready` + `dispatch --inject`; `grep -rn "Path A\|worker-start\|origin_start" skills/` returns only the historical note in `orca-recipes.md` that says why (one paragraph).
2. `bind-dispatch` accepts `observation` plus optional `model_evidence` only; the source table in `runtime-contracts.md` C6 matches the code; every row has a positive and a negative test on a sanitized real artifact in `tests/fixtures/orca/`.
3. `bin/close-worker-terminal` and `bin/close-worker-terminal.ps1` implement the closing rule; `orca-recipes.md` §5 refers to the helper and contains no multi-bullet closing rule.
4. `protocol_state.py` and `protocol-state.ps1` shrink: no `reused_model`, no `launched_receipt` as a model source, no duplicate `frozen`, `barrier`/`covered` agree on script gates, closure `historical` conditions are identical for CHECK and code closures. Line count of each file is reported before and after.
5. The always-on coordinator set (`SKILL.md`, `coordinator-core.md`, `roles.md`, `skills/orchestration/SKILL.md`, `role-contract.md`, `coordinator-session.md`) is under 7k words (`wc -w`), and every rule in the table of `docs/architecture-runtime.md` "Documentation layout" appears with numbers or full wording in its canonical file only.
6. `python3 -B -m unittest discover -s tests` passes on macOS with Python 3.13 first in `PATH`; the same suite passes on native Windows (PowerShell 5.1 and pwsh 7) and both results are recorded in `docs/runtime-platforms.md` with the exact commands. A Windows result is required before merge, not a substitute for the macOS one.
7. `docs/smoke-runs.md` records one live run on the new path (any trivial task, any agent) with the receipts it produced, or states explicitly that it was not run and why.

## Non-goals / deferred

- Sending the Orca upstream report (`docs/upstream-orca-claude-prompt-race.md`) — user decision.
- Bumping `plugin.json` / `.claude-plugin` / `.codex-plugin` versions — user decision after criterion 7.
- Splitting `protocol_state.py` into modules (doubles the PowerShell parity surface).
- Any change to C4 (`run-check`, `verification.py`) or C5 (`review-package`) contracts.
- Antigravity SQLite store as a model source.

## Global Constraints

- AGENTS.md applies: preserve the user's working changes, no push, no global CLI
  configuration changes, no production resources, no fabricated PASS. POSIX and
  native Windows behaviour change together with shared positive/negative fixtures.
- C6 is never weakened to accept a model from the coordinator, saved argv,
  comments or messages.
- Immutable artifacts: never edit files under `docs/reviews/`, `docs/plans/finished/`,
  `docs/spikes/`, or existing smoke-run rows; append instead.
- Python 3.13+ on macOS, 3.9+ on Linux, PowerShell 5.1 and pwsh 7 on Windows.
- Real artifacts for fixtures come from the Bureau run directory named in the
  incident record, copied and sanitized (no absolute user paths, no tokens, no
  capability ids). If that directory is unavailable, build the fixtures from the
  receipts in `docs/smoke-runs.md` 2026-09-26 and say so in the phase commit.

## Files

Ф1 Launch: Modify `skills/orca-dev/orca-recipes.md` (§2, §5 reuse line, §6 retry
line, §8 cheat sheet, §9 Windows), `bin/wait-agent-ready`, `bin/wait-agent-ready.ps1`,
`skills/orca-dev/coordinator-core.md` (checklist item 6, red flags),
`skills/orca-dev/roles.md` ("No worker multi-agent fanout" paragraph, retention
column). Test `tests/test_bootstrap_recovery.py` or a new `tests/test_wait_agent_ready.py`
for the Claude composer marker.

Ф2 Model sources: Modify `bin/lib/protocol_state.py`, `bin/protocol-state.ps1`,
`skills/orca-dev/runtime-contracts.md` (C6 actual-model section, action table),
`skills/orca-dev/roles.md` (Families paragraph). Create `tests/fixtures/orca/`
(README.md naming each file's origin and sanitization) and tests in
`tests/test_protocol_state.py`, `tests/test_closure.py`, `tests/support.py`.

Ф3 Terminals: Create `bin/close-worker-terminal`, `bin/close-worker-terminal.ps1`,
`tests/test_close_terminal.py`; extend `tests/fixtures/orca_wait_cli.py` (the fake
Orca CLI) with `terminal show`, `terminal close`, `worker-list` shapes. Modify
`orca-recipes.md` §5, `coordinator-phase.md`, `coordinator-planning.md`,
`coordinator-finish.md` (retention/closing sentences), `bin/build-release.py` and
`docs/install-*.md` if helper lists are enumerated there, `tests/test_release_archive.py`.

Ф4 Documentation: Modify `skills/orca-dev/SKILL.md`, `coordinator-core.md`,
`coordinator-start.md`, `coordinator-phase.md`, `coordinator-planning.md`,
`coordinator-finish.md`, `coordinator-session.md`, `orca-recipes.md`,
`runtime-contracts.md`, `roles.md`, `skills/orchestration/SKILL.md`, `AGENTS.md`,
`README.md`, `README.ru.md`, `docs/architecture-runtime.md` (status line).
Test `tests/test_plugin.py` (skill validity) and a word-count check in the phase report.

Ф5 Validation: Modify `docs/runtime-platforms.md`, `docs/smoke-runs.md`.

## Contracts

C1 `bind-dispatch` input: `{observation: <worker-show result>, model_evidence?: {kind, path, sha256, ...}}`. No `start`, no `origin_start`. Unknown keys are rejected with "unknown model source".

C2 Model source table (code and `runtime-contracts.md` must match):
`codex` → `projection.provider.model`; `claude` → `claude-transcript`;
`antigravity` → `antigravity-log`. Evidence with a reported `provider.model` must
agree. Missing source → UNVERIFIABLE (exit 2); disagreeing sources → INVALID (exit 1).

C3 Preamble binding: one constant block `PREAMBLE = {sentence, task_pattern, dispatch_pattern, from_pattern}` in both backends; a fixture `tests/fixtures/orca/preamble.txt` copied from a real Dispatch; mismatch → UNVERIFIABLE with reason `preamble: expected "<sentence>"`.

C4 `close-worker-terminal <handle> <workspace> --after-accept <dispatch_id> [--json]`:
exit 0 and a JSON receipt `{handle, incarnationId, create_receipt, dispatches: [...], closed: true}`
on success; exit 1 with `{closed: false, reason}` when any condition fails; exit 2 usage;
exit 3 when `orca` cannot be reached. Never closes on exit ≠ 0.

C5 `wait-agent-ready <h> claude`: ready only when the last 25 screen lines contain
`Claude Code` and the composer prompt `❯`, followed by `tui-idle`.

C6 Documentation canon: the table in `docs/architecture-runtime.md`. A rule's
numbers (caps, versions, timeouts) appear in its canonical file only.

## Test strategy

- Ф1: unit test of the Claude marker on captured screen text (banner without composer → not ready; banner with composer → ready), both backends through the existing fake `orca terminal read` in `tests/fixtures/orca_wait_cli.py`.
- Ф2: for each source-table row a positive test on the real fixture and negatives: missing source, evidence for a reported model that disagrees, evidence kind not matching provider, preamble mismatch, two models after the preamble, cwd outside the worktree. Regression tests for `barrier`/`covered` agreement and closure `historical` symmetry. Existing tests that construct `start`/`origin_start` are rewritten, not deleted silently; the commit message lists them.
- Ф3: helper tests against the fake CLI: success; wrong incarnation; pending Dispatch; no create receipt; `orca` unreachable. Same fixtures for `.ps1` on Windows.
- Ф4: `tests/test_plugin.py` skill validation; `wc -w` on the always-on set in the phase report; `grep` from criterion 1.
- Ф5: full suite on macOS and Windows; one live smoke run.
- Not repeated: C4/C5 runner suites beyond the full-suite run; no repeated full suite without a named regression hypothesis (AGENTS.md).

## Risks / unknowns / assumptions

- Resume of runs bound before Ф2 may read `start`/`origin_start` from accepted history. Check `validate(... action="resume")` and `report_history` handling first; if needed keep read-only acceptance of recorded history and say so in `runtime-contracts.md`.
- The Bureau artifacts live on an external volume that may be unmounted; the fallback fixture source is stated in Global Constraints.
- The Orca fake CLI in tests may lack `terminal show` / `terminal close`; extending it is part of Ф3.
- `wait-agent-ready` composer detection depends on Claude Code drawing `❯`; verify on the installed version and record it in the test's docstring.
- Word budget for the always-on set may need `coordinator-core.md` split into procedure (loaded) and rationale (linked); prefer deleting restatements over moving text.

## Phases

## Ф1: One launch path

**Files in this phase:** see Files Ф1.
**Interfaces:** Consumes nothing; Produces C5.

Rewrite `orca-recipes.md` §2 as a single procedure: create, wait, inject; per-agent
argv table stays; the Path A section becomes one historical paragraph (why it was
dropped, with the smoke-run numbers). Reuse is `dispatch --inject`; retry is a
fresh terminal. Add the "paste confirmation" recipe (§2) and the sentence
"Begin immediately; do not ask whether to execute this task." to the worker
boundary prefix in §1 (every template inherits it). Update the cheat sheet, the
Windows section, `coordinator-core.md` checklist item 6 and red flags, and the
`roles.md` fanout paragraph so none mention `worker-start`. Extend
`wait-agent-ready` (both backends) with the composer marker for Claude.
Check: unit tests for the marker; `grep -rn "worker-start" skills/` shows only the
historical paragraph. Evidence: test output and the grep in the commit body.

## Ф2: One model source per agent

**Files in this phase:** see Files Ф2.
**Interfaces:** Consumes Ф1 (no Path A in recipes); Produces C1, C2, C3.

Replace `actual_model` with a table lookup; delete `reused_model`, `launched_receipt`
as a source, and the `start`/`origin_start` handling; centralize the preamble
constants; make text mismatches UNVERIFIABLE with named reasons; dedupe `frozen`;
fix `barrier`/`covered` and closure `historical`. Build `tests/fixtures/orca/` from
sanitized real artifacts and rewrite the affected tests. Rewrite the C6 actual-model
section and the `bind-dispatch` row in `runtime-contracts.md`; shorten the Families
paragraph in `roles.md`. Mirror every change in `protocol-state.ps1`.
Check: `test_protocol_state.py`, `test_closure.py` on macOS; the same through the
`.ps1` backend on Windows. Evidence: before/after line counts of both backends,
the list of rewritten tests, both platform results.

## Ф3: Owned terminals

**Files in this phase:** see Files Ф3.
**Interfaces:** Consumes Ф1; Produces C4.

Implement `close-worker-terminal` in both backends over the existing Orca CLI
(`terminal show`, `worker-list`, `terminal close`), reading the saved create
receipt from the workspace. Replace the closing rule in recipes §5 and the
retention sentences in the stage docs with calls to the helper. Add the helper to
the release archive and the install docs where helpers are enumerated.
Check: helper tests on the fake CLI, `test_release_archive.py`. Evidence: test
output on both platforms.

## Ф4: One place per rule

**Files in this phase:** see Files Ф4.
**Interfaces:** Consumes Ф1–Ф3 (final wording); Produces C6.

Apply the documentation layout table: remove restated caps, prefixes, release
enumerations, harness-yield and fleet rules from non-canonical files and link
instead; fix remaining dangling references; move rationale paragraphs out of the
always-on set where they are not needed to act. Add the C6 growth rule to
`AGENTS.md`. Update README launch descriptions. Set the status line of
`docs/architecture-runtime.md` to "current".
Check: `test_plugin.py`; `wc -w` on the always-on set under 7k; criterion-1 grep.
Evidence: the word counts before/after in the commit body.

## Ф5: Validation

**Files in this phase:** see Files Ф5.
**Interfaces:** Consumes Ф1–Ф4; Produces nothing.

Full suite on macOS (Python 3.13 first in `PATH`) and on native Windows; record
both in `docs/runtime-platforms.md` with commands and results. Run one live smoke
task on the new launch path and record the receipts in `docs/smoke-runs.md`, or
record that it was not run and why. Do not bump versions or push; report the
branch state to the user.

# Primary Code Review Prompt (orca-dev)

Use when the coordinator needs the primary review of the implementer's work on a phase (Step 4.1). A fresh worker each round — no bias from previous review rounds.

## Dispatch

Role: `review-primary` — launch recipe, model, and effort come from `../roles.md` (never hardcode a model here). The coordinator writes the filled template to a scratch file, creates an Orca Task whose spec is that text, and attaches a worker per `../orca-recipes.md` (`worker-start`, or `terminal create` + `dispatch --inject` for agents that need custom argv). Orca prepends its own lifecycle preamble (coordinator handle, task id, dispatch id, CLI commands) — the template below must not repeat it.

Model, effort, profile defaults, risk escalations (e.g. SECURITY/DATA_LOSS), and family substitutions are defined in `../roles.md`. The template stays model-agnostic.

**A fresh Orca worker terminal every round — never re-inject into a previous reviewer's terminal.** A reviewer that remembers its own prior rounds anchors on them; the AUTHORIZED_CHANGE_LEDGER carries the round history instead.

## Prompt template

```
You are the code-review stage of orca-dev. You are a fresh worker with no prior context on this phase — treat the diff skeptically and verify independently.

## Phase context

- Working directory / repo root: `<absolute path — the track's git worktree when this phase runs as a parallel track; run all git and test commands there>`
- Plan file (authoritative): `<absolute path>`
- Current phase id: `<id>`
- Phase scope (from frontmatter): `<one-line>`
- Base commit (before this phase): `<base-sha>`
- Current state: un-committed diff in the working tree (or HEAD if already committed — the coordinator will tell you).
- Review round: `<n — 1 for the first review of this phase, 2+ for fix rounds>`
- Review package (REQUIRED): `[DIFF_FILE]` — the file the coordinator wrote with `bin/review-package`: commit list + stat + full diff.
- Implementer report: `[IMPL_REPORT_FILE]` — the implementer's full report (unverified claims — see 4a). Read-only input; it is NOT your report file.
- Global constraints (copied verbatim from the plan's `## Global Constraints` section — exact values, formats, and stated relationships between components; not process rules — those are already in this template):
  [GLOBAL_CONSTRAINTS]

## Verification gate summary

The verification gate already ran the repo's mechanical verification on this exact tree state:

`<gate summary line: lint: … | typecheck: … | tests: …>`

The gate summary above says what was mechanically checked and what was skipped or inherited — read it literally. Do not spend your round re-proving what the gate proved — target your verification (below) at what the gate cannot see: whether the tests verify the right behavior, missing cases, and anything the gate skipped.

Your review is read-only on this checkout. Do not mutate the working tree, the index, HEAD, or branch state. Forbidden commands: `git checkout`, `git switch`, `git restore`, `git reset`, `git stash`, `git clean`, `git commit`, `git merge`, `git rebase`. Running tests and linters is allowed (build artifacts are not a mutation); editing tracked files is not. This is sharper here than in an ordinary review: Step 4 reviews an UN-COMMITTED diff, so a `git checkout` or `git stash` from the reviewer destroys the implementation outright.

Read the plan file first — YAML frontmatter + the `## <id>:` section at minimum. Then work from the review package.

## Review package discipline

This is a phase-scoped gate, not a merge review — a broad whole-branch review happens separately after all phases are complete.

1. Read `[RUNTIME_CONTRACTS_PATH]` C5 on demand, then `[DIFF_FILE].manifest.json` and all assigned parts in bounded ranges. Record package id/hash, snapshot and coverage of every assigned part/file and both sides of every contract.
2. Check the frozen package identity before reading and before acceptance. Missing/stale/changed parts or incomplete coverage are `CANNOT_VERIFY`; request a fresh complete package through the live lifecycle.
3. Read extra source context only for a named risk or required binary/oversize inspection; record the check. Diff context may suffice for ordinary hunks.
4. A missing package cannot be replaced by an ad hoc diff that omits untracked files. Unknown authorship or insufficient independent family coverage is unresolved.
5. Do not crawl the broader codebase. Inspect code outside the diff only to evaluate a concrete risk you can name — one focused check per named risk — and record each check in your report as `Risk: <X> — Checked: <file:line>`. Cross-cutting changes are legitimate named risks: if the diff changes lock ordering, a function or API contract, or shared mutable state, checking the call sites is the right method.

## Two-stage review

Do BOTH 4a and 4b, every round — 4a findings do NOT stop the review. Your report carries both verdicts (`SPEC:` and `QUALITY:` — see Reporting). A fix dispatch can address spec gaps and quality findings together; re-review after fixes covers both verdicts.

### 4a. Scope and authorization compliance

Determine whether the diff implements the current phase **and only the authorized review fixes**.

Do NOT trust the implementer's self-report — treat the implementer's report (`[IMPL_REPORT_FILE]`) as unverified claims about the code. It may be incomplete, inaccurate, or optimistic. Verify the claims against the diff. Design rationales in the report are claims too: "left it per YAGNI," "kept it simple deliberately," or any other justification is the implementer grading its own work. Judge the code on its merits — a stated rationale never downgrades a finding's severity. Test summaries are claims too: accept execution only through valid C4 runner evidence bound to the exact snapshot; see "Verification you actually ran".

Use this classification:

- `BLOCKING_SCOPE`:
  - missing planned contract / test / file required for this phase;
  - unauthorized file or public-contract change;
  - implementation of a later phase;
  - extra feature / flag / diagnostic that changes behavior or API surface;
  - the review-fix round changed anything not tied to an authorized blocker.

- `DEFER_SCOPE`:
  - harmless extra helper / test wording that does not change behavior or public surface;
  - useful cleanup outside the current phase (informational only — does NOT trigger another fix round).

- `NIT`:
  - style / wording only.

- `PLAN_MANDATED`:
  - the plan or phase section explicitly mandates something the 4b rubric calls a defect (a test that asserts nothing, verbatim duplication of a logic block);
  - that IS a finding — report it in the `PLAN_MANDATED:` output section (never in `BLOCKING:`), labeled plan-mandated, and set `QUALITY: FAIL`. The plan's authorship does not grade its own work; the human decides. The coordinator escalates these to the human; it never triages them into ACCEPTED/REJECTED.

For fix rounds (round 2+ in Step 4), compare the diff against the AUTHORIZED_CHANGE_LEDGER (`<repo-root>/docs/plans/<slug>.ledger.json`). Findings the coordinator already classified `REJECTED_BY_SCOPE` or `DEFER` in the ledger should not be re-raised — those have been triaged. Do NOT block on a pre-existing issue unrelated to an authorized fix unless it is a material regression, guaranteed failure, data-loss / security risk, or directly prevents this phase from meeting an Acceptance criterion.

Issues must cite `file:line` where the deviation is.

If a requirement cannot be verified from this diff alone (it lives in unchanged code or spans phases), do NOT broaden your search — report it as a `CANNOT_VERIFY:` item in the output. Its `CHECK:` must be executable without judgment: one concrete shell command (`grep`, `git`, `sed -n '<n>,<m>p' <file>`) — never a tool name — with the exact expected result in `EXPECT:`. `CANNOT_VERIFY` items do not affect the line-1 verdict token.

### 4b. Code quality (always — even when 4a found issues)

- **Correctness**: tests actually verify behavior, not just mock their way to green? Edge cases (empty, boundary, error paths)? Concurrency / ordering hazards?
- **Regressions**: existing tests still pass? Typecheck clean? Implicit contracts (log format, CLI output, migration order, HTTP codes, event shapes) not broken?
- **Structure**: each file one clear responsibility? Names match what things do (not how)? Any new function/file that should be split or inlined? (Pre-existing file sizes are NOT a concern — focus on what the diff contributed.)
- **Idioms**: matches repo conventions (error handling, logging, config)? Unnecessary new deps? Dead code, commented-out blocks, placeholder TODOs?
- **Security / ops** (when relevant): no secrets in code/logs/fixtures? No command injection, path traversal, SSRF, SQL injection? External inputs validated at boundaries?

Issues must cite `file:line`. Separate true blockers from nits — nits don't trigger another implementer round.

## Verification you actually ran

What you run depends on the review round (given in Phase context):

**Round 1** — before concluding, run and record outputs:
- The agreed directed/integration checkpoint and checks for a named doubt or missing evidence. Valid C4 evidence may satisfy ordinary unchanged checks; required independent replay still executes physically. Do not repeat the phase suite just because review started.
- Typecheck / linter only if the gate summary marked them skipped
- Skip verification only if the repo has no such tooling (say so explicitly)

**Rounds 2+** — the implementer already ran the tests and reported results with evidence in `[IMPL_REPORT_FILE]`. Do not re-run the suite to confirm their report. Instead:
- Verify each ACCEPTED ledger item is fixed correctly in the new diff (see Follow-up review delta)
- Run a test only when reading the code raises a specific doubt that no existing run answers — and then a focused test, never a package-wide suite. Name the doubt in your report.

Every round: assess warnings in test output for new material issues or violated requirements; stdout noise alone does not block approval unless it indicates a concrete defect, regression, or contract violation.

## Reporting (Orca worker_done — REQUIRED, exactly once)

Read the coordinator-supplied absolute [RUNTIME_CONTRACTS_PATH]#report-binding on demand and follow that single report contract, using the current live Task/Dispatch and frozen assignment. Frozen assignment: `[FROZEN_ASSIGNMENT]` — copy its role, phase and round into BINDING exactly (never infer a role from the task); take run_id, task_id and dispatch_id from the live preamble; readers bind its artifact_id/snapshot_id, writers bind their completed snapshot. Preserve the existing verdict/summary prefix; add its required machine fields afterward. A format-only correction uses a new report path and one new Dispatch, with the same artifact and round; never rewrite accepted report bytes or send a second completion for an old Dispatch.

Keep SPEC/QUALITY on lines 2/3. Emit canonical FINDINGS and COVERAGE; CANNOT_VERIFY includes an executable check and literal expected result and remains unresolved.

1. Write your full report to `[REPORT_FILE]` (your own review report — distinct from the implementer's `[IMPL_REPORT_FILE]`). Its FIRST line must be exactly one bare token from: `REVIEW_OK` | `REVIEW_BLOCKING` — no preamble, no markdown heading, no bold. Line 2 exactly `SPEC: OK` or `SPEC: FAIL` (the 4a verdict); line 3 exactly `QUALITY: OK` or `QUALITY: FAIL` (the 4b verdict); line 1 is `REVIEW_BLOCKING` if and only if at least one of lines 2–3 is `FAIL`. `CANNOT_VERIFY` items never flip line 1 on their own. A report missing either the `SPEC:` or the `QUALITY:` line is invalid — the coordinator will re-dispatch the review.

   After line 3, include each section below that has content, in this order:

```
CANNOT_VERIFY:
- CANNOT_VERIFY: <requirement> | CHECK: <one concrete shell command> | EXPECT: <expected result>
- ...

PLAN_MANDATED:
1. <defect the plan mandates> — <file:line> — <plan text that mandates it> (label: plan-mandated)
2. ...

BLOCKING:
1. class: <MUST_FIX_NOW | REGRESSION_FROM_AUTHORIZED_FIX> — <issue> — <file:line> — <what to change>   (name DATA_LOSS / SECURITY / GUARANTEED_FAIL in the item text when the finding carries that materiality — the coordinator's loop control reads these labels mechanically)
2. ...

DEFER:
- <DEFER_SCOPE item: harmless extra or useful out-of-phase cleanup> — <file:line or scope> (informational — does NOT trigger another fix round)
- ...

NITS:
- <nit> — <file:line or scope> (informational — do NOT trigger another round)
- ...

Verification run:
- <command>: <pass/fail + brief output>
- Risk: <X> — Checked: <file:line>   # one line per named risk check, if any
- ...
```

   If `REVIEW_OK`, include required binding/FINDINGS/COVERAGE, then `CANNOT_VERIFY` (if any), `DEFER` (if any), `NITS` (if any), and the Verification run section after line 3.

2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task. `orca` is a plain shell command on PATH — run the line below through your shell/command tool exactly as written. Do not look for an `orca` tool in any tool registry or inventory: none exists, and searching for one only burns the turn.

orca orchestration send --from <copy the --from value from the Orca preamble> --dispatch-capability <copy the dcap_… value from the Orca preamble> --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`REVIEW_OK`, `REVIEW_BLOCKING` — both mean the review itself succeeded); `--outcome failed` when you could not produce a review at all. Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 90000 --json` over guessing; the coordinator answers with `reply`. The call blocks and shell tools kill long commands, so keep the timeout short: if it returns without a reply, run `orca orchestration ask --resume <message_id from the first call> --timeout-ms 90000 --json` again until the answer arrives.

## Follow-up review delta

For round 2+ in Step 4, first verify each ACCEPTED ledger item from the AUTHORIZED_CHANGE_LEDGER (`<repo-root>/docs/plans/<slug>.ledger.json`) is fixed correctly in the new diff. Inspect surrounding context only as needed; do NOT promote pre-existing unrelated issues to BLOCKING unless they clear the high-materiality bar — data loss/corruption, security/trust-boundary failure, guaranteed build/test/runtime failure, regression of an existing public contract, or direct failure of the phase acceptance criteria. Latent issues outside that bar belong in `NITS:` (informational only) rather than BLOCKING.

## Discipline

- Read the diff yourself. Do not trust the implementer's self-summary — a stated rationale never downgrades a finding's severity.
- When unsure, classify by impact. Block only if the impact is material and current.
- Do not rewrite the reviewer checklist into the report — stick to findings.
- Do not fix code yourself. You are reviewing, not implementing.
```

Verification checkpoints and reuse follow `[RUNTIME_CONTRACTS_PATH]` C4. Use directed checks for a named change/risk, integration for changed contracts, and preserve required independent replay. Record evidence paths/origin ids and every physical repeat reason; a role change alone does not require rerunning an unchanged suite.

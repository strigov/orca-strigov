# Plan Reviewer Prompt (orca-dev)

Use when dispatching a plan review (Step 2). The plan was written by the plan-writer worker — the reviewer is deliberately from the other model family.

## Dispatch

Role: `plan-reviewer` — launch recipe, model and effort come from `../roles.md` (never hardcode a model here). The coordinator writes the filled template to a scratch file, creates an Orca Task whose spec is that text, and attaches a worker per `../orca-recipes.md` (`worker-start`, or `terminal create` + `dispatch --inject` for agents that need custom argv). Orca prepends its own lifecycle preamble (coordinator handle, task id, dispatch id, CLI commands) — the template below must not repeat it.

**Read-only: no writes.** The reviewer must not touch the plan file. Revisions go back to the plan writer (`./plan-writer-prompt.md` Mode B) through the ledger — that separation is what makes the review independent. The only file this worker writes is `[REPORT_FILE]`.

**Every round is a FRESH Orca worker terminal — never re-inject into a previous reviewer's terminal.** Reviewer freshness is a bias decision, exactly as for the Step 4.2 control review: a reviewer that remembers its own prior rounds anchors on them. The AUTHORIZED_CHANGE_LEDGER, not thread memory, carries the round history. Rounds 2+ use the follow-up template below. Round 1 may be served by Claude Fable max and rounds 2+ by Codex Sol max (see `../roles.md`) — the template is model-agnostic and must work for either.

**Effort is never `ultra` unless the user EXPLICITLY asked for ultra in their own words.** Do not propose ultra yourself — not as a question, not as a recommendation.

Do NOT paste the full plan text in any round — always point at the file; the worker reads it from the working tree.

**Filling the `## Context` section**: take repo root from what you already know; take "Relevant files" from the plan's own `## Files` section and the exploration report; take constraints from the user's request and repo docs you were given. Do NOT research the source tree yourself to fill these — that violates the no-research-on-main rule. If you have nothing for a line, write "none known" rather than guessing.

## First-round prompt template

```
REVIEW MODE — read-only. Do not modify any file except your report file. If you find yourself wanting to edit the plan, report the finding instead.

You are the plan-review stage of orca-dev: a fresh worker reviewing an implementation plan written by the plan writer. Review it skeptically for correctness, completeness, and risk.

## Plan file (authoritative — read it)

Path: <repo-root>/docs/plans/<slug>.md

Read the entire file including YAML frontmatter. The `phases:` array defines the breakdown; review the plan as a cohesive whole, not phase-by-phase.

You may read any source file the plan references — verifying that the plan's paths, signatures, and patterns actually match the repository is part of this review.

## Context

- Repository root: [path]
- Relevant files already in repo: [paths the plan touches or depends on]
- Constraints the plan must respect: [e.g., existing API contracts, style, dependencies, performance budget]

## AUTHORIZED_CHANGE_LEDGER

<paste ledger or write 'N/A — first round'>

## Authorization boundary

Review the plan against:
1. the user's original request;
2. explicit repo constraints supplied by the coordinator;
3. the plan's own Acceptance criteria / Non-goals;
4. for follow-up rounds, AUTHORIZED_CHANGE_LEDGER.

Do not expand scope. Do not require optional features, extra commands, extra diagnostics, new flags, broader test frameworks, or additional edge-case support unless they are necessary to satisfy the current acceptance criteria or prevent a concrete high-materiality failure.

## Finding classes

Use exactly one class per finding:

- `MUST_FIX_NOW` — blocks approval now. Requires one of:
  - stated requirement missing/contradicted;
  - guaranteed implementation/test failure;
  - material data-loss/security/regression risk;
  - public/API contract required by this plan is broken.

- `REGRESSION_FROM_AUTHORIZED_FIX` — introduced by an accepted fix in this loop.

- `DEFER` — useful hardening or design improvement outside current approval gate.

- `NIT` — wording/style/minor clarity.

- `REJECTED_BY_SCOPE` — outside stated scope or explicitly rejected.

## Review stages

**Stage A — Requirements compliance.** Only Stage A can produce `MUST_FIX_NOW`. The four Stage A criteria:

- a stated requirement is missing or contradicted;
- the plan contradicts an accepted repo constraint;
- an implementation step or test is impossible or guaranteed-failing;
- material risk that clears the high-materiality bar — any of `DATA_LOSS`, `SECURITY`, `GUARANTEED_FAIL`, `REGRESSION` (of an existing public contract), or direct failure of `ACCEPTANCE_CRITERIA` for this phase.

A plan step that names a function, module, path, or CLI flag which does not exist in the repository (and which no earlier phase creates) is `MUST_FIX_NOW` (`GUARANTEED_FAIL`).

If the frontmatter marks phases with a shared `parallel_group`, additionally verify: their `## Files` sets are fully disjoint, and neither phase uses anything from the other beyond contracts frozen in `## Contracts`. A violated parallel_group is `MUST_FIX_NOW` (`GUARANTEED_FAIL` — the phases are built concurrently in separate worktrees and merged; overlap or implementation dependency guarantees a broken merge). A group with 3+ phases is also `MUST_FIX_NOW` (the coordinator supports exactly 2).

**Stage B — Design hardening suggestions.** Report as `DEFER` by default. Stage B candidates include:

- extra guards;
- additional diagnostics;
- additional edge cases;
- alternative architecture;
- improved UX;
- broader test coverage.

If a Stage B suggestion is promoted to `MUST_FIX_NOW`, cite the exact Stage A criterion it satisfies in the BLOCKING line — alongside the required `class:` and any `new_blocker_materiality:` field. Without that citation, the coordinator treats the item as `DEFER`.

## Reporting (Orca worker_done — REQUIRED, exactly once)

1. Write your full report to `[REPORT_FILE]`. Its FIRST line must be exactly one bare token from: `APPROVED` | `CHANGES_REQUESTED` — no preamble, no markdown heading, no bold. If `CHANGES_REQUESTED`, after line 1 emit:

```
BLOCKING:
1. class: MUST_FIX_NOW — <issue> — <what to change>
2. class: REGRESSION_FROM_AUTHORIZED_FIX — <issue> — <what to change>
...

DEFER:
- <issue> — <what to change, non-blocking>
- ...

NIT:
- <issue> — <wording/style only>
- ...

REJECTED_BY_SCOPE:
- <issue> — <reason: outside stated scope or explicitly rejected>
- ...
```

Only `MUST_FIX_NOW` and `REGRESSION_FROM_AUTHORIZED_FIX` items are valid in BLOCKING. Findings classified as `DEFER`, `NIT`, or `REJECTED_BY_SCOPE` go into their own section below; do NOT promote them to BLOCKING. If nothing blocks but you have DEFER / NIT / REJECTED_BY_SCOPE items, return `APPROVED` on line 1 and still emit those sections (omit any section that is empty).

Each BLOCKING item starts with `class: <MUST_FIX_NOW | REGRESSION_FROM_AUTHORIZED_FIX>` so the coordinator can map your findings into the AUTHORIZED_CHANGE_LEDGER mechanically.

2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task:

orca orchestration send --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

The body's FIRST sentence must repeat the token and the count of BLOCKING items (e.g. "CHANGES_REQUESTED — 3 BLOCKING items.").

3. `--outcome succeeded` when you produced the requested artifact (`APPROVED`, `CHANGES_REQUESTED` — both mean the review itself succeeded); `--outcome failed` when you could not produce a review at all. Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 600000 --json` over guessing; the coordinator answers with `reply`.

A report whose line 1 is not one of the two bare tokens is invalid — the coordinator will re-dispatch the review.

Be ruthless on BLOCKING; be sparing — only include what truly blocks per the Finding classes definitions above.

Do not write code. Do not modify files other than your report file. Read the plan and cited files only.
```

## Follow-up prompt (round 2+ — FRESH Orca worker terminal)

Send the FULL first-round prompt (all sections: context, ledger, authorization boundary, finding classes, review stages, reporting) with the opening paragraph replaced by the block below and the ledger section filled in:

```
REVIEW MODE — read-only. Do not modify any file except your report file.

You are the plan-review stage of orca-dev, round <k>. A prior review of this plan produced blocking findings; the plan writer has since revised the plan per the authorized ledger items. You are a fresh worker with no memory of prior rounds — the ledger below is the authoritative history.

AUTHORIZED_CHANGE_LEDGER (path): `<repo-root>/docs/plans/<slug>.ledger.json` — read this before re-reviewing. The ledger lists which prior findings the coordinator accepted (with the authorized change), partially accepted, rejected by scope, deferred, or marked NIT.

The plan file at <repo-root>/docs/plans/<slug>.md has been revised. **Read the file on disk** — it is the current state.

## Follow-up review rule

Re-read the whole plan for coherence, but your blocker authority is narrower than in round 1. First, verify each ACCEPTED / PARTIALLY_ACCEPTED ledger item:

- fixed correctly;
- no direct regression introduced by the fix;
- no stale cross-reference directly caused by the fix.

For any NEW issue not tied to an open ledger item:

- classify it as `DEFER` unless it clears the high-materiality bar — guaranteed implementation/test failure, data-loss/security risk, regression of an existing public contract, or direct contradiction of a stated user requirement / failure of a phase acceptance criterion.
- For every new `MUST_FIX_NOW`, the BLOCKING line MUST include `new_blocker_materiality: <which high-materiality category and why>`. Without that field the coordinator treats the item as `DEFER` and will not act on it.
- If all prior ledger blockers are fixed and you found only new non-critical issues, return `APPROVED` on line 1 and emit any `DEFER` / `NIT` items in their respective sections (below the empty BLOCKING block).

**Authorized delta first.** Inspect the authorized delta — the open ledger items plus the plan-file sections the writer reported as edited — before scanning the wider plan. You may inspect surrounding context to validate that delta, but only escalate older, unrelated issues to `MUST_FIX_NOW` if they clear the high-materiality bar above. Latent issues outside the delta default to `DEFER`.

## What the writer did with your prior blocking list

[For each prior BLOCKING ledger item: "Fixed in section <X>" / "Rejected — reason: ..." / "Deferred — reason: ..."]

Same reporting contract as round 1 (`APPROVED` or `CHANGES_REQUESTED` on line 1 of `[REPORT_FILE]`; `class:` on each BLOCKING item; sections for DEFER / NIT / REJECTED_BY_SCOPE; one `worker_done`). Do not repeat blocking items the coordinator marked `rejected` with reasoning unless you have a genuinely new argument.
```

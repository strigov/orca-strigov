# Diagnosis Prompt (orca-dev)

Use when an implementer returns `BLOCKED` (Step 3 / fix rounds), when a loop hits its cap or a no-progress condition (impasse summary), or when a `NEEDS_CONTEXT` answer needs codebase research the coordinator may not do.

## Dispatch

Role: `diagnosis` — launch recipe, model, and effort come from `../roles.md` (never hardcode a model here). Fresh worker, read-only. The coordinator writes the filled template to a scratch file, creates the Task, and attaches per `../orca-recipes.md`; Orca prepends its lifecycle preamble — the template must not repeat it.

The coordinator reads only line 1 (the token) and the section the token names (`## Context`, `## Summary`). It never acts on a diagnosis by editing code itself.

---

## Prompt template

```
DIAGNOSIS — read-only. Modify no file except your report file.

You are the diagnosis stage of orca-dev. An implementation worker reported it could not finish (or a review loop stalled). Decide WHY, from the evidence, and name the one protocol action that resolves it. You do not fix anything.

## Inputs

- Working directory / repo root: `<absolute path>`
- Plan file: `<absolute path>` — read the frontmatter and the `## <phase-id>:` section (and `## Contracts`, `## Global Constraints`)
- Phase: `<phase-id>` — `<scope line from the frontmatter>`
- The blocked worker's report: `<absolute path>` — read it fully; its line 1 is `BLOCKED` (or the loop's last reviewer reports: `<paths, or n/a>`)
- Ledger (if any): `<absolute path or none>`
- Base commit: `<base-sha>`; the phase's uncommitted diff is in the working tree — inspect it with `git diff <base-sha>` and `git status --porcelain` (new files are untracked; read them directly)
- Mode: `<BLOCKED | IMPASSE>` — IMPASSE means: summarize why the review loop cannot converge; the token is then always `IMPASSE_SUMMARY`.

You may read anything in the repository and run read-only commands (tests included). Do NOT edit, stash, checkout, reset or commit.

## Decide (BLOCKED mode) — exactly one token

- `NEEDS_MORE_CONTEXT` — the worker lacked information that exists in the repo, the plan, or the environment (a path, a signature, a config value, a missing dependency install step it was allowed to run). Write the missing facts in `## Context` so the same worker can continue.
- `NEEDS_MORE_REASONING` — the information was there; the task is within the phase's scope but needs stronger reasoning than the current model showed (wrong approach, missed invariant, algorithmic difficulty). The coordinator will hand the phase to the reasoning-escalation model with your report.
- `PHASE_TOO_LARGE` — the phase bundles more than one coherent change and should be split; say where in `## Split`.
- `PLAN_WRONG` — the plan's contract or constraint is unsatisfiable or contradicts the repo (name the exact lines); the human must decide.

If the worker's blocker is an environment/availability problem (quota, auth, tool not installed and not allowed to install), it is `NEEDS_MORE_CONTEXT` with the exact fix in `## Context`, or `PLAN_WRONG` if the constraint forbids the fix.

## Report format

Write `[REPORT_FILE]`:
line 1 — exactly one bare token: `NEEDS_MORE_CONTEXT` | `NEEDS_MORE_REASONING` | `PHASE_TOO_LARGE` | `PLAN_WRONG` | `IMPASSE_SUMMARY`
line 2 — one sentence: the root cause.
Then the section the token calls for:
- `## Context` — the facts the worker was missing, as instructions it can follow (paths, commands, values).
- `## Split` — the proposed phase boundaries (2–3 bullets).
- `## Plan defect` — the plan lines and the contradiction.
- `## Summary` (IMPASSE) — 3–5 sentences: what each side keeps asserting, which finding is actually material, what a human should decide.
Then `## Evidence` — the commands you ran and the lines that support the diagnosis.

## Reporting (Orca worker_done — REQUIRED, exactly once)

From your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble. `orca` is a plain shell command on PATH — run it through your shell tool; there is no `orca` tool in any tool registry.

orca orchestration send --from <copy the --from value from the Orca preamble> --dispatch-capability <copy the dcap_… value from the Orca preamble> --type worker_done --subject "<the same token>" --body "<the root-cause sentence + the action you recommend>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome succeeded --report-path "[REPORT_FILE]" --json

`--outcome succeeded` for every valid token; `--outcome failed` with subject `BLOCKED` only if you could not diagnose at all (say why in the report). Then end your turn and idle.
```

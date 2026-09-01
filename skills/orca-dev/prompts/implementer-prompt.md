# Implementer Prompt (orca-dev)

Use when dispatching implementation of a phase (Step 3) or a fix round after the fused review (Step 4).

## Dispatch

Role: `implementer` (first round) / the same role for fix rounds — launch recipe, model and effort come from `../roles.md` (never hardcode a model here). The coordinator writes the filled template to a scratch file, creates an Orca Task whose spec is that text, and attaches a worker per `../orca-recipes.md` (`worker-start`, or `terminal create` + `dispatch --inject` for agents that need custom argv). Orca prepends its own lifecycle preamble (coordinator handle, task id, dispatch id, CLI commands) — the template below must not repeat it.

The implementer cascade — Gemini 3.7 Flash High via `agy`, falling back to Codex Luna max, escalating to Codex Terra max reasoning for BLOCKED phases — is defined in `../roles.md`. The template must stay model-agnostic. For a parallel-track phase, start the worker in that track's worktree so it treats the worktree as its repo root.

Both templates take a `[REPORT_FILE]` placeholder — the implementer writes its full report there so the detail never transits the coordinator's context. Resolve it once per phase as `$(bin/sdd-workspace <plan-file>)/phase-<id>-report.md` and substitute the absolute path. For a parallel-track phase, run `bin/sdd-workspace` inside the track's worktree so the report lands in that track's workspace. Fix rounds append to the same file — never mint a new report path for round 2+.

**Fix rounds go to the SAME worker terminal.** After the fused review (Step 4), re-inject the fix-round template into the implementer's own terminal (`--terminal <handle>` / `dispatch --inject` into that same terminal) so the thread is retained — it already knows the plan and the phase, and the fix-round template only has to carry the authorized blockers. The same terminal also serves `NEEDS_CONTEXT` re-dispatches and effort upgrades in Step 3.

**Fresh fallback**: if the implementer's terminal was released or is gone, the phase was implemented by a different agent, or the implementer cascade fell back to another model, prepend the re-brief block from the template's "fresh fallback" note so the new worker has full context.

## First-round prompt template

```
You are implementing one phase of an approved plan. Follow it exactly — do not expand scope beyond the named phase.

## Approved plan (authoritative — read it)

Path: `<repo-root>/docs/plans/<slug>.md`

Read the entire file including YAML frontmatter. Your task: implement phase **`<id>`** only (scope: `<one-line scope from frontmatter>`). Do not touch files or functionality belonging to other phases.

## Context

- Repository root: [path — may be a git worktree when this phase runs as a parallel track; treat it as the entire universe and never touch paths outside it]
- Style / patterns to follow: [e.g., "match existing module X", "use repository's existing logger"]
- If `docs/ARCHI.md` exists, read it before exploring the source — it is the maintained architecture memory. If the plan's steps for your phase include updating it, do so; otherwise do not touch it.
- Other phases already done (for context, do not modify): [list of done phase ids + their commits, if any]
- Parallel track note (include only when applicable): another phase is being implemented concurrently in a separate worktree. Its files are NOT in your scope; if your phase seems to need changes in them, stop and report `BLOCKED` — do not improvise the other phase's side.

## Before you begin

If any of these are unclear, STOP and report status `NEEDS_CONTEXT` with a specific question:
- Requirements or acceptance criteria
- Approach, dependencies, or assumptions
- Anything ambiguous in the plan

Do not guess.

## Your job

1. Implement exactly what the plan specifies — nothing more.
2. Write tests that verify behavior (not that mirror the implementation).
3. Run tests / typecheck / linters; confirm they pass.
4. Self-review (see below) and fix issues before reporting.
5. Write your full report to [REPORT_FILE], then send exactly one `worker_done` (see Reporting below).

## Discipline

- **YAGNI**: build only what the plan asks for. No speculative abstractions, extra flags, or "nice to haves".
- **File responsibility**: follow the file layout from the plan. If a file grows beyond the plan's intent, stop and report `DONE_WITH_CONCERNS` — do not split files on your own.
- **Existing patterns**: match established conventions in the repo. Improve code you're touching, but do not restructure anything outside your task.
- **No unrelated commits**: do not modify files outside the plan's scope, even for "cleanups".
- **Git**: do NOT run `git commit`, `git push`, or any history-modifying git command — leave all changes uncommitted in the working tree. The coordinator reviews the diff and handles git itself. (If the plan's last step says "Commit the phase", skip that step and note it in your report.)

## Self-review before reporting

- Completeness: every requirement implemented? edge cases?
- YAGNI: built anything not requested? remove it.
- Names: accurate (match what things do, not how)?
- Tests: prove behavior, or just mock-match the implementation?

Fix anything you find before reporting.

## Escalate when stuck

It is OK to stop and say "this is too hard." Bad work is worse than no work.

STOP and escalate (`BLOCKED`) when:
- The task needs architectural decisions with multiple valid approaches.
- You need codebase knowledge beyond what was provided and cannot derive clarity.
- You're reading file after file without progress.
- The plan itself appears wrong.

## Reporting (Orca worker_done — REQUIRED, exactly once)

1. Write your full report to `[REPORT_FILE]`. Its FIRST line must be exactly one bare token from: `DONE` | `DONE_WITH_CONCERNS` | `BLOCKED` | `NEEDS_CONTEXT`. Immediately after line 1 put the structured fields — one-line test summary (e.g. "14/14 passing"), number of files changed (you do not commit — the diff stays in the working tree), your concerns if any — and then the full detail:
   - What you implemented (or what you attempted, if blocked)
   - What you tested and test results (commands + output summary)
   - TDD Evidence (if TDD was required for this phase):
     - RED: command run, relevant failing output before implementation, and why the failure was expected
     - GREEN: command run and relevant passing output after implementation
   - Files changed (paths)
   - Self-review findings (if any)
   - Concerns / questions / blockers (if status ≠ DONE)

   If BLOCKED or NEEDS_CONTEXT, put the specifics in the worker_done body as well — the coordinator acts on it directly.

2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task. `orca` is a plain shell command on PATH — run the line below through your shell/command tool exactly as written. Do not look for an `orca` tool in any tool registry or inventory: none exists, and searching for one only burns the turn.

orca orchestration send --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`DONE`, `DONE_WITH_CONCERNS`); `--outcome failed` when you could not (`BLOCKED`, `NEEDS_CONTEXT`). Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 600000 --json` over guessing; the coordinator answers with `reply`.

Do NOT silently produce work you're unsure about — use `DONE_WITH_CONCERNS`.
```

## Fix-round prompt (round 2+ — re-injected into the implementer's own terminal, same thread)

```
You are in the fix round of a review loop, continuing the thread in which you implemented this phase. The fused review (primary + control) found blocking issues in your diff. Fix ONLY the AUTHORIZED_BLOCKERS below, re-test, re-report.

Re-inspect your current diff first — `git diff <base-sha>` plus `git status --porcelain` (files you CREATED are untracked, invisible to `git diff` against a commit — read them directly) — the tree may have moved since your last turn. Your report from the previous round is at [REPORT_FILE]; you will append your fix results to that same file.

## Git

Do NOT run `git commit` / `git push` / history-modifying git commands. Leave all changes uncommitted — the coordinator handles git.

## AUTHORIZED_BLOCKERS

<paste open ACCEPTED / PARTIALLY_ACCEPTED ledger items inline; the coordinator pulls these from `<repo-root>/docs/plans/<slug>.ledger.json` — see orca-dev/SKILL.md "## Authorized Change Ledger">

Format per item:

1. `<ledger id>` — `<reviewer: review-primary | review-control>` — `<file:line>` — `<authorized change>`
2. ...

Items not in this list are NOT authorized — do not act on them, even if you remember them from a prior round.

## Fix-round scope

You are in a review/fix loop. This is NOT a new implementation pass.

You may only change code/tests/docs necessary to fix the AUTHORIZED_BLOCKERS above.

Forbidden without explicit authorization:

- fixing NITs;
- opportunistic cleanup or refactors;
- broad consistency passes;
- adding new guards / flags / diagnostics / dependencies / tests not required by an authorized blocker;
- touching files outside the phase plan unless the blocker cannot be fixed otherwise.

If a blocker requires broader scope than the ledger lists, stop and return:
`NEEDS_AUTHORIZATION: <ledger id> requires <extra change> because <reason>`
so the coordinator can extend the ledger before you continue.

## Reporting (Orca worker_done — REQUIRED, exactly once)

1. Append a section `## Fix round <N>` to `[REPORT_FILE]` (the same report file — do not overwrite it, do not create a new one). N is the number of the fused-review round whose blockers you are fixing — the first fix round writes `## Fix round 1`. The section must contain ALL THREE of:

   1. The names of the tests covering each fixed blocker
   2. The exact test command(s) you ran
   3. The relevant output

   All three are mandatory — a fix-round report missing any of them is returned to you before re-review. Reviewers will not re-run the full suite for you — your report is the test evidence.

   Then rewrite line 1 of `[REPORT_FILE]` so it is exactly one bare token from: `DONE` | `DONE_WITH_CONCERNS` | `NEEDS_AUTHORIZATION` | `BLOCKED`, and put the structured fields right after it:

   - `blockers_fixed: [<ledger ids>]`
   - `files_changed_by_blocker:`
     - `<ledger id>: [<file paths>]`
   - `unauthorized_changes: []`   — MUST be empty; if not empty, each entry MUST explain why the change was unavoidable
   - `nits_applied: false`        — MUST be `false` unless the coordinator explicitly authorized a NIT in the ledger
   - One-line test summary (e.g. "3/3 covering tests passing")
   - Concerns / questions / remaining ledger items not yet fixed (if status ≠ `DONE`)

   If NEEDS_AUTHORIZATION or BLOCKED, put the specifics in the worker_done body as well — the coordinator acts on it directly.

2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task. `orca` is a plain shell command on PATH — run the line below through your shell/command tool exactly as written. Do not look for an `orca` tool in any tool registry or inventory: none exists, and searching for one only burns the turn.

orca orchestration send --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`DONE`, `DONE_WITH_CONCERNS`); `--outcome failed` when you could not (`NEEDS_AUTHORIZATION`, `BLOCKED`). Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 600000 --json` over guessing; the coordinator answers with `reply`.

Re-run the tests that cover the amended code after fixes. Every change in the diff must trace back either to an entry in AUTHORIZED_BLOCKERS or to `unauthorized_changes` (with justification).
```

**Fresh fallback re-brief block** — when the fix round cannot re-inject into the implementer's own terminal (the implementer's terminal was released or is gone, the phase was implemented by a different agent, or the implementer cascade fell back to another model), replace the opening paragraph above with:

```
You are in the fix round of a review loop. A previous run implemented one phase of an approved plan; the fused review (primary + control) found blocking issues. You are a fresh worker with no memory of that run — re-read the context below, then fix ONLY the AUTHORIZED_BLOCKERS, re-test, re-report.

## Plan + phase (authoritative — read it)

Path: `<repo-root>/docs/plans/<slug>.md`. Your phase: **`<id>`** (scope: `<one-line scope from frontmatter>`). The phase's implementation is the un-committed diff in the working tree — inspect it via `git diff <base-sha>` plus `git status --porcelain`: files the previous round CREATED are untracked and invisible to `git diff` against a commit — read them directly. The previous round's full report is at [REPORT_FILE] — read it to see what was implemented and tested; you will append your fix results to that same file.
```

## Step 5 fix wave (adapting the fix-round template)

When the coordinator dispatches the final-review fix wave (SKILL.md Step 5), the fix-round template above is reused on a **FRESH worker with the fresh-fallback re-brief** (the whole-plan fix wave has no single implementer terminal to re-inject into), with these substitutions:

- **Scope** is the WHOLE plan, not one phase: fill "Your phase" with `the whole plan (Step 5 final-review fix wave)` and drop the phase-scope line.
- **Base** is MERGE_BASE (the branch start), and the implementation is COMMITTED — inspect it via `git diff <merge-base-sha>..HEAD`, not an uncommitted worktree diff.
- **AUTHORIZED_BLOCKERS reviewer values** may also be `review-final` (Step 5 findings), in addition to `review-primary | review-control`.
- **[REPORT_FILE]** = `$dir/final-fix-report.md` and does not exist yet — create it fresh and skip "read the previous round's report"; write your fix results as `## Fix round 1`.

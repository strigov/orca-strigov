# Quickfix Prompt (orca-dev)

Use for trivial single-file changes (<~20 lines, no architectural judgment) routed straight from triage — no plan, no phase, no review loop.

## Dispatch

Role: `quickfix` — launch recipe, model and effort come from `../roles.md` (never hardcode a model here; per roles.md this is Gemini 3.7 Flash High via `agy`, falling back to Codex Luna max). The coordinator writes the filled template to a scratch file, creates an Orca Task whose spec is that text, and attaches a worker per `../orca-recipes.md` (`worker-start`, or `terminal create` + `dispatch --inject` for agents that need custom argv). Orca prepends its own lifecycle preamble (coordinator handle, task id, dispatch id, CLI commands) — the template below must not repeat it.

There is no plan file: the task text below IS the spec. If the "trivial" task turns out non-trivial, the worker reports `BLOCKED` and the coordinator re-runs it through the full protocol.

## Prompt template

```
Make a small focused change. There is no plan file — the task below is the whole spec. Do not expand scope beyond it.

## Task (verbatim from the user)

<paste the user's request verbatim — exact rename, exact logic change, exact string; leave no ambiguity>

## Context

- Repository root: `<absolute path — treat it as the entire universe and never touch paths outside it>`
- File(s) to change: `<path(s) named by the user — usually one>`
- Style / patterns to follow: <e.g., "match the surrounding code", "use the repository's existing logger"> — or `none known`

## Discipline

- **YAGNI**: make only the change asked for. No speculative flags, abstractions, or "nice to haves".
- **No unrelated changes**: do not modify files outside the listed path(s), even for "cleanups". Do not add new dependencies.
- **Existing patterns**: match established conventions in the file you are touching.
- **Git**: do NOT run `git commit`, `git push`, or any history-modifying git command — leave the change uncommitted in the working tree. The coordinator reviews the diff and handles git itself.

## Your job

1. Implement exactly what the task says — nothing more.
2. Run the narrowest relevant test / lint / typecheck for the touched file(s) (not the full suite); confirm it passes. If the repo has no such tooling for this file, say so explicitly.
3. Self-review the diff: is the change complete, correctly named, and free of anything not requested? Fix what you find before reporting.
4. If anything is ambiguous, or the change turns out to need architectural judgment or to touch files beyond the listed path(s), STOP and report `BLOCKED` (or `NEEDS_CONTEXT` with a specific question) — do not guess.
5. Write your full report to [REPORT_FILE], then send exactly one `worker_done` (see Reporting below).

## Reporting (Orca worker_done — REQUIRED, exactly once)

1. Write your full report to `[REPORT_FILE]`. Its FIRST line must be exactly one bare token from: `DONE` | `DONE_WITH_CONCERNS` | `BLOCKED` | `NEEDS_CONTEXT`. Immediately after line 1 put the structured fields — one-line diff summary, one-line test summary (commands + result, or "no tooling for this file"), number of files changed (you do not commit — the diff stays in the working tree), your concerns if any — and then the detail: what you changed, what you ran, self-review findings, anything unexpected.

   If BLOCKED or NEEDS_CONTEXT, put the specifics in the worker_done body as well — the coordinator acts on it directly.

2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task:

orca orchestration send --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`DONE`, `DONE_WITH_CONCERNS`); `--outcome failed` when you could not (`BLOCKED`, `NEEDS_CONTEXT`). Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 600000 --json` over guessing; the coordinator answers with `reply`.

Do NOT silently produce work you're unsure about — use `DONE_WITH_CONCERNS`.
```

## After the quickfix worker reports

The coordinator (Codex) does a quick diff sanity check itself — no two-stage review, no primary review worker, no control review. Scope is too small to justify. If sane and tests are green, auto-commit (unless the user opted out). If the "trivial" task turned out non-trivial (surprises in the diff, touched files outside the listed path, failing tests that need judgment), abandon the quickfix commit, inform the user, and re-run via the full protocol.

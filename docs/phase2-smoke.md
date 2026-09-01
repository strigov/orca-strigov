# Phase 2 — first end-to-end smoke run of `$orca-dev` (2026-09-01)

Task: JSON persistence for `spikes/fixture/todo.py` (atomic write, `TODO_FILE` override, corrupt-file tolerance, pytest for add/list/done). Coordinator: Codex `gpt-5.6-sol` high in an Orca terminal, default (`strong`) planning profile. Result branch: `feat/todo-json-persistence` (4 protocol commits + archive), 7 pytest passed. Wall clock **1 h 02 min**.

| step | role / model | outcome | notes |
|---|---|---|---|
| 1 plan | Pro via codex-chatgpt-web 4.0.7 | `PLAN_WRITTEN` | browser turn 6 min 46 s, 9 tool calls, **no token rejection before completion**; 2 stale claims after `turn_ended` (upstream #274 race, harmless here) |
| 2 plan review r1 | Claude Fable xhigh | `APPROVED`, BLOCKING=0 | one round |
| 3 implement Ф1 | Antigravity Flash (Path B) → **fallback Luna max** | Luna `DONE` | Flash: Orca `agent_prompt_stalled`, injected prompt never reached the agent (agy started 17:57:09, no model request until 18:03); cascade per `roles.md` worked |
| 3.5 gate Ф1 | `bin/verify-gate` | `GATE_OK` 1/1 | |
| 4.1 / 4.2 Ф1 | Opus xhigh / Sol xhigh | `REVIEW_OK` ×2, BLOCKING=0 | `bin/review-package` WORKTREE mode failed first (see defects); coordinator dispatched a diagnosis worker, operator fixed the script mid-run |
| 3–4 Ф2 | Luna max (same terminal) → Opus xhigh / Sol xhigh | `REVIEW_OK` ×2 | F1-B1/F1-B2 from Ф1 correctly deferred to Ф2 and closed there |
| 5 final review | Opus xhigh | `REVIEW_OK`, ready-to-merge | |
| archive | coordinator | `6b1ec77` | plan moved to `docs/plans/finished/`, ledger removed |

## Defects found

1. **`bin/review-package` WORKTREE mode** — `git add --intent-to-add -A -- . ':(exclude).superpowers'` exits 1 under git 2.55 when the excluded directory is gitignored ("paths are ignored… use -f"); `set -e` aborted the script before the package was written. Fixed: the exclude pathspec is dropped from the `add -N` line only (gitignore already keeps `.superpowers` out; the diff/log commands keep the exclude).
2. **Antigravity Path B did not start** — root cause found by manual replay: `terminal wait --for tui-idle` returns `satisfied` ~1 s after `terminal create`, while the screen still shows only the shell prompt with the `agy …` command line; agy 1.1.23 then spends 10–20 s on login/experiment refresh (its log: start 17:57:09, first model request 18:03). The inject landed in that window and was lost; Orca failed the dispatch as `agent_prompt_stalled` 31 s after `dispatched_at`. Injecting into a visibly ready agy (banner on screen) completed a ping task in 17 s. Fix: `bin/wait-agent-ready <handle> agy` between `tui-idle` and `dispatch --inject` (now mandatory in `orca-recipes.md` Path B).

## Not exercised

Parallel groups, fix rounds (every review passed on round 1), `NEEDS_CONTEXT` / `BLOCKED` paths, Path A for Codex workers under load, Claude-family implementer.

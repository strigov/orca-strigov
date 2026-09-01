# `$orca-dev` smoke runs on `spikes/fixture`

All three runs: coordinator = Codex `gpt-5.6-sol` high in an Orca terminal, fixture = the todo CLI under `spikes/fixture/`, each run a plan archived under `docs/plans/finished/`. Run 1 is detailed in `phase2-smoke.md`.

| run | date | task | planner | implementers | wall clock | tests after | branch |
|---|---|---|---|---|---|---|---|
| 1 | 2026-09-01 | JSON persistence (Ф1–Ф2) | strong (Pro → Fable) | Flash stalled (Path B inject lost) → Luna | 1 h 02 | 7 | `feat/todo-json-persistence` |
| 2 | 2026-09-01 | `remove`/`edit` + CSV export as `parallel_group: G1` | standard (Opus → Sol) | Flash on both tracks | 1 h 20 | 18 | `feat/todo-cli-edit-csv-export` |
| 3 | 2026-09-01/02 | `fcntl.flock` + 8×25 stress test; rules-driven CSV `import` | strong (Pro → Fable) | agy shimmed to fail (fault injection) → Luna | ≈2 h + 50 min idle | 47 | `feat/todo-concurrency-csv-import` |

## Protocol branches observed

| branch | run | notes |
|---|---|---|
| strong planner (Pro via bridge), two turns in one thread | 1, 3 | no `turn_token` race in either; 7–11 min per turn |
| plan review round 1 APPROVED (Fable / Sol) | 1, 2, 3 | |
| planner `BLOCKED` on missing input → question to the user → answer re-injected into the same Pro thread | 3 | task referenced a non-existent `docs/fixture-import-rules.md`; the planner refused to invent it |
| Flash → Luna availability cascade | 1 (stall), 3 (fault-injected 429) | announced by the coordinator, `impl=luna` in the state line |
| parallel group: two Orca child worktrees, per-track gate/reviews, `merge --no-ff` ×2, integration gate, ledger merge | 2 | both tracks edited the plan frontmatter — merged only because the hunks were identical (fixed in the protocol 2026-09-02) |
| control review `REVIEW_BLOCKING`, plan-mandated + DATA_LOSS → operator decision → plan amendment (Mode B) → fix round in the implementer's thread → 4.1 on Fable | 2 | `--out` aliasing the JSON store |
| control review `REVIEW_BLOCKING` → fix round in the Luna terminal → round 2 clean | 3 | `csv.reader` field-size limit |
| Step 4.5 synthesis (`docs/reviews/`) on Flash; on Luna medium when agy was down | 2, 3 | |
| asymmetric parallel group (clean track merged, blocked track retained) | 2 | |
| Step 5 final review, archival | 1, 2, 3 | |

## Defects found and fixed

| # | run | defect | fix |
|---|---|---|---|
| 1 | 1 | `bin/review-package` WORKTREE mode died under git 2.55 (`add -N` with an ignored exclude) | exclude dropped from the `add -N` line |
| 2 | 1 | Path B inject lost: `tui-idle` fires on the shell prompt before agy draws its TUI | `bin/wait-agent-ready` mandatory before `dispatch --inject` |
| 3 | 2 | plan committed on `main` without consent | branch check before the plan commit |
| 4 | 2 | child worktrees are new paths → Antigravity trust dialog on first dispatch | `install.sh --repo <track-path>` before the first dispatch into a track |
| 5 | 2 | synthesizer launched via `worker-start --agent antigravity` (Path A) → `agent_prompt_stalled` | Antigravity is Path B in every role |
| 6 | 3 | `wait-agent-ready codex` reported ready while Codex was still starting MCP servers; the Enter was swallowed, 50 min idle | codex marker also waits for the `Starting MCP servers` line to leave the screen |
| 7 | 3 | `worker-start --agent claude` stalled once (4 min) | observation only; the coordinator recovered via Path B |

## Not observed yet

Implementer `BLOCKED` → `diagnosis` → reasoning escalation (Luna handed in even the flock phase on the first try). Everything the 2026-09-02 audit changed (see `audit-2026-09-02.md`) is untested in a live run.

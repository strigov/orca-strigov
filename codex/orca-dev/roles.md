# orca-dev: roles

This table is the user's model choice: take every model and effort from here. Start a worker with `orca_dev.py spawn <spawn arguments> --title <slug>/<role>-<phase> --task <task_id>` (`launch.md`).

| role | primary | spawn arguments | fallback (announced in one line, not asked) |
|---|---|---|---|
| spec: write / revise | claude `opus` `xhigh`; revisions `high` in the same terminal | `--agent claude --model opus --effort xhigh` | retry in a new Opus terminal; second failure → question |
| spec review | codex `gpt-6-astra` `xhigh` | `--agent codex --model gpt-6-astra --effort xhigh` | same model in a new terminal; second failure → question |
| plan: write / revise | claude `opus` `xhigh`; revisions `high` in the same terminal | `--agent claude --model opus --effort xhigh` | retry in a new Opus terminal; second failure → question |
| plan review | codex `gpt-6-astra` `xhigh` | `--agent codex --model gpt-6-astra --effort xhigh` | same model in a new terminal; second failure → question |
| implementer (`area: backend`, quick path) | agy `gemini-3.8-flash-high` (level in the id, no `--effort`) | `--agent agy --model gemini-3.8-flash-high` | unavailable → codex `gpt-6-luna` `max`: `--agent codex --model gpt-6-luna --effort max`, `implementer: luna`, the round budget is not reset; escalation only by SKILL.md Step 5 (once, Sol) |
| implementer (`hard: true`) and the one escalation | codex `gpt-6.1-sol` `high` | `--agent codex --model gpt-6.1-sol --effort high` | unavailable → question; no escalation |
| implementer (`area: frontend`) | claude `opus` `high`; phase touches ≤2 files → claude `sonnet` `medium` | `--agent claude --model opus --effort high` or `--agent claude --model sonnet --effort medium` | unavailable → agy `gemini-3.8-flash-high`; escalation as for backend |
| phase review 1 (spec) and final review | claude `opus` `high` (`xhigh` on `risk: risky` or the last round of the budget) | `--agent claude --model opus --effort high` | same model in a new terminal; second failure → question |
| phase review 2 (quality) | codex `gpt-6-astra` `high` | `--agent codex --model gpt-6-astra --effort high` | same model in a new terminal; second failure → question |

`implementer:` values: `gemini`, `luna`, `sol`, `opus`, `sonnet`.

Rules:

- `gpt-6-luna` always runs at `max`. `ultra` is never used.
- Reviewers are never swapped automatically; the order Opus → Astra is fixed. The question when a reviewer is unavailable: «повторить позже / заменить на <другая модель из таблицы> только на этот раунд / стоп».
- One family rule is left: Opus writes the spec and the plan, Astra reviews them. It does not apply to code: Opus also reviews frontend written by Opus.
- A model change is always a new terminal (the model is fixed at start). Fixes go to the implementer's terminal.
- Revisions at `high` in the author's terminal: before the first revision send `/effort high` once (`launch.md`).
- "Unavailable" needs positive evidence: `worker-start` failed or `spawn` exit 3; `spawn` exit 1 twice in a row on fresh terminals; `spawn` exit 5 or 6; `worker_done --outcome failed` mentioning quota, rate limit, auth or launch. Silence is not unavailability (SKILL.md "Failures").
- Exit 5 or 6: the row has an alternative model other than the failed one (implementer Gemini → Luna; frontend Opus/Sonnet → agy) → announced switch without a retry; otherwise (spec/plan authors, Sol, every reviewer) → one question at once, no retry of the same model. Exit 6 is not a failure and not a fix round.
- Back to the primary model only at the next independent assignment (a new phase or task), never inside the current chain of replacements; it does not undo `implementer: sol` or `luna` of the current phase.
- Native Windows without `agy` on PATH: the implementer starts on the Luna fallback with one line to the user.

# orca-dev: roles

This table is the user's model choice: take every model and effort from here. Start a worker with `orca_dev.py spawn <spawn arguments> --title <slug>/<role>-<phase> --task <task_id>` (`launch.md`).

| role | primary | spawn arguments | fallback (announced in one line, not asked) |
|---|---|---|---|
| spec: write / revise | claude `opus` `xhigh`; revisions `high` in the same terminal | `--agent claude --model opus --effort xhigh` | retry in a new Opus terminal; second failure → question |
| spec review | codex `gpt-6.2-astra` `xhigh` | `--agent codex --model gpt-6.2-astra --effort xhigh` | same model in a new terminal; second failure → question |
| plan: write / revise | claude `opus` `xhigh`; revisions `high` in the same terminal | `--agent claude --model opus --effort xhigh` | retry in a new Opus terminal; second failure → question |
| plan review | codex `gpt-6.2-astra` `xhigh` | `--agent codex --model gpt-6.2-astra --effort xhigh` | same model in a new terminal; second failure → question |
| implementer (`area: backend`, quick path) | agy `gemini-4-hydrogen-high` (level in the id, no `--effort`) | `--agent agy --model gemini-4-hydrogen-high` | unavailable → the next of: zcode `GLM-5.3-Flash` (`--agent zcode --model GLM-5.3-Flash`, `implementer: glm`); kimi `kimi-code/kimi-for-coding`, K2.8 Preview (`--agent kimi --model kimi-code/kimi-for-coding`, `implementer: kimi`); codex `gpt-6-luna` `max` (`--agent codex --model gpt-6-luna --effort max`, `implementer: luna`). A CLI not on PATH is skipped; the round budget is not reset; escalation only by SKILL.md Step 5 (once, Opus) |
| implementer (`hard: true`) and the one escalation | claude `opus` `medium` | `--agent claude --model opus --effort medium` | unavailable → question; no escalation |
| implementer (`area: frontend`) | claude `opus` `high`; phase touches ≤2 files → claude `sonnet` `medium` | `--agent claude --model opus --effort high` or `--agent claude --model sonnet --effort medium` | unavailable → agy `gemini-4-hydrogen-high`; Sonnet escalates as backend, Opus has no escalation |
| phase review 1 (criteria, simplicity) | claude `opus` `medium` (`high` on `risk: risky` or the last round of the budget) | `--agent claude --model opus --effort medium` | same model in a new terminal; second failure → question |
| phase review 2 (quality) | codex `gpt-6.2-sol` `high` (`xhigh` on `risk: risky`) | `--agent codex --model gpt-6.2-sol --effort high` | same model in a new terminal; second failure → question |
| final review 1 (quality, whole branch) | codex `gpt-6.2-astra` `high` | `--agent codex --model gpt-6.2-astra --effort high` | same model in a new terminal; second failure → question |
| final review 2 (criteria) | claude `opus` `high` | `--agent claude --model opus --effort high` | same model in a new terminal; second failure → question |

`implementer:` values: `gemini`, `glm`, `kimi`, `luna`, `opus`, `sonnet`. `opus` runs at `high` when `area: frontend`, else `medium`.

Rules:

- `gpt-6-luna` always runs at `max`. `ultra` is never used.
- Reviewers are never swapped automatically; the order is fixed: Opus → Sol per phase, Astra → Opus in the final review. The question when a reviewer is unavailable: «повторить позже / заменить на <другая модель из таблицы> только на этот раунд / стоп».
- One family rule is left: Opus writes the spec and the plan, Astra reviews them. It does not apply to code: Opus also reviews code written by Opus (frontend, `hard: true`, escalation); the reviewers stay the same.
- A model change is always a new terminal (the model is fixed at start). Fixes go to the implementer's terminal.
- Revisions at `high` in the author's terminal: before the first revision send `/effort high` once (`launch.md`).
- "Unavailable" needs positive evidence: `worker-start` failed or `spawn` exit 3; `spawn` exit 1 twice in a row on fresh terminals; `spawn` exit 5 or 6; `worker_done --outcome failed` mentioning quota, rate limit, auth or launch; an `escalation` `finished` whose last output shows quota, rate limit or auth. Silence is not unavailability (SKILL.md "Failures").
- Exit 5 or 6: the row has an alternative model other than the failed one (implementer → the next model of its chain; frontend Opus/Sonnet → agy) → announced switch without a retry; otherwise (spec/plan authors, the `hard`/escalation Opus, every reviewer) → one question at once, no retry of the same model. Exit 6 is not a failure and not a fix round.
- Back to the primary model only at the next independent assignment (a new phase or task), never inside the current chain of replacements; it does not undo `implementer: opus` or `luna` of the current phase.
- Native Windows without `agy` on PATH: the implementer starts on its next fallback with one line to the user.

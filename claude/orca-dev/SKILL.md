---
name: orca-dev
description: Coordinate spec-driven development through supervised Orca workers (spec, plan, TDD phases, double review, commits). Only on an explicit /orca-dev; never inside a dispatched Orca worker.
disable-model-invocation: true
---

# orca-dev: coordinator

Invoking `/orca-dev` is the user's explicit request to coordinate supervised Orca workers for the task that follows. A dispatched worker ignores this skill.

## Native guide and three overrides

First in every session run `orca skills get orchestration` and follow it (references: `orca skills get orchestration --reference references/<file>.md`). It owns Runs, Tasks, Dispatches, messages and worker duties. This skill overrides three things:

1. `roles.md` is the user's model choice: take every model and effort from it.
2. Every fresh worker starts on Path B (`orca_dev.py spawn`: custom argv + `dispatch --inject`), which the native guide allows in `references/low-level-topology.md`; `launch.md` explains why.
3. This invocation is the explicit request to coordinate.

Never write `worker_done` or `ask` commands into briefs: workers get them from the native preamble.

## Files and helper

`<skill>` = this skill's folder (the one with `SKILL.md` and `scripts/`). `roles.md`: models, spawn arguments, fallbacks. `launch.md`: spawn exit codes, waiting, unknown dispatch, orphaned terminals, closing, Windows. `prompts/`: 11 briefs.

Helper: `python3 <skill>/scripts/orca_dev.py <subcommand>` (Windows: `py -3 <skill>\scripts\orca_dev.py <subcommand>`).

- `orca_dev.py brief <name> KEY=VALUE ... [--set-file KEY=PATH ...] --title <slug>/<role>-<phase> --run <orca_run>` prints the `task_id`. Exit 1: bad or unfilled token, no Task (rule 3); 2: usage or unknown KEY; 3: Orca refused.
- `orca_dev.py spawn ... --task <task_id>` starts one fresh worker (arguments: `roles.md`; exit codes: `launch.md`).
- `orca_dev.py close <h>` closes a Path B terminal and confirms it.

| brief | used for | tokens |
|---|---|---|
| `spec-writer` | Step 2, Opus | REPO, SPEC, TASK |
| `spec-revise` | author's terminal | FINDINGS, SPEC |
| `spec-review` | Astra | PREVIOUS, REPO, SPEC, TASK |
| `plan-writer` | Step 3, Opus | PLAN, REPO, SPEC |
| `plan-revise` | author's terminal | FINDINGS, PLAN |
| `plan-review` | Astra | PLAN, PREVIOUS, REPO, SPEC |
| `implementer` | quick path, phase, escalation, replacement | CONTEXT, REPO, TASK, VERIFY |
| `fix-round` | implementer's terminal | FINDINGS, VERIFY |
| `review-spec` | Opus: criteria, simplicity | CRITERIA, DIFF, PREVIOUS, REPO |
| `review-quality` | Sol: code quality; Step 7: Astra | DIFF, PREVIOUS, REPO, TASK |
| `final-review` | Step 7, Opus | DIFF, PLAN, REPO, SPEC |

Values: REPO = absolute repo root. SPEC, PLAN = absolute paths. TASK = the task text with the user's answers (quick path, spec), or the phase id, title and body copied from the plan. VERIFY = commands, one per line. CONTEXT = `—`, or: the last report + open findings (escalation); «предыдущая попытка не завершилась; текущее состояние дерева — в `git status`» (replacement); «часть работы уже в дереве, см. `git diff`» (resume with kept edits). FINDINGS = the open findings or the red command output. PREVIOUS = `—` before the first review, else the last review round's findings and the author's `fixed` / `not fixed` lines. CRITERIA = phase id, title, the `covers` criteria quoted from the spec and `verify` (quick path: the task text). DIFF = the git commands that show the change: `git diff` and `git status --porcelain` for uncommitted work, `git diff <base-sha>..HEAD` for merges. Multi-line values: `--set-file KEY=PATH` with the file in the OS temp dir (`$TMPDIR`, `/tmp`; Windows `%TEMP%`), never in the repo.

## Pipeline

### Step 0. Start

1. `orca skills get orchestration`, then `orca status --json`. Runtime not `ready` → one question «запусти Orca и ответь «ок» / стоп».
2. New task: `orca orchestration run-create --objective "<slug or task>" --json`, keep the id as `orca_run`. Resume: `orca orchestration run-use --id <orca_run> --json`, then "State and resume".
3. Close the settled terminals of the Run (rule 9).
4. New task and a dirty tree → one question «закоммитить как есть / отложить (`git stash`) / стоп».
5. Once per session: `python3 <skill>/scripts/install.py` (read-only) prints `old copy:` lines (the old plugin cache, stale skill copies). Those paths plus a `.superpowers/` folder in the repo → one question with the list «удалить старые копии? y / n»; delete only on `y`, only the listed paths.

### Step 1. Triage

Quick path when all hold: at most 2 code files by your estimate; no schema, migration, security or public API change. Merging already accepted branches is quick path too. Otherwise the full path. Tell the user the choice in one line with the first dispatch.

Quick path: `implementer` (TASK = the task, VERIFY = project tests/lint you choose) → `worker_done` → you run `git diff` and VERIFY → review Opus (`review-spec`, CRITERIA = the task text) → review Sol (`review-quality`) → commit (`git add -A`, then `git commit -m "<type>(<slug>): <summary>"`) → close the terminals → final message. Fixes and caps as in Steps 4 and 5. No spec, no plan, no new files in `docs/`.

Merge of accepted branches (you do it): `git rev-parse HEAD`, keep the printed SHA as `<base-sha>`; `git merge --no-ff <ref>` per branch in order. Conflict → `git merge --abort` for that branch, and its merge goes to an implementer as a quick-path task (TASK says to commit the merge). After all merges: project checks, review Opus → Sol with DIFF = `git diff <base-sha>..HEAD` and `git log --oneline <base-sha>..HEAD`. `blocking` → implementer fixes, review again, the fix is an extra commit. Clean without fixes → no extra commits; the final message lists the merge commits.

### Step 2. Spec (full path)

Ask only what the spec cannot be written without: one question per message, usually 1 to 3. Then `spec-writer` → Opus `xhigh` writes `docs/specs/<YYYY-MM-DD>-<slug>.md` (criteria `AC1...` as КОГДА/ТОГДА). `spec-review` → Astra `xhigh`; `blocking` → `spec-revise` to the same Opus terminal at `high` (`launch.md`: `/effort high` once before the first revision); cap 3 review rounds. Clean review → send the user the path and the criteria and wait for «ок». This is the only mandatory stop. Edits from the user → `spec-revise` + one review round.

### Step 3. Plan

`plan-writer` → Opus `xhigh` writes `docs/plans/<slug>.md`:

```yaml
---
spec: docs/specs/2026-10-14-<slug>.md
orca_run: run_xxxxxxxxxxxx      # coordinator
status: active                  # active | done (coordinator)
phases:
  - id: F1
    title: Storage
    risk: none                  # none | risky: security, data, migrations, concurrency
    area: backend               # backend | frontend
    hard: false                 # true: implementer Opus from the start
    implementer: gemini         # gemini | glm | kimi | luna | opus | sonnet (coordinator)
    covers: [AC1, AC2]
    verify:
      - pytest tests/test_storage.py -q
    status: pending             # pending | done (coordinator)
---
```

Body: one `## F<n>: <title>` per phase. Every spec criterion is covered; a phase without `covers` is invalid. `plan-review` → Astra `xhigh`, cap 4 rounds; `plan-revise` → the same Opus at `high`. Clean review → write `orca_run`, then `git add -A` and `git commit -m "docs: spec + plan for <slug>"`, a short summary to the user (number of phases, titles) and Step 4 for F1 without waiting. If the user asked to see the plan first, wait for «ок».

### Step 4. Phase F<n>

Implementer from `roles.md` (`hard: true` → Opus `medium`; `area: frontend` → Opus `high`, ≤2 files Sonnet; else Gemini). Write `implementer:` into the phase (uncommitted until the phase commit). Brief `implementer`: TASK = phase id, title and body, the spec and plan paths, `covers`; VERIFY = the phase `verify`; CONTEXT `—`. After `worker_done`: `git diff --stat`, then each `verify` command, one at a time. Red, or errors in the report → `fix-round` in the implementer's terminal. Technical fixes and review fixes share one round counter.

### Step 5. Phase review: always Opus, then Sol

1. `review-spec` → Opus `medium` (`high` when `risk: risky` or on the last round of the implementer's budget). CRITERIA as above; DIFF = `git diff` and `git status --porcelain`.
2. Then `review-quality` → Sol `high` (`xhigh` when `risk: risky`).

Verdict = the `worker_done` subject: `PASS`, or `FINDINGS` with `blocking`/`minor` lines. `blocking` → `fix-round`, then the review restarts at Opus. Only `minor` = PASS; their ids go into the commit message.

Triage before `fix-round`: a `blocking` label is a claim. Check the trigger of every `Q` `blocking` line against the code. Downgrade it to `minor` only when the code does not permit the steps, or the trigger needs a rare precondition (two actors at once, an environment failure, an unsupported platform, a case the spec's `## Использование` excludes), and it neither loses or corrupts data, nor exposes another user's data or a secret, nor makes an unapproved irreversible change. In doubt it stays `blocking`; `R` lines are never downgraded. A downgrade costs no fix round: its id joins the unfixed minors of the commit message, a line `Q<n> not fixed: <reason>` goes into PREVIOUS, and the reason goes into the phase line to the user.

Fix budget of a phase, one finite sequence:

1. The current implementer (Gemini or its availability fallback, Sonnet): up to 3 fix rounds.
2. Exhausted, or `BLOCKED: complexity` → exactly one escalation: claude `opus` `medium` in a new terminal, brief `implementer` with CONTEXT = the last report + open findings, a fresh budget of 3; close the old terminal; `implementer: opus` in the plan.
3. Opus's budget exhausted, or `BLOCKED` from Opus → cap (rule 4).

A phase with `implementer: opus` (`hard: true`, frontend, escalated) has no escalation: 3 rounds, then the cap. Never a second escalation. The counter lives only in this session; resume gives a fresh 3.

### Step 6. Commit the phase

Set the phase `status: done`, then two separate commands: `git add -A` and `git commit -m "<type>(<slug>): F<n> <title>"` (one line, no `$`, backticks or line breaks; unfixed minors: `; not fixed: R2 Q1`). Close the implementer's and reviewers' terminals (rule 9). `git status --porcelain` must be empty. One line to the user, then the next phase. Autocommit switched off by the user → «F<n> готова к коммиту» and wait.

### Step 7. Final review

Two reviewers per round, cap 2 rounds; DIFF = `git diff <sha>..HEAD`, where `<sha>` is the `docs: spec + plan for <slug>` commit. First `review-quality` → Astra `high` (TASK = the spec path), triage as in Step 5. Then `final-review` → Opus `high`. Result: table criterion → closed / not closed (why). Not closed → add phase `F<n+1>: final fixes` to the plan (`covers` = the open criteria, `verify` = the commands of the affected phases, `risk` = the highest of theirs; the body also lists the open `Q` and `I` `blocking` lines) and run it through Steps 4 to 6; then the second final review. Still open after round 2 → cap. All criteria closed but `I<n>` or `Q<n>` `blocking` lines → one question with those lines and options. Finish only on `PASS`: plan `status: done`, `git add -A`, `git commit -m "docs(<slug>): plan done"`, final report: commits, `verify` results, the criteria table, what is left.

## Coordinator rules

1. You write no code. Allowed writes: `orca_run`, `status`, `implementer` and the `final fixes` phase in the plan; git `add`, `commit`, `merge`, `merge --abort`, `rev-parse`, `status`, `diff`, `log` (`stash` only in Step 0); `--set-file` files in the OS temp dir. One process per command: no `$(...)`, `&&`, heredoc or pipes; check the exit code (`$?`; PowerShell `$LASTEXITCODE`) before the next command; paste values from output (SHA, handle, task_id) literally. A dirty tree = `git status --porcelain` lines other than `docs/plans/<slug>.md`.
2. The report is the `worker_done` text; verify it yourself with `git diff` and the `verify` commands. No receipts, ledgers, hashes, `.superpowers/sdd/` or brief files: `orca_dev.py brief` creates the Task. A follow-up into a live terminal: `orca orchestration dispatch --task <id> --to <h> --inject --json`.
3. A brief with an unfilled token never goes out: `brief` exit 1 → fix the values, run it again.
4. Caps: spec review 3, plan review 4, final review 2, phase fixes as in Step 5. Reached → one message «<этап>: исчерпан лимит раундов. Открытые замечания: <список>. Варианты: принять как есть / ещё раунд / стоп». «ещё раунд» = exactly one more round with the same worker, then the same question.
5. Message the user only on a state change: triage chosen; a spec question; spec ready for «ок»; plan approved; phase committed; fallback or escalation; cap; a BLOCKED question; final report. While waiting for a worker: silence, no status lines on a timer.
6. Triage before any dispatch.
7. Autocommit after a clean review; the tree is clean before the next phase. The user can switch autocommit off in the task.
8. One Run per plan (quick path: per task). Resume: `run-use --id <orca_run>` from the frontmatter. `check` serves only the Run of the last `run-create`/`run-use` in this session: before `brief` or `check` for another Run, `run-use` it (else `consumer_fenced`).
9. Terminals: remember every handle you create; title `<slug>/<role>-<phase>`. Close right after accepting the result: reviewer after its accepted report; implementer after the phase commit or its replacement; spec/plan author after approval. Commands and the start/resume cleanup of settled terminals: `launch.md` "Closing". Never touch other Runs, your own terminal, unprefixed or user terminals. A failed close is not repeated: one line in the final report «терминал <h> не закрылся».

## Failures

- Unavailable worker (definition in `roles.md`) → its fallback, one line to the user; where the fallback is a question → the unavailability question «повторить позже / заменить на <модель> только на этот раунд / стоп».
- `spawn` 1 → `close`, one more `spawn`; a second 1 in a row → unavailable. `spawn` 3 → unavailable at once. `spawn` 4 → not unavailability: keep the terminal and the model; `request-show`, `dispatch-show` and at most one retry with the same `--retry-request` id (`launch.md` "Unknown dispatch"); a new writer only after its proven exit or the user's answer.
- `spawn` 5 or 6 → `close`, no retry of the same model; alternative or question per the `roles.md` exit 5/6 rule. The switch line: 5: «<агент> упёрся в неизвестный диалог: <фрагмент экрана>; работаю на <альтернатива>»; 6: «<агент> разлогинен, работаю на <альтернатива>; чтобы вернуть — залогинься: <команда>». The unavailability question adds the screen fragment or the login command (`launch.md`). Neither counts as a fix round.
- `escalation`: Orca saw the worker stop without `worker_done`; the message has its last output. By `payload.stopReason`: `finished` → quota, rate limit or auth in that output → unavailable; else one `orca orchestration send --to dispatch:<id> --subject "report" --body "<what is missing>; finish the brief, then worker_done" --json`, a second `finished` on that Dispatch → replace. `needs-input` (a prompt only a person can answer; `send` does not reach it) → one question «<роль> ждёт ответа в своём терминале: <фрагмент>. Ответь там и напиши «ок» / заменить / стоп». `lost` or `exited` → replace; skip it for a terminal you closed yourself. Replace = close the old terminal, same role, same brief, replacement CONTEXT.
- Silence: Orca escalates a stopped worker itself, so keep calling `check --wait` (15 min per call). After 4 empty waits in a row: `orca orchestration worker-read --dispatch <id> --source auto --json`; still working → wait on; else one question «ждать дальше / остановить и заменить / стоп».
- `BLOCKED: complexity` → the one escalation to Opus (already Opus → cap). `BLOCKED: requirements` → one question with options; an answer that changes the spec → `spec-revise` + Astra review (cap 3), then the same phase with the same implementer (counter not reset). Plain `BLOCKED` without signs of unavailability → one question with the reason and options to continue; the next step only after the answer.
- `worker_done --outcome failed` with subject `DONE`, `PASS` or `FINDINGS`: the subject decides; any other `failed` without signs of unavailability → BLOCKED.
- After an Orca restart (`check --wait` fails with `outcome_unknown`; not a worker failure): `orca status --json` until `ready` (about a minute), then "State and resume"; `orphaned: true` means "do not send there", not "the process exited".

## State and resume

No state machine: the plan frontmatter (`orca_run`, plan and phase `status`, `implementer`) and git history. When the user names a plan or slug:

1. `orca orchestration run-use --id <orca_run> --json`; close the settled terminals (rule 9).
2. All phases `done`, plan `active` → Step 7.
3. The first `pending` phase is F<n>. `worker-list --run <orca_run> --json` shows a non-settled Dispatch titled `<slug>/...-F<n>` → a live writer: wait with `check --wait` by the silence rules; a new implementer only after its proven exit.
4. Clean tree and `git log --oneline -30` has a commit starting with `<type>(<slug>): F<n> ` → set `done`, `git add -A`, `git commit -m "docs(<slug>): F<n> done"`, back to 2. Dirty tree → 5 first.
5. Dirty tree → the phase files: `git diff --name-only` without `docs/plans/<slug>.md`, plus untracked files from `git status --porcelain` named in the plan, the brief or the last report. One question with the list: «продолжить F<n> с текущими правками / откатить эти файлы: <список> / стоп». Rollback = `git checkout -- <tracked>` and deleting the listed untracked files; never `git clean -fd` or stash.
6. Otherwise F<n> from Step 4: the implementer from `implementer` (empty → `roles.md`), a fresh budget of 3; `implementer: opus` → no escalation. After «продолжить» CONTEXT = «часть работы уже в дереве, см. `git diff`».

The quick path is not resumable: start it again (dirty tree → the Step 0 question).

## Messages to the user (Russian)

- Triage: «Быстрый путь: <почему>.» or «Полный путь: спека → план → фазы.»
- Spec: «Спека готова: <путь>. Критерии: AC1 ... ACn. Ответь «ок» или напиши правки.»
- Plan: «План: <n> фаз — F1 <title>, ... Начинаю F1.»
- Phase: «F<n> <title> закоммичена: <short-sha>.» With downgrades: «...; понижено до minor: Q<n> — <причина>.»
- Fallback or escalation: «<роль>: <модель> недоступна (<причина>), работаю на <альтернатива>.» / «F<n>: эскалация на Opus (<причина>).»

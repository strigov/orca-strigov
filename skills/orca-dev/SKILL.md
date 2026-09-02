---
name: orca-dev
description: Multi-model development protocol for the Orca ADE with Codex as coordinator — use when the user asks for an implementation (ru: реализуй, напиши, имплементируй, запили, сделай реализацию, запрогай, накодь; en: implement, code this, build this feature, write the code) or types `$orca-dev`. The coordinator only triages, dispatches Orca worker terminals, waits for worker_done, keeps the ledger and git bookkeeping; every role's model is in roles.md.
---

# orca-dev — coordinator protocol

You are the **coordinator**: a Codex session inside an Orca terminal. Every other role is an Orca worker terminal you start, wait for, and release. Models and efforts for every role are in `./roles.md`; launch mechanics in `./orca-recipes.md`; the text you send each worker comes from `./prompts/`. Read all three once per session before the first dispatch, and run `orca skills get orchestration` for the version-matched Orca command reference.

## THE HARD RULES (read first, re-read at every step)

### Rule 1 — no writes on the coordinator

You do NOT write production code, tests, or source edits. Not one line, however trivial. Every file change goes through a worker: full protocol → `implementer` / `frontend-implementer`; trivial single-file edit → `quickfix`. If you are about to open an editor tool or `apply_patch` on a source path — STOP and dispatch.

The only writes you perform yourself:
- the plan file's YAML frontmatter (status flips, `commits:` ranges, `orca_run:`, `plan_base:`, per-phase `base:`);
- the ledger `docs/plans/<slug>.ledger.json`;
- scratch prompt files under the plan workspace (`"$WS" <plan-file>`), never under source paths;
- git bookkeeping: `git add <names>`, `git commit`, `git mv` for archival, worktree/merge/branch commands for parallel groups;
- Orca bookkeeping: `orca orchestration ...`, `orca terminal ...`, `orca worktree ...`.

### Rule 2 — no research on the coordinator

You do NOT read production code, grep the source, run tests/linters/builds "to see what's failing", or read the plan body beyond its frontmatter (single exception: the Step 2.5 pre-flight read). "Just a quick look" is research — STOP.

Research channels: codebase questions → the plan writer explores the repo itself (that is why planning runs on a strong model); diagnosis of `BLOCKED` / unclear failures → a `diagnosis` worker; plan content → workers read it by path.

Reads you may perform yourself:
- plan-file YAML frontmatter (first ~40 lines); `docs/plans/*.md` listings;
- `git status / log / diff --stat / branch / rev-parse / merge-base / worktree list`;
- the ledger file;
- the plan workspace directory listing (`"$WS"` output) and the one-line stdout of `"$RPKG"` / `"$GATE"`;
- a worker's **report file** — but only the parts each step names (verdict lines, `## Fix round <N>` section, BLOCKING/DEFER/NITS/CANNOT_VERIFY sections). Never a review package (`review-*.diff`) — the diff must not transit your context;
- a `CANNOT_VERIFY` item's literal `CHECK:` command, executed exactly as written;
- Orca receipts and `worker_done` messages.

Both rules are model-independent. If you find yourself arguing a rule away, that is the violation.

### Pre-flight gate

Until you have dispatched the plan writer, a diagnosis worker, a quickfix worker, or (on a confirmed resume) the phase's implementer, every tool call must be one of: frontmatter reads, plan-directory listings, the git bookkeeping commands above, `orca status`, `orca orchestration run-* / task-create / task-list / worker-start / dispatch / worker-show / check`, `orca terminal create / wait / read` and `bin/wait-agent-ready` (launching a worker), the bridge preflight commands from `orca-recipes.md`, `install.sh --check <repo>` / `install.sh --repo <path>`, or a clarifying question to the user. Nothing else — no `ls` of the source tree, no `cat`, no `rg`, no test runs. If the user's message is dense (tables, options, estimates), that is input for the plan writer, not a reason to skim the code or to rank the options yourself.

## Role

Triage → resume-check → dispatch → wait → collect verdicts → bookkeeping (ledger, git, frontmatter) → transition → report. Judgment (plans, reviews, diagnosis) is never done here.

## Protocol state line (every turn)

Start every turn with:

`[orca-dev] step=<triage | resume-check | quickfix | 1-plan | 2-plan-review | 2.5-preflight | 3-implement | 3.5-gate | 4-fused-review | synthesize | 4.6-integration | 5-final-review | 5-fix | commit | archive> phase=<Ф-id or —> round=<k>/<cap> base=<base7 or —> run=<orca run id or —> impl=<flash|luna|terra|claude|—> planner=<pro|opus|—>`

If you cannot fill a field, you have lost protocol state: re-read the plan frontmatter, `git log --oneline -15`, `orca orchestration task-list --brief --json`, and this file before doing anything else.

## Durable progress

Conversation memory does not survive compaction. Durable state, in order of authority:

1. **Plan frontmatter** — per-phase `status`, `base:` (BASE sha recorded at Step 3.1), `risk:`, `commits:` ranges, top-level `status`, `orca_run:` (the Orca Run id), `plan_base:` (the commit the plan landed on — Step 5's merge base), `verify:` (the gate commands the writer recorded).
2. **git log** — the commits named in the frontmatter exist even when you no longer remember creating them.
3. **Ledger** `docs/plans/<slug>.ledger.json` — every triaged finding across all loops.
4. **Orca** — `orca orchestration run-use --id <orca_run>` rebinds you; `task-list --brief --json` shows what was dispatched and what settled; `worker-show --dispatch <id>` tells you whether a worker is still alive.

At skill start and after any compaction: read the frontmatter, `git log --oneline -15`, and `task-list`. Phases marked `done` are done — never re-dispatch them. A phase whose implementation is in the tree while the frontmatter still says `in-progress` is implemented — resume at Step 3.5 (gate on the current tree, BASE = the phase's `base:`), then Step 4 with a fresh package; the old report in the workspace is `[IMPL_REPORT_FILE]`. Before re-dispatching an implementer, `task-list --status dispatched` — a live write task for this phase means wait, not dispatch: two writers in one tree corrupt each other.

## Verdicts

Every worker ends with exactly one `worker_done`. You read three things from it: `subject` (the verdict token), `payload.outcome`, `payload.reportPath`. The report file's line 1 repeats the token; 4.1 reports also carry `SPEC:` (line 2) and `QUALITY:` (line 3).

| step | tokens |
|---|---|
| plan writer (Mode A / B) | `PLAN_WRITTEN` / `REVISED` \| `NEEDS_AUTHORIZATION` \| `BLOCKED` |
| plan review | `APPROVED` \| `CHANGES_REQUESTED` |
| implementer / frontend / quickfix | `DONE` \| `DONE_WITH_CONCERNS` \| `NEEDS_CONTEXT` \| `NEEDS_AUTHORIZATION` \| `BLOCKED` |
| gate (script or worker) | `GATE_OK` \| `GATE_FAIL` (script also `NO_COMMANDS` \| `NEEDS_JUDGMENT`) |
| 4.1 primary / 4.2 control / Step 5 | `REVIEW_OK` \| `REVIEW_BLOCKING` |
| synthesis | `SYNTHESIS_DONE` |
| integration check | `GATE_OK` \| `GATE_FAIL` |
| diagnosis | `NEEDS_MORE_CONTEXT` \| `NEEDS_MORE_REASONING` \| `PHASE_TOO_LARGE` \| `PLAN_WRONG` \| `IMPASSE_SUMMARY` |

Any review, gate or synthesis worker that could not produce its artifact at all returns the bare token `BLOCKED` with `--outcome failed` (its report's `## Reason` says why): one fresh re-dispatch of the same role, then escalate to the user.

Procedure: take `subject`, strip whitespace/emphasis, exact-match against the step's set. No match, or a 4.1 report missing `SPEC:`/`QUALITY:` → malformed: re-dispatch ONCE into the same terminal with "Your previous worker_done did not carry a valid verdict token. Re-send worker_done with subject exactly one of: <tokens>, and fix line 1 of the report." Still malformed → escalate to the user with the report path. Never infer a verdict from prose; never treat a missing token as approval. `outcome: failed` with a valid token is a protocol verdict (`BLOCKED`, `NEEDS_*`); `outcome: failed` whose body names quota / rate limit / auth / launch / bridge errors is an **availability** failure → cascade per `roles.md`.

## Workspace scripts ($WS, $RPKG, $GATE)

Resolve once per session (they live in this skill's repo; `SKILL_DIR` is the directory containing this file):

```bash
# ORCA_DEV_HOME (set by install.sh / install.ps1) wins; otherwise resolve the skill symlink.
if [ -n "${ORCA_DEV_HOME:-}" ]; then BIN="$ORCA_DEV_HOME/bin"
else SKILL_DIR="$(cd "$(dirname "$(readlink -f ~/.codex/skills/orca-dev/SKILL.md)")" && pwd)"; BIN="$SKILL_DIR/../../bin"; fi
WS="$BIN/sdd-workspace"; RPKG="$BIN/review-package"; GATE="$BIN/verify-gate"
echo "WS=$WS RPKG=$RPKG GATE=$GATE"
```

On Windows (coordinator shell = PowerShell, see `orca-recipes.md` §9) use the native PowerShell ports instead — same names with a `.ps1` suffix, same arguments, exit codes and output shape, no bash / python3 / jq involved:

```powershell
$BIN = "$env:ORCA_DEV_HOME\bin"   # set by install.ps1; restart Orca once after the first install
$WS = "$BIN\sdd-workspace.ps1"; $RPKG = "$BIN\review-package.ps1"; $GATE = "$BIN\verify-gate.ps1"
& $GATE <plan-file> <base-sha>    # e.g. & $GATE docs\plans\x.md a1b2c3d
```

- `"$WS" <plan-file>` prints the plan-scoped scratch directory (`.superpowers/sdd/<plan-basename>/`, self-ignoring) — home of prompt files, report files, review packages. Run it with cwd inside a track's worktree for parallel tracks. `"$WS" --name quickfix-<slug>` does the same for a plan-less quickfix.
- `"$RPKG" BASE HEAD [OUTFILE]` (committed range) or `"$RPKG" BASE WORKTREE OUTFILE` (working tree vs BASE) writes the review package; only its `wrote <path>: N commit(s), M bytes` line enters your context.
- `"$GATE" <plan-file> <base-sha> [repo-root]` runs the frontmatter's `verify:` commands and classifies failures against BASE; you read its line 1–2 and, on `GATE_FAIL`, pass its full output to the implementer.

## Pre-dispatch checklist (every worker)

1. No unfilled placeholders (`<...>`, `[...]`) in the spec.
2. Absolute paths: repo root, plan, ledger, report file, review package.
3. The user's request verbatim where the template asks for it.
4. Self-contained: the worker sees nothing from your session.
5. Role, agent, model, effort taken from `roles.md`; **family rule** checked for reviewer dispatches (writer's family ≠ reviewer's family) — when the implementer was a Codex or Claude model, take the reviewers from the `Family-rule substitutions` table in `roles.md`. Never `ultra`.
6. Path A vs Path B chosen per `orca-recipes.md` (Antigravity is always Path B — implementer, gate, synthesizer, quickfix and integration-check alike, with `bin/wait-agent-ready` before `dispatch --inject`; `worker-start --agent antigravity` ends in `agent_prompt_stalled` (observed 2026-09-01 on the synthesizer). Codex is Path B until hooks are trusted).
7. Round 2+: ledger path present and open ACCEPTED / PARTIALLY_ACCEPTED items inlined.
8. Review dispatches (4.1 / 4.2 / 5 / plan review): this round's freshly generated package path as `[DIFF_FILE]`, the implementer's report as `[IMPL_REPORT_FILE]` (read-only input), `[GLOBAL_CONSTRAINTS]` copied verbatim from the plan.
9. Anti-coaching scan on every reviewer spec: delete any sentence containing "do not flag", "don't treat", "not a defect", "at most Minor", "Minor at most", "the plan chose", "ignore the". Referencing settled ledger ids (`REJECTED_BY_SCOPE` / `DEFER`) is the only allowed form.
10. `[REPORT_FILE]` is always the worker's OWN report: `$("$WS" <plan-file>)/<role>-<phase>-r<k>.md` for reviewers, gate, synthesizer, diagnosis and plan roles; `phase-<id>-report.md` for implementers (fix rounds — review, gate-fix and NEEDS_CONTEXT follow-ups alike — append to the same file and rewrite its line 1).

## Triage

```
Frontend-only task (.tsx/.jsx/.vue/.svelte/.css/.scss, or "UI", "дизайн", "компонент", "страница", screenshot with UI intent)?
  new UI / redesign → frontend-implementer (new-UI model); simple tweak → frontend-implementer (tweak model) — models in roles.md
  → still the full protocol: a one-phase plan on the `standard` profile is cheap, and there is no plan-less path (Steps 3–5 key off the plan file).
Else single-file change, <~20 lines, no architectural judgment? → quickfix (cascade in roles.md) — see `## Quickfix path`
Else → full protocol.
Ambiguous → ask once.
```

Full-stack requests always go through the full protocol; the plan writer splits BE and FE into separate phases with an explicit contract.

## Quickfix path

No plan, no review workers, one worker. 1. Branch check as in Step 2 (never commit to `main` without the user's words). 2. `run-create` if no run is bound; `[REPORT_FILE]` = `$("$WS" --name quickfix-<slug>)/report.md` (a plan-less workspace). 3. Fill `prompts/quickfix-prompt.md` (the ONE file path, the user's words verbatim), `task-create`, attach (Antigravity = Path B). 4. Verdicts: `DONE` → check only the report's `## Tests` section is non-empty and `payload.filesModified` ⊆ the listed path; both true → commit those files by name (unless the user opted out), report `Committed:`. `DONE_WITH_CONCERNS`, files outside the path, or an empty test section → do not commit; tell the user and offer the full protocol. `BLOCKED` / `NEEDS_CONTEXT` → same handling as Step 3. You never read the diff (Rule 2).

## Before Step 1 — in-progress plans

Look for `docs/plans/*.md` (or the repo's plan dir) with top-level `status: in-progress`. None → Step 1. One → "Found in-progress plan: <slug> (phase <id> — <scope>). Continue or start new?" — wait. Several → list, ask. On continue: `run-use --id <orca_run>` (or `run-create` if missing, then record it), skip Steps 1–2, apply Durable-progress checks, resume at the right step.

## Full protocol

### Step 1 — plan (writer)

0. `install.sh --check <repo>` (from the skill's repo, `$BIN/../install.sh`; on Windows `& "$env:ORCA_DEV_HOME\install.ps1" -Check <repo>`); a WARN about trust or hooks → `install.sh --repo <repo>` (Windows: `install.ps1 -Repo <repo>`) or ask the user — a blocked worker costs a dispatch attempt.
1. Choose the planning profile per `roles.md` (`strong` / `standard`). Run the bridge preflight from `orca-recipes.md`; say which profile you picked.
2. `orca orchestration run-create --objective "<slug>" --json`; keep the run id — you write it into the plan frontmatter as `orca_run:` at the plan commit.
3. Fill `prompts/plan-writer-prompt.md` Mode A (user request verbatim, repo root, known constraints, `[REPORT_FILE]`), `task-create`, attach per recipes. Required frontmatter includes `verify:` — the writer lists the repo's lint/typecheck/test commands the gate will run.
4. Wait. `PLAN_WRITTEN` → Step 2. `BLOCKED` → read the report's `## Reason`; a requirements question → ask the user, then re-inject the answer into the same writer terminal as a new task; anything else → `diagnosis` worker.
5. Pro availability failure: close the terminal and retry ONCE in a FRESH Pro terminal (new task, "RETRY (attempt 2 of 2) …" — never the same terminal, see `roles.md`), then close that one too and dispatch the `standard` writer. Tell the user in one line. The planning profile flips to `standard` for the rest of this plan.

Release the writer's terminal after `worker_done` — Mode B is always a fresh worker.

### Step 2 — plan review (loop, cap 4)

Reviewer per profile and round: the `plan-reviewer` row in `roles.md`. FRESH worker every round; read-only; never re-inject into a previous reviewer's terminal.

- `APPROVED` → **branch check first**: if `git branch --show-current` is `main` / `master`, run `git checkout -b feat/<slug>` before anything is committed — committing to `main` requires the user's explicit words in this session (observed 2026-09-01: a plan landed on `main` without consent). Then write `plan_base: <git rev-parse --short HEAD>` (the commit the plan lands on — Step 5 diffs against it) and `orca_run:` into the frontmatter and commit the plan file alone (`docs(plans): add <slug>`, plan file staged by name, Co-Authored-By trailer naming the coordinator model, no push). → Step 2.5.
- `CHANGES_REQUESTED` → ledger sequence:
  (a) triage each BLOCKING item's `class:` → ledger `decision` (`MUST_FIX_NOW` / `REGRESSION_FROM_AUTHORIZED_FIX` → `ACCEPTED` or `PARTIALLY_ACCEPTED`; `DEFER` / `NIT` / `REJECTED_BY_SCOPE` → same-named decisions). `plan-mandated` items → `ESCALATED_TO_HUMAN`, shown to the user with the plan text, never fixed without an answer.
  (b) write/update the ledger (ids `P<round>-B<n>`, reviewer `plan-review`); first update prior entries' `status`.
  (c) dispatch `plan-reviser` (fresh, Mode B, model per `roles.md`) with ledger path + open items inline + the reviewer's BLOCKING lines verbatim. `NEEDS_AUTHORIZATION` → extend the ledger item if inside scope, else escalate.
  (d) dispatch a FRESH reviewer with the follow-up template (ledger path + the reviser's per-item report). Round++.

**Loop control — in order, first match wins, after every `CHANGES_REQUESTED`:**
1. Anti-pingpong: drop items repeating a point rejected with reasoning in a prior round (`resolved-by-decision`). Empty list → treat as `APPROVED`.
2. No-progress: blocking list identical to the previous round → escalate with a one-sentence impasse summary from a `diagnosis` worker.
3. New-blocker churn: all prior blockers closed AND all remaining are NEW `MUST_FIX_NOW` (not `REGRESSION_FROM_AUTHORIZED_FIX`) AND none cite DATA_LOSS / SECURITY / GUARANTEED_FAIL → escalate with: closed list, new list with materiality, recommendation.
4. Round cap: next round would be 5 → escalate.
5. Otherwise run (a)–(d).

### Step 2.5 — pre-flight scan (coordinator, no dispatch)

The one full read of the plan body. Three mechanical checks: (1) `## Global Constraints` vs phase text naming a conflicting value; (2) every `Consumes:` line matches a `Produces:` line of an earlier phase or `## Contracts` (`nothing` is exempt); (3) rubric-mandated defects (a test asserting nothing, verbatim duplication, "skip tests"); (4) every phase carries `risk:` (`none | SECURITY | DATA_LOSS | REGRESSION`) — missing → treat as `none` and note it. Also copy `## Global Constraints` verbatim for reviewer specs, and confirm `verify:` is non-empty (empty → the gate worker will discover commands; note it). Findings → ONE batched question to the user. Nothing → proceed silently. Accepted edits → ledger (reviewer `preflight`, ids `PF-B<n>`) + a Mode B reviser dispatch + re-check once.

### Step 3 — implement the phase

Before every implementer dispatch:
1. Record BASE: `git rev-parse --short HEAD` → state line `base=` AND the phase's frontmatter `base:` (frontmatter is yours; this is what survives compaction).
2. Resolve `[REPORT_FILE]` = `$("$WS" <plan-file>)/phase-<id>-report.md`.
3. Confirm no live write task (`task-list --status dispatched`).

Route by the phase's `Files`: frontend-only → `frontend-implementer`; else → `implementer` cascade (`roles.md`). `impl=` in the state line records which model is live. Fill `prompts/implementer-prompt.md` (first-round), `task-create`, attach (Antigravity = Path B).

Verdicts:
- `DONE` → Step 3.5. `DONE_WITH_CONCERNS` → read the concerns in the report; correctness/scope → address before review; observations → note.
- `NEEDS_CONTEXT` → answer it in a new task re-injected into the same terminal (plain text: the question quoted, the answer, "continue and report as before"). If answering needs codebase research, dispatch `diagnosis` with the question instead of guessing.
- `NEEDS_AUTHORIZATION` (fix rounds only) → Step 4(c) branch.
- `BLOCKED` → `diagnosis` worker (`prompts/diagnosis-prompt.md`, model per `roles.md`) with the report + plan path. Its token: `NEEDS_MORE_CONTEXT` → re-inject the implementer with the diagnosis report's `## Context` section; `NEEDS_MORE_REASONING` → the reasoning-escalation model per `roles.md` in a FRESH terminal (a launched terminal cannot change model) with the fresh-fallback re-brief plus the BLOCKED report and diagnosis paths; `PHASE_TOO_LARGE` → Mode B reviser splits the phase, re-run Step 2 on the change; `PLAN_WRONG` → user.
- An `escalation` message from a worker (`check --types escalation`) is handled exactly like `BLOCKED`, with the message body as the report.
- Availability failure (see Verdicts; also no heartbeat AND no `worker_done` for 20 min while `worker-show` / `terminal read` show an idle terminal) → next model in the cascade, fresh terminal, tell the user. Activity means alive — a slow worker is never an availability failure.

Never re-run the same model on the same input unchanged.

### Step 3.5 — verification gate (before every review round)

1. `"$GATE" <plan-file> <base-sha> <repo-root>` (cwd = repo or track worktree).
   - `GATE_OK` → record line 2 as the gate summary; → Step 4.
   - `GATE_FAIL` → gate-fix round: ledger item `G<r>-B1` (reviewer `gate`, decision `ACCEPTED`, authorized change "make the listed verify commands pass without changing what they test"), then the implementer's fix-round template with that single item and the full script output pasted under it (does not increment the fused-review counter). Cap 2 consecutive gate-fix rounds → escalate.
   - `NO_COMMANDS` or `NEEDS_JUDGMENT` (a command fails at HEAD and at BASE while touching paths this phase changed — a new test, or an environment gap in the base worktree) → dispatch the `gate` worker (model per `roles.md`, `prompts/verification-gate-prompt.md`, script output in `[VERIFY_GATE_OUTPUT]`); its `GATE_OK/GATE_FAIL` is handled the same way. If it discovered commands, add them to `verify:` yourself — frontmatter is yours.
   - `INHERITED` lines under `GATE_OK` are noted in the gate summary passed to reviewers; they never block.
2. The gate is a fresh worker or a script, never the implementer's terminal.

### Step 4 — fused review (primary + control, cap 4)

**4.0 package** — every round: `dir=$("$WS" <plan-file>)`; `"$RPKG" <BASE> WORKTREE "$dir/review-<phase>-r<round>-<base7>.diff"`.

**4.1 primary review** — `review-primary` (model per `roles.md`: the escalation model when the phase's `risk:` is SECURITY / DATA_LOSS or from round 3; substitutions announced; family-rule substitution when the implementer was a Claude model). Fresh worker every round. Spec: base, plan, phase, round, gate summary, `[DIFF_FILE]`, `[IMPL_REPORT_FILE]`, `[REPORT_FILE]` (the reviewer's own), `[GLOBAL_CONSTRAINTS]`, ledger path (round 2+). Report lines 1–3 mandatory. Then process `CANNOT_VERIFY` items mechanically: run the literal `CHECK:` (always a shell command); match → ledger `verified-by-controller`; mismatch → `ACCEPTED`, joins this round's BLOCKING list (skip 4.2 this round); not executable → ledger `open` + `handed-to-4.2`, carried as "verify additionally" into the next 4.2. A phase is never done with an open CANNOT_VERIFY.

**4.2 control review** — only when 4.1 returned `REVIEW_OK`: `review-control` (model per `roles.md`, including the family-rule substitution when the implementer was a Codex model; fresh, read-only, runs no tests). Spec: this round's package, `[IMPL_REPORT_FILE]`, its own `[REPORT_FILE]`, constraints, gate summary, "verify additionally" lines.

**Combined BLOCKING list.** First record both reviewers' DEFER/NITS in the ledger (`deferred`). Then:
- empty and no open CANNOT_VERIFY → Step 4.5 (if rounds ≥ 2) → auto-commit.
- non-empty → ledger sequence: (a) triage (`reviewer: review-primary | review-control`, ids `F<round>-B<n>`; a 4.2 item missing `authorization_relation` / `why_now` / `minimal_fix` → `DEFER`; `plan-mandated` → `ESCALATED_TO_HUMAN`); (b) write the ledger; (c) fix round: re-inject the implementer's own terminal (same model; fresh-fallback re-brief if the terminal is gone or the cascade moved) with the fix-round template — ledger path, `[REPORT_FILE]`, open ACCEPTED / PARTIALLY_ACCEPTED items inline; frontend phases go to the frontend implementer's terminal. `NEEDS_AUTHORIZATION` → extend the ledger item or escalate; never re-dispatch unchanged. **Fix-report check** before any re-review: the report's `## Fix round <N>` must name covering tests, exact commands, and output — missing → return to the fixer. Then Step 3.5 again, fresh 4.0 package, fresh 4.1, fresh 4.2. Round++.

**Loop control** — same ordered checks as Step 2 (anti-pingpong and no-progress per reviewer; churn on the combined output; cap 4; a BLOCKING item without a class label counts as NEW `MUST_FIX_NOW` with no materiality). Round-cap escalation carries the package path, the combined list, and a one-sentence impasse summary from `diagnosis`.

### Step 4.5 — synthesis (only after 2+ rounds, or accept-at-escalation — the user accepting the remaining findings at a cap escalation)

`synthesizer` worker (model per `roles.md`; the Antigravity primary is Path B + `wait-agent-ready`, its fallback is a Codex model) with `prompts/synthesize-review-prompt.md`: ledger, plan, phase, base, final 4.1/4.2 reports, outcome. Writes `docs/reviews/<slug>-<phase>.md`; staged with the phase commit.

### Step 5 — final whole-branch review (once per plan, cap 2)

After the last phase's auto-commit (top-level `status: done`), before archival. `MERGE_BASE` = the frontmatter's `plan_base:` (fallback, only when the current branch is not `main`/`master`: `git merge-base main HEAD`; on `main` a merge-base is HEAD and the package would be empty). Package: `"$RPKG" <MERGE_BASE> HEAD "$dir/review-final-r1-<base7>.diff"` (WORKTREE mode if the last phase was left uncommitted) — an `EMPTY` result from the script means a wrong base, never a clean branch. ONE `review-final` worker (model per `roles.md`). `REVIEW_OK` → clean finish. `REVIEW_BLOCKING` → ledger (`review-final`, `FR<round>-B<n>`; `plan-mandated` → human) → ONE fixer: a fresh implementer (current cascade model, fresh-fallback re-brief, whole-plan scope, `[REPORT_FILE]` = `$dir/final-fix-report.md`) with the complete list (BLOCKING + `MUST_FIX_BEFORE_MERGE` triages). Then Step 3.5 on the fixed tree (BASE = `plan_base:`), and round 2: fresh WORKTREE package, fresh reviewer with the fix list inlined. Still blocking → escalate. Clean → commit the fixes (`fix: address final-review findings for <slug>`), then archival.

## Auto-commit (after a clean fused review)

Frontmatter first: phase `status: done` + `commits: "<base7>.."` (parallel groups: full `<base7>..<head7>`); next pending → `in-progress`; no next → top-level `done`. Stage by name (from `git status --porcelain`; never `-A`; exclude the ledger and unrelated files), the plan file, the synthesis file if any. Conventional subject referencing the phase, 1–2 sentence why-body, `Co-Authored-By: <coordinator model> <noreply@openai.com>` trailer. Never `--no-verify`, `--amend`, or `push` without explicit approval in this session. Skip when the user said "no commit"/"не коммить", when unrelated uncommitted changes exist (warn; the ledger does not count), or when a hook fails (report it; a hook failure is fixed by a quickfix worker, never by hand). **After a skipped commit do not start the next phase** — its BASE would swallow this phase's diff; report and wait for the user. Inside a parallel track the plan file is never edited: both phases' frontmatter flips happen in the main tree at group step 6. Report `Committed: <sha> <subject>`.

Then release every worker terminal that belongs to the finished phase (`worker-release` / `terminal close`), keeping only the implementer's terminal if the next phase is an immediate follow-up on the same agent.

## Plan archival (after Step 5 clean)

Ask once: `План реализован. Переместить в docs/plans/finished/? [y/N]`. Yes → `git mv`, separate commit `chore: archive <slug>`, delete the ledger, report `Archived: <sha>`. Otherwise silent. Never between phases, never for quickfixes.

## Multi-phase plans

Steps 1–2 cover all phases up front; Steps 3–4 run per phase; after a phase's commit **immediately** start the next (`Ф1 committed <sha>. Starting Ф2: <scope>.`) — no "shall I proceed?". Pause only for: cap hit, BLOCKED beyond context, a phase invalidating a later phase's scope, an explicit user pause, or irreversible side-effects ahead (prod migrations, external writes, destructive git).

## Parallel groups (two tracks max)

Two pending phases sharing `parallel_group` run concurrently. Preconditions: plan approved, clean `git status` (the untracked ledger excepted), no live write task.

1. Flip both to `in-progress`, commit `docs(plans): start parallel group <G>`.
2. Per phase: `orca orchestration worker-start --task <t> --worktree new-child --name <slug>-<phase> --setup run --agent … ` (Path A) or `orca worktree create --name <slug>-<phase> --setup run --json` + Path B in that worktree. Read the worktree id from the receipt, then **pre-trust the new path** before the first dispatch into it — `install.sh --repo <track-path>` (recipes §3; a parent directory's trust does not cover a child worktree, and Claude/Antigravity workers otherwise stall on the trust dialog and burn a dispatch attempt); all later `"$WS"` / `"$RPKG"` / `"$GATE"` calls for the track run with cwd inside it; per-track ledger lives inside the worktree. **A track never edits the plan file** (no `base:`/`status:` flips — keep the track's BASE in its state line and ledger); that is what keeps step 4's merges conflict-free.
3. Steps 3 → 3.5 → 4 per track independently; commit per track inside its worktree (source and test files only — the plan file stays untouched in the track).
4. Merge sequentially in the main tree: `git merge --no-ff <track-branch>` twice (branch name: `git -C <track-path> branch --show-current`); a conflict falsifies the plan's independence claim → `git merge --abort`, escalate.
5. Integration check (state `4.6-integration`): `"$GATE" <plan-file> <pre-merge-sha>` on the merged tree → `GATE_FAIL` → repair rounds, cap 2: fresh implementer repair (ledger item `G<r>-B1`) → Step 3.5 → one 4.1 round on the repair diff → commit `fix: repair integration of group <G>`.
6. Merge track ledgers into the main ledger (suffix colliding ids with the phase id), flip both phases `done` with full ranges, commit `docs(plans): complete parallel group <G>`, then `orca worktree rm` both tracks — only after `git branch --merged` lists both track branches.
7. Asymmetry: one track passes, the other escalates → merge the passing one, keep the failed worktree, escalate with its path. Never delete a worktree with unmerged work.

State line during a group: append `tracks=<id>:<step>-r<k>,<id>:<step>-r<k>`.

## Authorized Change Ledger

`docs/plans/<slug>.ledger.json` — one flat JSON array, transient (never committed), deleted at archival. Written only by the coordinator. Item:

```json
{ "id": "P<r>-B<n> | PF-B<n> | F<r>-B<n> | G<r>-B<n> | FR<r>-B<n>",
  "reviewer": "plan-review | preflight | review-primary | review-control | gate | review-final",
  "decision": "ACCEPTED | PARTIALLY_ACCEPTED | REJECTED_BY_SCOPE | DEFER | NIT | ESCALATED_TO_HUMAN",
  "authorized_change": "<exact allowed change, or null>",
  "forbidden_expansions": [],
  "materiality": "BUILD_BREAK | ACCEPTANCE_CRITERIA | DATA_LOSS | SECURITY | REGRESSION | CONSISTENCY | NICE_TO_HAVE",
  "status": "open | fixed | rejected | deferred | verified-by-controller" }
```

Fixers receive only open ACCEPTED / PARTIALLY_ACCEPTED items; reviewers receive the ledger path. Reviewer classes (`MUST_FIX_NOW`, `REGRESSION_FROM_AUTHORIZED_FIX`, `DEFER`, `NIT`, `REJECTED_BY_SCOPE`) map to decisions at triage; only the first two are valid in a BLOCKING list. `ESCALATED_TO_HUMAN` is for `plan-mandated` findings and out-of-scope `NEEDS_AUTHORIZATION` — never handed to a fixer, never counted in loop control.

## Reporting cadence

One line entering each step (`Plan ready → plan review r1/4 (plan-reviewer, model per roles.md)`), one line per loop iteration with the verdict, no polling narration, 1–2 sentences at end of turn. Availability fallbacks and Fable→Opus substitutions are always stated.

## Red flags — never

- Write source or tests yourself; research the codebase yourself; run tests yourself except via `"$GATE"`; read a diff (not even "a quick sanity check" after a quickfix).
- Launch Codex without an explicit `--model` (the user's default routes to the Pro bridge).
- Re-inject into a previous reviewer's terminal — reviewers are fresh every round; the only terminal reuse is the implementer's own thread (a model escalation is always a fresh terminal).
- Use `--effort high` for a Claude judgment role (it is a low setting), `--effort max` for any Claude role (billed ×1.5 — `xhigh` is the ceiling), or `ultra` anywhere without the user's word.
- Skip 4.1 and go to 4.2; run 4.2 after a blocking 4.1; review without this round's fresh package; review without a `GATE_OK` on the current tree.
- Pair a writer and a reviewer from the same model family.
- Tell a reviewer what not to flag; triage a `plan-mandated` item into ACCEPTED / REJECTED.
- Re-dispatch a `done` phase; mark a phase done with an open CANNOT_VERIFY; one fixer per finding in Step 5; archive before Step 5 is clean.
- Two writers in one working tree, more than two tracks, or parallelizing phases the plan did not group.
- Stop, close or release a worker because it is slow — heartbeats and terminal activity mean alive. Leave a settled worker open without a reason.
- Resolve merge conflicts between tracks; delete a worktree with unmerged work; push, force-push, skip hooks, `--amend`; start on `main` without consent.
- Let a nit block progress.

## Files

- `./roles.md` — who runs what (models, efforts, cascades, family rule, planning profiles)
- `./orca-recipes.md` — launch paths A/B, blockers, waiting, release, retries
- `./prompts/plan-writer-prompt.md` (Mode A / Mode B), `plan-reviewer-prompt.md`, `implementer-prompt.md`, `frontend-implementer-prompt.md`, `verification-gate-prompt.md`, `review-primary-prompt.md`, `review-control-prompt.md`, `synthesize-review-prompt.md`, `final-review-prompt.md`, `quickfix-prompt.md`, `diagnosis-prompt.md`
- `../../bin/verify-gate`, `../../bin/review-package`, `../../bin/sdd-workspace`, `../../bin/wait-agent-ready` (+ their `.ps1` ports for Windows)

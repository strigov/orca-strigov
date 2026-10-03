# Coordinator reference: planning

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

### Step 1 — plan (writer)

0. `install.sh --check <repo>` (from the loaded plugin, `$BIN/../install.sh`; on Windows `& "$PluginDir\install.ps1" -Check <repo>`). A WARN about trust/hooks requires the user's authorization or existing explicit approval for that setup change. `--repo` / `-Repo` grants repository trust; it does not install the plugin or approve hooks. A duplicate-skill warning requires resolving discovery, not another legacy installation. Never silently change global setup to clear a worker blocker.
1. Choose the planning profile per `roles.md` (default: `astra`; `pro` only on explicit user opt-in; `opus` only as explicit user override). State which profile you picked.
2. **Branch check before anything is written:** if `git branch --show-current` is `main` / `master`, run `git checkout -b feat/<slug>` (committing to `main` needs the user's explicit words in this session). Then `orca orchestration run-create --objective "<slug>" --json` and record `plan_base = git rev-parse HEAD` (full SHA, the commit directly before the plan commit — Step 5 diffs against it).
3. Resolve the plan path and create its workspace with `sdd-workspace --name <slug>` (native Windows uses `.ps1`). Write the initial C6 state: `schema_version:2`, `mode:plan`, `step:plan`, `phase:null`, `base` = `plan_base`, `plan:{path:<absolute plan path>,sha256:null,structure:null}` and the empty lists of the C6 state shape; never invent a phase. Fill the writer body through prompt-routing.md with the user's request, the actual `orca_run` and `plan_base` (the writer puts them in the frontmatter, so the reviewed bytes are the committed bytes) and a fresh ATTEMPT report. Create the Task, validate `dispatch` (no `artifact` before the plan exists), launch, `bind-dispatch`. The writer records `risk:`, `verify:` and the phases; no phase `base:` yet.
4. Wait. On `PLAN_WRITTEN` copy the plan byte for byte into the workspace and run `accept-report` with `plan` = the live plan `{path,sha256}` and `artifact` = that copy (`kind:plan`, `source_path` = the live path). `BLOCKED` / `NEEDS_AUTHORIZATION` (no artifact): resolve the requirement or authority, then dispatch a fresh plan-writer Task/Dispatch/ATTEMPT; readers stay blocked until a plan is accepted. A failed writer's draft at the plan path is not bound; the retry may replace it. Follow the existing recovery route for an unavailable writer.
5. Availability failure on opt-in Pro: retry ONCE in a FRESH Pro terminal (new task, "RETRY (attempt 2 of 2) …"), then switch to `astra`. Tell the user in one line.

**Author retention:** Keep the plan-writer terminal alive until the plan is approved and committed; `orca orchestration worker-retain --dispatch <id> --json` (recording expected next action `plan review r<k>`) applies only to an Orca-owned terminal, i.e. a Path A reuse; a Path B terminal the coordinator created stays open per recipes §5 until the plan is committed and its closing rule applies. Mode B normally reuses the actual author. The `pro` profile is the narrow exception: its first revision goes to a fresh native `plan-reviser` per `roles.md`, with announced full handoff (plan, ledger, latest author/review reports); retain and reuse that reviser for later revisions. Keep the settled initial author for context until the plan commit; it receives no revision task. Actual context loss uses a fresh replacement of the authorized revision profile with the same full handoff, announced.


### Step 2 — plan review (loop, cap 4)

Reviewer per `roles.md` (ordinary plan reviewer vs. complex plan reviewer). FRESH worker every substantive round (cap 4); read-only; never re-inject into a previous reviewer's terminal.

The plan reviewer evaluates requirements compliance, semantic consistency (contracts, consumes/produces matching, global constraints, phase risks), and performs the mandatory **Simplicity** check (`## Simplicity`, `SIMPLICITY: OK | CHANGES_REQUESTED`).

- `APPROVED` (requires `SIMPLICITY: OK`) → commit the approved bytes unchanged: stage the plan file by name, C6 `prepare-commit` with the approved `kind:plan` artifact, commit the plan alone (`docs(plans): add <slug>`, the Auto-commit trailer from coordinator-finish.md, no push), `confirm-commit` with `commit:{sha,base:<plan_base>}`, then `advance`. Do not edit the plan between approval and this commit. After the commit receipt request release of the author/reviser terminals per recipes §5 → Step 3, which records the first phase's `base:`.
- `CHANGES_REQUESTED` → ledger sequence:
  (a) triage each BLOCKING item's `class:` → ledger `decision` (`MUST_FIX_NOW` / `REGRESSION_FROM_AUTHORIZED_FIX` → `ACCEPTED` or `PARTIALLY_ACCEPTED`; `DEFER` / `NIT` / `REJECTED_BY_SCOPE` → same-named decisions). `plan-mandated` items → `ESCALATED_TO_HUMAN`, shown to the user with the plan text, never fixed without an answer.
  (b) write/update the ledger (ids `P<round>-B<n>`, reviewer `plan-review`); first update prior entries' `status`.
  (c) dispatch `plan-reviser` with Mode B: normally reuse the retained author; for the first revision after the `pro` initial plan, use a fresh native reviser per `roles.md` with announced full handoff and reuse it thereafter; actual context loss uses a fresh worker of the authorized revision profile with full handoff, announced. Every revision spec includes the ledger path + open items inline + the reviewer's BLOCKING lines verbatim. `NEEDS_AUTHORIZATION` → extend the ledger item if inside scope, else escalate.
  (d) dispatch a FRESH reviewer with the follow-up template (ledger path + the reviser's per-item report). Round++.

For (c), supply `[FIX_FINDING_REFERENCES]` through prompt-routing.md. Accept the
reviser's `REVISED` with the fresh `plan` reference and a workspace copy as the
artifact. A blocker is resolved when the next accepted plan review of the revised
plan no longer lists it (or by a recorded ledger decision); no CHECK or receipt.

**Loop control — in order, first match wins, after every `CHANGES_REQUESTED`:**
1. Anti-pingpong: drop items repeating a point rejected with reasoning in a prior round (`resolved-by-decision`). Empty list → treat as `APPROVED` if simplicity is OK.
2. No-progress: blocking list identical to the previous round → escalate with a one-sentence impasse summary from a `diagnosis` worker.
3. New-blocker churn: all prior blockers closed AND all remaining are NEW `MUST_FIX_NOW` (not `REGRESSION_FROM_AUTHORIZED_FIX`) AND none cite DATA_LOSS / SECURITY / GUARANTEED_FAIL → escalate with: closed list, new list with materiality, recommendation.
4. Round cap: next round would be 5 → escalate.
5. Otherwise run (a)–(d).

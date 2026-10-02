# Coordinator reference: planning

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

### Step 1 — plan (writer)

0. `install.sh --check <repo>` (from the loaded plugin, `$BIN/../install.sh`; on Windows `& "$PluginDir\install.ps1" -Check <repo>`). A WARN about trust/hooks requires the user's authorization or existing explicit approval for that setup change. `--repo` / `-Repo` grants repository trust; it does not install the plugin or approve hooks. A duplicate-skill warning requires resolving discovery, not another legacy installation. Never silently change global setup to clear a worker blocker.
1. Choose the planning profile per `roles.md` (default: `astra`; `pro` only on explicit user opt-in; `opus` only as explicit user override). State which profile you picked.
2. `orca orchestration run-create --objective "<slug>" --json`; keep the run id — you write it into the plan frontmatter as `orca_run:` at the plan commit.
3. Resolve the intended plan path and create its workspace with `sdd-workspace --name <slug>` (native Windows uses `.ps1`). Save the user's actual
   request as immutable authorization JSON per runtime-contracts bootstrap, with
   real Run/worktree IDs, current full plan_base and target plan path. Initialize
   `step:bootstrap`, `mode:plan`, `plan:null`, `phase:null`; never invent a phase.
   Select and fill the writer body through prompt-routing.md, including the
   authorization path/hash, supplied metadata and fresh ATTEMPT report. Create
   the real Task, validate the C6 dispatch proposal with `artifact.kind:request`,
   launch and bind its real Dispatch. On PLAN_WRITTEN supply the actual plan hash
   as both `plan` and `artifact.kind:plan` to accept-report. The writer records
   `request_sha256`, `risk:` and `verify:`. C6 changes step to `plan` only after
   validating the produced plan; independent review uses that exact plan artifact.
4. Wait. Accepted `PLAN_WRITTEN` → Step 2. `BLOCKED` / `NEEDS_AUTHORIZATION` keeps bootstrap: read the report, resolve the missing requirement/authority, retain failed history and validate a fresh plan-writer Task/Dispatch/ATTEMPT at round 1. A format correction may bind a pending draft but does not authorize readers; a failed correction also stays in bootstrap. Follow the existing recovery route for an unavailable writer.
   If `state.plan` is null but the failed writer left an unparseable draft at the
   target path, follow contracts/c6-protocol-validation.md **First-plan bootstrap**: verify
   settlement, ownership and absence of artifact/report bindings, then preserve
   the draft under a fresh workspace recovery path with its original path/hash
   recorded. Resume and validate the retry only after the original path is absent;
   preserve authorization and failed history. Never apply this to a bound plan.
5. Availability failure on opt-in Pro: retry ONCE in a FRESH Pro terminal (new task, "RETRY (attempt 2 of 2) …"), then switch to `astra`. Tell the user in one line.

**Author retention:** Keep the plan-writer terminal alive until the plan is approved and committed; `orca orchestration worker-retain --dispatch <id> --json` (recording expected next action `plan review r<k>`) applies only to an Orca-owned terminal, i.e. a Path A reuse; a Path B terminal the coordinator created stays open per recipes §5 until the plan is committed and its closing rule applies. Mode B normally reuses the actual author. The `pro` profile is the narrow exception: its first revision goes to a fresh native `plan-reviser` per `roles.md`, with announced full handoff (plan, ledger, latest author/review reports); retain and reuse that reviser for later revisions. Keep the settled initial author for context until the plan commit; it receives no revision task. Actual context loss uses a fresh replacement of the authorized revision profile with the same full handoff, announced.


### Step 2 — plan review (loop, cap 4)

Reviewer per `roles.md` (ordinary plan reviewer vs. complex plan reviewer). FRESH worker every substantive round (cap 4); read-only; never re-inject into a previous reviewer's terminal.

The plan reviewer evaluates requirements compliance, semantic consistency (contracts, consumes/produces matching, global constraints, phase risks), and performs the mandatory **Simplicity** check (`## Simplicity`, `SIMPLICITY: OK | CHANGES_REQUESTED`).

- `APPROVED` (requires `SIMPLICITY: OK`) → **branch check first**: if `git branch --show-current` is `main` / `master`, run `git checkout -b feat/<slug>` before anything is committed — committing to `main` requires the user's explicit words in this session. Then write `plan_base: <git rev-parse HEAD>` (the full commit SHA directly before the plan commit — Step 5 diffs against it) and `orca_run:` into the frontmatter and commit the plan file alone (`docs(plans): add <slug>`, plan file staged by name, the Auto-commit trailer from coordinator-finish.md, no push). After successful commit receipt, request release of the author/reviser terminals per recipes §5 and record the actual receipts → Step 3.
- `CHANGES_REQUESTED` → ledger sequence:
  (a) triage each BLOCKING item's `class:` → ledger `decision` (`MUST_FIX_NOW` / `REGRESSION_FROM_AUTHORIZED_FIX` → `ACCEPTED` or `PARTIALLY_ACCEPTED`; `DEFER` / `NIT` / `REJECTED_BY_SCOPE` → same-named decisions). `plan-mandated` items → `ESCALATED_TO_HUMAN`, shown to the user with the plan text, never fixed without an answer.
  (b) write/update the ledger (ids `P<round>-B<n>`, reviewer `plan-review`); first update prior entries' `status`.
  (c) dispatch `plan-reviser` with Mode B: normally reuse the retained author; for the first revision after the `pro` initial plan, use a fresh native reviser per `roles.md` with announced full handoff and reuse it thereafter; actual context loss uses a fresh worker of the authorized revision profile with full handoff, announced. Every revision spec includes the ledger path + open items inline + the reviewer's BLOCKING lines verbatim. `NEEDS_AUTHORIZATION` → extend the ledger item if inside scope, else escalate.
  (d) dispatch a FRESH reviewer with the follow-up template (ledger path + the reviser's per-item report). Round++.

For (c), supply `[FIX_FINDING_REFERENCES]` through prompt-routing.md: exact finding
IDs and original accepted reviewer report paths/raw hashes. Require the reviser's
FIX_EVIDENCE binding, then a later accepted independent review before closing an
ordinary blocker; retain accepted report order. A text-only revision needs no CHECK.

**Loop control — in order, first match wins, after every `CHANGES_REQUESTED`:**
1. Anti-pingpong: drop items repeating a point rejected with reasoning in a prior round (`resolved-by-decision`). Empty list → treat as `APPROVED` if simplicity is OK.
2. No-progress: blocking list identical to the previous round → escalate with a one-sentence impasse summary from a `diagnosis` worker.
3. New-blocker churn: all prior blockers closed AND all remaining are NEW `MUST_FIX_NOW` (not `REGRESSION_FROM_AUTHORIZED_FIX`) AND none cite DATA_LOSS / SECURITY / GUARANTEED_FAIL → escalate with: closed list, new list with materiality, recommendation.
4. Round cap: next round would be 5 → escalate.
5. Otherwise run (a)–(d).

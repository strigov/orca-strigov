# Coordinator reference: core

Always loaded with SKILL.md and roles.md. Stage detail lives in the coordinator-*
files the router names. REPORT_FILE always names the current Dispatch's fresh
report; previous reports are immutable. No runtime barrier is waived by this split.

## THE HARD RULES (read first, re-read at every step)

### Rule 1 — no writes on the coordinator

You do NOT write production code, tests, or source edits. Not one line, however trivial. Every file change goes through a worker: full protocol → `implementer` / `frontend-implementer`; trivial single-file edit → `quickfix`. If you are about to open an editor tool or `apply_patch` on a source path — STOP and dispatch.

The only writes you perform yourself:
- plan frontmatter bookkeeping lines (top-level `status`, phase `status`, phase `base:`, `commits:`); `orca_run:` and `plan_base:` are given to the plan writer, not written later;
- the ledger `docs/plans/<slug>.ledger.json`;
- prompt/spec files, JSON proposals, saved raw Orca receipts, fleet/check requests,
  byte-for-byte plan copies and resume outputs under the plan workspace
  (`"$WS" --name <slug>` works before the plan exists);
- git bookkeeping: `git add <names>`, `git commit`, `git mv` for archival, worktree/merge/branch commands for parallel groups;
- Orca bookkeeping: `orca orchestration ...`, `orca terminal ...`, `orca worktree ...`.

### Rule 2 — no research on the coordinator

You do NOT read production code, grep the source, run tests/linters/builds "to see what's failing", or perform semantic reviews of the plan body (that is the `plan-reviewer`'s job; you only check structure mechanically). "Just a quick look" is research — STOP.

Research channels: codebase questions → the plan writer explores the repo itself; diagnosis of `BLOCKED` / unclear failures → a `diagnosis` worker; plan content → workers read it by path.

Reads you may perform yourself:
- plan-file YAML frontmatter (first ~40 lines); `docs/plans/*.md` listings;
- `git status / log / diff --stat / branch / rev-parse / merge-base / worktree list`;
- the ledger file and the plan workspace listing; the one-line stdout of `"$RPKG"` / `"$GATE"`;
- a worker's **report file** — only the parts each step names (verdict lines, `## Fix round <N>`, BLOCKING/DEFER/NITS/CANNOT_VERIFY sections). Never a review package (`review-*.diff`);
- a `CANNOT_VERIFY` item's literal `CHECK:` command, executed exactly as written through the runner;
- Orca receipts and `worker_done` messages.

**Rule 3 — large artifacts never transit your context.** C6 states and proposals, fleet receipts, package manifests and sealed check results are files you reference by `{path,sha256}`, not text you read. To know where you are, run `"$BIN/protocol-state" summary <state-or-proposal.json>` (about twenty lines: barrier, active, rounds, accepted entries with findings, commits, waivers). To take one field from a receipt, query it (`jq -r .result.dispatch.status`, or a one-liner printing only that key). Never `cat`, `sed -n` or `Get-Content` such a file whole, and never paste one into a proposal by value.

All three rules are model-independent. If you find yourself arguing a rule away, that is the violation.

### Pre-flight gate

On resume restore the unfinished barrier and use its permitted commands. Before
the first writer only these are allowed: skill references and repository
instructions; the reads above; `orca --version`, `orca status`, `orca
orchestration` run/task/worker/dispatch/check commands and `orca terminal
create|wait|read`; the bundled helpers (`sdd-workspace`, `run-check
capabilities`, `wait-agent-ready`, `wait-worker-event`, `collect-worker-fleet`,
`prompt-fill`, `protocol-state`, `coordinator-session`, `.ps1` on Windows); and
`install.sh --check` / `install.ps1 -Check`. Workspace files are written and
hashed without reading source; installation changes need the user's authorization.

## Role

Triage → resume-check → dispatch → wait → collect verdicts → bookkeeping (ledger, git, frontmatter) → transition → report. Judgment (plans, reviews, diagnosis) is never done here.

## Protocol state line (every turn)

Start every turn with:

`[orca-dev] step=<triage | resume-check | quickfix | 1-plan | 2-plan-review | 3-implement | 3.5-gate | 4-fused-review | synthesize | 4.6-integration | 5-final-review | 5-fix | commit | archive> phase=<Ф-id or —> round=<k>/<cap> base=<base7 or —> run=<orca run id or —> impl=<role/model or —> planner=<profile or —>`

If you cannot fill a field, you have lost protocol state: run `protocol-state summary` on the last resume, re-read the frontmatter, `git log --oneline -15` and `orca orchestration task-list --brief --json` before anything else.

## Durable progress (C6)

Every dispatch, bind, report acceptance, gate record, commit, advance and final
checkpoint goes through `protocol-state validate` first; only its VALID result
permits that one lifecycle effect. C6 checks the current transition against the
current candidate and three invariants: a fresh complete fleet with no live
writer before a writer or a commit, a commit tree equal to the accepted
candidate, and reviewers outside every author family. It does not re-prove
history; you never write closure receipts. Input shape and actions are in
[C6](contracts/c6-protocol-validation.md); after INVALID/UNVERIFIABLE start from the
[rejection table](runtime-contracts.md#c6-rejections--what-to-supply). A
rejection is never permission to bypass or work around C6.

- Keep the returned state as the resume (RESUME_OUT) in the plan workspace and
  checkpoint the proposal through C8 (coordinator-session.md).
- Supply `plan` (fresh `{path,sha256}`) whenever the plan file changed and
  `ledger` whenever the ledger changed. Bookkeeping lines move freely; any other
  plan change must come from the plan writer/reviser report.
- Fleet evidence comes from `collect-worker-fleet` (orca-recipes.md C6); copy its
  `fleet` array into the proposal. A scoped or incomplete collection is a barrier.
- Stage the candidate paths by name before the gate and package. Gate, reviews and
  commit must all be on the same bytes; a later source change needs a new gate
  and reviews. Bookkeeping edits to the plan file do not change the candidate.
- Pass `[RUNTIME_CONTRACTS_PATH]` and `[FROZEN_ASSIGNMENT]` (`{role, phase, round,
  artifact_id, snapshot_id}` from the VALID dispatch) to every worker.

Conversation memory does not survive compaction. Reconcile the C6 resume, the
frontmatter, Git history, the ledger and Orca (`run-use --id <orca_run>`,
`task-list --brief --json`, `worker-show --dispatch <id>`). Frontmatter is intent:
a prepared `done` or `commits:` without a confirmed commit is unfinished. After a
crash recover the existing commit from Git with `confirm-commit`; never commit the
same candidate twice. Missing or stale evidence returns to its barrier within
the existing caps; never skip review or blindly re-dispatch implementation.
A live or unverifiable unsettled write task blocks another writer; an alive
retained terminal whose Task is durably settled is not a writer.

Worker results, verdict tokens and ledger triage: [coordinator-results.md](coordinator-results.md).
Pre-dispatch checklist and prompt assembly: [prompt-routing.md](prompt-routing.md).
Helper paths (`$WS`, `$RPKG`, `$GATE`, `$STATE`, `$SESSION`): [orca-recipes.md](orca-recipes.md) §0.

## Reporting cadence

One commentary line entering each step (`Plan ready → plan review r1/4 (plan-reviewer, model per roles.md)`), one per loop iteration with the verdict, no polling narration. Final answers are only for verified completion, an evidenced human hold or an explicitly status-only request (coordinator-session.md). A routine phase report does not end the turn. Availability fallbacks and family-rule substitutions are always stated.

Wait through recipes §4 (C7). An empty window, keepalive or tool-harness yield is
not a protocol iteration or a reason for `worker-show`/screen reads; keep the same
waiter. Inspect workers when the waiter returns a delivery, attention or error.

## Red flags — never

- Write source or tests; research the codebase; run tests except via `"$GATE"`; read a diff.
- Launch/reuse a Codex worker without an explicit model and proven `features.multi_agent=false`, or send a spec without the mandatory no-delegation prefix.
- Re-inject into a previous reviewer's terminal (reviewers are fresh every round; only the author/implementer thread is reused; a model change is a fresh terminal). Use `ultra` without the user's word.
- Skip 4.1 and go to 4.2; run 4.2 after a blocking 4.1; review without this round's fresh package or without `GATE_OK` on the current tree.
- Pair a writer and a reviewer from the same model family for the same artifact; tell a reviewer what not to flag; triage a `plan-mandated` item into ACCEPTED / REJECTED.
- Re-dispatch a verified phase; advance after a failed/skipped commit or with an unresolved finding (including an unchecked CANNOT_VERIFY); one fixer per finding in Step 5; report the plan done before final review, delivery and completion commit.
- Two writers in one tree, more than two tracks, or parallel phases the plan did not group.
- Stop, close, retry or cascade on timeout/idle alone; close retained/external/uncertain terminals.
- Open a terminal per bookkeeping command, fleet page or wait; relay receipts through terminal reads.
- Resolve merge conflicts between tracks; delete a worktree with unmerged work; push, force-push, skip hooks, `--amend`; start on `main` without consent.
- Let a nit block progress.

## Files

- `./roles.md` — who runs what (models, efforts, cascades, family rule, planning profiles)
- `./orca-recipes.md` — helper paths, launch paths A/B, blockers, waiting, release, retries, C6 fleet
- `./coordinator-results.md` — verdicts, rejected deliveries, ledger and finding resolution
- `./prompt-routing.md` — pre-dispatch checklist and task-body assembly
- `./prompts/*` — role templates, assembled by `prompt-fill`, never read whole
- `../../bin/verify-gate`, `review-package`, `sdd-workspace`, `wait-agent-ready`, `wait-worker-event`, `collect-worker-fleet`, `prompt-fill`, `protocol-state`, `coordinator-session` (+ `.ps1` ports)

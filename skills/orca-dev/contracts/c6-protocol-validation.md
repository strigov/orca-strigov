# C6 — protocol validation (v2: the transition, not the history)

Part of [runtime-contracts.md](../runtime-contracts.md); load only when the index says so.

## What C6 checks

`bin/protocol-state validate INPUT_JSON [RESUME_OUT]` (native Windows:
`bin/protocol-state.ps1`) checks one coordinator proposal and prints `VALID`,
`INVALID` (contradictory bound facts, exit 1) or `UNVERIFIABLE` (missing facts or
unknown ownership/family, exit 2), then one JSON line. VALID carries
`{decision,state}`; a rejection carries `{reason,next_action}`. With
`RESUME_OUT` the resulting state is written atomically to a new path inside the
existing plan workspace; a rejection leaves any prior file untouched and input
artifacts are never overwritten. C6 runs only bounded read-only Git queries. It
never dispatches, acknowledges a Delivery, releases a worker, commits, edits the
plan or selects a model. `VALID` means this transition passed; inspect
`state.barrier` for what is pending.

C6 checks the **current transition** against the **current candidate** (the
bytes of the working tree under review). It does not re-prove history: the state
is the coordinator's bookkeeping, produced mechanically from earlier VALID
results, and each call reads only its own hashed inputs plus the plan and ledger
supplied fresh. Three hard invariants carry the safety:

1. **One writer per tree** — before a writer dispatch and before any commit, a
   fresh complete fleet shows no live or unverifiable writer in the worktree.
2. **Commit = accepted candidate** — a commit's tree equals the staged bytes of
   the candidate that the gate and both reviews (or the step's required roles)
   accepted; a plan-only commit holds exactly the approved plan bytes.
3. **Independent review** — a reviewer's actual model family is outside every
   actual author family of each covered file, except files the user released
   with `waive-independence` because every known family authored them.

Also checked per transition: report binding, the actual launched model, round
caps and the user's records. Soft facts are never blocking: declared check
inputs, deferred findings and cannot_verify outcomes are ledger and report
content for the user to read.

Other subcommands: `protocol-state summary STATE_OR_PROPOSAL_JSON` prints the
compact facts of a saved state or proposal (read-only; the coordinator's only
way to inspect one). `protocol-state migrate STATE_V1_JSON OUT_JSON` converts a
schema 1 state once (see Migration). `claude-model-evidence` and
`antigravity-model-evidence` freeze model proof (see Observations).

## Proposal and references

```json
{"schema_version":1,"action":"<action>","state":{...},"plan":{"path","sha256"},"ledger":{"path","sha256"}, "<action inputs>":...}
```

A file reference is `{path:<absolute literal path>,sha256:<raw byte hash>}`.
Paths through symlinks/reparse points are rejected. Hashes cover the original
bytes (BOM, CRLF, EOF); only after the hash check do both backends parse CRLF as
LF. Only saved real receipts are evidence in production; fixture receipts are
simulations, and C6 does not authenticate a fabricated local receipt.

`plan` and `ledger` are optional on every action and are supplied fresh by the
coordinator whenever their files changed; the state keeps the plan reference and
only the ledger path.

## State (schema 2)

```json
{"schema_version":2,"mode":"plan|quickfix","plan":{"path","sha256","structure"}|null,"ledger_path":null,
 "orca_run","plan_base","phase","base","step","worktree","worktree_id","workspace",
 "active":null,"rounds":{"plan_review":0,"fused_review":0,"final_review":0,"gate_fix":0},
 "cap_extensions":[],"independence_waivers":[],"provenance":[],"accepted":[],"write_ownership":[],
 "phase_commits":[],"final_source":null,"processed_messages":[],"used_fleet_ids":[],"barrier":"..."}
```

- `mode:plan` uses steps `plan`, `phase`, `final-review`, `delivery`,
  `completion`; `mode:quickfix` uses only step `quickfix` with `plan:null`.
- `plan` starts as `{path:<absolute future plan path>,sha256:null,structure:null}`
  before the first plan exists. `phase` is null in the plan and quickfix steps.
- `plan_base` and `base` are full existing commits; `worktree` is the Git
  worktree top level, `workspace` the existing plan workspace.
- `accepted` holds entries of the **current step and phase only**:
  `{role,token,round,phase,step,candidate,artifact,findings,coverage,family,report,dispatch_id,evidence}`.
  `advance` and `finish-checkpoint` clear it.
- `phase_commits`: `{phase,step,sha,base,candidate}` per confirmed commit (plan,
  phase, final-fix, quickfix and completion commits).
- `provenance`: observation references of every accepted writer (plan authors
  for plan-review independence; Path A start receipts for C5 write receipts).
- `final_source`: the candidate the final review accepted (set by
  `finish-checkpoint`); delivery and the completion commit must match it.

## Plan reference and bookkeeping

Plan frontmatter uses `protocol_version: 2`, the actual `orca_run` and full
`plan_base` (given to the plan writer up front, so the reviewed bytes are the
committed bytes), one-line JSON `contracts`, and phases with `risk`
(`none|SECURITY|DATA_LOSS|REGRESSION`), one-line JSON `consumes`/`produces`
(consumers reference earlier producers) and, once the phase starts, `base`.
In a phase step the current phase's `base` must equal `state.base`.

`plan.structure` is the SHA-256 of the frontmatter with its bookkeeping lines
removed, a NUL, then the body. Bookkeeping lines are top-level `status:`,
`plan_base:`, `orca_run:`, `commits:` and phase-level (four-space) `status:`,
`base:`, `commits:`. Every call verifies the plan file against `plan.sha256`
and `structure`. A fresh `plan` reference with the same path is accepted on any
action when its structure is unchanged; any other change is accepted only on
`accept-report` of the active plan-writer/plan-reviser (and then must be the
delivered artifact). Everything else is `plan change outside the plan
author/review path`.

## Artifacts and the candidate

`artifact` adds `kind:plan|snapshot|package` to a file reference. A plan
artifact names an immutable workspace copy of the plan (`source_path` = the live
plan path); its id and candidate are its raw hash. A snapshot is a valid C4
record; a package is a complete C5 manifest whose `package_id` matches its
content. A **candidate** is the SHA-256 of the canonical JSON map
`{path: sha256 (or type)}` over the artifact's `repo:` entries, excluding
missing entries and the plan file. HEAD, capture exclusions, staging and
declared inputs are not part of it: a C4 snapshot and a C5 package of the same
bytes are the same candidate, and a commit that leaves the bytes unchanged
(phase or final-fix) does not stale an accepted review.

A *current* artifact matches a fresh snapshot of the worktree (same candidate);
otherwise `stale artifact`. Dispatch, accept-report, record-gate,
prepare-commit, finish-checkpoint and waive-independence require current
artifacts; confirm-commit and complete check currency inside the commit check.

## Actions

| Action | Inputs and effect |
| --- | --- |
| `resume` | Structure only: state shape, plan, bases, caps; returns the barrier. |
| `dispatch` | `fleet`, `proposed` (`run_id,task_id,dispatch_id:null,role,phase,round,worktree_id,model`, review `coverage`, optional `fix:true`, `gate_fix:true`), `artifact` (omitted only for the first plan-writer before the plan exists). Freezes the assignment in `active`; a writer becomes `pending:<task>` in `write_ownership`. Reviewer rounds go `count` or `count+1` within the cap; repeating a role/round with the same family needs a new round; review coverage must be independent. |
| `bind-dispatch` | `observation` of the pending fresh Task (not a `--retry-of`); the actual model must match the proposal (a roles.md `MODEL_ALIASES` alias matches its full-id prefix). A writer then owns the worktree. |
| `accept-report` | `event`, `message_id`, settled `observation`, `report`, `artifact` (omitted only when the assignment had none). See Accepting a report. Clears `active`. |
| `record-gate` | Current `artifact` and `evidence` (sealed C4 `result.json` references of a green verify-gate run) in the phase or delivery step with no writer; recorded as an accepted `gate` GATE_OK entry. |
| `prepare-commit` | `fleet`, current `artifact`; the candidate is ready and nothing is unstaged. Records nothing. |
| `confirm-commit` | `fleet`, the accepted `artifact`, `commit:{sha,base}`. Readiness plus the commit check; records the commit once (a repeat confirms the same commit idempotently). Steps `plan`, `phase`, `quickfix`, `final-review` (final-fix commit). |
| `advance` | After a confirmed commit of this step/phase: next phase with `base` = that commit, or `final-review` after the last phase. Clears `accepted`, `active`, fused-review and gate-fix rounds. |
| `finish-checkpoint` | `fleet`, current `artifact`; all phases committed. `final-review` → `delivery` (records `final_source`), `delivery` → `completion` (the gate's candidate must equal `final_source`). Clears `accepted`. |
| `complete` | `fleet`, `artifact` whose candidate equals `final_source`, a separate `commit`; the commit check holds and the committed plan has top-level `status: done`. |
| `extend-cap` | `authorization`: `{schema_version:1,run_id,phase,group,extra_rounds:1,findings,user_decision}` at a reached cap, naming accepted finding ids. One round per record. |
| `waive-independence` | `authorization`: `{schema_version:1,run_id,step,phase,files,reviewer_family,user_decision}` and the current package `artifact`; only files every known family authored. |

`extend-cap` and `waive-independence` records are the user's words, saved
verbatim by the coordinator; never written without them.

## Accepting a report

The saved `event` is a send receipt's `result.message` or a check receipt's
`result.messages`; payload may be a JSON string. Only `message_id` is
processed. A processed id is `duplicate`; an empty timed-out wait and
non-`worker_done` messages are `not-completion`; a `worker_done` for another
Run/Task/Dispatch is `stale`. These change nothing but `processed_messages`.

A completion is accepted only when: `observation` shows the active Dispatch
`completed` with durable evidence; the sender is its assignee; the payload's
`reportPath` is the report and the subject's first token (anything after `:` or
whitespace is ignored) equals report line 1; the report path is not already bound
to an accepted entry; the artifact is current, and for a reader it is the
assigned one; the report satisfies the worker contract in runtime-contracts.md
(verdict token, outcome, BINDING equal to the live assignment including
artifact and snapshot ids, role sections, FINDINGS, COVERAGE, FIX_EVIDENCE on
fix rounds, gate EVIDENCE); a successful plan author delivered the current plan.
Reviews (except plan review) pass the independence check on their coverage;
a plan reviewer's family differs from every recorded writer family. Gate
`GATE_OK` EVIDENCE: valid sealed C4 results of this candidate, at least one
passing, inherited failures proven by a BASE baseline with the same signature,
no reused origin where independent replay is required. A defective report is
rejected and the role is simply re-dispatched (a new Task, same round).
SECURITY/DATA_LOSS findings return `decision:risk-escalation`.

## Resolution and readiness

A finding of an accepted entry is **resolved** when:

- the ledger entry with its id has `decision` `DEFER`, `NIT` or
  `REJECTED_BY_SCOPE`; `ESCALATED_TO_HUMAN` and `ACCEPTED` leave it unresolved
  until the user's answer is recorded as one of the three or the finding is
  fixed and re-reviewed; or
- it is `cannot_verify` and the ledger entry has `check`: an absolute path to a
  C4 `result.json` that exists and reports integer `exit_code` 0; or
- it is `blocking` and the latest accepted entry of the same role on the
  current candidate came later, has a higher round, and no longer lists the id.

The ledger is a JSON array of objects with unique string `id`; C6 reads nothing
else from it. A candidate is **ready** for the step's commit or checkpoint when
the latest accepted entry of each required role on that candidate is positive
and no finding of the step is unresolved:

| Step | Required roles (positive token) |
| --- | --- |
| `plan` | `plan-reviewer` (APPROVED) on the plan bytes |
| `phase` | `gate` (GATE_OK or record-gate), `review-primary`, `review-control` (REVIEW_OK) |
| `quickfix` | `quickfix` (DONE / DONE_WITH_CONCERNS) |
| `final-review` | `review-final` (REVIEW_OK) |
| `delivery` | `gate` (GATE_OK or record-gate) on `final_source` |

The reviews' COVERAGE together covers every file (except the plan file), part
and contract side of the first review's package. Reviews of earlier candidates
stay in `accepted` only for their findings.

## Commits

`commit:{sha,base}` uses full SHAs; the commit exists, differs from `base`,
descends from `base` and is an ancestor of HEAD.

- **Plan-only commit** (plan step): `base` = `plan_base`, the commit changes
  exactly the plan path, and that blob hashes to the approved plan bytes.
- **Source commit**: `base` = the accepted artifact's HEAD; a fresh snapshot
  still is the candidate; nothing is unstaged; every present repository entry
  is staged; the commit tree without the plan file equals those index entries;
  a committed plan has the state's structure (bookkeeping lines may differ).

Hooks or formatters that change bytes after acceptance therefore reject. Recover
a crashed commit by confirming the existing commit from Git; never commit twice.

## Final steps and barriers

After the last phase commit `advance` enters `final-review`. A final-fix commit
(confirm-commit in `final-review`) keeps the final review valid when the bytes
are those reviewed. `finish-checkpoint` then records `final_source` and moves to
`delivery`; a delivery gate on the same candidate moves to `completion`; the
separate completion commit (top-level `status: done`) completes the plan.

`state.barrier`, in order: `awaiting_writer` (a writer intent or bound writer);
after a recorded commit of this step `ready_next_phase`, `awaiting_final_review`
or `complete`; `awaiting_final_review`, `awaiting_delivery`,
`awaiting_completion_commit` in the final steps; `awaiting_plan_writer` /
`awaiting_implementation` without a candidate (no entry, or the last writer
failed); `awaiting_commit` when ready; else `awaiting_plan_review` /
`awaiting_gate` without the first required role, `awaiting_resolution` with a
non-positive latest required report or an unresolved finding, `awaiting_review`
otherwise. The candidate of the plan step is the plan; of other steps the last
accepted non-diagnosis entry.

Caps: plan review 4, fused review 4 per phase, final review 2, consecutive gate
fix 2. Only the user lifts a reached cap, one round per `extend-cap` record.

## Observations and actual model

Saved `observation` is current `worker-show --dispatch ID --json`: `ok`,
`result.dispatch` (`id,taskId,runId,status,assigneeHandle,retryOfDispatchId`),
`projection.provider.model`, `projection.workspace.id`, `projection.evidence.durable`.
An observation reference may add `start:{path,sha256}` pointing to the immutable
saved `worker-start` receipt. It must have `ok:true` and exact matching
`result.runId/taskId/dispatchId`; the model fact is `result.launch.effective.model`,
never `launch.requested` or the provider name. A non-null observed model is used;
if a start fact is also supplied it must agree. A null observed model needs that
bound effective model; missing, mismatched or conflicting facts do not establish
family. Keep this reference on accepted observations and author entries in
`state.provenance`; C5 write receipts match those entries by path and raw hash.
Neither original receipt is rewritten or enriched on disk.

Orca reports `provider.model` for Codex but not for Claude, so two further model
sources exist. Precedence: observed `provider.model`, then the one launch-derived
fact below; any two facts that are present must agree (`conflicting actual model
facts`). No source is the coordinator's word, saved argv, a comment or a message.

- **Reuse chain (`origin_start`).** A `worker-start --terminal` reuse has a
  `start` receipt with an empty `launch.effective`. The reference may then add
  `origin_start:{path,sha256}`: the `worker-start` receipt that created that
  terminal. Accepted only when the current `start` matches the Dispatch and has
  one agent terminal effect `reused`; the origin has `ok:true`, the same `runId`,
  another Dispatch, one agent terminal effect `created` with the same handle,
  equal to `dispatch.assigneeHandle` and `worker.agentTerminalHandle`; both
  receipts carry the same non-empty `prompt.processIncarnation`, which also
  equals the observed `terminal.incarnationId` and ends `dispatch.processIncarnation`
  (continuity: the process was not restarted); the origin `launch.effective.model`
  is non-empty and its `agent` equals `provider.id`. The model is the origin one.
- **Claude transcript (`model_evidence`).** Only for `provider.id:"claude"` with a
  null `provider.model` and no `start`. The reference adds
  `model_evidence:{kind:"claude-transcript",path,sha256}` pointing to an
  immutable copy of the Claude Code session JSONL made by
  `protocol-state claude-model-evidence OBSERVATION_JSON SNAPSHOT_OUT [TRANSCRIPT]`
  (the live file keeps growing, so C6 never hashes it). The builder searches
  `$CLAUDE_CONFIG_DIR` or `~/.claude`, `projects/<worktree path with every
  non-alphanumeric character as ->/*.jsonl` changed since `dispatch.createdAt`
  minus five minutes; none or several matching sessions are UNVERIFIABLE.
  C6 binds the copy: one non-sidechain user record contains the Orca preamble
  whose `Your task ID is:` line equals `taskId`, whose every `--dispatch-id`
  equals the Dispatch and every `--from` equals `assigneeHandle`. From there
  until the next Orca preamble of another Dispatch, every record keeps that
  `sessionId`, every present `cwd` lies inside `terminal.worktreePath` (whose
  `terminal.worktreeId` equals the observed workspace), and assistant records
  carry exactly one `message.model` (Claude Code's local `<synthetic>` stubs
  are not model output). Several models are conflicting; none is UNVERIFIABLE.
  Build it after the first assistant response; after settlement the copy also
  proves no later model switch.
- **Antigravity log (`model_evidence` kind `antigravity-log`).** Only for
  `provider.id:"antigravity"` with a null `provider.model` and no `start`. Orca
  does not report the agy model and agy's conversation store is SQLite, which the
  native Windows validator cannot read; two text files are frozen instead by
  `protocol-state antigravity-model-evidence OBSERVATION_JSON SNAPSHOT_OUT`:
  `SNAPSHOT_OUT` copies `brain/<conversation>/.system_generated/logs/transcript.jsonl`
  and `SNAPSHOT_OUT.cli.log` copies the one `log/*.log` CLI process log that
  created that conversation (under `$ORCA_AGY_HOME` or `~/.gemini/antigravity-cli`).
  The reference is `{kind,path,sha256,conversation_id,log:{path,sha256}}`. C6
  requires a `USER_INPUT` transcript row with this Dispatch's Orca preamble (same
  task/dispatch/`--from` rule), a log line `Created conversation <conversation_id>`
  and exactly one distinct `Resolving model <id>` in that process log. The
  conversation-to-transcript link is the directory name recorded by the builder,
  weaker than Claude's single transcript; a per-process model switch is conflicting.

Actual model-to-family mapping lives only in roles.md. C5 write provenance points
to these hashed observations; unknown or mixed authors need independent coverage.

## Fleet

`fleet` is an array of hashed `worker-list --json --limit 100` page references,
each with its input `cursor` (null for the first page), across all local runs.
C6 checks `scope.source:all`, `page.total/hasMore/nextCursor`, unique dispatch
IDs and each worker's workspace, dispatch status, resource ownership, terminal
state and durable/liveness projection. Incomplete/unknown observations block; a
receipt id proves freshness once (`used_fleet_ids`). A durably completed or
failed retained terminal is not a writer even when its workspace is null,
provided ownership is not external/user-owned/pre-existing and release is not
pending/unknown; other null-workspace records remain unknown. Unknown/external
ownership or pending/unknown release in the worktree blocks, as does an unbound
writer intent: bind or reconcile it before another proposal.

### C6 fleet collector (no Orca terminal)

`bin/collect-worker-fleet REQUEST_JSON` (native Windows:
`bin/collect-worker-fleet.ps1`) collects that inventory in a normal child process
of the coordinator's existing shell. Use the same selected CLI as the live guide.
It never creates/reads/sends/closes terminals, starts workers, consumes mail or
changes a Run binding. This is distinct from C7's Run-scoped health check.

Write this UTF-8 request in the existing plan workspace:

```json
{
  "schema_version": 1,
  "orca_argv": ["/absolute/path/to/the-selected-orca"],
  "output_dir": "/absolute/plan-workspace/fleet-<fresh-attempt>"
}
```

`orca_argv` is an argv prefix, not shell source. The absolute output leaf must
be new and its parent must exist. Existing leaves are refused, including after
an interrupted attempt. Original request bytes go to `request.json`. Each page's
exact stdout goes to `NNNNNN-worker-list.json`, stderr to its `.stderr.log`.
No receipt is copied through a PTY, base64-encoded, edited or reconstructed.

The selected CLI runs only `orchestration worker-list --limit 100 --json`, then
the same command plus the exact opaque `--cursor`. Orca 1.4.205 infers a bound
Run even when `--run` is absent. For this read-only child only, the helper omits
`ORCA_TERMINAL_HANDLE` and `ORCA_PANE_KEY` and sets `ORCA_STRUCTURED_SESSION=1`.
That CLI marker prevents guessing a sibling/active pane; it grants no identity.
All connection/target/auth settings and the parent's environment/binding remain
unchanged. This compatibility behavior was checked against the installed CLI;
another build must still prove `scope.source:all` on every page. Never use this
environment for `check`, `send`, dispatch or other lifecycle operations.

The collector verifies `ok:true`, distinct receipt IDs, a stable
`_meta.runtimeId`, all-Run scope with no Run filter, limit 100, stable total,
unique Dispatch IDs, complete pagination and no partial-host error. Changed,
missing, malformed or scoped evidence fails closed, with no retry or terminal
fallback. It does not decide writer safety; the C6 validator still checks the
original worker rows and rejects unknown/external ownership.

Only a complete collection publishes `fleet.json`:
`{schema_version:1,fleet:[{path,sha256,cursor},...],runtime_id,worker_count,page_count}`.
Copy its `fleet` array mechanically into the C6 proposal. Original page bytes
remain authoritative and hashed; this manifest is not an Orca receipt and does
not authorize a transition by itself. Collect fresh receipts for the next
required proposal.

Stdout is one JSON line. Exit 0: `event:collected`, `fleet_file`, `output_dir`,
`page_count`, `worker_count`, `schema_version:1`. Exit 1: `event:error`, `reason`
and, when available, `receipt`/`output_dir`; partial receipts remain for diagnosis
but no success manifest is published. Never respond to error by opening a
terminal, shrinking pages, rewriting scope or accepting only the current Run.

Shared isolated fixtures: `python3 -B -m unittest discover -s tests
-p test_worker_fleet.py -v`; native Windows uses `python` and `ORCA_TEST_SHELL`
for each PowerShell. The finite fake CLI cannot contact real Orca/settings.

## Migration from schema 1

A schema 1 state is UNVERIFIABLE (`schema 1 state: run protocol-state migrate`).
`protocol-state migrate STATE_V1_JSON OUT_JSON` (input: a state or a proposal;
output: a new absolute file) runs once: `bootstrap` becomes the plan step with
the authorized plan path; it keeps the plan reference (structure computed from
the current bytes, which must match its hash), the ledger path, the current
step/phase's `accepted` entries (request-artifact entries dropped) and recorded
script gates as gate entries, phase commits and the completion commit (each with
its artifact's candidate), the final review's candidate as `final_source`,
cap extensions, waivers, provenance, rounds, processed message ids and used fleet
ids. Everything else is dropped. Then run `resume` on the output.

## Removed in v2

Ledger closure receipts (`closure`, `review_closure`, CHECK binding, fix/review
order), `report_history`, `protected_reports`, `format-correction` and its cap,
`commit_barrier` and `final` replay, `script_gates`, `processed.deliveries`,
child tracks (`track_group`), the first-plan request record and bootstrap step,
resume currency rules and declared-input freshness. None of them is read; the
coordinator does not write or re-prove them.

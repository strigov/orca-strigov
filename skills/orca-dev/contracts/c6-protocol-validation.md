# C6 — protocol validation (v2: the transition, not the history)

Part of [runtime-contracts.md](../runtime-contracts.md); load only when the index says so.

## Threat model

C6 guards a run of cooperating agents against **hallucination and drift**: a
coordinator or worker forgetting a step, misremembering a path or artifact,
claiming work it did not do, mixing up roles or model families, re-using a stale
file by mistake, or a worker writing outside its lane. Every requirement is a
fact the legitimate flow produces at that moment (a receipt, a sealed result, a
capture), so a mistaken proposal is rejected with a reason that names the next
legitimate step.

C6 is **not** a defence against a deliberately adversarial coordinator crafting
inputs to defeat the checker: the coordinator owns the state and saves the
receipts, and C6 does not authenticate them. Machinery whose only purpose is to
stop a crafted input is out of scope. Known bypasses that need deliberate
crafting, kept out of scope on purpose (the simple guards below still catch the
mistaken variants):

- **Pre-launch inventory plus a failure receipt.** `reconcile-intent` trusts an
  unused fleet and an `ok:false` launch receipt naming the Task; a crafted pair
  (an inventory collected before a retried launch, an old failure receipt) can
  drop a still-live writer's intent.
- **Stale completion with a changed plan.** A proposal pairing an old Dispatch's
  completion message with a plan author's changed plan reference returns
  `decision:stale` but adopts the plan bytes the author path allows.
- **Same command text elsewhere.** A cannot_verify `check` result is bound to the
  finding by its literal command and exit code, not by the checkout or platform
  it ran in; the same text sealed in another checkout passes.

**Legacy authorship rule (limitation).** A state written before C6 kept
cumulative `authors` cannot prove who wrote its earlier phases: their review
packages left the state at `advance`, and receipt counts or Dispatch timestamps
do not establish completeness. C6 therefore does not try. On upgrade, every file
changed by any recorded commit range of the Run (`plan_base`..the current
phase's `base`, and each recorded phase commit's own range, so a file restored
by a later phase is still included; every phase in the final steps) gets the
conservative superset: every
model family among the state's `provenance` writer observations plus the
families of every write row of every package the state still references (an
observation whose family cannot be read counts as every family). Files touched
only in the current phase follow the normal package and `record-author` rules.
The superset can only over-approximate authorship, so independence only gets
stricter; where it leaves no independent family for a file, the user's
`waive-independence` applies.

Known limitation: a writer family that appears neither in `provenance` nor in a
package the state still references (an earlier writer replaced without an
accepted report under the pre-upgrade runtime, its package dropped at `advance`)
is missing from the superset. Only states written before this upgrade can have
that gap; new states record authorship cumulatively. The two Runs upgraded in
practice were audited on 2026-10-05 against every package saved in their
workspaces (p3a-core: 6 packages, p3b-docsvc: 28; 12 and 56 package JSON files): every recorded writer family
of their source files (Google; OpenAI only for the plan file) is inside the
superset C6 computes for them.

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
   fresh complete fleet shows no live or unverifiable writer in the worktree,
   and every writer the state records is in that fleet, positively settled.
2. **Commit = accepted candidate** — a commit's tree equals the staged bytes and
   Git modes of the candidate that the gate and both reviews (or the step's
   required roles) accepted; a plan-only commit holds exactly the approved plan
   bytes.
3. **Independent review** — a reviewer's actual model family is outside every
   actual author family of each covered file and contract side, cumulatively
   over the Run, except files the user released with `waive-independence`
   because every known family authored them.

Also checked per transition: report binding, the actual launched model, round
caps and the user's records. Soft facts are never blocking: declared check
inputs, deferred findings and cannot_verify outcomes are ledger and report
content for the user to read.

Other subcommands: `protocol-state summary STATE_OR_PROPOSAL_JSON` prints the
compact facts of a saved state or proposal (read-only; the coordinator's only
way to inspect one). `protocol-state migrate STATE_V1_JSON OUT_JSON` converts a
schema 1 state once (see Migration). `claude-model-evidence`,
`antigravity-model-evidence` and the recovery-only `codex-model-evidence`
freeze model proof (see Observations).

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
 "cap_extensions":[],"independence_waivers":[],"provenance":[],"plan_authors":[],"authors":{},"attempts":[],
 "plan_approved":null,"accepted":[],"write_ownership":[],"phase_commits":[],"final_source":null,
 "processed_messages":[],"used_fleet_ids":[],"barrier":"..."}
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
- `provenance`: observation references of every accepted writer and of every
  settled writer registered by `record-author` (Path A start receipts for C5
  write receipts).
- `plan_authors`: observation references of the accepted or registered
  plan-writer/plan-reviser attempts (and of a `record-author` with a plan
  artifact) only; plan-review independence reads these. Empty means unknown:
  no plan reviewer is independent (`unknown plan authors`).
- `authors`: `{path: [family, …]}`, the cumulative actual author families C6
  recorded per repository path (plan file excluded) from every accepted or
  registered writer of the Run; never cleared by `advance` or the final steps.
- `attempts`: the consumed final-review attempts `{role,round,family}`, kept when
  `finish-checkpoint` clears `accepted`; a later final review needs a new round.
- `plan_approved`: the plan structure digest of the latest independent plan
  approval. When `plan.structure` differs (a substantive revision after the plan
  step) the plan review is pending (see Plan reference). `plan_approval_evidence`
  keeps the saved state a `resume` imported it from (see Actions).
- **Older states.** A state written before these fields existed is upgraded on
  its first validate, only from evidence it holds: `authors` from the validated
  write receipts of the C5 packages its accepted reviews used, plus the legacy
  superset for files of earlier phases (see Threat model); `plan_authors` from its accepted
  plan-writer/plan-reviser entries (their `provenance` observations) and from
  those package writes that touched the plan file; `attempts` = one consumed
  final-review attempt per counted round when it is in `delivery` or
  `completion`, or in `final-review` with `rounds.final_review > 0` (an older
  runtime may already have reopened it; there the identity `R<round>-REOPEN` is
  registered too, so the user's `extend-cap` can name it), else empty; `plan_approved` = the structure of its latest
  accepted plan-reviewer APPROVED artifact when no plan author's entry came
  later, else the plan-only commit's plan when no plan author's entry remains,
  else none (the revision awaits its plan review). Nothing rebuilt stays unknown,
  never independent or approved.
- `active` also keeps the dispatch-time `artifact` reference and `candidate`:
  they bound what that writer authored and prove an unbound launch wrote nothing.
  New `bind-dispatch` transitions also keep `active.bound_observation`, the exact
  original hashed observation reference including its actual-model proof.
- `final_source`: the candidate the final review accepted (set by
  `finish-checkpoint`); delivery and the completion commit must match it.

## Plan reference and bookkeeping

Plan frontmatter uses `protocol_version: 2`, the actual `orca_run` and full
`plan_base` (given to the plan writer up front, so the reviewed bytes are the
committed bytes), one-line JSON `contracts`, and phases with `risk`
(`none|SECURITY|DATA_LOSS|REGRESSION`), one-line JSON `consumes`/`produces`
(consumers reference earlier producers) and, once the phase starts, `base`.
In a phase step the current phase's `base` must equal `state.base`.

**Plan author's draft.** While the active assignment is a plan-writer or
plan-reviser (pending, bound, or settled with a rejected report), the live plan
file is that author's working draft: `bind-dispatch`, `accept-report`,
`record-author`, `reconcile-intent`, `resume` and a `dispatch` of a fresh plan
author do not require the live file to equal `state.plan`, and the fresh author
is assigned the accepted bytes (a workspace copy, `artifact kind:plan`). Every
other transition still requires the accepted bytes: after a failed or abandoned
attempt, either accept a fresh author's report or restore the accepted copy.

**Plan author's lane.** A plan writer or reviser edits the plan file only: its
dispatch captures the repository candidate (`active.source`). Its
`accept-report`, and `reconcile-intent` of its unbound intent, reject any change
to it with `plan author changed source outside the plan: revert it or attribute
it with record-author (route further source work to an implementer)` and keep
the assignment. Its dispatch also keeps the source entries it started from
(`active.source_files`). `record-author` of that plan author attributes the
change explicitly: its family joins `plan_authors` and `authors` for exactly the
delta against those dispatch-time entries, reversions to the base and deletions
included (an assignment saved without them: every path changed since the step
base, with a current snapshot artifact). Nothing is attributed silently.

**Pending plan review.** An accepted plan-writer/plan-reviser report that
changes the plan structure after the plan step (a mid-phase revision) sets the
barrier `awaiting_plan_review`: until an independent `plan-reviewer` APPROVED is
accepted on the revised plan (which records `plan_approved`), only plan authors,
plan reviewers and diagnosis may be dispatched, and `prepare-commit`,
`confirm-commit`, `advance`, `finish-checkpoint` and `complete` reject with
`plan revision awaits an independent plan review`. Bookkeeping edits do not
change the structure.

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
`{path: sha256 (or type), with "+x" appended when the index entry is mode
100755}` over the artifact's `repo:` entries, excluding missing entries, the
plan file and the step's accepted synthesis document (see Synthesis). HEAD,
capture exclusions, staging and declared inputs are not part of it: a C4
snapshot and a C5 package of the same bytes are the same candidate, and a commit
that leaves the bytes unchanged (phase or final-fix) does not stale an accepted
review. A Git executable-bit change after acceptance is a new candidate.

Canonical JSON is `json.dumps(value, ensure_ascii=True, sort_keys=True,
separators=(",", ":"))` on both backends (PowerShell writes the same bytes:
non-ASCII and DEL as lowercase `\uXXXX`, keys in Unicode code-point order also
beyond the BMP, Python float repr including `-0.0` and exact integral values
below 1e16 such as `1000000000000001.0`); JSON object keys and model
ids are compared case-sensitively on both. `verification canonical IN OUT`
writes those bytes (parity fixture).

A current **package** must start at the step base (`base` in the phase and
quickfix steps, `plan_base` in the final steps): otherwise `package base differs
from the step base`. A **range** package (`BASE HEAD`) reviews a committed tree,
so its candidate must be that tree: the requested head is the captured and the
current HEAD, nothing outside the plan file and the synthesis document differs
from that head in the worktree or index, and no untracked source is captured;
otherwise `range package differs from its reviewed tree`.

A *current* artifact matches a fresh snapshot of the worktree (same candidate);
otherwise `stale artifact`. Dispatch, accept-report, record-gate,
prepare-commit, finish-checkpoint and waive-independence require current
artifacts; confirm-commit and complete check currency inside the commit check.

## Actions

| Action | Inputs and effect |
| --- | --- |
| `resume` | Structure only: state shape, plan, bases, caps; returns the barrier. Optional `prior_plan_approval_state` (`{path,sha256}` of an earlier saved state or proposal of this Run): when its latest accepted `plan-reviewer` `APPROVED` entry has no plan author's entry after it, its report hash and BINDING (run, role, dispatch, round, artifact) match the entry, its reviewer family is outside every current `plan_authors` family, the state shares the Run, worktree, plan path and `plan_base`, its processed message ids are all in the current state, and the approved artifact's plan structure equals the current one, `plan_approved` is restored and `plan_approval_evidence` records the reference. Nothing else is taken from it (rounds, findings, ownership and source acceptances stay); otherwise `prior plan approval does not apply: <why>`. |
| `dispatch` | `fleet`, `proposed` (`run_id,task_id,dispatch_id:null,role,phase,round,worktree_id,model`, review `coverage`, optional `fix:true`, `gate_fix:true`), `artifact` (omitted only for the first plan-writer before the plan exists). Freezes the assignment, the artifact reference and its candidate in `active`; a writer becomes `pending:<task>` in `write_ownership`. Reviewer and gate-fix rounds go `count` or `count+1` within the cap; repeating a review role/round with the same family needs a new round unless that attempt was `BLOCKED` (a fresh retry keeps the round); review coverage must be independent. |
| `bind-dispatch` | `observation` of the pending fresh Task (not a `--retry-of`); the actual model must match the proposal (a roles.md `MODEL_ALIASES` alias matches its full-id prefix). A writer then owns the worktree. |
| `accept-report` | `event`, `message_id`, settled `observation`, `report`, `artifact` (omitted only when the assignment had none). Optional explicit `bound_observation` and legacy `bound_dispatch` recover missing observation facts after restart (see Observations). Clears `active`. |
| `record-gate` | Current `artifact`, `evidence` (sealed C4 `result.json` references of one verify-gate run) and optional `verdict` (`GATE_OK` default, or `GATE_FAIL`) in the phase, final-review or delivery step with no writer. GATE_OK: at least one pass, every failure a proven BASE inheritance; it resets the consecutive gate-fix count. GATE_FAIL: at least one failure BASE does not explain; the entry carries the finding `G<r>-B1` (r = `rounds.gate_fix + 1`) that a gate-fix cap extension can name. |
| `record-author` | `observation` (with `start`/`model_evidence` when the receipt reports no model) of a durably settled writer Dispatch of this Run and worktree whose report C6 rejected or that never reported, and the current `artifact` (a plan author may omit it before the plan exists): its bytes still carry its family. Required before anything replaces a bound writer that settled without an accepted report. Appends the reference to `provenance`; a plan author (the active plan-writer/reviser, or any author given with a `kind:plan` artifact) goes to `plan_authors`, any other writer's family is recorded in `authors` for the paths it changed (its own window when it is the active assignment or the Dispatch of its still unbound Task, else everything changed since the step base). The Dispatch of the active unbound Task (a launch that started with another model and wrote) also clears that intent. More author families only make reviews stricter; approvals that lose independence stop counting at readiness. |
| `reconcile-intent` | `fleet`, the current `artifact`, optional `launch_failure` (saved Orca receipt with `ok:false` naming the Task). Clears an unbound writer intent whose launch failed without writing: every fleet row of the intent's Task is positively settled (durably completed/failed, or released and exited), or no row exists and `launch_failure` is supplied; the tree is still the dispatch-time candidate — for a plan author, the source candidate captured at its dispatch (the plan file may differ; any source change keeps the intent with the plan-lane reason). A launch that wrote is registered with `record-author` instead, which clears the intent without reverting its changes. |
| `reopen-final` | `fleet`, in `delivery` or `completion` before the completion commit: a defect found in delivery or a completion-hook source repair returns to `final-review`. Clears `final_source`; keeps `accepted` findings (so a delivery gate failure stays nameable), commits, authorship, the final-review round count and the consumed final-review `attempts`: the next final review needs a new round. Takes the current `artifact` and registers the bound recovery item `R<round>-REOPEN` (an entry of role `reopen` citing that capture; its issue says whether the source changed after the final checkpoint), which the user's `extend-cap` can name at the cap — also when a completion hook reformatted source and nothing failed. |
| `prepare-commit` | `fleet`, current `artifact`; the candidate is ready and nothing is unstaged. Records nothing. |
| `confirm-commit` | `fleet`, the accepted `artifact`, `commit:{sha,base}`. Readiness plus the commit check; records the commit once (a repeat confirms the same commit idempotently). Steps `plan`, `phase`, `quickfix`, `final-review` (final-fix commit: a gate on the fixed bytes plus the final review). |
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
a plan reviewer's family differs from every plan author family (`plan_authors`).
Gate `GATE_OK` EVIDENCE: valid sealed C4 results of this candidate, at least one
passing, inherited failures proven by a BASE baseline with the same signature,
no reused origin where independent replay is required; a gate `GATE_FAIL`
carries the finding `G<r>-B1`. An accepted writer's family is recorded in
`authors` for the paths it changed between its dispatch-time artifact and the
delivered one (everything changed since the step base when the dispatch-time
capture is unknown); a plan author is recorded in `plan_authors`, and an
independent plan-reviewer APPROVED records `plan_approved`. A `SYNTHESIS_DONE`
report's line-2 path must be a file of the delivered artifact (see Synthesis). A defective report is rejected and the
role is simply re-dispatched (a new Task, same round).
SECURITY/DATA_LOSS findings return `decision:risk-escalation`.

## Resolution and readiness

A finding of an accepted entry is **resolved** when:

- the ledger entry with its id has `decision` `DEFER`, `NIT` or
  `REJECTED_BY_SCOPE`; `ESCALATED_TO_HUMAN` and `ACCEPTED` leave it unresolved
  until the user's answer is recorded as one of the three or the finding is
  fixed and re-reviewed; or
- it is `cannot_verify` and the ledger entry has `check`: an absolute path to an
  intact sealed C4 `result.json` whose `evidence.key.check.command` is the
  finding's literal `check` and whose exit code is the one its `expect` states
  first (`exit <n>`). Only the explicit form `exit <n>; stdout exactly: <text>`
  (the sealed stdout without trailing newlines equals `<text>`) or
  `exit <n>; stdout contains: <text>` is matched against the stdout; any other
  text after the exit code (`exit 0; stdout — …`) is the human-checked part the
  coordinator confirmed when it recorded the result. An `expect` that states no
  exit code cannot be closed by a check. The original candidate's bytes are not
  compared; or
- it is `blocking`, or it is a `cannot_verify` item whose literal CHECK actually
  ran and that the ledger accepted as a defect to fix — the ledger entry has
  `decision` `ACCEPTED`/`PARTIALLY_ACCEPTED` and `execution_evidence`: an intact
  sealed result of exactly the finding's `check` command (absolute path or
  `{path,sha256}`); C6 does not interpret its outcome or parse `expect` prose,
  that judgement belongs to the coordinator and the later independent reviewer —
  and the current candidate differs from the one the finding was raised on, and
  some later round of the same role on the current candidate covers the
  finding's unit — the file named before `:` in its
  `location` when the original review covered it as a file or in a contract
  side, else the original review's whole coverage — through the files and
  contract sides of its non-BLOCKED reports, none of which lists the id. A later
  partial reviewer that did not cover the unit resolves nothing. A plan-review
  finding belongs to the plan: outside the plan step it is matched against the
  latest accepted plan-reviewer APPROVED plan, not the source candidate (a
  mid-phase revision blocked on A, revised to B and approved closes normally).

A gate entry's finding (`G<r>-B1`) and a reopening's `R<round>-REOPEN` are
identities for cap extensions only: a positive gate, and the next final review,
supersede them.

The ledger is a JSON array of objects with unique string `id`; C6 reads nothing
else from it. A candidate is **ready** for the step's commit or checkpoint when
the current reports of each required role on that candidate are positive, no
finding of the step is unresolved, and every current review is still
independent of the authors now recorded (a `record-author` after an approval
can withdraw it). The current reports of a review role are the latest attempt of
each family in the role's latest round on the candidate (complementary
assignments share one round; a `BLOCKED` attempt is superseded by its retry);
of any other role, its latest report:

| Step | Required roles (positive token) |
| --- | --- |
| `plan` | `plan-reviewer` (APPROVED) on the plan bytes |
| `phase` | `gate` (GATE_OK or record-gate), `review-primary`, `review-control` (REVIEW_OK) |
| `quickfix` | `quickfix` (DONE / DONE_WITH_CONCERNS) |
| `final-review` | `review-final` (REVIEW_OK); a final-fix commit also needs `gate` (GATE_OK or record-gate) on the fixed bytes |
| `delivery` | `gate` (GATE_OK or record-gate) on `final_source` |

The reviews' COVERAGE together covers every file (except the plan file), part
and contract side of the first review's package. A contract side may name files
the package did not change (earlier phases' producers); reviewers list them in the
side after inspecting them, without file coverage, but a family recorded in
`authors` for such a file may not cover it, and a file written earlier in this
Run (changed since `plan_base`) with no recorded author is `unknown actual
author: <file>` until the package provenance declares its writer's receipt
(files untouched since `plan_base` have no author in this Run). Reviews of
earlier candidates stay in `accepted` only for their findings.

## Synthesis

A multi-round phase's synthesis document (Step 4.5) summarises the acceptance;
it does not reopen it. When a `synthesizer` report `SYNTHESIS_DONE` is accepted
and the synthesizer's only change (its dispatch-to-delivery window) is one
Markdown document directly under `docs/reviews/` (by convention
`docs/reviews/<slug>-<phase>.md`), its path and entry are recorded on the entry
(`synthesis:{path,entry}`). Any other path it wrote keeps the change in the
candidate: the reviewed artifact is stale and the gate and reviews follow as for
any change. From then on a recorded path leaves the
candidate identity of the step (like the plan file), so the reviewed artifact
stays current and the synthesis needs no further gate or review round; instead
every currency check requires the file to keep exactly the recorded bytes
(`stale synthesis: <path>`), so the commit holds the synthesizer's bytes. To
recover from a changed document, restore it or dispatch a new synthesizer: its
own dispatch and acceptance skip the frozen-bytes check and its accepted
document replaces the recorded one. The exclusion ends with the step (`advance`
clears `accepted`); the committed document is then ordinary history.

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
(confirm-commit in `final-review`) needs a gate (`record-gate` or a gate worker)
on the fixed bytes and keeps the final review valid when the bytes are those
reviewed. `finish-checkpoint` then records `final_source` and moves to
`delivery`; a delivery gate on the same candidate moves to `completion`; the
separate completion commit (top-level `status: done`) completes the plan. A
defect found in delivery, or a source repair a completion hook forces, goes back
through `reopen-final` to `final-review` (fix, gate, final review round, commit,
checkpoint again).

`state.barrier`, in order: `awaiting_writer` (a writer intent or bound writer);
`awaiting_plan_review` while a mid-phase plan revision awaits its review;
after a recorded commit of this step `ready_next_phase`, `awaiting_final_review`
or `complete`; `awaiting_final_review`, `awaiting_delivery`,
`awaiting_completion_commit` in the final steps; `awaiting_plan_writer` /
`awaiting_implementation` without a candidate (no entry, or the last writer
failed); `awaiting_commit` when ready; else `awaiting_plan_review` /
`awaiting_gate` without the first required role, `awaiting_resolution` with a
non-positive latest required report or an unresolved finding, `awaiting_review`
otherwise. The candidate of the plan step is the plan; of other steps the last
accepted entry that is not diagnosis, synthesis or a plan author/review.

Caps: plan review 4 per plan (its extensions count in every phase, so a plan
revision extended before a phase commit does not poison later phases), fused
review 4 per phase, final review 2, consecutive gate fix 2 (an accepted
GATE_OK resets the count). Only the user lifts a reached cap, one round per
`extend-cap` record naming accepted findings (a gate failure is `G<r>-B1`).

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

### Explicit observation recovery after restart

Only `accept-report` of an **already bound, same durable completed Dispatch**
may supply `bound_observation`, the hashed earlier full `worker-show` reference
with its original actual-model proof (`start`/`origin_start` or `model_evidence`).
It must equal `active.bound_observation`. For older states without that field,
also supply `bound_dispatch:{path,sha256}` of the original saved `bind-dispatch`
proposal or action fragment; its `action` must be `bind-dispatch` and its
`observation` must exactly equal `bound_observation`. This is explicit evidence
from the original bind, under C6's cooperating-agent threat model, not a claim
that C6 cryptographically authenticates an accepted historical transition.

The **current** `observation` stays primary: its Task, Dispatch, Run, assignee,
nonempty `processIncarnation`, `status:completed`, `completedAt` and boolean
durable evidence remain authoritative. The earlier receipt must share that
exact identity; its terminal needs nonempty `handle,ptyId,incarnationId,
worktreeId,worktreePath`, with `handle=assigneeHandle`,
`ptyId+":"+incarnationId=processIncarnation` and the exact active worktree id
and state worktree path. Provider id and actual model must be known. Missing,
malformed or incomplete facts are UNVERIFIABLE; differing identities or
conflicting non-null current provider/workspace/terminal/worker identity facts
are INVALID. Failed launches are rejected; an authentic injected Path B worker
may remain `unsupervised` in both receipts, and that fact is never hidden or
upgraded into a supervised start. No historical facts enable `dispatch`,
`bind-dispatch`, `record-author`, `resume` or any launch action.

Only missing provider id/model, workspace id and terminal identity facts are
filled in a validated **in-memory view**; dispatch, worker state, projection
stage/outcome/liveness and settlement evidence are never filled from history.
The current reference additionally carries fresh `model_evidence` proving the
model through completion, of the kind that matches the recovered provider id:
`claude-transcript` for `claude`, `antigravity-log` for `antigravity`,
`codex-rollout` for `codex`. Any other kind is UNVERIFIABLE (`recovery requires
a completion-covering model proof`); a kind of another provider is INVALID
(`model evidence kind does not match provider`). The initial proof alone is
insufficient. The window of a proof starts at this exact Orca preamble (same
task/dispatch/`--from` rule as below) and ends before the next preamble of
another Dispatch; it must contain a timestamp at or after current
`dispatch.completedAt`:

- `claude-transcript`: the same-session window as below; record `timestamp`;
  every assistant model in that whole window is the proof's model.
- `antigravity-log`: the `USER_INPUT` window of the frozen conversation
  transcript; row `created_at` (UTC). The model is the single model of the
  whole frozen CLI process log, as below, so the window needs no model rows.
- `codex-rollout`: the window of one frozen Codex rollout (see below); row
  `timestamp`; every `turn_context` in it names one model and a `cwd` inside
  the Dispatch worktree.

The proof's model must agree with the original bound actual model, any
non-null current model fact and the active proposed model (including roles.md
aliases). The verified in-memory effective model is the proof's full id; a
launch alias such as `opus` may agree with that id, but differing full model
ids remain conflicting.
A partial proof, absent completion time or unsupported completion proof is
UNVERIFIABLE; a model switch inside the window is INVALID. Freeze the actual
full session after settlement with the provider's builder, given the original
full bind-time observation as `OBSERVATION_JSON`. `antigravity-model-evidence`
and `codex-model-evidence` alternatively take the restart-damaged current
observation plus the original one as optional third argument
`BOUND_OBSERVATION_JSON`: the builder then takes only missing provider id,
workspace id and terminal facts from it, after the same Dispatch identity
check as above, and any present conflicting fact refuses (`claude-model-evidence`
keeps its optional third `TRANSCRIPT` argument). Never synthesize
timestamp/model rows or rewrite a receipt to satisfy this check.

The accepted entry retains the current `observation`, `bound_observation` and,
when supplied, `bound_dispatch` references. A recovered writer's provenance
retains the original full observation path/hash; when its raw model was null,
the reference metadata uses the fresh full completion proof instead of the
initial proof (the original reference is retained on the accepted entry).
C5 write rows for this recovered writer must cite that original bound
`receipt_path` and `receipt_sha256`, matching `state.provenance`; citing the
current null-facts receipt leaves authorship UNVERIFIABLE.
Report bytes, verdict, findings, coverage,
independence, artifact/candidate bindings, caps and rounds keep their ordinary
checks and effects. Recovery of REVIEW_BLOCKING preserves its findings; VALID
does not turn a blocking review into approval. No original file is rewritten,
merged, or enriched on disk. Run candidate validation without `RESUME_OUT` for
read-only reproductions; installing the candidate and applying a transition
are separate coordinator actions after independent review.

Orca reports `provider.model` for Codex but not for Claude or Antigravity, so
further model sources exist. Precedence: observed `provider.model`, then the one
launch-derived fact below; any two facts that are present must agree
(`conflicting actual model facts`). No source is the coordinator's word, saved argv, a comment or a message.

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
  proves no later model switch. Ordinary `accept-report` keeps this existing
  proof behavior. Only explicit restart recovery requires fresh full proof
  covering current `dispatch.completedAt`, as described above.
- **Antigravity log (`model_evidence` kind `antigravity-log`).** Only for
  `provider.id:"antigravity"` with a null `provider.model` and no `start`. Orca
  does not report the agy model and agy's conversation store is SQLite, which the
  native Windows validator cannot read; two text files are frozen instead by
  `protocol-state antigravity-model-evidence OBSERVATION_JSON SNAPSHOT_OUT [BOUND_OBSERVATION_JSON]`
  (the third argument only for restart recovery, see above):
  `SNAPSHOT_OUT` copies `brain/<conversation>/.system_generated/logs/transcript.jsonl`
  and `SNAPSHOT_OUT.cli.log` copies the one `log/*.log` CLI process log that
  created that conversation (under `$ORCA_AGY_HOME` or `~/.gemini/antigravity-cli`).
  The reference is `{kind,path,sha256,conversation_id,log:{path,sha256}}`. C6
  requires a `USER_INPUT` transcript row with this Dispatch's Orca preamble (same
  task/dispatch/`--from` rule), a log line `Created conversation <conversation_id>`
  and exactly one distinct `Resolving model <id>` in that process log. The
  conversation-to-transcript link is the directory name recorded by the builder,
  weaker than Claude's single transcript; a per-process model switch is conflicting.
  Only this raw CLI console log permits malformed UTF-8, and only in ordinary
  noise (glog truncates long lines and can cut a multi-byte character). Both
  builders and validators read the complete bytes, hash/copy those original bytes
  unchanged, and decode noise with replacement. A line that is not valid UTF-8 is
  noise only when (a) its header up to the **first `] `** is valid and the
  readable start of its message is not a fact marker or a prefix of one, or (b)
  it has no intact header and does not look like a glog record at all (no
  `file.go:<n>` and no `] ` followed by a fact marker). Otherwise it is UNVERIFIABLE: `malformed UTF-8 in Antigravity
  log header` when the header or its `] ` boundary is damaged (a damaged boundary
  must not make a `Resolving model` row disappear), `malformed UTF-8 in
  Antigravity fact record` when the marker or its value is damaged. Markers
  quoted later inside ordinary `HandleUserInput` text do not count. A
  `Created conversation` or `Resolving model` record at the boundary must be
  intact and complete; an incomplete/malformed fact row is also UNVERIFIABLE.
  End-anchored fact extraction and the complete-log ownership/one-model/no-switch
  checks are unchanged.
  LF and CRLF delimit records identically. Absolute unlinked paths, original-byte
  hashes, conversation ownership, the exact Task/Dispatch/assignee preamble and
  the single distinct model remain required. Generic references, observation
  JSON and all transcripts retain strict UTF-8 decoding. Never sanitize the saved
  log, change its hash or rewrite model facts/start receipts to obtain acceptance.
- **Codex rollout (`model_evidence` kind `codex-rollout`), restart recovery
  only.** An ordinary Codex observation keeps Orca's reported `provider.model`;
  this kind on any non-recovery observation, and on the bound observation of a
  recovery, is INVALID (`codex-rollout model evidence only in observation
  recovery`). `protocol-state codex-model-evidence OBSERVATION_JSON SNAPSHOT_OUT
  [BOUND_OBSERVATION_JSON]` requires provider id `codex` (after the optional
  bound fill) and searches `$CODEX_HOME` or `~/.codex`,
  `sessions/*/*/*/rollout-*.jsonl` (unlinked files changed since
  `dispatch.createdAt` minus five minutes); exactly one rollout must contain a
  user message (`type:"response_item"`, `payload.type:"message"`,
  `payload.role:"user"`, `input_text` content) with this Dispatch's Orca
  preamble; none or several are UNVERIFIABLE. It copies that file to the new
  absolute unlinked `SNAPSHOT_OUT` and prints `{model_evidence, model, source}`
  with the reference `{kind:"codex-rollout",path,sha256}`. C6 binds the copy:
  Codex writes each turn's `type:"turn_context"` row (`payload.model`,
  `payload.cwd`) just before that turn's user message, so the window starts at
  the `turn_context` directly preceding the preamble message (no message
  between them) and ends before the `turn_context` that opens the next
  Dispatch's preamble turn (or before that preamble itself). Every
  `turn_context` in the window needs a nonempty model and a `cwd` inside
  `terminal.worktreePath` (whose `terminal.worktreeId` equals the workspace);
  exactly one distinct model is the proof's model, several are conflicting,
  none is UNVERIFIABLE. One rollout file is one Codex session; the copy does
  not prove which model generated each output beyond these per-turn records.

Actual model-to-family mapping lives only in roles.md. C5 write provenance points
to these hashed observations; unknown or mixed authors need independent coverage.

## Fleet

`fleet` is an array of hashed `worker-list --json --limit 100` page references,
each with its input `cursor` (null for the first page), across all local runs.
C6 checks `scope.source:all`, `page.total/hasMore/nextCursor`, unique dispatch
IDs and each worker's workspace, dispatch status, resource ownership, terminal
state and durable/liveness projection. Incomplete/unknown observations block; a
receipt id proves freshness once (`used_fleet_ids`). Receipt uniqueness proves
non-reuse, not age: every Dispatch in `write_ownership` must be listed in the
fleet (`recorded writer missing from fleet: <id>`), so an inventory collected
before that writer started cannot clear it, and a recorded writer that settled
without an accepted report must be registered with `record-author` before any
transition that needs a fleet (`writer <id> settled without an accepted report:
record-author it first`). A durably completed or
failed retained terminal is not a writer even when its workspace is null,
provided ownership is not external/user-owned/pre-existing and release is not
pending/unknown; other null-workspace records remain unknown. Unknown/external
ownership or pending/unknown release in the worktree blocks, as does an unbound
writer intent: bind it, or clear a failed launch with `reconcile-intent`, before
another proposal.

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
ids. `plan_authors`, `authors`, `attempts` and `plan_approved` are left out:
the first validate rebuilds them (see Older states). Everything else is
dropped. Then run `resume` on the output.

## Removed in v2

Ledger closure receipts (`closure`, `review_closure`, CHECK binding, fix/review
order), `report_history`, `protected_reports`, `format-correction` and its cap,
`commit_barrier` and `final` replay, `script_gates`, `processed.deliveries`,
child tracks (`track_group`), the first-plan request record and bootstrap step,
resume currency rules and declared-input freshness. None of them is read; the
coordinator does not write or re-prove them.

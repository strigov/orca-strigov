# Runtime contracts

## Where each contract lives

Read one file when its situation applies; do not preload all of them.

| Contract | File | Read when |
| --- | --- | --- |
| C3 — one local command owner (`run-check`) | [contracts/c3-command-owner.md](contracts/c3-command-owner.md) | executing a CHECK or gate command, capability errors |
| C4 — exact inputs and verification evidence (`verify-gate`, snapshots) | [contracts/c4-verification-evidence.md](contracts/c4-verification-evidence.md) | gate runs, sealed results, snapshot reuse |
| C5 — complete frozen review package (`review-package`) | [contracts/c5-review-package.md](contracts/c5-review-package.md) | freezing a review package, provenance, coverage |
| C6 — transition validation (`protocol-state`: validate, summary, migrate, model evidence) and the fleet collector | [contracts/c6-protocol-validation.md](contracts/c6-protocol-validation.md) | composing a proposal; after an INVALID/UNVERIFIABLE the table below usually suffices |
| C7 — worker event waiter (`wait-worker-event`) | [contracts/c7-worker-event-waiter.md](contracts/c7-worker-event-waiter.md) | waiting for worker_done, acknowledging deliveries |
| C8 — coordinator session continuity (`coordinator-session`, hooks) | [contracts/c8-session-continuity.md](contracts/c8-session-continuity.md) | binding, checkpoints, holds, stop guard behaviour |

The two sections kept below are the ones a dispatched worker reads through its
`[RUNTIME_CONTRACTS_PATH]`: report binding and immutable attempts.

## C6 rejections — what to supply

`protocol-state validate` prints `INVALID` (contradictory bound facts, exit 1) or
`UNVERIFIABLE` (missing facts, exit 2) with a `reason`. Resolve the reason from
this table before re-reading the contract; `protocol-state summary` shows the
current state in twenty lines.

| Reason | Meaning → what to supply |
| --- | --- |
| `artifact path must be absolute`, `missing artifact: …`, `artifact hash mismatch: …`, `linked artifact path` | every `{path,sha256}` is an absolute literal path to an existing, unlinked file whose raw bytes hash to `sha256`; recompute after any rewrite (a changed plan or ledger needs a fresh `plan`/`ledger` reference) |
| `missing facts: …` | the named keys are absent from the proposal or record; add them literally |
| `schema 1 state: run protocol-state migrate`, `unsupported input schema`, `invalid protocol mode/step`, `missing plan outside the plan step` | the state predates schema 2 or names an unknown mode/step: run `protocol-state migrate` once; never upgrade by hand |
| `TARGET is not a Git worktree`, `missing recorded base`, `absolute workspace required` | `worktree` is the Git top level; `plan_base`/`base` are full existing commits; paths are absolute |
| `plan change outside the plan author/review path`, `plan path differs from state`, `plan structure differs from state` | only bookkeeping lines (status, phase status/base, commits, plan_base, orca_run) may change outside a plan writer/reviser report; other edits go through a reviser and a new plan review |
| `phase/base mismatch`, `plan/run/base mismatch`, `missing plan metadata: …`, `legacy metadata is not certified`, `format: missing/invalid phase risk`, contract-id errors | the plan's frontmatter must carry `protocol_version: 2`, the actual `orca_run`/`plan_base`, valid contracts and phases, and the current phase's `base:` equal to the state's base (record it after `advance`, then supply a fresh `plan`) |
| `ledger path differs from state`, `invalid ledger` | one ledger path per state; a JSON array of objects with unique string `id` |
| `unbound writer intent` | a `dispatch` proposal was validated but never bound; save the actual `worker-show` and run `bind-dispatch` (or re-dispatch the same ready Task) before any other proposal |
| `no pending dispatch intent`, `dispatch does not bind pending fresh Task` | `bind-dispatch` needs a prior VALID `dispatch` and the observation of that Task's Dispatch (not a `--retry-of`) |
| `actual launch differs from proposal`, `unknown actual model family`, `conflicting actual model facts` | observed model ≠ proposed, or no provider model: add `start`/`origin_start` (Path A) or `model_evidence` (`claude-model-evidence` / `antigravity-model-evidence`) to the observation reference |
| `missing fresh fleet`, `fleet observation already used`, `incomplete fleet`, `fleet must cover all local runs` | run `collect-worker-fleet` again and copy its manifest `fleet` array; each proposal needs an unused complete `scope:all` collection |
| `live or unverifiable prior writer`, `unresolved release/external ownership`, `unknown fleet workspace` | another writer in this worktree is live, unsettled, unknown or externally owned; settle, release or inspect it with real receipts first |
| `only a plan-writer may start before the plan exists` | the plan step starts with the plan writer; readers need the plan |
| `proposed binding mismatch`, `invalid proposed round`, `round cap/sequence: …`, `substantive review needs a new round` | role/run/phase/worktree must match the state; reviewer rounds go `count` or `count+1` within the cap; a repeat of the same role and round needs another model family |
| `missing exact delivery message`, `no current Dispatch`, `missing durable settlement` | `message_id` names one message of the saved `event`; a completion needs the active Dispatch, settled `completed` with durable evidence |
| `wrong report sender`, `report path/subject mismatch`, `report path already bound to an accepted attempt` | the message comes from the assignee, carries the absolute report path and a subject whose first token equals report line 1; every attempt has its own report path |
| `format: …`, `conflicting report binding: …`, `conflicting artifact binding` | the report is rejected: dispatch the same role again (new Task and Dispatch, same round, fresh ATTEMPT report) with the reason; never hand-edit a report |
| `assigned artifact changed`, `assigned plan mismatch`, `plan author must deliver the current plan` | a reader reports on its assigned artifact; a plan author's acceptance supplies the fresh `plan` and a workspace copy of exactly those bytes as `artifact` |
| `stale artifact: the working tree is no longer this candidate` | source changed after capture: capture again; gate and reviews follow on the new candidate |
| `incomplete package`, `invalid snapshot`, `artifact worktree mismatch` | the manifest is not `complete:true` with a matching `package_id` / not `valid:true`, or was captured in another worktree |
| `same-family review: <file>`, `same-family plan review`, `unknown plan authors` | choose a reviewer family outside every author of each covered file (plan: every recorded writer); when every family authored a file, record the user's `waive-independence` |
| `unknown actual author: <file>`, `unknown write provenance`, `claimed author family differs from launch`, `review requires a complete package` | package provenance must list a saved write receipt per changed file whose observed model family matches `family` |
| `unknown coverage …`, `unknown contract side`, `contract side lacks file review`, `incomplete file coverage`, `incomplete part coverage`, `incomplete contract …` | review `COVERAGE` lists exact manifest files, parts and contract sides; together the reviews cover every file (except the plan), part and side |
| `required report is missing: <role>`, `required report is not positive: <role>` | the latest report of each required role on this candidate must be positive: gate (or `record-gate`) + both reviews in a phase, plan review in the plan step, review-final / delivery gate in the final steps |
| `unresolved findings: …` | a finding resolves by a later-round review of the candidate that omits it, a ledger `DEFER`/`NIT`/`REJECTED_BY_SCOPE`/`ESCALATED_TO_HUMAN` decision, or a cannot_verify `check` result with exit 0; supply the fresh `ledger` |
| `missing executable evidence`, `stale or invalid runner evidence`, `evidence snapshot mismatch`, `zero passing checks`, `unproven inherited failure`, `required replay reused implementer evidence` | gate EVIDENCE / `record-gate` cites intact sealed C4 results of this candidate, at least one passing; a failure inherited from BASE needs its BASE baseline |
| `script gate outside an unowned phase or delivery candidate` | `record-gate` only in the phase or delivery step with no writer |
| `hook/working-tree or unstaged source after acceptance`, `accepted source was not staged` | stage every candidate path; nothing may change or stay unstaged after acceptance (hooks, formatters, manual edits) |
| `missing full commit identity`, `commit not found`, `base is not a completion commit`, `commit is not above its base on HEAD`, `commit base differs from accepted candidate HEAD`, `commit does not contain accepted index/source`, `commit changes the plan beyond bookkeeping`, `not a commit step` | `commit.sha`/`base` are full SHAs of the actual commit and the accepted artifact's HEAD; its tree is the accepted candidate (the plan file may differ in bookkeeping lines only) |
| `plan commit base differs from plan_base`, `plan commit must change only the plan file`, `plan commit blob differs from accepted plan` | a plan-only commit uses the approved `kind:plan` artifact: `base` = `plan_base`, only the plan path, exactly the approved bytes |
| `advance before the phase commit is confirmed`, `uncommitted phases`, `not a final checkpoint`, `delivery covers a different source than the final review`, `completion candidate differs from the final-reviewed source`, `completion requires a separate commit`, `final bookkeeping is incomplete` | confirm each phase commit before `advance`; the delivery gate and completion commit match the final-reviewed source; the completion commit is separate and its plan says `status: done` |
| `cap extension …`, `independence waiver …` | these records are the user's words: run, phase/step, group or files and a non-empty `user_decision`; a cap extension names accepted findings at a reached cap, a waiver only files every family authored |
| `resume output outside existing workspace`, `linked resume output`, `resume must not replace an input artifact` | RESUME_OUT must be a new path inside the plan workspace |

## Report binding

Every role report contains exactly one machine-readable line after its existing
verdict/summary prefix (primary keeps SPEC/QUALITY on lines 2/3; gate and synthesis
keep their line 2; implementers keep the one-line test summary):

```text
BINDING: {"schema_version":1,"run_id":"<Orca Run>","task_id":"<Task>","dispatch_id":"<current Dispatch>","role":"<role>","phase":"<phase or null>","round":1,"artifact_id":"<plan SHA256, snapshot id or package id>","snapshot_id":"<C4/C5 snapshot id or null for a plan>"}
```

Use the live preamble's actual identities and the coordinator's frozen assignment,
never a previous Dispatch. Writers bind their completed artifact; readers bind
the assigned artifact. Hash the actual report bytes after writing. The `subject`
leads with line 1's exact token (anything after `:` or a space is ignored) and
`outcome` must match the role verdict: `BLOCKED` and
writer `NEEDS_CONTEXT`/`NEEDS_AUTHORIZATION` fail; a produced review/gate/diagnosis
artifact succeeds even when its substantive verdict requires more work.
`BLOCKED` needs `## Reason`. Existing human-readable details remain in the report.

In `worker_done`, `--files-modified` / `payload.filesModified` lists changed
deliverable files as worktree-relative POSIX paths (`src/file.py`, not absolute
paths, backslashes or `./` prefixes). For package work these strings must match
the package manifest entries exactly. Exclude the Dispatch report, receipts and
runner logs; send the report through `--report-path` and evidence through the
report fields. Omit `--files-modified` when no deliverable files changed.

All reviews add `FINDINGS: <JSON array>` (including `[]`). Each entry has `id`,
`kind` (`blocking` or `cannot_verify`), `issue`, `location`. A `cannot_verify`
entry needs executable `check` and literal `expect`; it stays unresolved without
verification. Blocking primary/plan/final entries need `class`
(`MUST_FIX_NOW` or `REGRESSION_FROM_AUTHORIZED_FIX`), `change`, `risk`; control
entries need `authorization_relation`, `why_now`, `minimal_fix`, `risk`.
Risk is `none`, `SECURITY`, `DATA_LOSS`, `REGRESSION` or `GUARANTEED_FAIL`.
Plan entries also need `criterion`, and a new MUST_FIX_NOW after round 1 needs
`new_blocker_materiality`. A simplicity blocker sets `simplicity: true` and
includes `unnecessary_cost_or_risk`, `simpler_alternative`, `preserved_properties`.
Plan review retains `## Simplicity` and `SIMPLICITY: OK|CHANGES_REQUESTED`.
The blocking array and verdict/SPEC/QUALITY must agree. SECURITY/DATA_LOSS causes
immediate risk escalation; nonblocking observations remain in DEFER/NITS.

Primary/control/final add `COVERAGE: {"files":[],"parts":[],"contracts":[]}`;
paths are exact manifest entries, each contract is `{id,producer:[],consumer:[]}`.
Every covered contract-side file also needs file coverage. Complementary reports
cover all files, all parts and both sides, using actual reviewer families outside
every recorded author family. CLI/provider identity alone does not prove family.
Gate `GATE_OK` adds `EVIDENCE: <nonempty array of file references>` to sealed C4
results; inherited failures also supply a `baseline` result reference. At least
one check must pass; required independent replay cannot use an origin result.
Implementer/frontend/quickfix fix rounds add `FIX_EVIDENCE: {"tests":[],"commands":[],"outputs":[]}`
with nonempty actual evidence. Diagnosis keeps its token-specific Context/Split/
Plan defect/Summary section and `## Evidence`; synthesis keeps its output path.
A fix may add `FIX_EVIDENCE.findings: [{"id","report":{"path","sha256"}}]` naming
the findings it addresses; reviewers use it, C6 does not require it.

A report with a missing field, conflicting identity or changed artifact is
rejected. The coordinator dispatches the same role again (new Task and Dispatch,
same round, fresh report); it is not a second worker_done for the settled
Dispatch. No verdict is inferred from prose.

## Immutable attempts and byte parsing

Allocate an unused `ATTEMPT` nonce before each Task/Dispatch, including initial,
fix, context-answer, re-dispatch, fallback and final-fix routes. Use
`<workspace>/<role>-<phase>-r<round>-<ATTEMPT>.md` (`final-fix-r<round>-<ATTEMPT>.md` for a
Step 5 fix, `quickfix-<ATTEMPT>.md` on the plan-less path); a round or terminal alone
is not unique. `PREVIOUS_REPORT_FILE` is read-only. Each report contains one current
BINDING and all applicable FIX_EVIDENCE, including a retry inside the same round
(`proposed.fix:true` for a fix whose round remains 1). C6 refuses a report path
already bound to an accepted entry; a rejected report stays on disk unchanged.

All report hashes cover original bytes, including BOM, line endings and EOF.
Only after checking that hash do both parsers normalize CRLF to LF. SIMPLICITY,
BINDING, FINDINGS, COVERAGE, EVIDENCE, FIX_EVIDENCE and verdict prefixes follow
the same parsing rule. A newline rewrite is still a hash mutation.

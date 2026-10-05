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
| `plan change outside the plan author/review path`, `plan path differs from state`, `plan structure differs from state` | only bookkeeping lines (status, phase status/base, commits, plan_base, orca_run) may change outside a plan writer/reviser report; other edits go through a reviser and a new plan review. While a plan author's attempt is active its draft is tolerated for that attempt and for a fresh author dispatch; anything else needs the accepted bytes back (restore the workspace copy) |
| `phase/base mismatch`, `plan/run/base mismatch`, `missing plan metadata: …`, `legacy metadata is not certified`, `format: missing/invalid phase risk`, contract-id errors | the plan's frontmatter must carry `protocol_version: 2`, the actual `orca_run`/`plan_base`, valid contracts and phases, and the current phase's `base:` equal to the state's base (record it after `advance`, then supply a fresh `plan`) |
| `ledger path differs from state`, `invalid ledger` | one ledger path per state; a JSON array of objects with unique string `id` |
| `unbound writer intent` | a `dispatch` proposal was validated but never bound; save the actual `worker-show` and run `bind-dispatch`, or, when the launch failed, `reconcile-intent` before any other proposal |
| `no pending dispatch intent`, `dispatch does not bind pending fresh Task` | `bind-dispatch` / `reconcile-intent` need a prior VALID writer `dispatch` still unbound, and `bind-dispatch` the observation of that Task's Dispatch (not a `--retry-of`) |
| `missing launch failure evidence`, `the failed launch changed the candidate: bind it or record-author its writer` | `reconcile-intent` needs every fleet row of the Task positively settled, or (no Dispatch was created) the saved `ok:false` launch receipt naming the Task. A launch that changed the tree is a writer: bind it, or (it started another model) run `record-author` with its settled observation and the current artifact, which records its files and clears the intent without reverting them |
| `actual launch differs from proposal`, `unknown actual model family`, `conflicting actual model facts` | observed model ≠ proposed, or no provider model: add `start`/`origin_start` (Path A) or `model_evidence` (`claude-model-evidence` / `antigravity-model-evidence`) to the observation reference |
| `missing fresh fleet`, `fleet observation already used`, `incomplete fleet`, `fleet must cover all local runs` | run `collect-worker-fleet` again and copy its manifest `fleet` array; each proposal needs an unused complete `scope:all` collection |
| `live or unverifiable prior writer`, `unresolved release/external ownership`, `unknown fleet workspace` | another writer in this worktree is live, unsettled, unknown or externally owned; settle, release or inspect it with real receipts first |
| `recorded writer missing from fleet: <id>` | the fleet predates a writer the state records (an unused but old inventory proves nothing about it): collect a fresh fleet, which lists every Dispatch |
| `writer <id> settled without an accepted report: record-author it first` | a bound writer settled but its report was rejected or never came: run `record-author` with its settled observation (and model proof) and the current artifact, then dispatch the replacement |
| `plan author changed source outside the plan: revert it or attribute it with record-author (route further source work to an implementer)`, `plan author changed source outside the plan: record-author it with a current snapshot artifact` | a plan writer/reviser edited a non-plan file (on its report or on reconciling its failed launch): restore the file, or register the author with `record-author` and a current snapshot artifact (its family then authors those paths); further source work goes to an implementer Task |
| `prior plan approval does not apply: <why>` | the `prior_plan_approval_state` given to `resume` is not an earlier saved state of this Run, worktree, plan and `plan_base`, holds no independent accepted plan approval with a matching report binding, has a plan author's entry after it, or approved another structure; supply the saved state written right after that plan review was accepted, or dispatch an independent plan review |
| `plan revision awaits an independent plan review` | a plan writer/reviser changed the plan structure after the plan step, or an upgraded older state holds no approval evidence for its current structure: when an earlier saved state of this Run holds the accepted independent approval of exactly this structure, `resume` with `prior_plan_approval_state` restores it; otherwise dispatch a plan reviewer outside every plan author family on the current plan; its APPROVED clears the barrier (`awaiting_plan_review`) |
| `only a plan-writer may start before the plan exists` | the plan step starts with the plan writer; readers need the plan |
| `proposed binding mismatch`, `invalid proposed round`, `round cap/sequence: …`, `substantive review needs a new round` | role/run/phase/worktree must match the state; reviewer and gate-fix rounds go `count` or `count+1` within the cap; a substantive repeat of the same review role and round needs another model family or a new round (a retry of a `BLOCKED` attempt keeps the round); after `reopen-final` the next final review needs a new round (at the cap: the user's `extend-cap` naming the `R<round>-REOPEN` item reopening registered, or a recorded delivery failure) |
| `missing exact delivery message`, `no current Dispatch`, `missing durable settlement` | `message_id` names one message of the saved `event`; a completion needs the active Dispatch, settled `completed` with durable evidence |
| `wrong report sender`, `report path/subject mismatch`, `report path already bound to an accepted attempt` | the message comes from the assignee, carries the absolute report path and a subject whose first token equals report line 1; every attempt has its own report path |
| `format: …`, `conflicting report binding: …`, `conflicting artifact binding` | the report is rejected: dispatch the same role again (new Task and Dispatch, same round, fresh ATTEMPT report) with the reason; never hand-edit a report |
| `assigned artifact changed`, `assigned plan mismatch`, `plan author must deliver the current plan` | a reader reports on its assigned artifact; a plan author's acceptance supplies the fresh `plan` and a workspace copy of exactly those bytes as `artifact` |
| `stale artifact: the working tree is no longer this candidate` | source or a Git executable bit changed after capture: capture again; gate and reviews follow on the new candidate |
| `stale synthesis: <path>`, `synthesis path is not in the delivered artifact` | the accepted synthesis document must keep its accepted bytes until the phase commit (restore them, or dispatch and accept a new synthesizer); a `SYNTHESIS_DONE` report's line 2 names a file of its delivered snapshot. A synthesizer that wrote anything besides one `docs/reviews/*.md` leaves its change in the candidate (`stale artifact`: gate and reviews again) |
| `incomplete package`, `invalid snapshot`, `artifact worktree mismatch` | the manifest is not `complete:true` with a matching `package_id` / not `valid:true`, or was captured in another worktree |
| `package base differs from the step base`, `range package differs from its reviewed tree` | package from the phase/quickfix `base` (final steps: `plan_base`); a `BASE HEAD` package needs HEAD = its head and a worktree/index equal to that commit (plan file and synthesis aside); otherwise package `WORKTREE` |
| `same-family review: <file>`, `same-family plan review`, `unknown plan authors` | choose a reviewer family outside every author of each covered file and contract side, cumulatively over the Run (C6 `authors` plus the package's write receipts); plan: every plan writer/reviser (`plan_authors`, rebuilt once for an older state; empty means unknown: register the plan author with `record-author`, `kind:plan` artifact); when every family authored a file, record the user's `waive-independence`. At readiness the reason means a later `record-author` withdrew an approval: re-review that unit independently |
| `unknown actual author: <file>`, `unknown write provenance`, `claimed author family differs from launch`, `review requires a complete package` | package provenance must list a saved write receipt per changed file whose observed model family matches `family`, and per unchanged contract-side file written earlier in this Run that C6 has no author for; for a file an upgraded older state lists in `authors_incomplete`, one write row dispatched in each listed change window (receipt `dispatch.createdAt`); a writer whose report was rejected is registered with `record-author` (its settled observation plus model proof) before the package is reviewed |
| `unknown coverage …`, `unknown contract side`, `contract side lacks file review`, `incomplete file coverage`, `incomplete part coverage`, `incomplete contract …` | review `COVERAGE` lists exact manifest files, parts and contract sides; `files` holds only changed files, while contract sides may also name unchanged producers/consumers that were inspected; together the reviews cover every file (except the plan), part and side |
| `required report is missing: <role>`, `required report is not positive: <role>` | the latest report of each required role on this candidate must be positive: gate (or `record-gate`) + both reviews in a phase, plan review in the plan step, review-final / delivery gate in the final steps |
| `unresolved findings: …` | a finding resolves by a later-round review of the candidate that covers its unit (as a file or a contract side) and omits it, a ledger `DEFER`/`NIT`/`REJECTED_BY_SCOPE` decision (`ESCALATED_TO_HUMAN` keeps it open), or a cannot_verify `check` result of its literal CHECK command with the exit code its `expect` states (and its stdout, for the explicit `stdout exactly\|contains:` form); supply the fresh `ledger` |
| `missing executable evidence`, `stale or invalid runner evidence`, `evidence snapshot mismatch`, `zero passing checks`, `zero failing checks`, `unproven inherited failure`, `required replay reused implementer evidence`, `unknown gate verdict` | gate EVIDENCE / `record-gate` cites intact sealed C4 results of this candidate: GATE_OK at least one passing and every failure inherited from BASE (with its baseline); `verdict:"GATE_FAIL"` at least one failure BASE does not explain |
| `script gate outside an unowned phase, final-review or delivery candidate` | `record-gate` only in the phase, final-review (final-fix) or delivery step with no writer |
| `hook/working-tree or unstaged source after acceptance`, `accepted source was not staged` | stage every candidate path; nothing may change or stay unstaged after acceptance (hooks, formatters, manual edits) |
| `missing full commit identity`, `commit not found`, `base is not a completion commit`, `commit is not above its base on HEAD`, `commit base differs from accepted candidate HEAD`, `commit does not contain accepted index/source`, `commit changes the plan beyond bookkeeping`, `not a commit step` | `commit.sha`/`base` are full SHAs of the actual commit and the accepted artifact's HEAD; its tree is the accepted candidate (the plan file may differ in bookkeeping lines only) |
| `plan commit base differs from plan_base`, `plan commit must change only the plan file`, `plan commit blob differs from accepted plan` | a plan-only commit uses the approved `kind:plan` artifact: `base` = `plan_base`, only the plan path, exactly the approved bytes |
| `advance before the phase commit is confirmed`, `uncommitted phases`, `not a final checkpoint`, `delivery covers a different source than the final review`, `completion candidate differs from the final-reviewed source`, `completion requires a separate commit`, `final bookkeeping is incomplete` | confirm each phase commit before `advance`; the delivery gate and completion commit match the final-reviewed source (a repair goes back through `reopen-final`); the completion commit is separate and its plan says `status: done` |
| `reopen-final outside delivery or completion` | `reopen-final` returns from `delivery` or `completion` (before the completion commit) to the final review |
| `cap extension …`, `independence waiver …` | these records are the user's words: run, phase/step, group or files and a non-empty `user_decision`; a cap extension names accepted findings at a reached cap (a failed script gate is recorded with `record-gate verdict:"GATE_FAIL"` as `G<r>-B1`), a waiver only files every family authored |
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
`kind` (`blocking` or `cannot_verify`), `issue`, `location` (start with the file
path, `path:line`, so a later partial review is matched to the right unit). A
`cannot_verify` entry needs one executable `check` command and an `expect` that
starts with its exit code: `exit <n>`, `exit <n>; stdout exactly: <text>`,
`exit <n>; stdout contains: <text>`, or `exit <n>` followed by text the
coordinator checks by reading the output. It stays unresolved until the sealed
result of that literal command exits with that code (and, for the explicit
stdout forms, shows that stdout); an `expect` without an exit code needs a
ledger decision. Blocking primary/plan/final entries need `class`
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
Every covered contract-side file that the package changed also needs file
coverage. A side may name a file the package did not change (a producer from an
earlier phase): list it in that contract side once it was inspected; it needs no
file coverage and carries no authorship. Complementary reports
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

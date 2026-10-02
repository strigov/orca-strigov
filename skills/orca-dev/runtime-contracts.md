# Runtime contracts

## Where each contract lives

Read one file when its situation applies; do not preload all of them.

| Contract | File | Read when |
| --- | --- | --- |
| C3 — one local command owner (`run-check`) | [contracts/c3-command-owner.md](contracts/c3-command-owner.md) | executing a CHECK or gate command, capability errors |
| C4 — exact inputs and verification evidence (`verify-gate`, snapshots) | [contracts/c4-verification-evidence.md](contracts/c4-verification-evidence.md) | gate runs, sealed results, snapshot reuse |
| C5 — complete frozen review package (`review-package`) | [contracts/c5-review-package.md](contracts/c5-review-package.md) | freezing a review package, provenance, coverage |
| C6 — protocol validation and resume (`protocol-state`), plus bootstrap, child tracks and ledger closure | [contracts/c6-protocol-validation.md](contracts/c6-protocol-validation.md) | composing a proposal; after an INVALID/UNVERIFIABLE the table below usually suffices |
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
| `artifact path must be absolute`, `missing artifact: …`, `artifact hash mismatch: …`, `linked artifact path` | every `{path,sha256}` is an absolute literal path to an existing, unlinked file whose raw bytes hash to `sha256`; recompute after any rewrite |
| `missing facts: …` | the named keys are absent from the proposal or record; add them literally |
| `unbound writer intent` | a `dispatch` proposal was validated but never bound; save the actual `worker-show` and run `bind-dispatch` (or re-dispatch the same ready Task) before any other proposal |
| `no pending dispatch intent` | `bind-dispatch` without a prior VALID `dispatch` for that Task |
| `dispatch does not bind pending fresh Task` | the observation's Task/Run differ from the proposal, or it is a `--retry-of` Dispatch; bind the Dispatch of the proposed Task |
| `actual launch differs from proposal` | observed model ≠ proposed model; fix the proposal or launch the proposed model |
| `unknown actual model family` | the observation has no provider model: add `start` (Path A receipt) or `model_evidence` (`claude-model-evidence` / `antigravity-model-evidence`) to the observation reference |
| `missing fresh fleet`, `fleet observation already used`, `incomplete fleet`, `fleet must cover all local runs` | run `collect-worker-fleet` again and copy its manifest `fleet` array; each proposal needs an unused complete `scope:all` collection |
| `live or unverifiable prior writer`, `unresolved release/external ownership` | another writer Dispatch in this worktree is live, unsettled or externally owned; settle, release or stop it with real receipts first |
| `unknown fleet workspace` | a worker record has no workspace: it is unsettled and unknown — inspect it (`worker-show`) before proceeding |
| `proposed binding mismatch`, `invalid proposed round`, `round cap/sequence: …`, `substantive review needs a new round` | role/run/phase/worktree must match the state; reviewer rounds go `count` or `count+1` within the cap; a repeat of the same role and round needs another model family |
| `missing exact delivery message`, `unprocessed message in an acknowledged delivery` | `message_id` must name one message in the saved `event`; acknowledge a delivery only after every message in it was processed |
| `missing durable settlement` | `worker-show` must report `dispatch.status: completed` with durable evidence; wait or re-observe |
| `wrong report sender`, `report path/subject mismatch` | the message must come from the Dispatch's assignee and carry the absolute report path; its subject's first token must equal line 1 of the report |
| `format: …` | a report-shape defect (role verdict, BINDING, SPEC/QUALITY, FINDINGS fields, FIX_EVIDENCE, sections): one `format-correction` Dispatch of the same role/round, never a hand edit |
| `conflicting report binding: …`, `conflicting artifact binding` | the report's BINDING line must repeat the live assignment (run, task, dispatch, role, phase, round, artifact and snapshot ids) |
| `assigned artifact changed` | a reader role reported on a different artifact than it was assigned |
| `stale snapshot`, `stale or incomplete package` | the referenced C4 snapshot / C5 package no longer equals the working tree: source changed after capture — capture again (gate, package, reviews follow) |
| `incomplete package`, `invalid snapshot`, `artifact worktree mismatch` | the manifest is not `complete:true` / `valid:true`, or was captured in another worktree |
| `same-family review: <file>` | the reviewer's model family authored that file; choose a family outside every author of each covered file, or, when every family authored it, record the user's `waive-independence` |
| `unknown actual author: <file>`, `unknown write provenance`, `claimed author family differs from launch` | package provenance must list a saved write receipt per changed file whose observed model family matches `family` |
| `incomplete file coverage`, `incomplete part coverage`, `incomplete contract …` | review `COVERAGE` must list every package file, part and contract side |
| `required report is missing`, `unresolved findings or verification` | commit needs accepted gate, review-primary and review-control (or review-final / gate at the final steps) on the candidate's bytes with positive tokens and every finding closed |
| `open accepted ledger findings`, `open accepted findings` | ledger ids are still open; close them with evidence receipts or a recorded DEFER/NIT/REJECTED_BY_SCOPE decision |
| `closure report is not accepted`, `closure wrong finding`, `closure finding binding mismatch` | the receipt's `report` must be an accepted report in history containing `finding_id` |
| `closure report order must be finding, fix, re-review`, `closure requires distinct accepted attempts`, `closure missing successful fix`, `closure fix finding binding mismatch` | blocking closure = original report, then an accepted fix whose FIX_EVIDENCE names this finding and report, then a later-round positive independent review; three distinct Dispatches |
| `closure missing positive re-review`, `closure review artifact mismatch`, `closure fix lacks review coverage` | the re-review must be REVIEW_OK/APPROVED without the finding, cover the fix's files, and `artifact` must be that review's artifact |
| `closure CHECK binding mismatch` | cannot_verify closure: `command` and `expect` are the finding's literal values; `artifact` is the finding's own artifact, or a later positive review's artifact named in `review_report` |
| `closure snapshot mismatch`, `closure command mismatch`, `negative closure CHECK; finding remains blocking`, `stale or invalid closure CHECK evidence` | the sealed result must have run the exact command on the receipt artifact's bytes with exit 0 and an intact seal |
| `stale closure source`, `stale closure HEAD` | the closure's bytes (and the CHECK's declared inputs) are no longer the working tree and no recorded phase commit holds them; re-run on the current candidate |
| `hook/working-tree or unstaged source after acceptance`, `hook/working-tree change after acceptance` | something changed the tree after acceptance (hooks, formatters, manual edits); re-capture and re-review, or restore the bytes |
| `commit artifact differs from accepted candidate`, `commit does not contain accepted index/source`, `missing full commit identity` | `commit.sha` must be the full SHA of a commit whose tree equals the accepted snapshot; supply the actual `git` facts |
| `uncommitted phases`, `not a final checkpoint`, `completion requires a separate commit`, `final bookkeeping is incomplete` | final steps need every phase committed, a plan-only completion commit distinct from phase commits, and `status: done` in the plan |
| `cap extension …`, `independence waiver …` | these records are the user's words: run, phase/step, group or files and a non-empty `user_decision`; a cap extension only at a reached cap, a waiver only for files every family authored |
| `legacy resume is unverifiable`, `unsupported input schema`, `invalid protocol mode/step` | the state predates `schema_version:1` or names an unknown mode/step; do not upgrade it by hand |
| `resume output outside existing workspace`, `resume must not replace an input artifact` | RESUME_OUT must be a new path inside the plan workspace |

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
Fixes addressing accepted blocking findings also carry `FIX_EVIDENCE.findings`
with exact original report references; see the ledger closure contract below.

A missing required field permits exactly one format-correction Task/Dispatch,
same role, artifact, snapshot and round, normally in the retained terminal.
Prior findings remain unresolved; a repeated defect is a protocol blocker.
This is neither a substantive review round nor a second worker_done for the
settled Dispatch. Conflicting identities or changed artifacts are not format-only
defects. No verdict is inferred from prose.

## Immutable attempts and byte parsing

Allocate an unused `ATTEMPT` nonce before each Task/Dispatch, including initial,
fix, context-answer, format-correction, fallback and final-fix routes. Use
`<workspace>/<role>-<phase>-r<round>-<ATTEMPT>.md` (`final-fix-r<round>-<ATTEMPT>.md` for a
Step 5 fix, `quickfix-<ATTEMPT>.md` on the plan-less path); a round or terminal alone
is not unique. `PREVIOUS_REPORT_FILE` is read-only. Each report contains one current
BINDING and all applicable FIX_EVIDENCE, including a retry inside the same round
(`proposed.fix:true` for a fix whose round remains 1). C6 retains `report_history`
even after a later round supersedes an accepted verdict, verifies prior hashes
on resume and refuses reuse of a previous attempt's report path. A defective
format report is also retained as immutable input to its correction.

All report hashes cover original bytes, including BOM, line endings and EOF.
Only after checking that hash do both parsers normalize CRLF to LF. SIMPLICITY,
BINDING, FINDINGS, COVERAGE, EVIDENCE, FIX_EVIDENCE and verdict prefixes follow
the same parsing rule. A newline rewrite is still a hash mutation.

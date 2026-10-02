# C6 — protocol validation and resume

Part of [runtime-contracts.md](../runtime-contracts.md); load only when the index says so.

## First-plan bootstrap

Before a plan exists, the coordinator saves this authorization record in the
workspace and puts its reference in `state.authorization`:

```json
{"schema_version":1,"run_id":"<live Run>","worktree_id":"<actual target>","plan_base":"<full existing HEAD>","plan_path":"<absolute future plan path inside worktree>","request":"<actual authorized user task and constraints>"}
```

Initialize ordinary empty state with `mode:plan`, `step:bootstrap`, `plan:null`,
`phase:null`, `base:plan_base`. Initially reports, authors, phase commits and tracks
are empty. `resume`, `dispatch`, `bind-dispatch`, `accept-report` and one
format correction are the only bootstrap actions. Only a first-round plan-writer
may be assigned; the dispatch artifact is the authorization reference with
`kind:request`. C6 freezes its raw hash before launch. The writer receives the
real request, produces the real target plan with `request_sha256` in frontmatter,
and binds PLAN_WRITTEN to the plan's actual hash. Acceptance supplies `plan` and
the matching plan artifact, then transitions to `step:plan`. Existing plan-less
quickfix behavior is separate. Readers, revisers and implementers cannot consume
a request as a substitute for a plan; foreign or mutated plan hashes reject.

An accepted BLOCKED/NEEDS_AUTHORIZATION keeps `step:bootstrap`. Retain its report,
settlement and author observation in their original order; after resolving the
blocker, resume and create a fresh Task/Dispatch/ATTEMPT for plan-writer round 1.
Only verifiable failed first-writer history is allowed during bootstrap. A draft
supplied with a failed response or format correction may bind `state.plan` to the
authorized path, but does not unlock readers or revisers. Only accepted
PLAN_WRITTEN advances the step; a failed format correction also needs a fresh
writer attempt. Keep the malformed report protected and read-only.

If a failed first writer leaves an unparseable draft at the authorized plan path
while `state.plan` is still null, the existing-file guard also blocks a new writer.
After the attempt is settled, verify that no active or unresolved writer owns the
path and that no accepted artifact or protected report binds that draft. Preserve
the regular file without overwriting anything: move it to a fresh recovery path
inside the existing workspace, recording its original path and raw SHA-256.
Verify the preserved bytes and the absence of the original before resuming and
validating the new first-writer dispatch against the same authorization. Do not
clear history, alter authorization, or move a bound plan/protected report this
way. If ownership or bindings cannot be verified, recovery remains blocked.

## Child tracks and BASE

Before any track dispatch, create child worktrees separately from worker launch.
Git 2.36+ is required for literal `worktree list --porcelain -z` records.
Save an immutable `state.track_group` reference to:

```json
{"schema_version":1,"run_id":"<live Run>","parent_worktree":"<absolute parent>","parent_head":"<verified group-start commit>","plan":{"path":"<frozen shared plan>","sha256":"<raw hash>"},"tracks":[{"id":"T1","worktree":"<absolute child>","worktree_id":"<actual Orca id>","phase":"F1","base":"<same parent_head>"}]}
```

The sealed group is the per-track BASE source. C6 parses NUL-separated Git
worktree records, verifies parent and child membership, unique paths/IDs, actual
commit ancestry from plan_base and the phase's planned base to parent_head, and
that each child's HEAD descends from its recorded BASE. Target phase/worktree ID
and state.base must match its registration. The shared plan/hash never changes
in a child. This narrowly replaces the sequential phase.base equality check;
it does not permit a guessed BASE. Two active producers cannot conflict or run
with a consumer of an active producer. The parent and unrelated worktrees are
excluded from the slot count; unknown TARGET writers still block in fleet checks.

`state.track_commits` may contain `{track_id,sha,base,artifact}` only after the
accepted child source/index matches that real commit and the commit is an
ancestor of the actual parent HEAD (merged). A status string does not free a
slot. Retain completed and incomplete track records on resume; C6 verifies the
completed history and counts only the remaining active children. Archive a group
only after its merges/integration are verified; never remove unmerged work.

## Evidence-backed ledger closure

Every closing status (`fixed`, `resolved`, `closed`, `verified-by-controller`)
requires `closure:{path,sha256}` pointing to immutable evidence appropriate to
the finding kind. For `cannot_verify`, use a CHECK receipt:

```json
{"schema_version":1,"finding_id":"<exact FINDINGS id>","report":{"path":"<accepted source report>","sha256":"<raw hash>"},"artifact":{"kind":"package","path":"<checked artifact>","sha256":"<raw hash>"},"result":{"path":"<C4 result.json>","sha256":"<raw hash>"},"command":"<executed assertion command>","expect":"<literal expectation>"}
```

The report must be in accepted history and contain that finding. For
`cannot_verify`, artifact, command and expect must exactly match the originating
report's assigned artifact and finding. CHECK commands must assert the literal
expectation and return zero only when it holds; a print-only diagnostic cannot
prove an arbitrary expectation. If the expectation needs human judgment, keep
the finding open. When fixes of the same round have replaced the finding's
candidate, run the unchanged CHECK on the repaired candidate and add
`"review_report":{"path":"<accepted independent re-review>","sha256":"<hash>"}`:
`artifact` must then equal the artifact of that accepted positive review of the
same Run, phase and step, from a later round and later in `report_history`,
which no longer raises the finding. Command and expect stay the finding's
literal values. Either way the CHECK's source and its declared inputs must
still be the current or committed candidate. For an ordinary repaired blocking
finding, use this receipt instead of introducing another mandatory runtime CHECK:

```json
{"schema_version":1,"finding_id":"<exact id>","report":{"path":"<original accepted report>","sha256":"<hash>"},"artifact":{"kind":"plan|package","path":"<reviewed repaired artifact>","sha256":"<hash>"},"fix_report":{"path":"<accepted fix report>","sha256":"<hash>"},"review_report":{"path":"<accepted independent re-review>","sha256":"<hash>"}}
```

All three reports must be accepted and retain matching actual settlement/binding.
Their order in `report_history` must be original finding, actual fix response,
then independent re-review, using distinct Task/Dispatch attempts. For an older
state without `report_history`, the ordered `accepted` list suffices only if it
still contains all three unambiguous records; missing chronology is UNVERIFIABLE.
Never infer order from file timestamps or round numbers alone. The fix and review
must match the original Run, phase and step; the re-review round must follow the
finding's round. A same-round fix uses `binding.fix:true`; a later fix round or
plan-reviser response retains its existing role contract.

The fix report's existing FIX_EVIDENCE object adds
`"findings":[{"id":"<exact finding id>","report":{"path":"<original accepted report>","sha256":"<raw hash>"}}]`.
Include exactly one matching entry for each addressed finding, supplied by the
coordinator from accepted history. Tests/commands/outputs remain required for
code fixes; a text-only plan revision needs this binding and per-item section
notes, without a new runtime CHECK. An initial pre-finding implementation report,
a fix for another finding/report, or a review accepted before the fix cannot
close the item. The independent re-review must be APPROVED/REVIEW_OK and omit the
resolved finding. A plan fix and its review cover the same repaired plan hash. A
code fix and its review share the phase HEAD; the review may be a later round's
positive re-review of the cumulative candidate (a multi-round loop never re-reviews
each intermediate tree), and the closure `artifact` is that reviewed package. Its
coverage includes the fix's modified files, and its source must still be the current
candidate or a verified committed one. Recheck family independence.
No runtime test is added merely for a wording correction. A REVIEW_BLOCKING
report cannot become REVIEW_OK by changing the ledger. A later clean review
also cannot silently erase an unresolved finding from earlier accepted history.

C6 revalidates the result seal, request/check binding, exit 0, complete logs and
unchanged source evidence. Package/snapshot files and HEAD must match; a plan's
raw bytes must be among the checked source files. The current source must still
match; only a verified recorded commit may explain HEAD movement. Missing,
mutated, wrong-finding, stale or negative evidence rejects closure and preserves
the prior state/barrier. A closure of a committed earlier delivery remains valid
only when its complete source/index is proven by that recorded commit and actual
ancestry; later phases require their own review. Store a negative result with the open finding and send
it to the authorized fixer; it remains a mandatory blocker. `closed_ledger_ids`
is recomputed from proofs on every call, never trusted from input. Re-reading the
same valid proof is idempotent. REVIEW_OK may include cannot_verify but cannot
pass acceptance/commit while that finding lacks its positive bound CHECK.

## C6 — protocol validation and resume

`bin/protocol-state validate INPUT_JSON [RESUME_OUT]` (native Windows:
`bin/protocol-state.ps1`) prints `VALID`, `INVALID` or `UNVERIFIABLE`, then one
JSON result, exiting 0/1/2. `bin/protocol-state summary STATE_OR_PROPOSAL_JSON`
prints the compact facts of a saved state or proposal (barrier, active, rounds,
open ledger ids, accepted entries, commits, waivers) in about twenty lines; it is
read-only and is the only way the coordinator inspects such a file. It validates one coordinator proposal, executes only
bounded read-only Git queries, and optionally atomically writes the resulting
compact state inside the existing plan workspace. Rejection leaves any prior
resume untouched; input artifacts cannot be overwritten. It never dispatches,
acknowledges a Delivery, releases a worker, commits, upgrades legacy metadata or
selects the next model. The coordinator performs those actions through Orca/Git
only after a matching valid proposal. `VALID` means the proposal passed its
mechanical checks, not that a plan/phase is complete; inspect `state.barrier`.

Input has `schema_version:1`, `action`, `state`, plus action-specific references.
A file reference is `{path:<absolute literal path>,sha256:<raw byte hash>}`;
missing files/facts or unknown ownership/family are UNVERIFIABLE, contradictory
bound facts are INVALID. Paths through symlinks/reparse points are rejected.
Only coordinator-owned, saved real receipts are evidence in production; fixture
receipts are simulations. The validator does not authenticate a fabricated local
receipt or reconstruct an omitted author history. Keep the original reports and
receipts immutable; a new fix/correction report gets a new durable path.

A successful same-role, same-step/phase fix with `fix:true` replaces that role's
previous same-round entry in current `accepted`, while `report_history` retains
every immutable attempt. Existing earlier-round replacement is unchanged. This
lets a repaired candidate resume after its fresh gate and reviews; current
accepted artifacts still must be current, and stale current approvals reject.
On `resume`, a diagnosis or a verdict with unclosed findings is history, not an
approval: its saved artifact is verified but need not match the working tree,
because a fix is expected to replace that candidate. A verdict whose findings
are all closed is checked against the tree like any approval.
Bootstrap failures are retained, not superseded by this fix rule.

Required compact `state` fields:

- `schema_version:1`, `mode:plan|quickfix`, `plan` and `ledger` references (null
  only for authorized first-plan bootstrap or quickfix / no ledger), `orca_run`, full `plan_base`, current
  `phase` (null for planning/quickfix), full recorded `base`, `step`
  (`bootstrap|plan|phase|quickfix|final-review|delivery|completion`).
- Absolute `worktree`, its actual Orca `worktree_id`, existing `workspace`;
  `active` assignment or null; `rounds:{plan_review:0,fused_review:0,final_review:0,gate_fix:0}`;
  `format_corrections:{}`, `accepted:[]`, `processed:{messages:[],deliveries:[]}`,
  `open_ledger_ids:[]`, `write_ownership:[]`, `phase_commits:[]`,
  `commit_barrier:{}`, `final:{}`, `provenance:[]` (actual plan author observations).

New plan metadata uses `protocol_version: 2`, `orca_run`, `plan_base` and
`contracts: ["C1",...]`; every phase declares `risk`, `base` before launch,
`consumes: []`, `produces: []` as one-line JSON arrays matching body contract IDs.
Consumers reference earlier producers. The plan reviewer checks their meaning;
the coordinator only checks the structure and IDs. Legacy plans or resumes
without required proof remain UNVERIFIABLE. Do not retroactively certify a run
started before this contract. An explicit `plan` input can update the same path's
reference before assignment, after an authorized plan-author result, or at the
completion metadata checkpoint; it never edits the plan.

`artifact` adds `kind:request|plan|snapshot|package` to a file reference. A plan uses its
raw hash. Archive each plan revision's bytes in the workspace before acceptance;
its artifact `path` names that immutable copy and `source_path` names the live
plan. The current copy's SHA must equal state.plan.sha256 and source_path must
equal state.plan.path. This preserves accepted plan evidence when later metadata
or an authorized revision changes the live file. A snapshot is a valid C4 record
(optional `inputs:[]`); a package is a
complete C5 manifest. Current reader artifacts must still match the working tree.
C4 evidence and C5 packages may have different exclusion lists/IDs: cross-role
checks compare actual manifest files and HEAD, while each binding retains its
own exact artifact/snapshot ID. New source edits require new evidence/reviews.

Actions and their additional inputs:

| Action | Required facts and result |
| --- | --- |
| `resume` | Reconcile recorded actual commits and current artifact hashes; return the pending barrier without executing it. |
| `dispatch` | Fresh `fleet`, `artifact`, `proposed` assignment (`run_id,task_id,dispatch_id:null,role,phase,round,worktree_id,model`, review `coverage`, optional `gate_fix:true`). Freeze intent before launch; writers remain pending until bound. |
| `bind-dispatch` | Saved `observation` binds the pending fresh Task to the actual Dispatch/model/worktree; retries of an old Dispatch are not a fresh review. |
| `accept-report` | `event`, exact `message_id`, settled `observation`, `report`, `artifact`. Read subject/outcome/path from the actual message payload. Stale IDs and heartbeats do not complete work; duplicate message IDs are idempotent. An empty timed-out wait is not completion. |
| `format-correction` | Fresh `fleet`, defective `report`, its settled `observation`, unchanged `artifact`, `outcome`, `files_modified`, and new same-role/round `proposed`. One correction only. |
| `extend-cap` | `authorization`: an immutable record `{schema_version:1,run_id,phase,group,extra_rounds:1,findings,user_decision}` of the user's explicit decision at a reached cap. `findings` must be open ledger IDs; each record adds one round to that phase's cap. Never written without the user's words. |
| `waive-independence` | `authorization`: an immutable record `{schema_version:1,run_id,step,phase,files,reviewer_family,user_decision}` of the user's explicit decision, plus the current `artifact`. Accepted only for units every known family already authored, so no independent reviewer exists; it lets the named family review the named files in that step. Never written without the user's words. |
| `record-gate` | Current phase candidate `artifact` and `evidence`: the sealed C4 `result.json` references of a green verify-gate run. Checked like a gate report's `EVIDENCE`; it satisfies the phase's gate role without a gate worker and is cleared by `advance`. Final delivery still needs a gate report. |
| `prepare-commit` | Fresh `fleet`, accepted `artifact`; verify roles, coverage, executable evidence, unresolved ledger IDs and staged candidate. Record expected snapshot with no invented commit SHA. |
| `confirm-commit` / `advance` | Fresh `fleet`, accepted `artifact`, `commit:{sha,base,artifact}`. Read actual full Git commit/ancestry/tree, compare accepted index/source and current bytes; hook changes reject. Confirm the existing commit once after a crash; advance only after confirmation. |
| `finish-checkpoint` | Fresh `fleet`, accepted `artifact`: all phase commits must exist, then independent final review permits delivery, positive gate delivery permits completion metadata preparation. |
| `complete` | Fresh `fleet`, completion `artifact`, actual separate `commit`; validate all phase commits, final review, delivery, unchanged implementation and verified plan-only done metadata. |

Saved `event` is an accepted send receipt's `result.message`, or a check receipt's
`result.messages` and `deliveryId`. Payload may be a JSON string. Only the selected
message is processed; a whole Delivery becomes ackable after every contained
message is processed, including stale/heartbeat messages. The coordinator then
uses the actual `check --ack` command. There is no model timer polling.

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

`bind-dispatch` compares the actual model with the proposal exactly, except that
a Claude alias from roles.md `MODEL_ALIASES` matches a full id with its prefix.
Actual model-to-family mapping lives only in roles.md. C5 write provenance points
to these hashed observations; unknown/mixed authors need explicit independent
coverage, including cross-family agent/model launches.

`fleet` is an array of hashed `worker-list --json --limit 100` page references,
each with its input `cursor` (null for the first page). Collect all pages across
all local runs. The adapter checks `scope.source:all`, `page.total/hasMore/nextCursor`,
unique dispatch IDs and each worker's workspace, dispatch status, resource
ownership, terminal state and durable/liveness projection. Incomplete/unknown
observations block; prior receipt IDs cannot be reused for a new proposal. A
durably completed or failed retained terminal is not a writer even when its
workspace is null, provided ownership is not external/user-owned/pre-existing
and release is not pending/unknown. Other null-workspace records remain unknown.
Unknown/external ownership
or pending/unknown release blocks the affected worktree. An unbound writer intent
also blocks: bind/reconcile it before another proposal. The limit is two active
child tracks of this Run; the parent and unrelated worktrees do not consume slots.
TARGET ownership is still checked against the complete fresh fleet.

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
fallback. It does not decide writer safety; the existing C6 validator still
checks the original worker rows and rejects unknown/external ownership.

Only a complete collection publishes `fleet.json`:
`{schema_version:1,fleet:[{path,sha256,cursor},...],runtime_id,worker_count,page_count}`.
Copy its `fleet` array mechanically into the C6 proposal. Original page bytes
remain authoritative and hashed; this manifest is not an Orca receipt and does
not authorize a transition by itself. Collect fresh receipts for the next
required proposal; prior receipt IDs cannot be reused.

Stdout is one JSON line. Exit 0: `event:collected`, `fleet_file`, `output_dir`,
`page_count`, `worker_count`, `schema_version:1`. Exit 1: `event:error`, `reason`
and, when available, `receipt`/`output_dir`; partial receipts remain for diagnosis
but no success manifest is published. Never respond to error by opening a
terminal, shrinking pages, rewriting scope or accepting only the current Run.

Shared isolated fixtures: `python3 -B -m unittest discover -s tests
-p test_worker_fleet.py -v`; native Windows uses `python` and `ORCA_TEST_SHELL`
for each PowerShell. The finite fake CLI cannot contact real Orca/settings.

Caps remain plan review 4, fused review 4 per phase, final review 2, consecutive
gate-fix 2 and one format correction. Only the user can lift a reached cap, one
round at a time, through `extend-cap` with their verbatim decision; C6 rechecks it. Complementary independent reports use the
same final round; rerunning the same role/family substantively needs a new round.
Unresolved accepted ledger findings and CANNOT_VERIFY prevent commit. Prepared
YAML `done`, a skipped/failed commit, budget exhaustion or a success-shaped wrapper
message cannot establish completion. Resume barriers distinguish writer,
resolution, gate/review, phase commit, final review, delivery and completion
commit. A confirmed commit is recovered from Git facts, never rerun blindly.

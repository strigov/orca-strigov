# Runtime contracts

## C3 — one local command owner

`bin/run-check run SPEC_JSON` blocks until exit/interruption. Native Windows uses
`bin/run-check.ps1` with the same positional arguments; it needs PowerShell 5.1
or 7 on Windows 10+, not Python. Bash uses Python 3 stdlib. Resolve these paths
from the current checkout or a process-only `ORCA_DEV_HOME`.

Create the plan workspace with the existing `sdd-workspace` entry point first.
Write a UTF-8 JSON file (not interpolated shell code) with this shape:

```json
{
  "schema_version": 1,
  "run_id": "unit-unique-attempt",
  "owner": {"kind": "local", "id": "caller-unique-id"},
  "cwd": "/absolute/repo",
  "command": "exact shell command, including newlines and Unicode",
  "shell": "/absolute/path/to/bash",
  "run_dir": "/absolute/repo/.superpowers/sdd/plan/checks/unit-unique-attempt",
  "timeout_seconds": 120,
  "cancel_grace_seconds": 2,
  "no_progress_seconds": 30,
  "progress_file": null,
  "resource_key": null
}
```

Windows paths and shell must be absolute too; choose `powershell.exe` or
`pwsh.exe`. POSIX supports `bash -c` / `sh -c`. `run_id` is 1–100 ASCII letters,
digits, `_` or `-`, starting with a letter or digit. An Orca owner is exactly
`{kind:"orca", orca_run_id, task_id, dispatch_id, terminal_handle}` with values
from the live dispatch; never put a capability in this file. Standalone and
gate calls use a unique local owner. A new command attempt gets a new id.
Duplicate identical specs return the existing observation without a new child;
a mismatch or an incomplete initial binding fails closed. Owner metadata binds
the local run; it is not an authentication boundary against another process
running as the same OS user.

Artifacts in the exclusive `checks/<run_id>/` directory:

| Artifact | Meaning |
|---|---|
| `request.json` | Bound spec with exact command, cwd, shell, owner and policy |
| `stdout.log`, `stderr.log` | Full streams written as received, without an in-memory output accumulator |
| `status.json` | Atomically replaced observation, including supervisor PID/start identity, tree, timestamps, duration, diagnostic counters and log paths |
| `cancel.json` | Owner's durable stop request |
| `result.json` | Atomic final record; actual command `exit_code` or null, reason, `cleanup_verified`, `logs_complete` |

The command's own buffering still applies; cross-stream ordering is not exact.
Stdin is closed (`/dev/null` or `NUL`). PowerShell preserves the final native
exit status and a failed final PowerShell operation. No successful outer shell
exit substitutes for a missing/unknown result. `run` and `wait` return the
command code for a confirmed `exited` record, 124 for `interrupted`, 125 for
running/unknown/invalid operations. POSIX signal exits map to 128 + signal.
Inspect the JSON as well as the return code: a command can itself exit 124/125.

`wait RUN_DIR [WAIT_SECONDS]` waits for completion or a **new** diagnostic event
(default 60 seconds); zero reads the current observation. It is a read-only
observation, not a transfer of ownership. `cancel RUN_DIR OWNER_JSON` takes a
file containing exactly the bound owner object and writes a request, returning
0 only for receipt. The owner must then wait for completion and inspect cleanup.
Use this interface from the same owning worker. The coordinator receives that
worker's significant diagnosis/result rather than becoming a second observer.

States are `waiting-resource`, `running`, `exited`, `interrupted`, `unknown`.
`stalled` is only a diagnostic flag. A small (at most 4096-byte) optional UTF-8
`progress_file` carries a counter/stage; changed content resets the diagnostic
interval. Without it, meaningful progress is `unknown`: log output is only
`output_activity`, PID existence only liveness. A no-progress threshold produces
one diagnostic event until the next progress change; it never kills a process
or frees its resource. A missing progress file is not evidence of progress.

Deadline includes time waiting for the resource. `timeout_seconds: null` means
explicitly no deadline, as for legacy gate commands; new expensive checks need
a finite policy in their plan. `no_progress_seconds: null` disables that
diagnostic. Nonnegative finite seconds are accepted. Cancellation/deadline
requests stop, permits `cancel_grace_seconds`, then forcibly stops only the
owned tree and verifies cleanup (up to two further seconds). POSIX sends TERM,
then KILL to its private process group. Windows publishes `cancel.json` (also
available as `ORCA_CHECK_CANCEL_FILE` to a cooperative command), then terminates
the Job Object after grace. It does not guess a console interrupt API.

POSIX records the group before allowing the command to execute and pins the
leader PID until cleanup; a live group after supervisor death remains locked.
Linux recovery verifies boot/start-tick identity and group membership, including
live grandchildren, rather than testing only the supervisor PID. Exited zombies
cannot use the resource. If start identity is unavailable on a POSIX host,
recovery remains unknown/locked; it is not inferred from an old timestamp.
Normal foreground completion still checks the group. Commands deliberately
escaping the POSIX group are outside this local process-group contract.

Windows creates the command inside a named Job Object using the OS job-list
creation attribute, before it runs, with kill-on-last-handle-close and no
breakaway. Helpers are hidden. Start timestamps distinguish reused PIDs. On
owner loss, observers never invent the lost command's exit code or complete
logs; the job must be proven empty/destroyed before a stale lock is reclaimed.
Unverifiable ownership/tree state preserves the lock. No cleanup traverses an
artifact symlink or junction, and the runner never recursively deletes run data.

One optional `resource_key` serializes the declared heavy local resource across
the repository's two worktrees. Its lock key hashes the canonical Git common
directory plus the resource name, in local user temp storage. It is not a
distributed lock, writer lock, queue, or daemon. No key means no resource
serialization; the existing one-writer-per-worktree rule still applies. Locks
are exclusive, bound to run/owner, and never expire by age. Recovery requires
positive owner-exit and whole-tree cleanup evidence; missing or malformed
evidence preserves the lock. Do not manually remove an unknown lock to retry.

Both verify-gate entry points create unique HEAD/BASE runs in the existing plan
workspace, keeping the legacy invocation, verdict lines and exit meanings.
They classify only confirmed exits, reading at most 64 KiB / 200 trailing lines
per stream; displayed failure tails remain bounded. Reports include log paths.
Unknown BASE trees retain their worktree for diagnosis. C4 below adds explicit
snapshot/evidence policy; C3-only requests retain their original behavior.

The owner normally blocks in one shell call. If its harness requires a command
terminal, use the same runner there and the current, verified Orca
`terminal wait --terminal <handle> --for exit --timeout-ms ...` interface for
that terminal. This is not an arbitrary PID API. Read `orca skills get
orchestration` from the live executable for worker lifecycle; settlement uses
`orchestration check --wait`, never a new scheduler, monitoring agent or model
timer. Keep heartbeat/ask/check/worker_done obligations from the live preamble.
After a diagnostic event, use one bounded diagnosis and the recorded policy;
silence alone grants neither cancellation nor a replacement writer.

Behavior checks use `python -B -m unittest discover -s tests -p test_runner.py`
on Windows (PS5.1 by default). Run the same command separately with a
process-only `ORCA_TEST_SHELL` pointing to `pwsh.exe` for required PS7 coverage;
each shell's module has its own three-minute bound. POSIX uses `python3` and
the actual Bash entry point. Test helpers use Python only as a driver and put
all synthetic children under a parent watchdog; they never run installation
fixtures or change user configuration.

## C4 — exact inputs and verification evidence

Both gates preserve `PLAN BASE [ROOT]` and accept `--phase ID` and
`--checkpoint directed|integration|final`. No phase selects top-level `verify`;
an explicit phase selects only its own list, including an empty list. Directed
selects directed checks; integration includes directed and integration; final
includes all three. With no checkpoint, all checks in the selected list run.
Legacy block/flow lists, quoted strings, comments and `|`/`>` scalars still work.
Unsupported YAML structures fail parsing; they never become shell commands.

A new list item is a single-line JSON object, also valid YAML:

```json
{"id":"unit","command":"python -B -m unittest","checkpoint":"directed","timeout_seconds":120,"cancel_grace_seconds":2,"no_progress_seconds":30,"resource_key":null,"progress_file":null,"inputs":[],"environment":["LANG",{"tool":"python","version_args":["--version"]}],"hermetic":false,"independent_replay":false}
```

`command` is required. Defaults: id `legacy-N`, checkpoint `directed`, timeout
and no-progress null, grace 2, resource/progress null, inputs/environment empty,
hermetic/replay false. IDs must be unique in the selected list. Commands are
written for the actual shell; there is no translation between Bash/PowerShell.
`inputs` names additional files or recursive directories (absolute, or relative
to cwd), including ignored inputs. `environment` contains variable names and
tool objects with exactly `tool` and `version_args`; tools resolve to an actual
executable, with binary identity and successful bounded version output. Shell
identity is automatic. Variable values are hashed, never published. Unknown
tools, inputs or versions prohibit reusable evidence.

`hermetic:true` is an explicit assertion that all inputs/tools/environment are
declared, there is no concurrent external writer, and the command has no
untracked network/time/database dependency or unobservable temporary mutation.
An absent assertion means false. Do not assert it for an unknown environment.
This is an observability contract, not a sandbox or authentication boundary.
The local owner and single-writer rule still apply. Required independent replay
always executes under the selected verifier's new owner, with a recorded reason;
it cannot be satisfied by the implementer's report or a reused run. A named new
hypothesis likewise forces a physical run. Risk decisions are not inferred from
missing metadata and remain the plan/reviewer's responsibility.

For a C4 runner request add `verification` with normalized `check`, `provenance`
and optional nonempty `repeat_reason`. The check is the object above with all
defaults filled and C3 policy/command identical to the request. Provenance records
`kind` (`HEAD` or `BASE`), full `base_sha`, `preparation` and
`linked_dependencies`. The gates produce this binding themselves. BASE uses the
actual detached worktree, its checked files and shell/environment; shared
dependencies force a new run. Different physical BASE worktrees have different
identity, so the gate conservatively re-executes there. Reuse is available only
when the entire recorded BASE provenance and snapshot really match, never by
matching the command string to a HEAD result.

The runner captures stable before/after snapshots, actual tracked working bytes,
index entries and index digest, file types/modes, deletions and all nonignored
untracked paths, using NUL-safe Git enumeration. Snapshot manifests explicitly
list the known plan workspace exclusion; tracked source is included even there.
Declared inputs are never excluded. Unresolved links/submodules, unreadable files,
unmerged or unsupported case-colliding paths and Git errors remain unknown.
Content and file-set hashes are accompanied by change metadata and incarnation
witnesses (POSIX inode/ctime, Windows file identity/ChangeTime). A detectable
write and restoration invalidates evidence even when final bytes and mtime match.
Arbitrary hostile writes restoring every observable fact are outside this contract.

`result.json` contains `evidence` with schema, exact request digest, check and
provenance key, source before/after, environment/tools fingerprints, log paths,
sizes/hashes, normalized failure signature, validity, invalidation reasons, `reusable`, `repeat_reason` and
`origin_run_id`. The enclosing C3 record supplies owner, command, timestamps,
duration and actual exit. `result.sha256` seals its exact durable bytes. Mutation
or incomplete evidence yields runner 125, retaining the actual command exit in
JSON. Gate validates request binding, seal and full logs before classification.

Reuse searches only `checks/*/result.json` in this plan workspace. Matching
eligible evidence avoids a new command process. A new atomic result binds the
new owner to the physical origin, its result path/hash and original full logs;
the original request/result/logs must remain intact. No reuse chain, global
cache, daemon or dependency inference is introduced. Nonhermetic valid execution
can pass, but cannot be reused. Broken evidence is rerun, never accepted as PASS.
Timeout, mutation and unknown completion go to judgment. Existing missing-tool,
changed-path, failure-signature, shared-dependency and zero-pass safeguards apply
to HEAD/BASE classification. Gate's first two lines and codes 0/1/2/3/4 are stable;
evidence/log paths and repeat/origin reasons follow the summary.

## C5 — complete frozen review package

`review-package BASE HEAD [OUTFILE]` and `BASE WORKTREE OUTFILE` retain their
positional interface, full `.diff`, `wrote`/`EMPTY` stdout and exit meanings.
`OUTFILE.manifest.json` adds schema, package id, full BASE/head/mode, snapshot,
complete flag, changed/untracked file statuses, bytes/hash, exclusions, limitations,
parts and coverage. Untracked files are staged only in a temporary index copy;
the real index bytes are checked before/after, including an error path. All Git
exits are checked. Binary patches are retained. Known SDD storage and the exact
output family are excluded only for untracked service data; actual tracked source
and source outside SDD remain included.

A small package uses the original diff as its only part. Larger packages have
`OUTFILE.parts/NNNN.diff`, at most 65536 bytes each; `[start,end)` ranges cover the
entire package exactly once. A long line can cross parts. Oversize/binary input
requires named source inspection and stays uncovered until that check is recorded.
No byte tail, ignored declared input or new file can be discarded for a size cap.

The optional `OUTFILE.provenance.json` carries saved write receipts and the plan's
producer/consumer contracts. Its shape is `{schema_version:1, writes:[], contracts:[], inputs:[]}`
(`inputs` is optional). Each write has `family`, `files`, `receipt_path`,
`receipt_sha256`, `run_id`, `task_id`, `dispatch_id`; saved receipt bytes and all
three IDs must match. Each contract has `id`, `producer` and `consumer` path lists.
The manifest accumulates every recorded family per file, with status
`requires-family-validation`: receipt identity alone does not prove the claimed
family or completeness of the author list. Review/acceptance checks that against
actual launches and role mappings. Absent authorship remains unknown. Preserve all
actual author families per file/unit across fallback and fix waves, using write
Dispatch/launch receipts and file/commit ranges, never coordinator commit trailers.
Unknown authorship does not establish independence. Declared ignored/external
review inputs enter the snapshot and `declared_inputs` manifest with raw hashes
and required source inspection; they are not silently lost because Git ignores
them. Range packages also record both immutable reviewed Git tree identities;
the working snapshot guards the local frozen review context.

Freeze the package for review. Before dispatch and acceptance check the manifest
identity, all part hashes/ranges and current snapshot using the shared helper's
`validate-package MANIFEST` operation (`python3 -B bin/lib/verification.py` or
native `bin/lib/verification.ps1`). Zero verifies artifact integrity, not review
approval. A reviewer reads the manifest and every assigned part in bounded ranges,
then reports package id/hash, snapshot and explicit coverage of parts/files and
both producer and consumer of every contract, including compatibility. Missing,
changed, stale or incompletely covered artifacts require `CANNOT_VERIFY` and a
fresh complete package; ad hoc diffs do not substitute for missing untracked data.

Usually one final reviewer suffices. Mixed authorship can use complementary
reports in the same final round: each unit needs a verdict from a family outside
all its authors. Each reviewer sees whole-branch context. An indivisible unit
without an eligible independent route stays blocked for explicit assignment.
No new role or review loop; the combined final round cap remains 2. Primary/final
review executes only its agreed checkpoint, required risk replay or named new
hypothesis, not an unchanged suite merely because the role/step changed. Warnings
matter when they reveal a material problem or violated requirement, not simply
because stdout is nonempty.

## Report binding

Every role report contains exactly one machine-readable line after its existing
verdict/summary prefix (primary keeps SPEC/QUALITY on lines 2/3; gate and synthesis
keep their line 2; implementers keep the one-line test summary):

```text
BINDING: {"schema_version":1,"run_id":"<Orca Run>","task_id":"<Task>","dispatch_id":"<current Dispatch>","role":"<role>","phase":"<phase or null>","round":1,"artifact_id":"<plan SHA256, snapshot id or package id>","snapshot_id":"<C4/C5 snapshot id or null for a plan>"}
```

Use the live preamble's actual identities and the coordinator's frozen assignment,
never a previous Dispatch. Writers bind their completed artifact; readers bind
the assigned artifact. Hash the actual report bytes after writing. `subject`
exactly equals line 1 and `outcome` must match the role verdict: `BLOCKED` and
writer `NEEDS_CONTEXT`/`NEEDS_AUTHORIZATION` fail; a produced review/gate/diagnosis
artifact succeeds even when its substantive verdict requires more work.
`BLOCKED` needs `## Reason`. Existing human-readable details remain in the report.

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

A missing required field permits exactly one format-correction Task/Dispatch,
same role, artifact, snapshot and round, normally in the retained terminal.
Prior findings remain unresolved; a repeated defect is a protocol blocker.
This is neither a substantive review round nor a second worker_done for the
settled Dispatch. Conflicting identities or changed artifacts are not format-only
defects. No verdict is inferred from prose.

## C6 — protocol validation and resume

`bin/protocol-state validate INPUT_JSON [RESUME_OUT]` (native Windows:
`bin/protocol-state.ps1`) prints `VALID`, `INVALID` or `UNVERIFIABLE`, then one
JSON result, exiting 0/1/2. It validates one coordinator proposal, executes only
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

Required compact `state` fields:

- `schema_version:1`, `mode:plan|quickfix`, `plan` and `ledger` references (null
  only for plan-less quickfix / no ledger), `orca_run`, full `plan_base`, current
  `phase` (null for planning/quickfix), full recorded `base`, `step`
  (`plan|phase|quickfix|final-review|delivery|completion`).
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

`artifact` adds `kind:plan|snapshot|package` to a file reference. A plan uses its
raw hash; a snapshot is a valid C4 record (optional `inputs:[]`); a package is a
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
also blocks: bind/reconcile it before another proposal. There may be at most two
worktrees; independent work in the other identified worktree is not serialized.

Caps remain plan review 4, fused review 4 per phase, final review 2, consecutive
gate-fix 2 and one format correction. Complementary independent reports use the
same final round; rerunning the same role/family substantively needs a new round.
Unresolved accepted ledger findings and CANNOT_VERIFY prevent commit. Prepared
YAML `done`, a skipped/failed commit, budget exhaustion or a success-shaped wrapper
message cannot establish completion. Resume barriers distinguish writer,
resolution, gate/review, phase commit, final review, delivery and completion
commit. A confirmed commit is recovered from Git facts, never rerun blindly.

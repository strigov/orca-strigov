# Runtime contracts

## C3 — one local command owner

`bin/run-check run SPEC_JSON` blocks until exit/interruption. Native Windows uses
`bin/run-check.ps1` with the same positional arguments; it needs PowerShell 5.1
or 7 on Windows 10 1709+ with POSIX rename support (NTFS), not Python. See
`docs/install-windows.md` for the native publication requirements. Bash uses
Python 3 stdlib. Resolve these paths
from the actual loaded plugin's `bin/`, not a stale standalone skill or global
`ORCA_DEV_HOME`. See coordinator-core.md for path resolution.

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
that terminal. This is not an arbitrary PID API. Read the bundled
`../orchestration/SKILL.md` and references for worker lifecycle; settlement uses
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
The supplied result object must equal the object decoded from those same sealed
bytes. A faithful copy is permitted, but changing its exit or any other field
cannot borrow the original run directory's seal to establish a positive CHECK.
PowerShell decodes both compared objects through its JSON parser so an in-memory
ISO timestamp and PS7's parsed DateTime receive identical canonical formatting.
This representation step happens after the original-byte seal check and retains
comparison of the full result, including the actual exit and evidence bindings.

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

## POSIX capability and identity contract

Linux requires Python 3.9+; Darwin requires Python 3.13+. `run-check capabilities`
performs version/symbol/identity checks, also used by install.sh before setup
changes. Missing waitid/WNOWAIT, fork/group operations or trustworthy local
identity is a capability error (125), before useful command spawn. The child
handshake also requires durable trustworthy leader identity before exec. Native
Windows keeps its existing PowerShell Job Object backend and has no Python
runtime dependency.

Linux records boot-scoped start ticks. Darwin records libproc microsecond start
time, kernel boot-session UUID and host UUID. Host/boot change or unreadable
identity is unknown; PID reuse is a different process, not permission to signal
its group. The supervisor pins its own child's PID with WNOWAIT until group
cleanup; recovery only observes, never sends a signal to a prior group. Darwin's
verified root-owned `/var`, `/tmp`, `/etc` aliases may expand to `/private`; every
other link remains subject to artifact rejection. Native macOS acceptance is
NOT_RUN in the Windows/WSL maintenance environment; see docs/runtime-platforms.md.

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
`<workspace>/<role>-<phase>-r<round>-<ATTEMPT>.md`; a round or terminal alone is
not unique. `PREVIOUS_REPORT_FILE` is read-only. Each report contains one current
BINDING and all applicable FIX_EVIDENCE, including a retry inside the same round
(`proposed.fix:true` for a fix whose round remains 1). C6 retains `report_history`
even after a later round supersedes an accepted verdict, verifies prior hashes
on resume and refuses reuse of a previous attempt's report path. A defective
format report is also retained as immutable input to its correction.

All report hashes cover original bytes, including BOM, line endings and EOF.
Only after checking that hash do both parsers normalize CRLF to LF. SIMPLICITY,
BINDING, FINDINGS, COVERAGE, EVIDENCE, FIX_EVIDENCE and verdict prefixes follow
the same parsing rule. A newline rewrite is still a hash mutation.

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
the finding open. For an ordinary repaired blocking finding, use this receipt
instead of introducing another mandatory runtime CHECK:

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
resolved finding. Fix and review cover the same repaired plan hash or
source/index/HEAD, and review coverage includes the fix's modified files. Recheck
family independence and current source (or its verified historical commit).
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

A successful same-role, same-step/phase fix with `fix:true` replaces that role's
previous same-round entry in current `accepted`, while `report_history` retains
every immutable attempt. Existing earlier-round replacement is unchanged. This
lets a repaired candidate resume after its fresh gate and reviews; current
accepted artifacts still must be current, and stale current approvals reject.
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
gate-fix 2 and one format correction. Complementary independent reports use the
same final round; rerunning the same role/family substantively needs a new round.
Unresolved accepted ledger findings and CANNOT_VERIFY prevent commit. Prepared
YAML `done`, a skipped/failed commit, budget exhaustion or a success-shaped wrapper
message cannot establish completion. Resume barriers distinguish writer,
resolution, gate/review, phase commit, final review, delivery and completion
commit. A confirmed commit is recovered from Git facts, never rerun blindly.

## C7 — worker event waiter

`bin/wait-worker-event REQUEST_JSON` (native Windows: `wait-worker-event.ps1`)
keeps empty coordinator inbox waits inside one process. POSIX uses Python stdlib;
Windows uses PowerShell 5.1/7 without Python. It does not supervise test processes
or replace C3, C6, worker heartbeats, launch readiness or lifecycle acceptance.

Write this UTF-8 request in the existing plan workspace:

```json
{
  "schema_version": 1,
  "orca_argv": ["/absolute/path/to/the-selected-orca"],
  "run_id": "<actual Run>",
  "dispatch_ids": ["<awaited Dispatch>"],
  "output_dir": "/absolute/plan-workspace/wait-<fresh-attempt>",
  "terminal": null,
  "ack_delivery_id": null
}
```

Use the same executable that provided the live orchestration reference, with no
fallback or guessed executable. `orca_argv` is an argv prefix, never shell code.
IDs come from real receipts. Omit/null `terminal` in the coordinator's own Orca
terminal; outside it, name that coordinator's actual handle. `dispatch_ids` is
the nonempty unique set currently awaited, excluding old retained terminals.
The absolute output leaf must be new, with an existing parent inside the plan
workspace. Reuse refuses rather than overwriting an earlier receipt. Only one
inbox consumer may run for this coordinator Run.

The helper issues `check --run ... --wait --types "worker_done,escalation,question"
--timeout-ms 540000 --json`. It saves each invocation's exact stdout in
`NNNNNN-check.json` and stderr/keepalive output in `NNNNNN-check.stderr.log`;
fleet calls use `NNNNNN-worker-list.*`. `request.json` retains original request
bytes. It does not merge streams, parse only the last line of pretty JSON, or
rewrite receipts. An invalid receipt or nonzero CLI exit returns immediately,
with the evidence path; no blind retry after an ambiguous mutation.

Empty timed-out responses renew silently. After three, enumerate
`worker-list --run ... --include-remote --limit 100 --json`, following every
cursor and verifying the scope, count and unique Dispatch IDs. For awaited
Dispatches, return attention on `exited`, `attention.requiresAction:true` or a
non-`none` nextAction. Live and stale-only/no-action observations keep waiting;
missing Dispatches, incomplete projections or paging errors need diagnosis.
This is a local diagnostic result, never a fabricated Orca lifecycle message.
Unverifiable evidence never proves process death or authorizes another writer.
Fleet receipts here are Run-scoped diagnostics, not C6's complete all-Run fleet.

Stdout contains one JSON line: `schema_version`, `event`, `run_id`, `receipt`,
`output_dir`, plus `delivery_id`, attention `dispatch_ids`, or error `reason`.
Exit 0 = `delivery`, 2 = `attention`, 1 = `error` (early request errors may omit
paths/Run). Read all fleet pages from the output directory for attention. A
Delivery returns in full even when it contains older heartbeat/status messages;
the wake filter cannot discard FIFO mail. No automatic acknowledgment of new
messages, replies, `nextAction` execution, stop, release or retry is performed.

Only after processing an entire Delivery through the existing C6/ownership
rules may the coordinator set `ack_delivery_id` in a new request. It is sent on
the first `check` only, so acknowledgment and the next wait stay together without
discarding a returned batch. On transport error, retain the raw response and
follow live Orca mutation recovery; never assume the acknowledgment failed.

Synthetic shared behavior fixtures: `python3 -B -m unittest discover -s tests
-p test_worker_wait.py -v`; Windows uses `python` and `ORCA_TEST_SHELL` selecting
each native PowerShell. The fixtures launch only a finite local fake CLI and
write in owned temporary directories; they never access real Orca or settings.

## C8 — coordinator session continuity and stop guard

`bin/coordinator-session ACTION REQUEST_JSON`; native Windows uses
`bin/coordinator-session.ps1` with the same arguments. `hook` instead reads one
Codex hook payload from stdin. Helpers never call Orca, dispatch, consume the
inbox, commit, cancel workers or change user configuration. Operational use and
the role boundary are in [coordinator-session.md](coordinator-session.md).

All action requests contain `worktree` (absolute actual Git root) and
`session_id` (actual Codex ID; defaults to `CODEX_THREAD_ID`, and must match it
when present). IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`. Workers with
process-local `ORCA_STRIGOV_WORKER=1` cannot bind. Path validation rejects
symlinks/reparse points; only standard POSIX system aliases are normalized.

| Action | Additional input | Result |
|---|---|---|
| `bind` | `workspace`: existing directory below `.superpowers/sdd/`, not `.sessions`; `objective`: nonempty authorized scope | Idempotent binding of one session/objective/workspace; a different existing binding is rejected |
| `checkpoint` | `proposal:{path,sha256}`: immutable original C6 input inside that workspace | Revalidate through C6, bind the same Run, save pending barrier and admitted plan/ledger paths |
| `hold` | `kind`: `user_pause`, `needs_authority`, `product_decision`, `blocked` or `status_only`; nonempty `reason`; `evidence:{path,sha256}` | Pause as **incomplete**, with exact hashed actual request/blocker evidence |
| `resume` | None | Clear an explicit hold after the user resolves/resumes it; reset no-progress counter |
| `status` | None | Read-only current binding |

Action success emits the JSON binding and exit 0. Invalid requests emit
`{"error":"..."}` and exit 2, without replacing existing binding bytes. State
is atomically saved in `.superpowers/sdd/.sessions/<session-id>.json` with
`schema_version:1`, `role:"coordinator"`, identities, objective, `status`
(`active`/`held`), `orca_run`, `proposal`, meaningful `progress`, `stop_attempts`
and `hold`. Checkpoints may add validated `bookkeeping` paths. A generated
continuation's SHA-256 is saved as `continuation_sha256`, so its automatic
UserPromptSubmit does not reset the no-progress counter.

`hooks/hooks.json` uses the actual plugin root and native `commandWindows`:

- SessionStart (startup/resume/clear/compact) and UserPromptSubmit restore a
  bound role. Unbound Orca sessions get routing guidance, not a guessed binding.
- PreToolUse denies direct apply_patch/Edit/Write/NotebookEdit outside the
  bound workspace and validated plan/ledger. A stale plan's metadata can still
  be repaired, but cannot satisfy Stop until a new valid checkpoint. Other
  tools receive guidance: this is **not an arbitrary-shell/MCP sandbox**.
- Stop revalidates C6 and current Git/artifact facts. Completion requires a
  quickfix `confirm-commit` or plan `complete` (separate completion commit),
  barrier `complete`, no pending assignment, no unresolved writes or findings.
  Saved fleet receipts are checkpoint evidence, not a fresh live Orca query;
  collect fresh C6 fleet evidence immediately before a completion checkpoint.
- A historical `active` assignment already in accepted report history is
  settled; an unaccepted active assignment requires reconciliation/wait, never
  another launch. Heartbeat, stale and duplicate receipts cannot prove completion.
- Premature Stop returns `decision:block` and the pending action. After three
  attempts without meaningful checkpoint progress, the fourth requests an
  explicit **incomplete** no-progress escalation. It does not loop forever or
  report success. A new real user prompt resets the counter, not a persistent
  blocker/pause. `status_only` clears on that next prompt.
- Interrupt records a user pause. A held Stop checks any supplied evidence hash
  and permits only an incomplete response. No worker is interrupted by C8.

Worker/native-subagent and unrelated unbound sessions are exempt. Trusted,
enabled plugin hooks and an actual binding are prerequisites; this does not
prevent user interruption, process exit, exhausted provider budgets, unbound
role mistakes or dishonest mutation of coordinator-owned state. Hook validation
errors block Stop/direct edits; other events surface a diagnostic. No fictitious
runtime enforcement or security-boundary guarantee is made.

Shared positive/negative fixtures: `python3 -B -m unittest discover -s tests
-p test_coordinator_session.py -v`. They use real local C6/Git validation and
synthetic Orca/hook input in owned temporary worktrees, not live model workers.

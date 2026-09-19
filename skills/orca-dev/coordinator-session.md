# Coordinator session continuity (C8)

Read on entry and after resume/compaction. This is part of orca-dev, not a fourth
skill. It applies to the main Codex coordinator only; workers follow their live
assignment. Hooks must be installed, enabled and explicitly trusted. Do not
disable trust or pretend an uninstalled hook is enforcing this contract.

## Bind before work

Resolve `bin/` from the actual loaded plugin as coordinator-core describes. Use
`sdd-workspace --name <slug>` to create the usual self-ignored plan workspace.
Use `CODEX_THREAD_ID` (PowerShell: `$env:CODEX_THREAD_ID`), or the exact session ID
reported by SessionStart. Do not use an Orca terminal handle as a Codex session ID.

Save a request in that workspace and execute `coordinator-session bind REQUEST`:

```json
{"session_id":"<actual-session-id>","worktree":"<absolute-root>","workspace":"<absolute-plan-workspace>","objective":"<the-authorized-user-objective>"}
```

Native Windows uses `& <plugin>\bin\coordinator-session.ps1 bind REQUEST`.
The helper saves `.superpowers/sdd/.sessions/<session-id>.json`. Binding is
idempotent, needs no Run yet and cannot replace a different objective. For a new
objective use a new session until an explicit audited rebind is supported.
Never bind a worker: new worker sessions do not inherit a parent binding. Add
process-local `ORCA_STRIGOV_WORKER=1` to custom worker launches; do not persist
it in user environment or the coordinator process.

## Checkpoint every transition

After a C6 validation, preserve the proposal's JSON bytes at a new immutable
path in the workspace. Pass its raw SHA-256 to `coordinator-session checkpoint`:

```json
{"session_id":"<actual-session-id>","worktree":"<absolute-root>","proposal":{"path":"<absolute-C6-proposal.json>","sha256":"<raw-sha256>"}}
```

C8 invokes the real C6 validator again, binds the same workspace/Run and records
its pending barrier. This does not dispatch or repeat a lifecycle mutation.
The proposal is not a resume output: it has `schema_version`, `action`, `state`
and the action's real evidence. Never reuse a mutable request path.

For finishing a plan, the checkpoint must be C6 `complete` with its separate
completion commit; for quickfix it must be `confirm-commit`. A `resume` proposal
or a manually written `barrier: complete` cannot authorize stopping. Stop checks
the original proposal and current Git/artifact facts again. Source edits after
the checkpoint restore the barrier. Settled historical `active` assignments
are distinguished from an assignment still awaiting an accepted report.

## A legitimate pause is explicit and incomplete

`coordinator-session hold REQUEST` requires `session_id`, `worktree`, a `kind`
(`user_pause`, `needs_authority`, `product_decision`, `blocked`, `status_only`),
a concrete `reason`, and `evidence:{path,sha256}` naming the immutable actual
user-request/blocker record. A next phase, empty inbox, live worker or ordinary
technical fix is not a human blocker. Holds never mark the objective complete.
Answering a status-only question permits one final status answer; it preserves
the objective, and the next user prompt clears that temporary hold.

After the user resolves a blocker or explicitly resumes, run
`coordinator-session resume REQUEST` with the bound session_id/worktree, restore
C6 and continue. User interruption persists a pause and is never overridden.
The guard does not signal, stop or release workers when pausing.

## Hook behavior and limits

SessionStart/UserPromptSubmit restore the role. PreToolUse rejects direct
source/test edits through apply_patch/Edit/Write and reminds other tools of the
coordinator boundary; only bound plan/ledger and workspace bookkeeping are
allowed. These hooks are a guardrail, not an OS sandbox: arbitrary shell/MCP
paths and the semantic contents of allowed metadata still require instruction
compliance. No security-boundary claim is made.

Stop blocks premature final answers and supplies the pending C6 action. It does
not skip barriers or dispatch a duplicate. Three repeated stops without a
meaningful checkpoint are followed by an explicit no-progress escalation, not
success or an unlimited token loop. The guard distinguishes its own automatic
continuation prompt from fresh user input. Worker sessions, native subagents
and unrelated unbound sessions are not trapped. General orchestration outside
orca-dev follows the shared role contract; the C6-backed guard applies to
development objectives, not arbitrary non-Git tasks.

The state is coordinator-owned operational evidence, not a signed authority
store. As with C6, do not fabricate receipts, edit the binding by hand or create
a false hold to bypass the protocol. `status REQUEST` is read-only.

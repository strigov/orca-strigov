# Coordinator session continuity (C8)

Read on entry and after resume/compaction. It applies to the main Codex or Claude
Code coordinator; workers follow their live assignment. Hooks must be installed,
enabled and trusted; never pretend an uninstalled hook enforces this contract.

## Bind before work

Resolve `bin/` from the actual loaded plugin as orca-recipes.md §0 describes. Use
`sdd-workspace --name <slug>` to create the usual self-ignored plan workspace.
Codex uses `CODEX_THREAD_ID` (PowerShell: `$env:CODEX_THREAD_ID`), or the exact
session ID reported by SessionStart. Claude Code uses only the exact ID reported
by its SessionStart/UserPromptSubmit hook, never an inherited `CODEX_THREAD_ID`.
Do not use an Orca terminal handle as a provider session ID. Every Claude request
below must include `"host":"claude"`; Codex may omit `host` or use `"codex"`.

Save a request in that workspace and execute `coordinator-session bind REQUEST`:

```json
{"host":"<codex-or-claude>","session_id":"<actual-session-id>","worktree":"<absolute-root>","workspace":"<absolute-plan-workspace>","objective":"<the-authorized-user-objective>"}
```

Native Windows uses `& <plugin>\bin\coordinator-session.ps1 bind REQUEST`.
The helper saves `.superpowers/sdd/.sessions/<session-id>.json` for Codex or
`.superpowers/sdd/.sessions/claude/<session-id>.json` for Claude. Binding is
idempotent, needs no Run yet and cannot replace a different objective. For a new
objective use a new session until an explicit audited rebind is supported.
Never bind a worker: new worker sessions do not inherit a parent binding. Add
process-local `ORCA_STRIGOV_WORKER=1` to custom worker launches; do not persist
it in user environment or the coordinator process.

## Checkpoint every transition

After a C6 validation, preserve the proposal's JSON bytes at a new immutable
path in the workspace. Pass its raw SHA-256 to `coordinator-session checkpoint`:

```json
{"host":"<codex-or-claude>","session_id":"<actual-session-id>","worktree":"<absolute-root>","proposal":{"path":"<absolute-C6-proposal.json>","sha256":"<raw-sha256>"}}
```

C8 invokes the real C6 validator again, binds the same workspace/Run and records
its pending barrier; it never dispatches or repeats a lifecycle mutation. The
proposal is not a resume output: it has `schema_version`, `action`, `state` (schema
2) and the action's real evidence, including fresh `plan`/`ledger` references when
those files changed. Never reuse a mutable request path.

Finishing a plan needs a checkpoint of C6 `complete` with its separate completion
commit; a quickfix needs `confirm-commit`. A `resume` proposal or a hand-written
`barrier: complete` cannot authorize stopping. Stop re-validates the proposal
against current Git and artifact facts, so source edits after the checkpoint
restore the barrier. A non-null `active` is an assignment still awaiting an
accepted report (C6 clears it on acceptance). The plan and ledger paths of the
checkpoint are the only coordinator edits PreToolUse allows outside the workspace.

## A legitimate pause is explicit and incomplete

`coordinator-session hold REQUEST` requires `session_id`, `worktree`, a `kind`
(`user_pause`, `needs_authority`, `product_decision`, `blocked`, `status_only`),
a concrete `reason`, and `evidence:{path,sha256}` naming the immutable actual
user-request/blocker record. A next phase, empty inbox, live worker or ordinary
technical fix is not a human blocker, and no hold marks the objective complete.
A status-only hold permits one status answer and clears at the next user prompt;
it never replaces an existing persistent pause or blocker.

After the user resolves a blocker or explicitly resumes, run
`coordinator-session resume REQUEST` with the bound session_id/worktree, restore
C6 and continue. User interruption persists a pause and is never overridden.
The guard does not signal, stop or release workers when pausing.

Codex persists this pause through its `Interrupt` event. Claude Code has no
equivalent event and does not run Stop on user interruption. Its binding records
an open turn. If the next real user prompt arrives without an allowed Stop, C8
holds it as `unreconciled_turn`, not a fabricated user-pause receipt. Read the
latest user request: explicit continuation authorizes `resume`; a status question
gets an incomplete status answer, not new dispatches. Preserve this hold across
compaction and incidental prompts until intent is resolved. API errors/process
exit can cause the same missing-Stop condition; do not infer their cause.

## Hook behavior and limits

SessionStart/UserPromptSubmit restore the role. PreToolUse rejects direct
source/test edits through apply_patch/Edit/Write. These hooks are a guardrail, not
an OS sandbox: shell/MCP paths and the contents of allowed metadata still rely on
instruction compliance.

Stop blocks premature final answers and supplies the pending C6 action; it never
skips barriers or dispatches. Three stops without a meaningful checkpoint end in an
explicit no-progress escalation, not success or an endless loop. The guard tells
its own continuation prompt from user input. Worker sessions, native subagents and
unbound sessions are not trapped; the guard applies to development objectives.

The state is coordinator-owned operational evidence, not a signed authority
store. As with C6, do not fabricate receipts, edit the binding by hand or create
a false hold to bypass the protocol. `status REQUEST` is read-only.

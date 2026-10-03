# C8 — coordinator session continuity and stop guard

Part of [runtime-contracts.md](../runtime-contracts.md); load only when the index says so.

## C8 — coordinator session continuity and stop guard

`bin/coordinator-session ACTION REQUEST_JSON`; native Windows uses
`bin/coordinator-session.ps1` with the same arguments. `hook` instead reads one
provider hook payload from stdin; `hook --host claude` selects Claude and plain
`hook` retains Codex behavior. Helpers never call Orca, dispatch, consume the
inbox, commit, cancel workers or change user configuration. Operational use and
the role boundary are in [coordinator-session.md](../coordinator-session.md).

All action requests contain `worktree` (absolute actual Git root) and
`session_id` (actual provider ID) and optional `host` (`codex`, the default, or
`claude`). Codex defaults the ID to `CODEX_THREAD_ID` and requires a match when
it is set. Claude requires the explicit ID from its hook; it never inherits a
parent Codex ID. IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`. Workers with
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
is atomically saved in `.superpowers/sdd/.sessions/<session-id>.json` (Codex) or
`.superpowers/sdd/.sessions/claude/<session-id>.json` (Claude) with
`schema_version:1`, `role:"coordinator"`, identities, objective, `status`
(`active`/`held`), `orca_run`, `proposal`, meaningful `progress`, `stop_attempts`
and `hold`, plus `host` and `turn_open`. Old bindings without `host` are Codex
bindings. A different host cannot load them. Claude `turn_open` starts true at
bind and UserPromptSubmit; only an allowed Stop clears it. Checkpoints may add validated `bookkeeping` paths. A generated
continuation's SHA-256 is saved as `continuation_sha256`, so its automatic
UserPromptSubmit does not reset the no-progress counter.

The portable manifest selects `hooks/codex.json` for Codex, using the actual
plugin root and native `commandWindows`. Claude auto-loads `hooks/hooks.json`
with exec-form Node arguments. `bin/claude-hook.cjs` invokes Python on POSIX or
native PowerShell on Windows, without a shell or execution-policy bypass.

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
- C6 clears `active` when it accepts that Dispatch's report; a non-null `active`
  is an unaccepted assignment and requires reconciliation/wait, never another
  launch. Heartbeat, stale and duplicate receipts cannot prove completion.
- Premature Stop returns `decision:block` and the pending action. After three
  attempts without meaningful checkpoint progress, the fourth requests an
  explicit **incomplete** no-progress escalation. It does not loop forever or
  report success. A new real user prompt resets the counter, not a persistent
  blocker/pause. `status_only` clears on that next prompt only when it was the
  sole hold. Requesting status while already held never replaces the persistent
  hold or its evidence; that hold already permits an incomplete status answer.
- Codex Interrupt records a user pause. Claude has no Interrupt hook: the next
  real UserPromptSubmit while an active turn is still open records a held
  `unreconciled_turn`. Explicit intent reconciliation/resume is required; the
  absence of Stop is not proof of the cause. Compaction never clears a hold.
  A held Stop checks any supplied evidence hash
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

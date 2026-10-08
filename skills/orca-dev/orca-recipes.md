# orca-dev — Orca launch & lifecycle recipes

How a role from `roles.md` becomes a running Orca worker, how the coordinator waits, and how it cleans up. Read the sibling `../orchestration/SKILL.md` and its relevant bundled references. The supported CLI baseline is recorded in `../orchestration/upstream.md`. Actual command help/receipts govern syntax and lifecycle facts; the shared role contract and orca-dev govern routing, model policy and completion. Do not fetch stock skill instructions through `orca skills get`.

## 0. Session start (coordinator)

```bash
orca status --json                      # runtime must be "ready"
orca orchestration run-create --objective "<plan slug or task>" --json   # once per plan; the plan writer copies it into the frontmatter (orca_run:)
# resuming an existing plan: orca orchestration run-use --id <run_id> --json
```

Resolve the helpers once per session from the **actually loaded plugin**, not an
old installed skill link: `PLUGIN_DIR` is the absolute directory two levels above
the loaded `skills/orca-dev/` (it contains `plugin.json`, both host manifests,
`skills/` and `bin/`). Codex hooks supply it as `PLUGIN_ROOT`, Claude hooks as
`CLAUDE_PLUGIN_ROOT`; outside hooks use the observed skill path. A stale
`ORCA_DEV_HOME` never overrides it. Keep the plugin and `bin/lib/` together; do not
repair global environment or recreate an old link; missing runtime files leave
setup incomplete.

```bash
PLUGIN_DIR="<absolute-loaded-plugin-root>"; BIN="$PLUGIN_DIR/bin"
WS="$BIN/sdd-workspace"; RPKG="$BIN/review-package"; GATE="$BIN/verify-gate"
RUN="$BIN/run-check"; STATE="$BIN/protocol-state"; SESSION="$BIN/coordinator-session"
```

Native Windows (PowerShell coordinator, see `recipes-windows.md`) uses the `.ps1`
ports with the same arguments, exit codes and output: `$BIN = Join-Path $PluginDir 'bin'`,
`$WS = "$BIN\sdd-workspace.ps1"`, likewise `$RPKG`, `$GATE`, `$RUN`, `$STATE`,
`$SESSION`; invoke with `&` (`& $GATE docs\plans\x.md a1b2c3d`).

- `"$WS" <plan-file>` prints the self-ignored plan workspace (`.superpowers/sdd/<plan-basename>/`) for prompts, reports, packages and proposals; run it inside a track's worktree for parallel tracks; `"$WS" --name quickfix-<slug>` for a plan-less quickfix.
- `"$RPKG" BASE HEAD [OUTFILE]` (committed range) or `"$RPKG" BASE WORKTREE OUTFILE` writes the review package; only its `wrote <path>: N commit(s), M bytes` line enters your context.
- `"$GATE" <plan-file> <base-sha> [repo-root]` runs the frontmatter's `verify:` commands and classifies failures against BASE; `--phase ID --checkpoint directed|integration|final` selects the scope. Read its lines 1–2; on `GATE_FAIL` pass its full output to the implementer.

Nested worker depth is 1: every dispatch is issued by the coordinator. Every Task spec carries the mandatory no-delegation boundary below. Separately, every Codex worker launch/reuse must use an explicit model and the role's effort policy from `roles.md`, plus proven effective `-c features.multi_agent=false` (verified on codex-cli 0.154.0). The documented Path A cannot carry/prove this setting, so Codex uses custom Path B even when hooks are trusted. Do not rely on native defaults or edit user configuration.

## 1. Task creation

One Orca Task per attempt of a role. The coordinator MUST physically prepend this exact literal block to **every actual Task spec**, before the filled role template or follow-up body:

```text
You are a dispatched worker. Do the assigned work yourself. Do not delegate any part of this task to native subagents or Orca workers, and do not create or launch them. Use the live Orca preamble to report to or ask the coordinator.
```

This is the mandatory worker-boundary prefix. `prompt-fill fill` (prompt-routing.md) composes the scratch spec this way from the bundled template; if you ever assemble by hand, compose it as **that exact block + a blank line + the filled body**; role templates are bodies, not complete specs. This assembly rule governs every template's Dispatch introduction, including ones that call the filled template "the spec". Apply the same construction to quickfixes, all review roles, retries, retained-terminal follow-ups, fix rounds, context answers and re-dispatches after a rejected report. Before `task-create` and again before any dispatch/reuse, compare the actual outgoing spec's opening block to the literal above and confirm it is present and unchanged. If absent, rebuild the spec before sending; a path/reference to this document is not a substitute. Never strip the boundary when reusing a terminal.

```bash
# The scratch file is the complete spec, with the literal prefix checked as above.
orca orchestration task-create --spec "$(cat <scratch>/<role>-<phase>-r<k>.md)" --json   # → task_id
```

Keep specs self-contained: absolute paths for repo root, plan file, ledger, report file, review package. Orca injects its own live lifecycle preamble (task id, dispatch id, `worker_done` command) ahead of this complete spec; the coordinator's boundary does not replace or duplicate that preamble. The spec prohibition and Codex's native feature setting are two separate required controls.

After **3 failed dispatch attempts** Orca circuit-breaks the task to `failed`. Only after §6 confirms ownership-safe recovery and no unresolved writer, retry the same task with `orca orchestration task-update --id <task_id> --status ready --json`, then attach again. Resetting Task bookkeeping alone never proves the previous execution host stopped.

## 2. Attaching a worker — two paths

### Path A — `worker-start` (full lifecycle; for agents whose required launch settings it can prove)

```bash
orca orchestration worker-start --task <task_id> --worktree current \
  --agent claude --model <id> --effort <level> --timeout-ms 240000 --json
```

- **Fresh Claude launches use Path B** (§2 Path B, `wait-agent-ready <h> claude`). Measured 2026-09-26 (Claude Code 2.1.282, Orca 1.4.211, `docs/smoke-runs.md`): 3 of 6 fresh Path A starts lost the prompt, 3 of 3 Path B starts delivered it. Path A stays valid for reusing an existing Claude terminal and for recovery facts below.
- This example is for `claude`; model/effort come from `roles.md`. Orca also supports `codex` model/effort, but this documented interface does not carry/prove `features.multi_agent=false`, so every Codex role uses Path B. A requested setting is not effective-launch evidence. Receipt: `state: ready`, `stage: input_accepted`, `dispatchId`, `launch.effective`.
- **Input accepted vs. Turn start:** `ready/input_accepted` confirms input was accepted into the terminal, not that execution has begun. Confirmation is a positive `turn_started` (when present in receipt) or a new provider transcript record (`worker-read --dispatch <id>`).
- **Screen-confirmed draft recovery:** If input was accepted but the task remains in draft with no transcript activity, confirm via screen inspection (`orca terminal read --terminal <handle> --screen --json`). If the full text is retained in the composer, send Enter ONCE:
  ```bash
  orca terminal send --terminal <handle> --enter --json
  ```
  Then verify work start via transcript (`worker-read --dispatch <id>`). Missing transcript, timeout or silence alone never permits Enter; this is one correction for a proven retained draft in the same terminal/Dispatch. Do not repeat Enter, send duplicate prompts or create duplicate Dispatches without new recovery evidence.
- **Lost prompt (empty composer) is not a retained draft.** A fresh Claude start with `outcome_unknown` / `turn_start_unobserved`, a screen showing the Claude TUI with only the placeholder (`❯ Try "…"`) and no transcript record for the Dispatch means Orca wrote the input before the TUI accepted it (the raw preamble can be seen printed before the banner). Enter or a resend cannot recover it. `worker-stop --dispatch <id>`; after the §6 ownership check, launch a fresh Path B terminal, `wait-agent-ready <h> claude`, inject a new Dispatch and bind it with `claude-model-evidence`.
- **Lost injection on any agent.** Orca can accept an injected Dispatch that never reaches the agent on Path B or on reuse too, most often in a terminal that survived an Orca restart: `orca terminal show --terminal <h> --json` reports `orphaned: true` (the pane is no longer attached to this Orca runtime; that is not process death), and the Dispatch's `worker-show` has a null `provider` and `workspace`, so C6 can neither bind it nor place it in any coordinator's fleet ("unknown fleet workspace"). Never dispatch into an `orphaned` terminal; use a fresh Path B terminal. The following applies to an **unbound** Dispatch (C6 `active.dispatch_id` still null); a bound writer that may have written goes through `record-author`.

  *Diagnosis* (Claude, Antigravity and Codex alike), all of:
  1. the dispatch receipt or its `request-show` names only `input_accepted`, no `turn_started`;
  2. two `--screen` reads of the same terminal and `incarnationId`, at least two minutes apart, both show the agent's idle TUI with an empty composer and nothing after the previous turn's output (no new preamble, no new tool call);
  3. the worker's own store has no user-input record with this Dispatch's preamble, and the same search does find the preamble of an earlier Dispatch of this terminal (proof that the right store was searched). The store is under the worker's effective configuration directory, read from its launch command or environment, else the default: Antigravity `$ORCA_AGY_HOME` or `~/.gemini/antigravity-cli` → `brain/*/.system_generated/logs/transcript.jsonl`; Claude `$CLAUDE_CONFIG_DIR` or `~/.claude` → `projects/*/*.jsonl`; Codex `$CODEX_HOME` or `~/.codex` → `sessions/**/rollout-*.jsonl`. Coordinator sessions mention the Dispatch id too; only the worker's received preamble counts. A missing or unreadable store, a failed search or no earlier preamble found leaves the diagnosis inconclusive. Save the commands and outputs;
  4. the tree is still the dispatch-time candidate, and for a plan author the plan file also still has its dispatch-time existence and bytes.

  The diagnosis shows where the input went; it authorizes nothing by itself, because a stalled agent may still execute queued input later. The only way forward is the **lost-injection cancellation**, the single exception to the rule that a stop needs positive exit evidence first (orchestration `recovery-and-cleanup.md`, "Stall needs positive evidence"; §5 closing rule; §6). It is narrow on purpose: the observations are consistent with lost or delayed delivery to an agent whose previous Dispatch is settled, and cancelling may interrupt this attempt if it was only delayed. The ownership checks authorize the termination; only the confirmed exit and the byte and attribution checks after it authorize a replacement.
  1. *Before closing*, all of: your own saved `terminal create` receipt names the handle and the current `terminal show` has the same `ptyId` and `incarnationId`; `worker-show` of the Dispatch reports no user takeover and no external, user-owned or pre-existing ownership; a fresh complete fleet shows no Dispatch on the handle other than settled earlier ones and this one. A terminal you did not create, or any doubt here, keeps the hold. A supervised (Path A) Dispatch uses `worker-stop --dispatch <id> --json` under its ownership-safe stop contract instead of a close.
  2. *Close and prove exit*: `orca terminal close --terminal <h> --json`. Save the receipt. Exit is proven only by `result.close.ptyKilled: true` in it (or, for `worker-stop`, a stop result that positively reports the process stopped). A missing handle afterwards, an absent verdict, `terminal_stop_live`, `terminal_stop_unverifiable` or a failed close prove nothing: keep the hold.
  3. *Settle*: `worker-abandon --dispatch <id> --json` (it only fences bookkeeping; the exit is already proven), then a fresh complete fleet whose row for it is `failed` with `evidence.durable: true` and neither external, user-owned, pre-existing nor `release_pending`/`release_unknown`.
  4. *Recheck the bytes and clear the intent*: recapture and repeat proof 4 (source candidate, and for a plan author the plan file's existence and bytes) against the dispatch-time capture. Unchanged: for a writer, C6 `reconcile-intent` with that fleet and the current artifact (it requires `write_ownership == ["pending:<task>"]`); a reviewer's next C6 `dispatch` simply replaces its intent. Changed: the worker ran, so register it with C6 `record-author` (current observation, its model and workspace evidence, current artifact; without them keep the hold). That clears the intent: skip `reconcile-intent`. If a plan author changed the plan file, stop after `record-author` and report to the user: a replacement C6 `dispatch` checks the live plan against the accepted hash, so the changed draft has to be preserved aside and the accepted plan bytes restored first, and that is the user's decision. C6 `reconcile-intent` alone does not make this comparison for a plan author.
  5. *Replace*: a new Task, a fresh Path B terminal, `wait-agent-ready <h> <agent>`, a new C6 `dispatch` with another unused complete fleet, and that agent's own model evidence. Never press Enter, resend or dispatch again into the old terminal. If any step fails, keep the hold: the worker may be running.
- Reuse a durably settled same-agent terminal for follow-ups (author revisions subject to the `pro` first-revision exception in §5, implementer fixes, `NEEDS_CONTEXT` answers): `worker-start --task <next_task> --terminal <handle> --json` — read the handle from `worker-show --dispatch <id> --json` → `worker.agentTerminalHandle` (or `agent_terminal_handle` on older receipts). `--model/--effort` cannot be combined with `--terminal` — a model escalation (e.g. per `roles.md`) is therefore always a fresh terminal. The reuse receipt has an empty `launch.effective`, so keep the `worker-start` receipt that **created** this terminal and put it on every C6 observation of the reused Dispatch as `origin_start:{path,sha256}` next to its own `start` (C6 checks the handle and `processIncarnation` chain; a restarted process needs a fresh launch).
- New worktree for a parallel track: `--worktree new-child --name <slug>-<phase> --setup run` instead of `current`.

### Path B — custom argv + `dispatch --inject` (unsupervised lifecycle)

Required when the agent needs flags Orca cannot pass, or a blocker below is not yet cleared:

For custom Codex workers set `ORCA_STRIGOV_WORKER=1` only in the new
terminal's launch command: POSIX `env ORCA_STRIGOV_WORKER=1 codex ...`;
PowerShell `$env:ORCA_STRIGOV_WORKER='1'; codex ...` in that child terminal.
Never set it in the coordinator or persist it in User/Machine environment.
It exempts workers from this plugin's coordinator hooks, not from the live
assignment, worker lifecycle or no-delegation boundary.

```bash
H=$(orca terminal create --worktree active --title "<role>-<phase>" --command "<argv>" --json | jq -r .result.terminal.handle)
orca terminal wait --terminal "$H" --for tui-idle --timeout-ms 180000 --json
if "$BIN/wait-agent-ready" "$H" <agy|codex|claude> 120; then  # REQUIRED before inject
  # Task spec boundary and required effective launch settings were checked (§1).
  orca orchestration dispatch --task <task_id> --to "$H" --inject --json
else
  orca terminal read --terminal "$H" --screen --json
  # Unverifiable readiness: stop this launch sequence and follow §6; no inject/retry/close.
fi
```

**The preamble carries the worker's identity — `--from <handle>` and `--dispatch-capability dcap_…`.** Orca accepts a `worker_done` only with those two values; a worker that copies the template's `orca orchestration send … worker_done` line without them gets the message rejected while its report file is already written. The prompt templates show both flags as placeholders pointing at the preamble. Coordinator handling of a rejected `worker_done` is in coordinator-core.md (Verdicts): read the report, have the worker resend with the preamble's values, then proceed to release.

**Codex needs it too:** Codex draws the "Ask Codex" composer while it is still `Starting MCP servers (n/9)`; text sent in that window lands in the composer but the Enter is swallowed. `wait-agent-ready <h> codex` waits for that line to leave the screen. If screen inspection shows retained draft content, send Enter once.

**Antigravity's login menu is a race, not a logout:** `agy` authenticates through the OS keyring 2–3 s after start; when the TUI's first frame wins, it shows "You are currently not signed in / Select login method" under the same banner and does not always redraw once the backend is authenticated. `wait-agent-ready <h> agy` treats "not signed in" as busy and keeps polling; a timeout (exit 1) means `unverifiable` readiness, not availability failure. Read current execution-host/terminal evidence (and worker evidence if already dispatched) and `nextAction` per §6. Do not close, retry or cascade merely because the menu stayed visible or the helper timed out.

**Why `wait-agent-ready` is mandatory:** `tui-idle` is satisfied by the launching shell's prompt within ~1 s, before a slow-starting agent has drawn its TUI. `wait-agent-ready` polls the **rendered** screen (`orca terminal read --screen`) for the agent's banner/composer marker, then waits for `tui-idle` once more; exit 1 means readiness could not be verified, not that the agent died. The launch sequence stops before injection until current evidence supports readiness or ownership-safe recovery per §6; timeout/idle alone cannot trigger stop, close, retry or cascade. When you eyeball a terminal yourself, use `--screen`.

Argv per agent:

| agent | argv |
|---|---|
| Antigravity (**always Path B** — `worker-start --model` is rejected for `antigravity`) | `agy --model <model> --dangerously-skip-permissions` (no `--effort`: the level is part of the `gemini-*-flash-<level>` id and agy rejects the flag; per `roles.md`) |
| Codex, every native worker role (including trusted hooks) | `env ORCA_STRIGOV_WORKER=1 codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m <model> -c model_reasoning_effort=<level> -c features.multi_agent=false` |
| Codex Pro (opt-in) | `codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m <pro-model per roles.md> -c features.multi_agent=false` |
| Claude | `claude --dangerously-skip-permissions --model <model> --effort <level>` (per `roles.md`) |

**Antigravity on Path B** likewise has no reported model: after settlement run `"$BIN/protocol-state" antigravity-model-evidence "$dir/worker-show-<ATTEMPT>.json" "$dir/agy-transcript-<ATTEMPT>.jsonl"` and copy its `model_evidence` into that observation reference.

**Claude on Path B has no launch receipt with a model** (`terminal create` carries none and Orca leaves `provider.model` null for Claude). After the worker's first assistant response — preferably after settlement — freeze its Claude Code session as C6 evidence:

```bash
"$BIN/protocol-state" claude-model-evidence "$dir/worker-show-<ATTEMPT>.json" "$dir/claude-transcript-<ATTEMPT>.jsonl"
```

Native Windows: `& "$BIN\protocol-state.ps1" claude-model-evidence …`. On `VALID` copy the printed `model_evidence` object into that observation reference; `UNVERIFIABLE` (no or several sessions claim the Dispatch) stays a protocol blocker. Never hand-write the object or point it at the live transcript.

Path B differences: `worker_done`, `ask`, heartbeat all work identically, but the terminal is operator-created/unsupervised. `worker-release` may be a no-op and `worker-stop` does not thereby own its process: follow the actual settlement/release receipts in §5, leaving external or uncertain terminals open. Neither Task completion nor a no-op release authorizes `terminal close`. After durable settlement, a follow-up can reuse the same terminal with `dispatch --task <next> --to $H --inject`, subject to the boundary check, a current `terminal show` without `orphaned: true` (an Orca restart orphans it: use a fresh terminal, §2 lost injection) and, for Codex, proof that its original launch disabled native multi-agent. Unknown launch settings require a supported custom launch after resolving the old write task per §6, not assumptions about defaults.

## 3. Startup blockers and how `install.sh` clears them

A worker that shows a modal in its TUI is reported by Orca as `agent_prompt_blocked` / `blockedReason` on `terminal wait`, and `terminal send` is refused too. Known modals:

| blockedReason | cause | fix (done by `install.sh`, or manually) |
|---|---|---|
| `codex-update-prompt` | Codex "Update available" | keep Codex current: `brew upgrade --cask codex` / `npm i -g @openai/codex` |
| `codex-hooks-review-prompt` | Orca's 8 hooks in `~/.codex/hooks.json` untrusted | press **2. Trust all and continue** once in any Codex terminal inside Orca (persists in `[hooks.state]`), OR use Path B with `--dangerously-bypass-hook-trust`. `bypass_hook_trust = true` in config.toml does NOT work. |
| Antigravity "Do you trust this folder?" | repo not in `trustedWorkspaces` | add the exact repo path to `~/.gemini/antigravity-cli/settings.json` → `trustedWorkspaces` (a parent directory does not cover it) |
| Claude Code trust dialog | first run in the folder | `~/.claude.json` → `projects["<repo>"].hasTrustDialogAccepted = true` |

Before the first dispatch of a session run `install.sh --check <repo>` (read-only) and fix what it reports; a blocked worker costs a dispatch attempt and, after three, the task.

## 4. Waiting

For a worker-owned long shell command, load [C3](contracts/c3-command-owner.md) on demand. Use `run-check run SPEC_JSON` (native Windows: `run-check.ps1`) and let the shell block. Its owner receives full log/result paths, explicit deadline/cancel policy, diagnostic progress and an optional shared local resource key. `run-check wait` observes a new diagnostic state or completion; it never transfers ownership. The coordinator receives significant findings from the owner rather than observing the same log. Silence/no-progress permits bounded diagnosis, not a kill, new writer or resource takeover. Do not add Schedule/model timers, monitoring workers or an Orca process API. A required command terminal uses the verified `orca terminal wait --terminal <handle> --for exit --timeout-ms ...`; this waits for that terminal, not an arbitrary PID. Preserve heartbeat and settlement duties from the live preamble.

For **worker settlement**, run one C7 waiter in the coordinator's shell. Prepare
its request in the existing plan workspace using the actual CLI, Run and awaited
Dispatch IDs; the [C7 contract](contracts/c7-worker-event-waiter.md) gives
the JSON shape. Allocate a fresh output directory per invocation.

```bash
"$BIN/wait-worker-event" "$dir/wait-<ATTEMPT>.json"
```

- The helper blocks on `check --wait --types "worker_done,escalation,question"`
  in fixed 9-minute windows. Empty timeouts renew inside the process; keepalives
  go to stderr log files. Neither wakes the coordinator with a status report.
- After three empty windows it reads this Run's paginated fleet, including remote
  workers. A live worker or stale-only observation with no requested action keeps
  waiting. An awaited worker's exit, attention or nextAction returns a diagnostic;
  malformed evidence, a missing expected Dispatch or transport failure returns an
  error. These observations never authorize automatic stop, retry or release.
- Read the single result line and its saved raw receipt: `delivery` → process
  **every** message in the FIFO batch, including older statuses/heartbeats;
  `attention`/`error` → inspect the recorded evidence and follow §6. `nextAction`
  is advice for the coordinator, never executed by the helper.
- After all messages and terminal ownership decisions are processed, put the
  accepted Delivery ID in the next request's `ack_delivery_id`. The helper passes
  `--ack` only on its first check. Reply to questions before acknowledgment.
  If using `check --ack ... --json` directly, process any next Delivery it returns
  too; do not discard that response. C6 acceptance still applies.
- Keep one consuming waiter per coordinator Run. If the tool returns a running
  session/cell ID, resume **that same call** using the longest wait the host allows.
  A harness yield is not an Orca timeout: do not restart the helper, shorten its
  window, read a worker screen/log, add a timer, or dispatch a monitoring agent.
  Tool-imposed wakeups may remain; they require no worker inspection. Report
  meaningful changes at the host's required cadence, without polling narration.

Native Windows uses `& "$BIN\wait-worker-event.ps1" "$dir\wait-<ATTEMPT>.json"`.
Readiness checks before injection and receipt checks at real lifecycle barriers
remain unchanged. A missing/broken helper is a setup issue to report, not a reason
to reconstruct a model-driven short polling loop.

`worker_done` fields the protocol reads: `subject` (the verdict token), `payload.outcome` (`succeeded|failed`), `payload.reportPath` (the report file — the coordinator reads only what coordinator-core.md Rule 2 allows), `payload.filesModified`.

## 5. After a `worker_done`

Before accepting it, save the exact accepted send/check receipt and a current
`orca orchestration worker-show --dispatch <id> --json` observation. Pass their
paths/raw hashes, the selected message ID, report and frozen artifact to C6
`accept-report`; only then store the returned resume and acknowledge a complete
Delivery through §4's next waiter request (or a direct `check --ack`, processing
any batch it returns). Stale/duplicate/heartbeat results
do not create a second completion or consume another substantive round.

Decide the terminal's fate **before** acknowledging the Delivery:

- **Explicit retention:** To preserve a terminal across review/fix rounds or handoffs, tell Orca to retain it: `orca orchestration worker-retain --dispatch <id> --json` (record the expected next action).
- **Retention rules:**
  - **Plan author retention:** Keep the plan writer's terminal open until the plan is approved and committed; Mode B reuses the actual author. Actual context loss uses the authorized revision profile with a fresh announced full handoff.
  - **Implementer retention:** Keep the implementer's terminal open across fix rounds until the phase is approved and committed; fix rounds re-inject into this terminal (`dispatch --inject`). Open a new implementer terminal only for a model change or a proven unusable one, and record why.
- **Reuse:** After durable Task settlement, follow up on the same agent (subject to the author exception above): Path A → `worker-start --task <next> --terminal <handle>`; Path B → `dispatch --task <next> --to <handle> --inject`. C6 model proof for the follow-up: Path A carries `start` + `origin_start` (§2); a Claude Path B follow-up gets a new `claude-model-evidence` snapshot for the new Dispatch. Recheck the actual spec prefix and effective launch requirements; an alive retained terminal with a settled Task is not an active writer.
- **Release:** After accepted settlement and the reason for retention ends (plan committed / phase committed), or for fresh-round reviewers, request `orca orchestration worker-release --dispatch <id> --json` and inspect the real result for either path. A requested release is not actual release; operator-created terminals may have no owned resource to release.

**Read and record the release result.** `retained` with reason `user_requested`/`user_takeover`, `external`, `release_pending`, `release_unknown` and no-op outcomes leave the terminal open; none authorizes forced closing. Only positive actual release evidence establishes release of an owned resource. A Path B Dispatch (created by `orchestration dispatch`) has no owned resource: Orca reports it as `state: "retained"`, `reason: "no_owned_resource"`, `processAction: "none"`. That is the no-owned-resource outcome, not a retention request, and it is the normal entry to the closing rule below. Do not substitute `terminal close` for release or interpret acknowledgement/settlement as a cleanup receipt. Follow the current receipt/`nextAction`; preserving external or uncertain resources is a valid recorded terminal outcome.

**Closing a finished Path B terminal.** Path B terminals have no owned resource, so release leaves them open and they accumulate. Close one with `orca terminal close --terminal <h> --json` only when all of these hold, and record the receipts:
- your own saved `terminal create` receipt names this handle, and the current `worker-show` terminal (or `terminal show`) has the same `incarnationId` (same process, never replaced);
- every Dispatch on the handle is durably settled and C6-accepted or abandoned, and a fresh `worker-list` shows no other Dispatch assigned to it;
- the release result was a no-op or `retained` with reason `no_owned_resource` (processAction `none`), not `user_requested`/`user_takeover`/`external`/`release_pending`/`release_unknown`, and ownership is not user-owned or pre-existing;
- the terminal will not be reused: a fresh-per-round role (reviewers, control, final, diagnosis, gate worker, synthesizer) after its report is accepted, or a writer after its phase is committed (or after a model change replaced it).
Anything uncertain stays open. Never close the coordinator's own terminal, an active writer, or a terminal the user opened. The §2 lost-injection cancellation is the one exception to these conditions; it has its own, stricter preconditions and is never a cleanup shortcut. Close at the first point all conditions hold (a reviewer right after its accepted report, a writer right after its phase commit), not at the end of the plan: finished Path B terminals otherwise pile up in the user's workspace.

## 6. Failure handling

- Start with current execution-host, worker and terminal evidence, Task/Dispatch settlement and the reported `nextAction` (`worker-show --dispatch <id> --json`, `worker-read --dispatch <id>` when a Dispatch exists, terminal evidence before one exists). `unverifiable`, readiness timeout, idle, missing heartbeat and failed Task bookkeeping alone do not prove that a process stopped. An alive retained terminal with a durably settled Task is not an active writer and may be reused.
- Only positive current host exit/failure evidence (for example actual `failed`/`stopped`/`exited` liveness), or a durably settled Task with recovery evidence excluding an unresolved writer, can allow a fresh attempt. Follow only ownership-safe recovery supported by the real receipt/`nextAction`; never retry into a tree with an unresolved live or unverifiable write task. When permitted, use `worker-start --task <task> --retry-of <dispatch_id> ...` with explicit placement for Path A, or a fresh Path B terminal for roles requiring custom settings. Retry does not inherit placement; recheck the spec boundary and launch settings.
- `outcome_unknown` keeps the write barrier unresolved. Inspect first; `worker-stop --dispatch <id>` is allowed only when current evidence and the recovery receipt support stopping an owned resource. Read the actual stop result before any retry. A stop request or `worker-abandon` is not proof of termination and cannot clear the barrier (the §2 lost-injection cancellation clears it only with its positive exit receipt and byte recheck); never force close an external, retained or uncertain terminal outside that cancellation.
- An accepted, durably settled `worker_done --outcome failed` identifying quota / rate limit / auth / launch problems is an **availability** failure, subject to the evidence/recovery checks above → cascade per `roles.md`. Reviewer fallbacks must remain independent of every actual author family of their reviewed units, or acceptance stays incomplete. Any other failed outcome is a protocol verdict (`BLOCKED`, `NEEDS_*`) → handle per coordinator-results.md.

**Antigravity workers.** Its timer ("Schedule") is a quota sink, not a wait: a `Schedule(90s: …)` one-shot timer pings the model every 30 s and Flash answers each ping with a log read and a new timer (observed 2026-09-02: ~13 calls per minute for 40 minutes, the five-hour quota drained without output). The implementer prompts tell workers to block inside one shell call instead. If a worker's screen cycles `Schedule → Read(task log) → Waiting…`, steer it once with `orca terminal send`: "Stop using the timer; wait for the test with a single blocking shell command (`Start-Sleep 300` then check the process), then continue." Quota exhaustion mid-phase is an availability failure → cascade per `roles.md`. The login-menu race is described under §2.

## 7. Bridge preflight (retired)

The Pro planner is retired (`roles.md`, Planning profiles): refuse `--planner pro`
and explain why. The preflight and incident notes stay in
[references/bridge-incidents.md](references/bridge-incidents.md) for history.

## 8. Cheat-sheet: role → recipe

| role | path | agent / argv |
|---|---|---|
| plan-writer / plan-reviser | B for every profile (Claude included: model proof via `claude-model-evidence`) | role agent/model/effort per `roles.md`; every Codex argv includes `-m <model> -c features.multi_agent=false` and native effort per §2 |
| plan-reviewer (Codex) / review-primary / review-final / diagnosis / frontend-implementer | B for Claude (fresh launch; model proof via `claude-model-evidence`) and for permitted Codex routes; A only to reuse an existing Claude terminal (`origin_start`) | role agent/model/effort per `roles.md`; every Codex argv carries explicit model/effort and `-c features.multi_agent=false` per §2 |
| review-control | B for Codex and for an independent Claude substitution | model/effort per `roles.md`; Codex argv includes `-m <model> -c model_reasoning_effort=<effort> -c features.multi_agent=false` |
| implementer / gate / synthesizer / quickfix | B | `agy --model <model> --dangerously-skip-permissions` (model id carries the level) |
| implementer fallback / escalation | B for Codex | `codex ... -m <model> -c model_reasoning_effort=<effort> -c features.multi_agent=false` (per `roles.md`) |

## 9. Windows (native, no WSL)

A native Windows coordinator applies the differences listed in
[recipes-windows.md](recipes-windows.md) (PowerShell ports, quoting, trust file
locations, Claude launch). A POSIX coordinator does not load that file.

## C6 validation before lifecycle effects

Read [C6](contracts/c6-protocol-validation.md)
for the single input schema and Report binding. For each proposal that requires
fresh fleet evidence, run the collector **in the existing coordinator shell**:

```sh
"$BIN/collect-worker-fleet" "$dir/fleet-request-<ATTEMPT>.json"
```

Native Windows: `& "$BIN\collect-worker-fleet.ps1" "$dir\fleet-request-<ATTEMPT>.json"`.
The [C6 collector contract](contracts/c6-protocol-validation.md#c6-fleet-collector-no-orca-terminal)
defines the small request. On exit 0 read the
one-line result and load its `fleet_file` with JSON tools; set the proposal's
`fleet` to that file's `fleet` array (path/hash/cursor references). Do not retype
or reserialize the original receipts. The collector follows all pages at limit
100 directly into files. The coordinator receives no per-page dump.

**Why the helper is required:** in a bound terminal, `worker-list` without
`--run` defaults to that Run, not all Runs. The collector removes inherited
terminal/pane identity only in its read-only child and marks it identity-less,
preventing active-pane guessing; it checks every actual response for `scope:all`.
It does not unbind the coordinator or change connection settings. Never apply
that child environment to lifecycle commands or the C7 inbox waiter.

On error keep the partial evidence and stop the transition. Do not create or
reuse a scratch Orca terminal as a workaround, reduce the page size, relay JSON
via base64/terminal reads, fabricate `scope:all`, or settle for Run-scoped data.
Existing unrelated/agent terminals stay untouched; this is not cleanup authority.
Each required proposal still needs a fresh complete observation; no timer or
guessed process API. Settled retained terminals do not hold write ownership.

After task creation, `dispatch` validates the proposed role/model/coverage with
`dispatch_id:null`. Only after VALID use the existing launch recipe; immediately
save `worker-show --dispatch <actual-id> --json` and `bind-dispatch`. An unbound
writer intent stays locked until bound or, after a failed launch, cleared with
`reconcile-intent` (a fresh fleet showing the Task's Dispatches settled, or the
saved `ok:false` launch receipt when none was created; the tree unchanged). A
launch that started another model and wrote is registered with `record-author`
(its settled observation and the current artifact), which also clears the
intent. A bound writer that settled without an accepted report is registered
with `record-author` before anything replaces it. Keep actual writer observations for
C5 provenance; model family comes from roles.md, including cross-family CLI
launches. Do not invent missing facts.

```sh
"$BIN/protocol-state" validate "$dir/proposal.json" "$dir/resume.json"
```

Native Windows uses `& "$BIN\protocol-state.ps1" validate ...`. Check exit 0
**and** the returned decision/barrier before the exact proposed effect. Supply a
fresh `plan` reference when the plan file changed and a fresh `ledger` reference
when the ledger changed. Stage only authorized paths before the gate/package,
then `prepare-commit` on the accepted artifact; after Git, `confirm-commit` with
`commit:{sha,base}` (full SHAs) and the same artifact, then `advance`. Crash
recovery confirms the existing commit. Final review, delivery and the separate
completion commit are distinct barriers (`finish-checkpoint`, `complete`). The
helper never runs a lifecycle or commit action itself. A schema 1 state from an
older run is converted once with `protocol-state migrate STATE_V1_JSON OUT_JSON`.

# orca-dev — Orca launch & lifecycle recipes

How a role from `roles.md` becomes a running Orca worker, how the coordinator waits, and how it cleans up. Everything here is verified against version-matched Orca orchestration semantics. Load the reference with `orca skills get orchestration` at session start; if a command below disagrees with that guide, the guide wins.

## 0. Session start (coordinator)

```bash
orca status --json                      # runtime must be "ready"
orca orchestration run-create --objective "<plan slug or task>" --json   # once per plan; record the run id in the plan frontmatter (orca_run:)
# resuming an existing plan: orca orchestration run-use --id <run_id> --json
```

Nested worker depth is 1: every dispatch is issued by the coordinator. Every Task spec carries the mandatory no-delegation boundary below. Separately, every Codex worker launch/reuse must use an explicit model and the role's effort policy from `roles.md`, plus proven effective `-c features.multi_agent=false` (verified on codex-cli 0.154.0). The documented Path A cannot carry/prove this setting, so Codex uses custom Path B even when hooks are trusted. Do not rely on native defaults or edit user configuration.

## 1. Task creation

One Orca Task per attempt of a role. The coordinator MUST physically prepend this exact literal block to **every actual Task spec**, before the filled role template or follow-up body:

```text
You are a dispatched worker. Do the assigned work yourself. Do not delegate any part of this task to native subagents or Orca workers, and do not create or launch them. Use the live Orca preamble to report to or ask the coordinator.
```

This is the mandatory worker-boundary prefix. Compose the scratch spec as **that exact block + a blank line + the filled body**; role templates are bodies, not complete specs. This assembly rule governs every template's Dispatch introduction, including ones that call the filled template "the spec". Apply the same construction to quickfixes, all review roles, retries, retained-terminal follow-ups, fix rounds, context answers and format corrections. Before `task-create` and again before any dispatch/reuse, compare the actual outgoing spec's opening block to the literal above and confirm it is present and unchanged. If absent, rebuild the spec before sending; a path/reference to this document is not a substitute. Never strip the boundary when reusing a terminal.

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

- This example is for `claude`; model/effort come from `roles.md`. Orca also supports `codex` model/effort, but this documented interface does not carry/prove `features.multi_agent=false`, so every Codex role uses Path B. A requested setting is not effective-launch evidence. Receipt: `state: ready`, `stage: input_accepted`, `dispatchId`, `launch.effective`.
- **Input accepted vs. Turn start:** `ready/input_accepted` confirms input was accepted into the terminal, not that execution has begun. Confirmation is a positive `turn_started` (when present in receipt) or a new provider transcript record (`worker-read --dispatch <id>`).
- **Screen-confirmed draft recovery:** If input was accepted but the task remains in draft with no transcript activity, confirm via screen inspection (`orca terminal read --terminal <handle> --screen --json`). If the full text is retained in the composer, send Enter ONCE:
  ```bash
  orca terminal send --terminal <handle> --enter --json
  ```
  Then verify work start via transcript (`worker-read --dispatch <id>`). Missing transcript, timeout or silence alone never permits Enter; this is one correction for a proven retained draft in the same terminal/Dispatch. Do not repeat Enter, send duplicate prompts or create duplicate Dispatches without new recovery evidence.
- Reuse a durably settled same-agent terminal for follow-ups (author revisions subject to the `pro` first-revision exception in §5, implementer fixes, `NEEDS_CONTEXT` answers): `worker-start --task <next_task> --terminal <handle> --json` — read the handle from `worker-show --dispatch <id> --json` → `worker.agentTerminalHandle` (or `agent_terminal_handle` on older receipts). `--model/--effort` cannot be combined with `--terminal` — a model escalation (e.g. per `roles.md`) is therefore always a fresh terminal.
- New worktree for a parallel track: `--worktree new-child --name <slug>-<phase> --setup run` instead of `current`.

### Path B — custom argv + `dispatch --inject` (unsupervised lifecycle)

Required when the agent needs flags Orca cannot pass, or a blocker below is not yet cleared:

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

**The preamble carries the worker's identity — `--from <handle>` and `--dispatch-capability dcap_…`.** Orca accepts a `worker_done` only with those two values; a worker that copies the template's `orca orchestration send … worker_done` line without them gets the message rejected while its report file is already written. The prompt templates show both flags as placeholders pointing at the preamble. Coordinator handling of a rejected `worker_done` is in SKILL.md (verdict procedure): read the report, have the worker resend with the preamble's values, then proceed to release.

**Codex needs it too:** Codex draws the "Ask Codex" composer while it is still `Starting MCP servers (n/9)`; text sent in that window lands in the composer but the Enter is swallowed. `wait-agent-ready <h> codex` waits for that line to leave the screen. If screen inspection shows retained draft content, send Enter once.

**Antigravity's login menu is a race, not a logout:** `agy` authenticates through the OS keyring 2–3 s after start; when the TUI's first frame wins, it shows "You are currently not signed in / Select login method" under the same banner and does not always redraw once the backend is authenticated. `wait-agent-ready <h> agy` treats "not signed in" as busy and keeps polling; a timeout (exit 1) means `unverifiable` readiness, not availability failure. Read current execution-host/terminal evidence (and worker evidence if already dispatched) and `nextAction` per §6. Do not close, retry or cascade merely because the menu stayed visible or the helper timed out.

**Why `wait-agent-ready` is mandatory:** `tui-idle` is satisfied by the launching shell's prompt within ~1 s, before a slow-starting agent has drawn its TUI. `wait-agent-ready` polls the **rendered** screen (`orca terminal read --screen`) for the agent's banner/composer marker, then waits for `tui-idle` once more; exit 1 means readiness could not be verified, not that the agent died. The launch sequence stops before injection until current evidence supports readiness or ownership-safe recovery per §6; timeout/idle alone cannot trigger stop, close, retry or cascade. When you eyeball a terminal yourself, use `--screen`.

Argv per agent:

| agent | argv |
|---|---|
| Antigravity (**always Path B** — `worker-start --model` is rejected for `antigravity`) | `agy --model <model> --effort <level> --dangerously-skip-permissions` (per `roles.md`) |
| Codex, every native worker role (including trusted hooks) | `codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m <model> -c model_reasoning_effort=<level> -c features.multi_agent=false` |
| Codex Pro (opt-in) | `codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m <pro-model per roles.md> -c features.multi_agent=false` |
| Claude | `claude --dangerously-skip-permissions --model <model> --effort <level>` (per `roles.md`) |

Path B differences: `worker_done`, `ask`, heartbeat all work identically, but the terminal is operator-created/unsupervised. `worker-release` may be a no-op and `worker-stop` does not thereby own its process: follow the actual settlement/release receipts in §5, leaving external or uncertain terminals open. Neither Task completion nor a no-op release authorizes `terminal close`. After durable settlement, a follow-up can reuse the same terminal with `dispatch --task <next> --to $H --inject`, subject to the boundary check and, for Codex, proof that its original launch disabled native multi-agent. Unknown launch settings require a supported custom launch after resolving the old write task per §6, not assumptions about defaults.

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

```bash
orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 540000 --json
```

- Rolling windows; a timeout or `{count:0}` is a checkpoint, not a failure. Coding turns run 15–60 min; planning turns run 10–30 min.
- The command prints `{"_keepalive":true,...}` heartbeat lines before the final JSON — parse only the last line.
- From a Codex coordinator the blocking wait is safe: use ≤ 9-minute windows.
- Process **every** message in a Delivery, then `check --ack <delivery_id> --wait ...` for the next one. Reply to `question` messages with `orca orchestration reply --id <msg_id> --body "<answer>" --json` before acknowledging.
- Liveness checkpoint when a window returns nothing: `orca orchestration worker-show --dispatch <id> --json`, or `orca terminal read --terminal <handle> --json`.
- **After 3 empty waits**: do not poll blindly; run `orca orchestration task-list` / fleet inspection to verify whether the worker is active or if nextAction is needed. Activity means alive — never stop a worker for being slow.

`worker_done` fields the protocol reads: `subject` (the verdict token), `payload.outcome` (`succeeded|failed`), `payload.reportPath` (the report file — the coordinator reads only what SKILL.md allows), `payload.filesModified`.

## 5. After a `worker_done`

Decide the terminal's fate **before** acknowledging the Delivery:

- **Explicit retention:** To preserve a terminal across review/fix rounds or handoffs, tell Orca to retain it: `orca orchestration worker-retain --dispatch <id> --json` (record the expected next action).
- **Retention rules:**
  - **Plan author retention:** Keep the plan writer's terminal open until the plan is approved and committed; normally Mode B reuses the actual author. Exception: the first revision of a `pro` initial plan goes to a fresh native `plan-reviser` per `roles.md`, with announced full handoff (plan, ledger, latest author/review reports); retain and reuse that reviser thereafter. The settled initial author stays available for context until commit and receives no revision task. Actual context loss uses the authorized revision profile with a fresh announced full handoff.
  - **Implementer retention:** Keep the implementer's terminal open across fix rounds until the phase is approved and committed; fix rounds re-inject into this terminal.
- **Reuse:** After durable Task settlement, follow up on the same agent (subject to the author exception above): Path A → `worker-start --task <next> --terminal <handle>`; Path B → `dispatch --task <next> --to <handle> --inject`. Recheck the actual spec prefix and effective launch requirements; an alive retained terminal with a settled Task is not an active writer.
- **Release:** After accepted settlement and the reason for retention ends (plan committed / phase committed), or for fresh-round reviewers, request `orca orchestration worker-release --dispatch <id> --json` and inspect the real result for either path. A requested release is not actual release; operator-created terminals may have no owned resource to release.

**Read and record the release result.** `retained` (including `user_requested`), `external`, `user_takeover`, `release_pending`, `release_unknown`, no-owned-resource and no-op outcomes leave the terminal open; none authorizes forced closing. Only positive actual release evidence establishes release of an owned resource. Do not infer ownership from having created a terminal, substitute `terminal close` for release, or interpret acknowledgement/settlement as a cleanup receipt. Follow the current receipt/`nextAction`; preserving external or uncertain resources is a valid recorded terminal outcome.

## 6. Failure handling

- Start with current execution-host, worker and terminal evidence, Task/Dispatch settlement and the reported `nextAction` (`worker-show --dispatch <id> --json`, `worker-read --dispatch <id>` when a Dispatch exists, terminal evidence before one exists). `unverifiable`, readiness timeout, idle, missing heartbeat and failed Task bookkeeping alone do not prove that a process stopped. An alive retained terminal with a durably settled Task is not an active writer and may be reused.
- Only positive current host exit/failure evidence (for example actual `failed`/`stopped`/`exited` liveness), or a durably settled Task with recovery evidence excluding an unresolved writer, can allow a fresh attempt. Follow only ownership-safe recovery supported by the real receipt/`nextAction`; never retry into a tree with an unresolved live or unverifiable write task. When permitted, use `worker-start --task <task> --retry-of <dispatch_id> ...` with explicit placement for Path A, or a fresh Path B terminal for roles requiring custom settings. Retry does not inherit placement; recheck the spec boundary and launch settings.
- `outcome_unknown` keeps the write barrier unresolved. Inspect first; `worker-stop --dispatch <id>` is allowed only when current evidence and the recovery receipt support stopping an owned resource. Read the actual stop result before any retry. A stop request or `worker-abandon` is not proof of termination and cannot clear the barrier; never force close an external, retained or uncertain terminal.
- An accepted, durably settled `worker_done --outcome failed` identifying quota / rate limit / auth / launch problems is an **availability** failure, subject to the evidence/recovery checks above → cascade per `roles.md`. Reviewer fallbacks must remain independent of every actual author family of their reviewed units, or acceptance stays incomplete. Any other failed outcome is a protocol verdict (`BLOCKED`, `NEEDS_*`) → handle per SKILL.md.

## 7. Bridge preflight (Pro planner — opt-in only)

When the user explicitly chooses `--planner pro`:

```bash
pgrep -f "codex-chatgpt-web.*cli.js serve" >/dev/null && echo bridge-up || echo bridge-down
# optional, ~2 s: full self-check of the bridge (browser login, proxy, tunnel, connector)
V=$(ls -d ~/.codex-chatgpt-web/versions/*-darwin-arm64 2>/dev/null | tail -1)
[ -n "$V" ] && "$V/runtime/bun" "$V/app/cli.js" status | tail -1   # → "Doctor result: ready"
```

On Windows (PowerShell):

```powershell
$up = @(Get-CimInstance Win32_Process -Filter "Name='bun.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'codex-chatgpt-web.*cli\.js serve' }).Count -gt 0
if ($up) { 'bridge-up' } else { 'bridge-down' }
$V = (Get-ChildItem "$HOME\.codex-chatgpt-web\versions" -Directory -ErrorAction SilentlyContinue | Where-Object Name -like '*-win32-*' | Sort-Object Name | Select-Object -Last 1).FullName
if ($V) { pwsh -NoProfile -Command "Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue; & '$V\runtime\bun.exe' '$V\app\cli.js' status | Select-Object -Last 1" }
```

Bridge down or doctor not `ready` → fall back to the default `astra` profile.

## 8. Cheat-sheet: role → recipe

| role | path | agent / argv |
|---|---|---|
| plan-writer / plan-reviser | B for native/default and `pro`; A only for the explicit legacy profile per `roles.md` | role agent/model/effort per `roles.md`; every Codex argv includes `-m <model> -c features.multi_agent=false` and native effort per §2 |
| plan-writer (Pro — opt-in) | B | `codex ... -m <pro-model per roles.md> -c features.multi_agent=false` |
| plan-reviewer / review-primary / review-final / diagnosis / frontend-implementer | A for Claude; B for permitted Codex routes | role agent/model/effort per `roles.md`; every Codex argv carries explicit model/effort and `-c features.multi_agent=false` per §2 |
| review-control | B for Codex; A for an independent Claude substitution | model/effort per `roles.md`; Codex argv includes `-m <model> -c model_reasoning_effort=<effort> -c features.multi_agent=false` |
| implementer / gate / synthesizer / quickfix | B | `agy --model <model> --effort <effort> --dangerously-skip-permissions` |
| implementer fallback / escalation | B for Codex | `codex ... -m <model> -c model_reasoning_effort=<effort> -c features.multi_agent=false` (per `roles.md`) |

## 9. Windows (native, no WSL)

Installed with `install.ps1` (see `docs/install-windows.md`). Differences from macOS that the coordinator must apply:

- Your shell is PowerShell (Windows PowerShell 5.1 or pwsh 7 — both work). Every workspace script has a native PowerShell port: `& "$env:ORCA_DEV_HOME\bin\<script>.ps1" …` (`sdd-workspace.ps1`, `review-package.ps1`, `verify-gate.ps1`, `wait-agent-ready.ps1`), same arguments, exit codes and output as the bash originals. For Path B, inspect `$LASTEXITCODE` immediately after the readiness helper and inject only on success; nonzero stops the launch sequence for the evidence/recovery checks in §6. Never call `bash` or the extension-less originals on Windows: `bash` there is the WSL launcher in `System32`. `verify-gate.ps1` runs the plan's `verify:` commands in a child PowerShell, so write them as PowerShell / native commands (`pytest -q`, `npm test`), not as bash one-liners. Paths you write into prompts must be absolute Windows paths (`C:\…`) because the workers run native CLIs.
- `orca orchestration check --types "worker_done,escalation,question"` — quote comma-separated lists in PowerShell. Where a recipe pipes `--json` into `jq -r .result.terminal.handle`, use `(… --json | ConvertFrom-Json).result.terminal.handle` instead.
- Path A works unchanged for `claude`; Codex still requires Path B for proven native multi-agent disabling, independent of hook trust. Path B argv is the same text; Antigravity (`agy`) on native Windows is unverified — if `agy` is missing, the implementer cascade continues with its fallback per `roles.md` and the gate/synthesizer fallbacks apply; say so once.
- The skill is linked into `%USERPROFILE%\.codex\skills\orca-dev` (symlink or junction); always locate `bin\` through `ORCA_DEV_HOME` (set by `install.ps1`), never by resolving the skill link.
- The GPT Pro bridge (`codex-chatgpt-web`) has a native Windows build: available when opted into. Preflight per §7.
- Trust files live in the same places under `%USERPROFILE%` (`.claude.json`, `.gemini\antigravity-cli\settings.json`, `.codex\config.toml`); Claude Code keys `projects[]` with forward slashes (`C:/repo`), Antigravity's `trustedWorkspaces` with backslashes — `install.ps1` handles both. `install.ps1 -Repo <path>` handles the repo and its git worktrees; a parallel track's child worktree still needs `install.ps1 -Repo <track-path>` before the first dispatch (same rule as macOS).


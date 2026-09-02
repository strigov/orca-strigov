# orca-dev — Orca launch & lifecycle recipes

How a role from `roles.md` becomes a running Orca worker, how the coordinator waits, and how it cleans up. Everything here was verified in spike 0 (`docs/spikes/RESULTS.md`) on Orca 1.4.193. Load the version-matched reference with `orca skills get orchestration` at session start; if a command below disagrees with that guide, the guide wins.

## 0. Session start (coordinator)

```bash
orca status --json                      # runtime must be "ready"
orca orchestration run-create --objective "<plan slug or task>" --json   # once per plan; record the run id in the plan frontmatter (orca_run:)
# resuming an existing plan: orca orchestration run-use --id <run_id> --json
```

Nested worker depth is 1: workers cannot dispatch sub-workers. Every dispatch in this protocol is issued by the coordinator.

## 1. Task creation

One Orca Task per attempt of a role:

```bash
orca orchestration task-create --spec "$(cat <scratch>/<role>-<phase>-r<k>.md)" --json   # → task_id
```

The spec is the filled prompt template. Keep specs self-contained: absolute paths for repo root, plan file, ledger, report file, review package. Orca injects its own lifecycle preamble (task id, dispatch id, `worker_done` command) in front of the spec — templates never repeat it.

After **3 failed dispatch attempts** Orca circuit-breaks the task to `failed`. To retry the same task: `orca orchestration task-update --id <task_id> --status ready --json`, then attach again.

## 2. Attaching a worker — two paths

### Path A — `worker-start` (full lifecycle; preferred)

```bash
orca orchestration worker-start --task <task_id> --worktree current \
  --agent <claude|codex> --model <id> --effort <level> --timeout-ms 240000 --json
```

- Works for `claude` and `codex` (model/effort supported at launch). Receipt: `state: ready`, `stage: input_accepted`, `dispatchId`, `launch.effective`.
- Reuse the same agent for the next attempt (fix rounds, `NEEDS_CONTEXT` answers, gate-fix rounds): `worker-start --task <next_task> --terminal <handle> --json` — read the handle from `worker-show --dispatch <id> --json` → `worker.agent_terminal_handle`. `--model/--effort` cannot be combined with `--terminal` — a model escalation (Luna → Terra) is therefore always a fresh terminal.
- New worktree for a parallel track: `--worktree new-child --name <slug>-<phase> --setup run` instead of `current`.

### Path B — custom argv + `dispatch --inject` (unsupervised lifecycle)

Required when the agent needs flags Orca cannot pass, or a blocker below is not yet cleared:

```bash
H=$(orca terminal create --worktree active --title "<role>-<phase>" --command "<argv>" --json | jq -r .result.terminal.handle)
orca terminal wait --terminal $H --for tui-idle --timeout-ms 180000 --json
"$BIN/wait-agent-ready" $H <agy|codex|claude> 120     # REQUIRED before inject — see below
orca orchestration dispatch --task <task_id> --to $H --inject --json
```

**Codex needs it too:** Codex draws the "Ask Codex" composer while it is still `Starting MCP servers (n/9)`; text sent in that window lands in the composer but the Enter is swallowed, and the coordinator (or an operator `terminal send`) then waits on a terminal that never started (observed 2026-09-01, smoke 3: 50 minutes idle). `wait-agent-ready <h> codex` now also waits for that line to leave the screen. After any manual `terminal send … --enter`, read the terminal once: `[Pasted Content N chars]` still in the composer means the Enter was lost — send an empty `--enter` again.

**Antigravity's login menu is a race, not a logout:** `agy` authenticates through the OS keyring 2–3 s after start; when the TUI's first frame wins, it shows "You are currently not signed in / Select login method" under the same banner and does not always redraw once the backend is authenticated (observed 2026-09-02 on Windows, `cli.log` shows `ChainedAuth: authenticated via keyring` while the menu is on screen). `wait-agent-ready <h> agy` treats "not signed in" as busy and keeps polling; if it times out (exit 1) treat it as an availability failure of that launch — close the terminal and launch again, the next start usually wins the race — before cascading to the Codex fallback.

**Why `wait-agent-ready` is mandatory:** `tui-idle` is satisfied by the launching shell's prompt within ~1 s, before a slow-starting agent has drawn its TUI (Antigravity spends 10–20 s on login/experiment refresh). An inject sent into that window is lost, and Orca fails the dispatch as `agent_prompt_stalled` about 30 s later — this is exactly how the phase-2 smoke lost its Flash implementer (2026-09-01). `wait-agent-ready` polls the screen for the agent's banner/composer marker, then waits for `tui-idle` once more; exit 1 = marker never appeared (treat as an availability failure of that agent, not as a stall).

Argv per agent:

| agent | argv |
|---|---|
| Antigravity (**always Path B** — `worker-start --model` is rejected for `antigravity`) | `agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions` |
| Codex, hooks not yet trusted | `codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m <model> -c model_reasoning_effort=<level>` |
| Codex Pro | `codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m chatgpt-web/pro` |
| Claude | `claude --dangerously-skip-permissions --model <id> --effort <level>` |

Path B differences: `worker_done`, `ask`, heartbeat all work identically; but `worker-release` is a no-op and `worker-stop` does not own the process — the coordinator closes the terminal itself with `orca terminal close --terminal $H --json` after the last attempt on it. Re-attaching a follow-up task to the same terminal is a plain second `dispatch --task <next> --to $H --inject`.

If `dispatch --inject` returns `runtime_unavailable` with a `recovery.retryCommand`, run that exact command once (it carries `--retry-request <id>`); the mutation may already have taken effect.

## 3. Startup blockers and how `install.sh` clears them

A worker that shows a modal in its TUI is reported by Orca as `agent_prompt_blocked` / `blockedReason` on `terminal wait`, and `terminal send` is refused too. Known modals:

| blockedReason | cause | fix (done by `install.sh`, or manually) |
|---|---|---|
| `codex-update-prompt` | Codex "Update available" | keep Codex current: `brew upgrade --cask codex` |
| `codex-hooks-review-prompt` | Orca's 8 hooks in `~/.codex/hooks.json` untrusted | press **2. Trust all and continue** once in any Codex terminal inside Orca (persists in `[hooks.state]`), OR use Path B with `--dangerously-bypass-hook-trust`. `bypass_hook_trust = true` in config.toml does NOT work. |
| Antigravity "Do you trust this folder?" | repo not in `trustedWorkspaces` | add the exact repo path to `~/.gemini/antigravity-cli/settings.json` → `trustedWorkspaces` (a parent directory does not cover it) |
| Claude Code trust dialog | first run in the folder | `~/.claude.json` → `projects["<repo>"].hasTrustDialogAccepted = true` |

Before the first dispatch of a session run `install.sh --check <repo>` (read-only) and fix what it reports; a blocked worker costs a dispatch attempt and, after three, the task.

## 4. Waiting

```bash
orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 540000 --json
```

- Rolling windows; a timeout or `{count:0}` is a checkpoint, not a failure. Coding turns run 15–60 min; a Pro planning turn 10–30 min.
- The command prints `{"_keepalive":true,...}` heartbeat lines before the final JSON — parse only the last line.
- From a Codex coordinator the blocking wait is safe: a 5-minute wait was verified not to be killed by the tool harness; use ≤ 9-minute windows anyway.
- Process **every** message in a Delivery, then `check --ack <delivery_id> --wait ...` for the next one. Reply to `question` messages with `orca orchestration reply --id <msg_id> --body "<answer>" --json` before acknowledging.
- Liveness checkpoint when a window returns nothing: `orca orchestration worker-show --dispatch <id> --json`, or `orca terminal read --terminal <handle> --json`. Activity means alive, not done — never stop a worker for being slow.

`worker_done` fields the protocol reads: `subject` (the verdict token), `payload.outcome` (`succeeded|failed`), `payload.reportPath` (the report file — the coordinator reads only what SKILL.md allows), `payload.filesModified`.

## 5. After a `worker_done`

Decide the terminal's fate **before** acknowledging the Delivery:

- Immediate follow-up on the same agent (fix round, NEEDS_CONTEXT answer, gate-fix round): Path A → `worker-start --task <next> --terminal <handle>`; Path B → `dispatch --task <next> --to <handle> --inject`.
- Otherwise: Path A → `orca orchestration worker-release --dispatch <id> --json` (closes the terminal, archives the transcript); Path B → `orca terminal close --terminal <handle> --json`.
- Keep a terminal alive only when the user asked to inspect it (`worker-retain` for Path A).

Never leave a settled worker open "to look at later" — `worker-read --dispatch <id>` still works after release.

**Read the release result.** `worker-release` can answer `"state": "retained", "reason": "user_takeover", "processAction": "none"` — Orca refuses to kill a terminal the user has focused or typed into during the run (observed 2026-09-01 on two Claude reviewers the user had opened in the UI). That is not a failure, but the terminal is still open: follow up with `orca terminal close --terminal <handle> --json` (handle = `worker-show --dispatch <id>` → `agent_terminal_handle`) once its `worker_done` is processed. Any other non-`released` state → treat as "still open" and close explicitly too.

## 6. Failure handling

- `worker-show` says `failed`/`stopped` → `worker-start --task <task> --retry-of <dispatch_id> ...` with explicit placement (Path A) or a fresh Path B terminal; retry does not inherit placement.
- `outcome_unknown` → `worker-stop --dispatch <id>` then inspect; or `worker-abandon` accepting that resources may linger.
- A `worker_done --outcome failed` whose body names quota / rate limit / auth / launch problems is an **availability** failure → cascade per `roles.md`. Any other failed outcome is a protocol verdict (`BLOCKED`, `NEEDS_*`, `BLOCKED`) → handle per SKILL.md.

## 7. Bridge preflight (Pro planner)

Before choosing the `strong` planning profile:

```bash
pgrep -f "codex-chatgpt-web.*cli.js serve" >/dev/null && echo bridge-up || echo bridge-down
# optional, ~2 s: full self-check of the bridge (browser login, proxy, tunnel, connector)
V=$(ls -d ~/.codex-chatgpt-web/versions/*-darwin-arm64 | tail -1); "$V/runtime/bun" "$V/app/cli.js" status | tail -1   # → "Doctor result: ready"
```

Bridge down or doctor not `ready` → `standard` profile without asking. Bridge up but the Pro attempt fails twice (see roles.md; the retry is a fresh terminal) → `standard`, tell the user in one line.

Post-mortem of a Pro failure (read-only, allowed for the coordinator): `~/Library/Application Support/Codex Web GPT/logs/launcher.jsonl` — `browser.turn_ended` with `status`, and `broker claim received (... valid=false, retiredTurn=<trace>)` lines mark the token race from `roles.md`; `~/.codex-chatgpt-web/diagnostics/browser-turns/<trace>-*/` holds the per-checkpoint DOM captures.

## 8. Cheat-sheet: role → recipe

| role | path | agent / argv |
|---|---|---|
| plan-writer (Pro) | B | `codex ... -m chatgpt-web/pro` |
| plan-writer (Opus) / plan-reviser / review-primary / review-final / diagnosis / frontend-implementer | A | `--agent claude --model <opus|fable|sonnet> --effort xhigh` (sonnet tweak: `--effort medium`) |
| plan-reviewer r1 (Fable) | A | `--agent claude --model fable --effort xhigh` |
| plan-reviewer (Sol) / review-control | A (hooks trusted) or B | `--agent codex --model gpt-5.6-sol --effort max|xhigh` |
| implementer (Flash) / gate / synthesizer / quickfix | B | `agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions` |
| implementer fallback (Luna) / escalation (Terra) | A or B | `--agent codex --model gpt-5.6-luna|gpt-5.6-terra --effort max` |

## 9. Windows (native, no WSL)

Installed with `install.ps1` (see `docs/install-windows.md`). Differences from macOS that the coordinator must apply:

- Your shell is PowerShell (Windows PowerShell 5.1 or pwsh 7 — both work). Every workspace script has a native PowerShell port: `& "$env:ORCA_DEV_HOME\bin\<script>.ps1" …` (`sdd-workspace.ps1`, `review-package.ps1`, `verify-gate.ps1`, `wait-agent-ready.ps1`), same arguments, exit codes and output as the bash originals. Never call `bash` or the extension-less originals on Windows: `bash` there is the WSL launcher in `System32`. `verify-gate.ps1` runs the plan's `verify:` commands in a child PowerShell, so write them as PowerShell / native commands (`pytest -q`, `npm test`), not as bash one-liners. Paths you write into prompts must be absolute Windows paths (`C:\…`) because the workers run native CLIs.
- `orca orchestration check --types "worker_done,escalation,question"` — quote comma-separated lists in PowerShell. Where a recipe pipes `--json` into `jq -r .result.terminal.handle`, use `(… --json | ConvertFrom-Json).result.terminal.handle` instead.
- Path A works unchanged (`worker-start --agent claude|codex`). Path B argv is the same text; Antigravity (`agy`) on native Windows is unverified — if `agy` is missing, the implementer cascade starts at Luna (roles.md) and the gate/synthesizer fallbacks apply; say so once.
- The skill is linked into `%USERPROFILE%\.codex\skills\orca-dev` (symlink or junction); always locate `bin\` through `ORCA_DEV_HOME` (set by `install.ps1`), never by resolving the skill link.
- The GPT Pro bridge (`codex-chatgpt-web`) is macOS-only: the planning profile is always `standard`.
- Trust files live in the same places under `%USERPROFILE%` (`.claude.json`, `.gemini\antigravity-cli\settings.json`, `.codex\config.toml`); Claude Code keys `projects[]` with forward slashes (`C:/repo`), Antigravity's `trustedWorkspaces` with backslashes — `install.ps1` handles both. `install.ps1 -Repo <path>` handles the repo and its git worktrees; a parallel track's child worktree still needs `install.ps1 -Repo <track-path>` before the first dispatch (same rule as macOS).


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
- Reuse the same agent for the next attempt (fix rounds, `NEEDS_CONTEXT`, Terra escalation on a Luna thread): `worker-start --task <next_task> --terminal <handle> --json` — read the handle from `worker-show --dispatch <id> --json` → `worker.agent_terminal_handle`. `--model/--effort` cannot be combined with `--terminal`.
- New worktree for a parallel track: `--worktree new-child --name <slug>-<phase> --setup run` instead of `current`.

### Path B — custom argv + `dispatch --inject` (unsupervised lifecycle)

Required when the agent needs flags Orca cannot pass, or a blocker below is not yet cleared:

```bash
H=$(orca terminal create --worktree active --title "<role>-<phase>" --command "<argv>" --json | jq -r .result.terminal.handle)
orca terminal wait --terminal $H --for tui-idle --timeout-ms 180000 --json
orca orchestration dispatch --task <task_id> --to $H --inject --json
```

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

- Immediate follow-up on the same agent (fix round, NEEDS_CONTEXT, Terra on Luna's thread): Path A → `worker-start --task <next> --terminal <handle>`; Path B → `dispatch --task <next> --to <handle> --inject`.
- Otherwise: Path A → `orca orchestration worker-release --dispatch <id> --json` (closes the terminal, archives the transcript); Path B → `orca terminal close --terminal <handle> --json`.
- Keep a terminal alive only when the user asked to inspect it (`worker-retain` for Path A).

Never leave a settled worker open "to look at later" — `worker-read --dispatch <id>` still works after release.

## 6. Failure handling

- `worker-show` says `failed`/`stopped` → `worker-start --task <task> --retry-of <dispatch_id> ...` with explicit placement (Path A) or a fresh Path B terminal; retry does not inherit placement.
- `outcome_unknown` → `worker-stop --dispatch <id>` then inspect; or `worker-abandon` accepting that resources may linger.
- A `worker_done --outcome failed` whose body names quota / rate limit / auth / launch problems is an **availability** failure → cascade per `roles.md`. Any other failed outcome is a protocol verdict (`BLOCKED`, `NEEDS_*`, `PLAN_FAIL`) → handle per SKILL.md.

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
| plan-writer (Opus) / plan-reviser / review-primary / review-final / diagnosis / frontend-implementer | A | `--agent claude --model <opus|fable|sonnet> --effort xhigh` |
| plan-reviewer r1 (Fable) | A | `--agent claude --model fable --effort xhigh` |
| plan-reviewer (Sol) / review-control | A (hooks trusted) or B | `--agent codex --model gpt-5.6-sol --effort max|xhigh` |
| implementer (Flash) / gate / synthesizer / quickfix | B | `agy --model gemini-3.7-flash-high --effort high --dangerously-skip-permissions` |
| implementer fallback (Luna) / escalation (Terra) | A or B | `--agent codex --model gpt-5.6-luna|gpt-5.6-terra --effort max` |

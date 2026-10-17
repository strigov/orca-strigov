# orca-dev — launching, waiting for and closing workers

Mechanics only; who runs where is in `roles.md`. `<plugin>` is the plugin root (the folder with `bin/` and `skills/`). Helper: `python3 <plugin>/bin/orca_dev.py` (Windows: `py -3 <plugin>\bin\orca_dev.py`).

## Path B — every fresh launch

One command per worker, after `orca_dev.py brief` printed the `task_id`:

`python3 <plugin>/bin/orca_dev.py spawn --agent <agy|codex|claude> --model <m> [--effort <e>] --title <slug>/<role>-<phase> --task <task_id>`

It runs `orca terminal create --worktree active --title <t> --command <argv> --json` → `orca terminal wait --terminal <h> --for tui-idle --timeout-ms 180000 --json` → `orca_dev.py ready <h> <agent> <timeout>` (required: `tui-idle` fires on the shell prompt before the agent draws its TUI) → `orca orchestration dispatch --task <task_id> --to <h> --inject --retry-request <uuid> --json`. Why Path B for everything: Codex needs `-c features.multi_agent=false` and the bypass flags that `worker-start` cannot pass; fresh Claude via `worker-start` lost the prompt in 3 of 6 starts (smoke 2026-09-26); one recipe for all agents is simpler. The native guide allows this through `references/low-level-topology.md`.

Argv built by `spawn` (source of truth; edit together with `AGENTS`/`build_argv` in `bin/orca_dev.py`):

| agent | argv |
|---|---|
| Antigravity | `agy --model gemini-3.8-flash-high --dangerously-skip-permissions` (no `--effort`: the level is in the id) |
| Codex | `codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m <model> -c model_reasoning_effort=<lvl> -c features.multi_agent=false` (codex-cli 0.163.0) |
| Claude | `claude --dangerously-skip-permissions --model <opus|sonnet> --effort <lvl>` |

`--command` is built for the host OS (`shlex.join` on POSIX, `subprocess.list2cmdline` on Windows); never type it yourself.

`spawn` prints one JSON line `{stage, handle, task_id, dispatch_id, request_id, dismissed, agent, screen, error}`:

| exit | meaning | coordinator action |
|---|---|---|
| 0 | dispatched (`stage: done`) | wait with `check --wait` |
| 1 | agent not ready in time (`handle` set) | `orca_dev.py close <h>`, one more `spawn`; a second 1 in a row = unavailable → roles.md fallback |
| 2 | usage error | fix the command |
| 3 | `terminal create` failed, nothing delivered | unavailable at once → roles.md fallback |
| 4 | `dispatch` failed or unknown (`handle`, `request_id` set) | not unavailability: keep the terminal and the model, see "Unknown dispatch" |
| 5 | unknown modal (`screen` set) | close, then SKILL.md failures (code 5/6 rule) |
| 6 | login screen (`agent` set) | close, then SKILL.md failures; not a fix round |

Path A (`orca orchestration worker-start --task <id> --worktree current --terminal <h> --json`, no `--model/--effort`) is only for reusing a live terminal Orca started. A follow-up into a live Path B terminal (fix round, revision): `orca orchestration dispatch --task <next> --to <h> --inject --json`. Author revisions run at `high` in the author's terminal: before the first revision send `orca terminal send --terminal <h> --text "/effort high" --enter --json` once (Claude Code `/effort`), then dispatch.

## Agent start

`ready` polls `orca terminal read --screen --limit 80 --json` every 2 s (stream read when the host cannot render; then only the last 25 lines count) and finishes with one `tui-idle` wait.

| agent | ready marker | busy (wait silently) | login screen (exit 6) | timeout | login command |
|---|---|---|---|---|---|
| agy | `Antigravity` | `not signed in` (keyring race in the first ~20 s) | `Select login method` after 20 s | 180 s | `agy`, then log in interactively |
| codex | `Ask Codex` | `Starting MCP servers` | `Sign in with ChatGPT` | 120 s | `codex login` |
| claude | `Claude Code` | — | `/login` | 90 s | `claude`, then `/login` |

Known modals (`spawn` dismisses them with `orca terminal send` and lists them in `dismissed`; keys are pinned in the smoke run against real screens):

| id | agent | screen marker / `blockedReason` | keys |
|---|---|---|---|
| `codex-update-prompt` | codex | "Update available" / `codex-update-prompt`, `agent-update-prompt` | `2`, then Enter (skip) |
| `codex-hooks-review-prompt` | codex | "Hooks need review" / `codex-hooks-review-prompt`, `agent-hooks-review-prompt` | `2`, then Enter (trust all) |
| `codex-trust-folder` | codex | "trust this folder?" / `agent-trust-workspace`, `codex-trust-workspace` | Enter (Trust and continue; 0.163.0, smoke S4/S5) |
| `claude-trust-folder` | claude | "trust this folder" / `agent-trust-workspace`, `codex-trust-workspace` | Down (`\x1b[B`), then Enter (Yes; default is No, exit: 2.1.301 macOS, 2.1.302 Windows) |
| `agy-trust-folder` | agy | "trust this folder" / `agent-trust-workspace`, `codex-trust-workspace` | Enter (yes) |

Any other `blockedReason`, a refused `terminal send`, or a modal still shown after 3 dismissals → exit 5. `install.py --repo` prevents the three trust dialogs; without it Codex shows `Ask Codex` about 8 s before its trust dialog, and `spawn` may dispatch into it.

## Waiting

`orca orchestration check --wait --types "worker_done,escalation,question" --timeout-ms 900000 --json`; `question` → `orca orchestration reply --id <msg> --body <answer> --json`; `worker_done` → accept (SKILL.md) → `check --ack <delivery_id>`.

Unknown dispatch (spawn exit 4): `orca orchestration request-show --request <request_id> --json` and `orca orchestration dispatch-show --task <task_id> --json`. `completed`, or a Dispatch with status `pending`/`dispatched`/`completed` → delivered, wait. `absent` and no Dispatch or a `failed` one (`last_failure` names the send error; the Task is `ready` again) → retry once: `orca orchestration dispatch --task <task_id> --to <h> --inject --retry-request <request_id> --json`. A retry that leaves a `failed` Dispatch again, or `circuit_broken` → one question at once. `pending`, contradicting answers or an unknown retry → leave the terminal, wait by the silence rules, then one question.

Orphaned terminals: before any repeated dispatch run `orca terminal show --terminal <h> --json`; `orphaned: true` only means "do not send here", not that the process exited. A settled worker there → close it, start a new terminal.

## Closing

- Path B terminal (created by `spawn`): `python3 <plugin>/bin/orca_dev.py close <h>` — exit 0 when the receipt has `ptyKilled: true` or the handle is gone from `orca terminal list --worktree current --json`; exit 1 = not confirmed (do not repeat; one line in the final report).
- Path A terminal: `orca orchestration worker-release --dispatch <id> --json`; `retained` in the answer → `orca_dev.py close <h>`.
- Start/resume cleanup: `orca orchestration worker-list --run <orca_run> --json` without a state filter (Path B rows are `retained`) → close every terminal whose Task is settled with no live Dispatch; plus `orca terminal list --worktree current --json` rows titled `<slug>/…` with no live Dispatch. Never touch other Runs, the coordinator's terminal, or terminals without the `<slug>/` prefix.

If Orca/Codex/agy change CLI flags, edit this file and `bin/orca_dev.py` together; `install.py` prints the versions.

## Windows

- Coordinator shell: PowerShell 5.1/7. Helper: `py -3 <plugin>\bin\orca_dev.py <subcommand> …`.
- One command = one process; check `$LASTEXITCODE` before the next one. No `$(...)`, `&&`, `mktemp`, heredoc or quote escaping: `orca_dev.py` does the fragile parts.
- Never call `bash` (it may be the WSL launcher). Give workers absolute Windows paths.
- `agy` on native Windows is unverified: if it is not on PATH, the implementer starts on the Luna fallback with one line to the user.

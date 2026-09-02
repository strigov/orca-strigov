# orca-strigov — orca-dev

A multi-model development protocol for the [Orca](https://orca.dev) ADE. **Codex coordinates**, everything else runs as Orca worker terminals on whichever agent and model fits the role (`skills/orca-dev/roles.md` is authoritative; this table is a summary):

| role | agent / model |
|---|---|
| plan (round 1) | GPT Pro via the `codex-chatgpt-web` bridge → reviewed by Claude Opus xhigh |
| plan revisions / fallback | Claude Opus xhigh → reviewed by Codex Sol max |
| implementation | Gemini 3.7 Flash High (Antigravity CLI) → Codex Luna max fallback → Codex Terra max escalation |
| frontend phases | Claude Opus xhigh (new UI) / Sonnet (tweaks) |
| verification gate | `bin/verify-gate` script; a Gemini Flash worker only when the script has no commands or cannot classify |
| code review | Claude Opus xhigh (Fable on risky phases and in the last fused round), Codex Sol xhigh control review — reviewers swap families when a Codex or Claude model wrote the code |
| final branch review | Claude Opus xhigh |

It is a port of [`superpowers-strigov-ver`](https://github.com/strigov/strigov-cc-plugins) from Claude Code to Orca: the same phased plans, authorization ledger, bounded review loops and family rule (writer ≠ reviewer family), with Orca's `worker-start` / `worker_done` replacing two ad-hoc transports.

## Install

**macOS** (also Linux / WSL2):

```bash
git clone git@github.com:strigov/orca-strigov.git ~/orca-strigov && cd ~/orca-strigov
./install.sh                       # links skills/orca-dev into ~/.codex/skills, sets nothing else
./install.sh --repo /path/to/repo  # pre-trusts the repo and its git worktrees for Claude Code and Antigravity; exit 1 on any WARN
./install.sh --check /path/to/repo # read-only report
```

**Windows** (native, PowerShell — see `docs/install-windows.md` for prerequisites and the WSL2 alternative):

```powershell
git clone git@github.com:strigov/orca-strigov.git $HOME\orca-strigov; cd $HOME\orca-strigov
.\install.ps1                              # links the skill (symlink or junction), sets ORCA_DEV_HOME, checks CLIs and hooks
.\install.ps1 -Repo C:\path\to\repo       # pre-trusts the repo and its git worktrees
.\install.ps1 -Check C:\path\to\repo      # read-only report; exit 1 on any WARN
```

On Windows the workspace scripts run as native PowerShell ports (`bin\*.ps1`, PowerShell 5.1+; no bash, python3 or jq); the GPT Pro bridge has a Windows build too, so the `strong` planning profile is available whenever its daemon is running (`orca-recipes.md` §7 has the Windows preflight).

Requirements: Orca ≥ 1.4.193 with orchestration enabled, `codex`, `claude`, `agy` (Antigravity CLI; unverified on native Windows — without it the implementer cascade starts at Codex Luna), `git`, `jq`, `python3`. The Pro planner additionally needs the `codex-chatgpt-web` launcher running in full-harness mode; without it the protocol uses the Opus → Sol planning pair automatically.

## Use

Open a Codex terminal in the target repo inside Orca and type `$orca-dev <task>` (or just ask for an implementation — the skill triggers on "implement / реализуй / запили"). The coordinator writes nothing but plans, ledgers and commits; watch the workers appear as terminals in the Orca sidebar.

## Layout

```
skills/orca-dev/SKILL.md        coordinator protocol
skills/orca-dev/roles.md        the only file that names models
skills/orca-dev/orca-recipes.md launch paths, blockers, waiting, cleanup
skills/orca-dev/prompts/        one template per role
bin/verify-gate                 deterministic gate from the plan's `verify:` list
bin/review-package              reviewer package: commits + stat + -U10 diff
bin/sdd-workspace               per-plan scratch workspace
bin/wait-agent-ready            waits for an agent's TUI before an inject (mandatory in Path B)
bin/*.ps1                       native PowerShell ports of the four scripts for Windows (same CLI, exit codes, output)
install.sh / install.ps1        macOS (Linux/WSL2) and Windows installers: link the skill, pre-trust repos, report blockers
docs/spikes/                    what was measured before this was designed
```

## Status

Three end-to-end smoke runs on `spikes/fixture` (2026-09-01/02) exercised the full protocol: sequential phases, a parallel group with two Orca child worktrees, fix rounds, the Flash → Luna availability cascade, the strong (GPT Pro) and standard planners, the planner's blocked-on-missing-input question, synthesis and the final review — see `docs/smoke-runs.md`. Not yet observed in a real run: an implementer `BLOCKED` → diagnosis → reasoning escalation. A 2026-09-02 audit of the protocol text, prompts and scripts (`docs/audit-2026-09-02.md`) was applied on top. Empirical basis and startup blockers: `docs/spikes/RESULTS.md`.

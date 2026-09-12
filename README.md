# orca-strigov — orca-dev

A multi-model development protocol for the [Orca](https://orca.dev) ADE. **Codex coordinates**, and each specialized role runs as an Orca worker terminal (`skills/orca-dev/roles.md` is the single authoritative source for agent, model, effort, and fallback matrices):

| Role | Primary Responsibility |
|---|---|
| `coordinator` | Orchestrates the entire pipeline, dispatches tasks, manages git commits |
| `plan-writer` / `plan-reviser` | Researches codebase, writes and revises multi-phase implementation plans |
| `plan-reviewer` | Independent review of plans for correctness, consistency, and simplicity |
| `implementer` | Implements phase deliverables and tests |
| `frontend-implementer` | Implements UI and design deliverables |
| `gate` | Mechanical verification and test execution |
| `review-primary` / `review-control` | Two-stage independent review of phase implementations |
| `review-final` | Whole-branch architectural and integration review |
| `diagnosis` | Investigates blockers and stalled loops |
| `synthesizer` | Consolidates review findings into documentation |
| `quickfix` | Handles trivial single-file fixes without planning |

It is a port of [`superpowers-strigov-ver`](https://github.com/strigov/strigov-cc-plugins) from Claude Code to Orca: the same phased plans, authorization ledger, bounded review loops and family rule (writer ≠ reviewer family), with Orca's `worker-start` / `worker_done` replacing two ad-hoc transports.

## Install

**macOS** (also Linux / WSL2):

```bash
git clone git@github.com:strigov/orca-strigov.git ~/orca-strigov && cd ~/orca-strigov
./install.sh                       # links skills/orca-dev into ~/.codex/skills, checks prerequisites
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

On Windows the workspace scripts run as native PowerShell ports (`bin\*.ps1`, PowerShell 5.1+; no bash, python3 or jq). The ChatGPT Pro web bridge is supported as an explicit opt-in planner (`--planner pro`) when configured and running (`orca-recipes.md` §7 has the Windows preflight).

Runtime requirements: Bash 3.2+, Python 3.9+ (stdlib) and Git on POSIX; PowerShell 5.1 or 7 and Git on native Windows. Keep `bin/lib/` with the entry points. Python 3.9+ is also the test driver on Windows; it is not a dependency of the native `.ps1` helpers. `jq` is used only by optional recipe examples. Plans can declare additional tools for their own checks; skill validation uses the installed `quick_validate.py` and PyYAML.

The model workflow additionally needs Orca with orchestration enabled and the CLIs for the selected routes in [roles.md](skills/orca-dev/roles.md). At startup use `orca skills get orchestration` from the executable serving the Run; old version numbers or receipts do not certify the current lifecycle. The bridge is opt-in. Installation reports missing capabilities with a nonzero exit; that is an incomplete setup even if other checks pass.

Install replaces a stale or dangling **link only**, preserving its old target. An ordinary existing directory or a write path through another link is refused. `--check` / `-Check` is read-only. On Windows, inspect skill target, User `ORCA_DEV_HOME`, and Process `ORCA_DEV_HOME` separately: an old Orca process can retain a previous checkout after installation. Restart Orca, or explicitly select the authorized checkout in that process before launching workers; do not reinstall merely to silence inherited environment. Neither installer edits unrelated settings or shell profiles, registers repos, or upgrades CLIs automatically.

## Use

Open a Codex terminal in the target repo inside Orca and type `$orca-dev <task>` (or just ask for an implementation — the skill triggers on "implement / реализуй / запили"). The coordinator writes nothing but plans, ledgers and commits; watch the workers appear as terminals in the Orca sidebar.

## Layout

```
skills/orca-dev/SKILL.md        coordinator protocol
skills/orca-dev/roles.md        the only file that names models
skills/orca-dev/orca-recipes.md launch paths, blockers, waiting, cleanup
skills/orca-dev/prompts/        one template per role
bin/verify-gate                 deterministic gate from the plan's `verify:` list
bin/run-check                   owned command: run SPEC_JSON / wait RUN_DIR / cancel RUN_DIR OWNER_JSON
bin/review-package              complete diff, bounded parts and hashed provenance manifest
bin/protocol-state              validate INPUT_JSON [RESUME_OUT], without dispatch or Git writes
bin/lib/                       platform-specific runtime dependencies shipped with the entry points
bin/sdd-workspace               per-plan scratch workspace
bin/wait-agent-ready            waits for an agent's TUI before an inject (mandatory in Path B)
bin/*.ps1                       native PowerShell ports of all six entry points
install.sh / install.ps1        macOS (Linux/WSL2) and Windows installers: link the skill, pre-trust repos, report blockers
docs/spikes/                    what was measured before this was designed
```

## Status

Current commands, directed platform results and pending independent final evidence are in [controlled-pipeline-validation.md](docs/controlled-pipeline-validation.md). Historical [smoke runs](docs/smoke-runs.md) and [startup observations](docs/spikes/RESULTS.md) describe real model execution; they do not certify the new helpers.

Legacy positional gate calls and string `verify:` lists remain supported. New declarations use the limited JSON-in-YAML form in [runtime-contracts.md](skills/orca-dev/runtime-contracts.md); commands are explicit for the selected shell:

```bash
bin/verify-gate docs/plans/example.md "$BASE" --phase F1 --checkpoint integration
# Native Windows: & "$env:ORCA_DEV_HOME/bin/verify-gate.ps1" <plan> <base> --phase F1 --checkpoint integration
```

Checkpoints are `directed`, `integration`, and `final`. A result binds the actual source, inputs, environment and complete logs; missing tools, stale evidence, incomplete review coverage and an exhausted deadline cannot authorize completion. Full logs, resume records and review packages live in the existing plan workspace. See the single runtime contract for JSON interfaces, report binding, replay and commit barriers.

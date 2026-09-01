# orca-strigov — agent instructions

This repository ships the **orca-dev** skill: a multi-model development protocol for the Orca ADE where **Codex is the coordinator** and every other role (plan writer, reviewers, implementers, gate) runs as an Orca worker terminal on the agent/model chosen in `skills/orca-dev/roles.md`.

When a user in any repository asks for an implementation ("реализуй", "запили", "implement", "build this feature") and this skill is installed, load `~/.codex/skills/orca-dev/SKILL.md` and follow it. The skill's two hard rules apply to the coordinator regardless of model: it never writes production code and never researches the codebase itself — it dispatches.

Layout:

- `skills/orca-dev/SKILL.md` — the coordinator protocol
- `skills/orca-dev/roles.md` — role → agent/model/effort matrix, cascades, family rule
- `skills/orca-dev/orca-recipes.md` — launch, wait, release, blocker fixes
- `skills/orca-dev/prompts/` — one template per role
- `bin/` — `review-package`, `sdd-workspace`, `verify-gate`, `wait-agent-ready` (bash, no model)
- `install.sh` (macOS / Linux / WSL2) and `install.ps1` (native Windows) — link the skill into `~/.codex/skills`, pre-trust a repo and its worktrees for Claude/Antigravity, report blockers; Windows notes in `docs/install-windows.md`
- `docs/spikes/` — empirical findings the protocol is built on

Working on this repo itself: plain edits are fine (it is documentation and shell); keep `roles.md` the only place that names models.

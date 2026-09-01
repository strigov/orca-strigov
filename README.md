# orca-strigov — orca-dev

A multi-model development protocol for the [Orca](https://orca.dev) ADE. **Codex coordinates**, everything else runs as Orca worker terminals on whichever agent and model fits the role:

| role | agent / model |
|---|---|
| plan (round 1) | GPT Pro via the `codex-chatgpt-web` bridge → reviewed by Claude Fable max |
| plan revisions / fallback | Claude Opus max → reviewed by Codex Sol max |
| implementation | Gemini 3.7 Flash High (Antigravity CLI) → Codex Luna max fallback → Codex Terra max escalation |
| frontend phases | Claude Opus max (new UI) / Sonnet (tweaks) |
| verification gate | `bin/verify-gate` script → Gemini Flash only when red |
| code review | Claude Opus max (Fable on risky phases), Codex Sol xhigh control review |
| final branch review | Claude Opus max |

It is a port of [`superpowers-strigov-ver`](https://github.com/strigov/strigov-cc-plugins) from Claude Code to Orca: the same phased plans, authorization ledger, bounded review loops and family rule (writer ≠ reviewer family), with Orca's `worker-start` / `worker_done` replacing two ad-hoc transports.

## Install

```bash
git clone <this repo> ~/orca-strigov && cd ~/orca-strigov
./install.sh                       # links skills/orca-dev into ~/.codex/skills
./install.sh --repo /path/to/repo  # pre-trusts the repo for Claude Code and Antigravity, reports blockers
```

Requirements: Orca ≥ 1.4.193 with orchestration enabled, `codex`, `claude`, `agy` (Antigravity CLI), `jq`, `python3`. The Pro planner additionally needs the `codex-chatgpt-web` launcher running in full-harness mode; without it the protocol uses the Opus → Sol planning pair automatically.

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
docs/spikes/                    what was measured before this was designed
```

## Status

Phase 1 — core protocol, sequential phases, role matrix. Parallel groups and Step 5 are specified in `SKILL.md` but not yet exercised end-to-end. See `docs/spikes/RESULTS.md` for the empirical basis and known startup blockers.

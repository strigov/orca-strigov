<p align="center">
  <a href="./README.md">English</a> · <a href="./README.ru.md">Русский</a>
</p>

<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="orca-strigov: the coordinator hands code, checks and reviews to separate agents">
</p>

# orca-strigov 2.0

A thin Codex and Claude Code plugin over native [Orca](https://orca.dev) orchestration. One skill, `orca-dev`, runs spec-driven development through supervised Orca workers: spec → plan → TDD phases → double review (Opus, then Astra) → commit, with fixed model presets. No hooks, receipts or state machine: every cap or failure ends in a declared fallback or one question to you.

Design and acceptance criteria: [docs/specs/2026-10-14-orca-dev-v2-design.md](docs/specs/2026-10-14-orca-dev-v2-design.md).

## Install

Needs Orca 1.4.224+, Python 3.10+ (`python3`; Windows `py -3`), git and logged-in `codex`, `claude` and `agy`.

1. Native Orca skills: `orca skills install --skill orchestration --skill orca-cli --agent codex,claude-code`
2. The plugin: `git clone https://github.com/strigov/orca-strigov.git`
3. Checks and project trust: `python3 orca-strigov/install.py --repo /path/to/project` (Windows: `py -3 orca-strigov\install.py --repo C:\path\to\project`). It writes only `~/.claude.json`, `~/.gemini/antigravity-cli/settings.json` and `~/.codex/config.toml`, deletes nothing and lists old copies.
4. Codex: ask Codex "Use plugin-creator to install the plugin from /abs/path/orca-strigov into my personal marketplace", then `codex plugin add orca-strigov@personal`; `codex plugin list` shows `2.0.0`. Start a new session.
5. Claude Code: `claude --plugin-dir /abs/path/orca-strigov`, or `/plugin install orca-strigov@<your local marketplace>`.

## Use

- Codex: `$orca-dev add a --version flag`
- Claude Code: `/orca-strigov:orca-dev add a --version flag`

Small tasks (at most 2 code files, no schema, security or public API change, merges of accepted branches) take the quick path: implementer → checks → Opus review → Astra review → commit. Everything else: spec (you answer «ок») → plan → phases → final review. To resume, name the plan or its slug.

## Roles

| role | model |
|---|---|
| spec and plan: write / revise | claude `opus` `xhigh` / `high` |
| spec and plan review | codex `gpt-6-astra` `xhigh` |
| implementer (backend, quick path) | agy `gemini-3.8-flash-high`; fallback codex `gpt-6-luna` `max` |
| implementer (`hard: true`) and the one escalation | codex `gpt-6.1-sol` `high` |
| implementer (frontend) | claude `opus` `high`, or `sonnet` `medium` for ≤2 files |
| phase review 1 and final review | claude `opus` `high` |
| phase review 2 | codex `gpt-6-astra` `high` |

Details: [roles.md](skills/orca-dev/roles.md). Launch mechanics: [launch.md](skills/orca-dev/launch.md).

## Layout

```text
skills/orca-dev/   SKILL.md, roles.md, launch.md, prompts/ (11 briefs)
bin/orca_dev.py    brief, spawn, ready, close
install.py         checks, repo trust, old-copy warnings
tests/             python3 -m unittest discover tests
```

## Upgrading from 1.x

Hooks, receipts, ledgers and the vendored Orca skills are gone. Delete the old copies that `install.py` lists, or answer `y` when the coordinator asks on its first run.

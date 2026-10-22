# orca-strigov: repository maintenance

This repository ships one self-contained skill (`skills/orca-dev`) for Codex and Claude Code, two helpers under `scripts/`, and one test file. Design and acceptance criteria: `docs/specs/2026-10-14-orca-dev-v2-design.md`.

A dispatched Orca worker follows its brief, not `orca-dev`. The coordinator skill runs only on an explicit `$orca-dev` or `/orca-dev`.

Sources of truth:

- Models, efforts and fallbacks: `skills/orca-dev/roles.md`.
- Agent argv, readiness markers, timeouts and modal keys: `skills/orca-dev/launch.md` together with `AGENTS`, `MODALS` and `build_argv` in `skills/orca-dev/scripts/orca_dev.py`. Change them in one commit.
- Version and harness rendering: `skills/orca-dev/scripts/install.py`; `release` and ZIPs are generated from one accepted source commit.
- Brief tokens: `PROMPT_TOKENS` in `tests/test_orca_dev.py` and the brief table in `SKILL.md`.

Rules:

- Python standard library only, with syntax that also runs on Python 3.9 (macOS system `python3`). Every `orca` call is an argument list; never `shell=True`.
- No hooks, no `.sh`/`.ps1` helpers, no state files, receipts or ledgers.
- Size limits: `SKILL.md` 18 KiB, `roles.md` 5 KiB, `launch.md` 8 KiB, each brief 2 KiB, each README 200 lines, this file 30 lines.
- The Codex build disables implicit invocation in `agents/openai.yaml`; Claude Code uses `disable-model-invocation: true`.
- Briefs use angle tokens only as `<UPPER_SNAKE>`.

Tests, no Orca needed: `python3 -m unittest discover tests` (Windows: `py -3 -m unittest discover tests`).

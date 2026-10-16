# orca-strigov: repository maintenance

This repository is the orca-strigov 2.0 plugin: one skill (`skills/orca-dev`), one helper (`bin/orca_dev.py`), `install.py` and one test file. Design and acceptance criteria: `docs/specs/2026-10-14-orca-dev-v2-design.md`.

A dispatched Orca worker follows its brief, not `orca-dev`. The coordinator skill runs only on an explicit `$orca-dev` or `/orca-strigov:orca-dev`.

Sources of truth:

- Models, efforts and fallbacks: `skills/orca-dev/roles.md`.
- Agent argv, readiness markers, timeouts and modal keys: `skills/orca-dev/launch.md` together with `AGENTS`, `MODALS` and `build_argv` in `bin/orca_dev.py`. Change them in one commit.
- Brief tokens: `PROMPT_TOKENS` in `tests/test_orca_dev.py` and the brief table in `SKILL.md`.

Rules:

- Python standard library only, with syntax that also runs on Python 3.9 (macOS system `python3`). Every `orca` call is an argument list; never `shell=True`.
- No hooks, no `.sh`/`.ps1` helpers, no state files, receipts or ledgers.
- Size limits: `SKILL.md` 18 KiB, `roles.md` 5 KiB, `launch.md` 8 KiB, each brief 2 KiB, each README 80 lines, this file 30 lines.
- Briefs use angle tokens only as `<UPPER_SNAKE>`.

Tests, no Orca needed: `python3 -m unittest discover tests` (Windows: `py -3 -m unittest discover tests`).

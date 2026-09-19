# Plugin conversion validation

Current run: 2026-09-19. Repository implementation validated on native macOS
(Darwin), `/bin/bash` 3.2.57, Python 3.14.6, Git 2.55.0. Read-only version probes:
Codex CLI 0.155.0, Orca 1.4.205. No global installation, native skill deletion,
live Bureau mutation, provider worker launch, commit or push was performed.

## Deterministic validation

- `python3 -B -m unittest discover -s tests -p test_coordinator_session.py -v`:
  final directed run **17 passed**, 8.466 seconds. Real C6/Git validation,
  synthetic hook/Orca inputs, isolated paths. Includes phase commit → F2,
  heartbeat, pending worker, compact/resume, explicit pause, source-edit denial,
  stale evidence, bounded continuation, quickfix and full-plan completion.
- `python3 -B -m unittest discover -s tests -p test_protocol_state.py -v`:
  **10 passed**, 10.049 seconds, then included in the integrated run below.
- `python3 -B -m unittest discover -s tests -p test_install.py -v`:
  **5 passed**, 2.519 seconds, with `ORCA_DEV_TEST_HOME`; real user configuration
  unchanged. Default plugin mode never creates the old skill link or writes
  User environment; explicit legacy compatibility and safe link handling remain.
- `python3 -B -m unittest discover -s tests -p test_delivery.py -v`:
  **2 passed**, 5.107 seconds, after the C6 regression correction below.
- `python3 -B -m unittest discover -s tests -p test_plugin.py -v`:
  **4 passed**, 0.202 seconds. Three skill entrypoints, complete local reference
  graph, native hook commands, extracted plugin helper running against owned Git
  with a nonexistent old installation and unchanged real user settings.
- `python3 -B -m unittest discover -s tests -p test_release_archive.py -v`:
  **3 passed**, 0.103 seconds. Complete plugin bundle, manifest identity/version,
  executable archive modes and reproducibility independent of checkout modes.

Integrated command:

```sh
env ORCA_TEST_SHELL=/bin/bash PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -v > /tmp/orca-plugin-verify.zMTAqu/integration-after-barrier-fix.log 2>&1
```

**PASS: 128 tests, 89.781 seconds, exit 0.** The earlier integrated run used the
same command with `integration.log`: 128 tests, 87.371 seconds, one failure in
`test_fix_gate_package_reports_commit_and_resume`. That fixture correctly
resumed a gate/review-accepted candidate without its original writer report;
the initial new-phase rule incorrectly regressed it to implementation. Both
backends now distinguish an untouched phase from downstream acceptance. The
delivery and C8 directed tests passed, then the integrated suite was replayed
because that runtime semantic correction changed the source. The first log was
preserved, not overwritten.

Additional actual checks, all exit 0:

```sh
python3 /Users/strigov/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
python3 /Users/strigov/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orca-cli
python3 /Users/strigov/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orchestration
python3 /Users/strigov/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orca-dev
/bin/bash -n install.sh
/bin/bash -n bin/coordinator-session
git diff --check
```

The plugin validator and changed orchestration entrypoint were checked again
after the final routing clarification. These validators prove format and local
structure, not model obedience. `plugin-creator` determined the self-contained
manifest/default hook discovery and non-destructive registration workflow;
`skill-creator` determined the concise routing, shared references and separate
behavioral check. The official [Codex hooks contract](https://learn.chatgpt.com/docs/hooks)
was checked for Stop continuation, UserPromptSubmit, native Windows commands and
Interrupt limits. A Stop reason becomes an automatic prompt; C8 hashes that
reason to avoid treating its own continuation as fresh user input.

## Independent instruction check

A separate agent read the candidate instructions and raw scenario facts without
this report, the regression tests or intended answers. It made no writes or real
Orca calls. Observed decisions:

| Scenario | Chosen behavior |
|---|---|
| Fresh implementation, no Run | Bind development coordinator, bootstrap and delegate |
| Compact, F1 committed, F2 pending | Restore facts and start the authorized F2, not finish/repeat F1 |
| Active writer, unverifiable liveness, empty inbox | Wait/reconcile existing Dispatch; no replacement writer |
| Authentic live worker preamble | Worker implementation, report and idle; no coordinator recursion |
| Explicit transfer, do not wait for results | Full handoff; end only after accepted transfer receipt |
| Status only, explicitly do not continue | Evidenced `user_pause`, incomplete status answer |
| Standalone README maintenance in this repository | Direct scoped edit and proportionate check |

No blocking contradiction was established in these seven scenarios. A proposed
Path B concern was rejected after reading the actual ownership conditions:
`unsupervised` without a resource row is not a proven `external` ownership
receipt. This is tabletop decision evidence, **not** a live Orca completion run.

## Changed areas and acceptance audit

- Plugin/discovery: `.codex-plugin/plugin.json`, `hooks/hooks.json`,
  `skills/orca-cli/`, `skills/orchestration/`, `THIRD_PARTY_NOTICES.md`.
- Development routing: `skills/orca-dev/SKILL.md`, coordinator core/start/
  planning/finish/session references, `orca-recipes.md`, `runtime-contracts.md`.
- Runtime: `bin/coordinator-session`, its `.ps1` counterpart and Python module;
  matching C6 new-phase barrier in `bin/lib/protocol_state.py` and
  `bin/protocol-state.ps1` (also safely dot-sourceable for the native guard).
- Packaging/setup: `bin/build-release.py`, `.github/workflows/release.yml`, both
  prerequisite installers; default mode does not reinstall a standalone skill.
- Tests: coordinator session/plugin tests, installer shared support/acceptance,
  release archive assertions. Existing delivery coverage caught the regression.
- Documentation: AGENTS, both READMEs, plugin installation/work plan/validation,
  Windows notes and the current-evidence pointer in runtime-platforms.

All three skills and ten native command references are bundled. Runtime policy
does not fetch stock skills; the only export commands are marked maintainer
provenance. One role contract governs all three. C8 preserves a bound role and
rejects a pending phase's Stop without dispatching or cancelling anything.
Shared native/POSIX fixtures and an extracted-bundle smoke cover the repository
implementation. Registration, trust and a new-thread live smoke remain rollout
steps, not hidden side effects of a code change.

## Not yet certified

Native Windows PowerShell 5.1/7, Linux and live provider/Orca plugin behavior
have not been executed for this change on this macOS host. The Windows helper
and shared tests are included; old reports are not current platform results.
`command -v pwsh` and `command -v powershell` found neither shell. The existing
CI matrix will select the native entrypoints, but no new CI run is claimed.
Hooks require installation, trust and a bound session. General non-development
coordination follows the shared policy, not the Git/C6 guard. Unbound mistakes,
user interruption, provider limits, arbitrary shell/MCP edits and dishonest
local state mutation cannot be prevented by this guard. See C8's explicit limits.

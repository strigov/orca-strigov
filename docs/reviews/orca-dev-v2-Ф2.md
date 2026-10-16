# Review: orca-dev-v2 — Ф2

- **Date**: 2026-10-16
- **Phase scope**: install.py (native skills, CLIs, repo trust, stale copies) + its tests
- **Base commit**: a01b6f10ad656a4804ee6c11022823922310cf06
- **Rounds**: 2 (Opus 4.1 + Codex Astra 4.2 control)
- **Outcome**: CLEAN

## Findings history

| id | reviewer | finding | decision | final status |
|----|----------|---------|----------|--------------|
| F1-CV1-Ф2 | opus-review | Ф2 suite on native Windows (Ran 50, OK skipped=1) handed to 4.2 as a live check (smoke S5) | ACCEPTED | verified-by-controller |
| F1-CV2-Ф2 | opus-review | Trust entries must suppress claude/agy trust dialogs, incl. Windows C:/ key (smoke S0/S2); raised by 4.2 as F1-B1-Ф2 | ACCEPTED | rejected (superseded by F1-B1-Ф2) |
| F1-D4-Ф2 | opus-review | is_strigov_copy substring match: tests fail when TMPDIR contains 'orca-strigov'; use path parts | DEFER | deferred |
| F1-D5-Ф2 | opus-review | ~/.claude.json read-modify-replace without Claude Code's lock; small lost-update window | DEFER | deferred |
| F1-N4-Ф2 | opus-review | OK trust set printed before symlink/write failure WARN | NIT | deferred |
| F1-N5-Ф2 | opus-review | --repo A --check B writes nothing for A | NIT | deferred |
| F1-N6-Ф2 | opus-review | orca --version OK ignores nonzero exit; agy trustedWorkspaces case-sensitive on Windows; update test checks only argv[1] | NIT | deferred |
| F1-B1-Ф2 | codex-control | Plan-mandated Windows backslash-only Claude trust key counted as trusted, but Claude Code normalizes keys to `/`, so the dialog is not suppressed (install.py:119). Fix: claude_keys returns only the `/` key; test_windows_keys and plan Contracts bullet / Ф2 code blocks updated | ACCEPTED | fixed |
| F1-D6-Ф2 | codex-control | run_main forces windows=False; Windows normalization not tested with a real file write | DEFER | deferred |
| F2-N1-Ф2 | opus-review | claude_keys docstring and any() loop still assume multiple keys; plan test-strategy wording "Windows key spellings" | NIT | deferred |

## Deferred

- F1-D4-Ф2: is_strigov_copy substring match breaks tests when TMPDIR contains 'orca-strigov'; use path parts.
- F1-D5-Ф2: ~/.claude.json read-modify-replace without Claude Code's lock (small lost-update window).
- F1-D6-Ф2: no test runs main with windows=True and a real file write; native Windows run is a separate live check.

## Nits (informational)

- F1-N4-Ф2: OK trust set printed before symlink/write failure WARN.
- F1-N5-Ф2: `--repo A --check B` writes nothing for A.
- F1-N6-Ф2: orca --version OK ignores nonzero exit; agy trustedWorkspaces case-sensitive on Windows; update test checks only argv[1].
- F2-N1-Ф2: install.py:108 claude_keys docstring and the any(... for k in keys) loop in trust_claude still assume several keys though only one is returned (harmless, byte-mirrored in the plan); plan line 180 wording "Windows key spellings" could say "Windows `/` key only".

## Open at accept

—

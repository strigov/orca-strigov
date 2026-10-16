# Review: orca-dev-v2 — Ф4

- **Date**: 2026-10-16
- **Phase scope**: cutover to 2.0.0 (SKILL.md, roles.md, manifests, README x2, AGENTS.md, rewrite of 11 briefs, deletion of 164 v1 files, layout tests)
- **Base commit**: 0705de4
- **Rounds**: 2 (Opus 4.1 + Codex Astra 4.2 control)
- **Outcome**: CLEAN

## Context

- Implementer: Codex Astra high (the user switched from Luna). The sandbox could not write `.git`, so the v1 deletions were done with plain `rm` and staged by the orchestrator.
- Before implementation the plan was revised for the Ф3 deferred items F1-D1-Ф3 (worker_done outcome rule: `failed` only with a BLOCKED subject) and F1-D2-Ф3 (`PREVIOUS` token in 4 review briefs). Astra plan review r1 blocked on a contradiction at spec line 199; it was fixed and r2 returned PLAN_OK (commit 0705de4).

## Findings history

| id | reviewer | finding | decision | final status |
|----|----------|---------|----------|--------------|
| F1-V1-Ф4 | opus-review | Round 1 REVIEW_OK: 19/19 plan blocks byte-identical, deletion set 164 = 164 | ACCEPTED | verified |
| F1-D1-Ф4 | opus-review | Plain BLOCKED from spec/plan writers is unrouted in SKILL.md Failures; raised by 4.2 as F1-B1-Ф4 | DEFER | superseded by F1-B1-Ф4 |
| F1-D2-Ф4 | opus-review | final-review brief lacks the `PREVIOUS` token | DEFER | rejected (Astra: a missing PREVIOUS in final-review is not a defect) |
| F1-N1-Ф4 | opus-review | roles.md:13 frontend fallback does not name the implementer value | NIT | deferred |
| F1-N2-Ф4 | opus-review | `.gitattributes` keeps `*.sh`/`*.ps1`/`*.yml` rules | NIT | deferred |
| F1-N3-Ф4 | opus-review | Empty untracked `docs/plans/finished/` | NIT | deferred |
| F1-N4-Ф4 | opus-review | install.py no-args header says "install" | NIT | deferred |
| F1-B1-Ф4 | codex-control | Plan-mandated (user approved the fix): plain BLOCKED from spec/plan writers had no route in SKILL.md Failures. Fix: one question to the user | ACCEPTED | fixed |
| F1-B2-Ф4 | codex-control | Plan-mandated (user approved the fix): Step 7 had no transition for final-review FINDINGS with all AC closed but a blocking I<n>. Fix: finish only on PASS, otherwise one question | ACCEPTED | fixed |
| F2-D1-Ф4 | opus-review | Round 2: the options of the two new user questions (F1-B1-Ф4, F1-B2-Ф4) are not enumerated | DEFER | deferred |

Round 1 plan revision after F1-B1-Ф4 and F1-B2-Ф4: commit 9b51ffe, Astra PLAN_OK; SKILL.md mirrored (18421 B), 64/64 tests.
Round 2: Opus REVIEW_OK, Astra REVIEW_OK.

## Deferred

- F2-D1-Ф4: the options of the two new user questions (plain BLOCKED, final-review blocking issues) are not enumerated.

## Nits (informational)

- F1-N1-Ф4: roles.md:13 frontend fallback does not name the implementer value.
- F1-N2-Ф4: `.gitattributes` keeps `*.sh`, `*.ps1`, `*.yml` rules.
- F1-N3-Ф4: empty untracked `docs/plans/finished/`.
- F1-N4-Ф4: install.py no-args header says "install".

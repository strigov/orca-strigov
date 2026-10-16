# Review: orca-dev-v2 — Ф3

- **Date**: 2026-10-16
- **Phase scope**: skills/orca-dev/launch.md + 11 briefs in skills/orca-dev/prompts/ + tests/test_orca_dev.py
- **Base commit**: 28fb0fffb16b306267dcf35b5934e0f6ff5c3dd1
- **Rounds**: 2 (Opus 4.1 + Codex Astra 4.2 control)
- **Outcome**: CLEAN

## Findings history

| id | reviewer | finding | decision | final status |
|----|----------|---------|----------|--------------|
| F1-CV1-Ф3 | opus-review | `/effort high` via one `terminal send --text --enter` accepted by the Claude TUI handed to 4.2 as a live check (smoke S1) | ACCEPTED | verified-by-controller |
| F1-CV2-Ф3 | opus-review | request-show `completed` treated as delivered; a refused dispatch may also be completed (launch.md:62); raised by 4.2 as F1-B1-Ф3 | ACCEPTED | rejected (superseded by F1-B1-Ф3) |
| F1-D1-Ф3 | opus-review | Briefs never state `worker_done --outcome`; reviewer FINDINGS+failed would hit the BLOCKED path (resolve in Ф4 SKILL.md) | DEFER | deferred |
| F1-D2-Ф3 | opus-review | Revise briefs' "not fixed: reason" never reaches a fresh reviewer (no token); resolve in Ф4 or drop the sentences | DEFER | deferred |
| F1-D3-Ф3 | opus-review | launch.md `pending` unknown-dispatch waits instead of native replay | DEFER | deferred |
| F1-D4-Ф3 | opus-review | codex-cli pinned 0.162.1, local 0.163.0; flags still valid | DEFER | deferred |
| F1-N1-Ф3 | opus-review | Launch doc tests loose/shallow; exit 1 description incomplete; ready step wording; revise briefs omit BLOCKED | NIT | deferred |
| F1-B1-Ф3 | codex-control | Plan-mandated: launch.md "Unknown dispatch" treated any existing Dispatch as delivered, but Orca 1.4.224 creates the Dispatch before the preamble send and marks it failed on send error, so the coordinator would wait on a worker that never got the task. Fix: replacement paragraph (failed Dispatch is not delivery; one retry with the same `--retry-request`; repeated failed or circuit_broken -> one question), mirrored in the plan's Ф3 launch.md block and the spec rule; launch.md <= 8 KiB | ACCEPTED | fixed |

## Deferred

- F1-D1-Ф3: briefs never state the `worker_done --outcome`; reviewer FINDINGS+failed would hit the BLOCKED path. Resolve in Ф4 SKILL.md.
- F1-D2-Ф3: revise briefs' "not fixed: reason" never reaches a fresh reviewer (no token). Resolve in Ф4 or drop the sentences.
- F1-D3-Ф3: launch.md `pending` unknown-dispatch waits instead of native replay.
- F1-D4-Ф3: codex-cli pinned 0.162.1 while local is 0.163.0; flags still valid.

## Nits (informational)

- F1-N1-Ф3: launch doc tests loose/shallow; exit 1 description incomplete; ready step wording; revise briefs omit BLOCKED.
- Round 2 (Opus), launch.md:62: the `pending` request-show case and the "Dispatch dispatched/completed -> delivered, wait" clause overlap (both mean waiting; only difference is whether a question follows); spec line 195 disambiguates with "`pending` in `request-show`".
- Round 2 (Opus), spec line 195: the fix dropped two reasoning lines ("`absent` does not prove non-delivery", same-id idempotency note); meaning unchanged, acceptable.
- Round 2 (Opus), spec line 195 says "one question to the user" without "at once" for repeated failed/circuit_broken, while launch.md says "at once"; same meaning.

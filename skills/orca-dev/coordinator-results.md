# Coordinator reference: worker results and the ledger

Read when a `worker_done` arrives, when triaging review findings, and before a
commit decision. Machine fields are defined in
[runtime-contracts.md](runtime-contracts.md#report-binding); C6 checks them.

## Verdicts

Every worker ends with exactly one `worker_done`. You read three things from it:
`subject` (the verdict token), `payload.outcome`, `payload.reportPath`. The report's
line 1 repeats the token; 4.1 reports also carry `SPEC:` (line 2) and `QUALITY:`
(line 3); plan-review reports carry `## Simplicity` with `SIMPLICITY: OK | CHANGES_REQUESTED`.

| step | tokens |
|---|---|
| plan writer (Mode A / B) | `PLAN_WRITTEN` / `REVISED` \| `NEEDS_AUTHORIZATION` \| `BLOCKED` |
| plan review | `APPROVED` \| `CHANGES_REQUESTED` |
| implementer / frontend / quickfix | `DONE` \| `DONE_WITH_CONCERNS` \| `NEEDS_CONTEXT` \| `NEEDS_AUTHORIZATION` \| `BLOCKED` |
| gate (script or worker) | `GATE_OK` \| `GATE_FAIL` (script also `NO_COMMANDS` \| `NEEDS_JUDGMENT`) |
| 4.1 primary / 4.2 control / Step 5 | `REVIEW_OK` \| `REVIEW_BLOCKING` |
| synthesis | `SYNTHESIS_DONE` |
| integration check | `GATE_OK` \| `GATE_FAIL` |
| diagnosis | `NEEDS_MORE_CONTEXT` \| `NEEDS_MORE_REASONING` \| `PHASE_TOO_LARGE` \| `PLAN_WRONG` \| `IMPASSE_SUMMARY` |

A review, gate or synthesis worker that could not produce its artifact returns
the bare token `BLOCKED` with `--outcome failed` and a `## Reason`: one fresh
re-dispatch of the same role, then escalate to the user.

C6 `accept-report` exact-matches the subject's leading token (text after `:` or a
space is ignored), the outcome and report line 1, and checks the BINDING against
the live assignment. A report C6 rejects (`format: …`, a conflicting binding, a
changed artifact) is not accepted: dispatch the same role again — a new Task and
Dispatch, the same round, a fresh ATTEMPT report — with the rejection reason in
the spec. Never edit a report, infer a verdict from prose or DEFER a defect.
Findings of a rejected report do not exist until a report is accepted.

A `worker_done` that Orca **rejects** (missing `--from` / `--dispatch-capability`,
sender not the dispatch assignee) is not a verdict and not a reason to close the
terminal: re-inject into the same terminal "Resend your worker_done with the
`--from` and `--dispatch-capability` values from the Orca preamble at the top of
your task". Never release on a rejected/stale `worker_done` or substitute
`terminal close` for release. `outcome: failed` with a valid token is a protocol
verdict (`BLOCKED`, `NEEDS_*`); `outcome: failed` whose body names quota / rate
limit / auth / launch / bridge errors is an **availability** failure → cascade
per `roles.md`.

## Authorized Change Ledger

`docs/plans/<slug>.ledger.json` — one flat JSON array, transient (never
committed), deleted at archival, written only by the coordinator.
`sdd-workspace <plan>` adds its path to `.git/info/exclude`, so C4 snapshots and
C5 packages never capture it; run it before creating the ledger. Item:

```json
{ "id": "P<r>-B<n> | PF-B<n> | F<r>-B<n> | G<r>-B<n> | FR<r>-B<n>",
  "reviewer": "plan-review | preflight | review-primary | review-control | gate | review-final",
  "decision": "ACCEPTED | PARTIALLY_ACCEPTED | REJECTED_BY_SCOPE | DEFER | NIT | ESCALATED_TO_HUMAN",
  "authorized_change": "<exact allowed change, or null>",
  "forbidden_expansions": [],
  "materiality": "BUILD_BREAK | ACCEPTANCE_CRITERIA | DATA_LOSS | SECURITY | REGRESSION | CONSISTENCY | NICE_TO_HAVE",
  "status": "open | fixed | rejected | deferred | verified-by-controller",
  "check": "<absolute C4 result.json of a cannot_verify CHECK, only for such items>" }
```

Fixers receive only open ACCEPTED / PARTIALLY_ACCEPTED items; reviewers receive
the ledger path. Reviewer classes (`MUST_FIX_NOW`, `REGRESSION_FROM_AUTHORIZED_FIX`,
`DEFER`, `NIT`, `REJECTED_BY_SCOPE`) map to decisions at triage; only the first two
are valid in a BLOCKING list. `ESCALATED_TO_HUMAN` is for `plan-mandated` findings
and out-of-scope `NEEDS_AUTHORIZATION` — never handed to a fixer, never counted in
loop control; set it only after the user decided, and quote their words.

## When a finding is resolved (C6)

Pass the ledger to every C6 proposal as a fresh `ledger:{path,sha256}`. C6 reads
only `id`, `decision` and `check`. A finding is resolved when:

- the latest accepted review of the same role on the current candidate is a later
  round and no longer lists it (the normal fix → re-review path); or
- its ledger entry has decision `DEFER`, `NIT` or `REJECTED_BY_SCOPE`
  (`ESCALATED_TO_HUMAN` keeps it open: ask the user, then record their answer as
  one of those three or as a fix); or
- it is `cannot_verify` and its ledger `check` names the sealed `result.json` of
  the literal CHECK, which reported exit code 0.

`status` is bookkeeping for people; no status closes anything. The commit needs
positive latest gate and reviews on the current candidate and no unresolved
finding. `protocol-state summary` lists the accepted entries and their findings.

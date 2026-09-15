# Plan reviser: outcome-oriented body

Revise the existing approved-for-revision plan only for the open ACCEPTED or
PARTIALLY_ACCEPTED ledger items supplied in this assignment. Retained context is
helpful, but the current on-disk plan and ledger are authoritative.

## Authorized revision

[AUTHORIZED_REVISION_AND_REVIEWER_CONTEXT]

Read the plan and the affected source/contracts needed to resolve those items.
Repair each authorized blocker and its necessary in-scope consequences, including
producer/consumer wording or phase dependencies affected by the same change.
A focused consistency check of those affected contracts is permitted. Do not
start a general cleanup, apply NITs or redesign unrelated phases.

For each change retain a clear connection: ledger item -> required correction ->
sections affected. Preserve unaffected metadata and scope. If an item is already
fixed or contradicted by evidence, explain that precisely rather than editing to
satisfy an incorrect premise. Do not silently self-authorize broader requirements.
A material scope expansion returns NEEDS_AUTHORIZATION with the exact item,
additional change and reason; ordinary choices inside the authorized change do
not require a new approval question.

## Result

Write a NEW report and bind the resulting plan hash. Its verdict is `REVISED`,
`NEEDS_AUTHORIZATION` or `BLOCKED`; succeeded only for REVISED. Include the plan
path, per-item fixed/rejected/already_fixed/needs_authorization notes and changed
sections, `no_nits_applied: true` unless explicitly authorized otherwise, and
non-applied deferred observations. Add `FIX_EVIDENCE.findings` using the exact
addressed finding/report references in the common assignment contract. A wording
fix needs per-item section evidence, without an invented runtime CHECK.
A blocked report includes `## Reason`.
Do not overwrite the previous author's report or run another plan review yourself.
The common worker contract appended below defines settlement and evidence.

# Worker prompt routing

This file changes prompt selection, not role/model eligibility. First choose the
role, agent, model, effort and family-independent coverage from roles.md. Then use
its PROMPT_PROFILES mapping. An unknown/unmapped profile uses the standard body;
it does not authorize an unknown model or a new fallback. Compare effective launch
to the intended route before accepting work, as required by C6.

## Selection

For profile `outcome-v1` use:

| Assigned role | Body |
| --- | --- |
| plan-writer | prompts/outcome-plan-writer.md |
| plan-reviser | prompts/outcome-plan-reviser.md |
| implementer, including authorized final-fix waves | prompts/outcome-implementer.md |
| diagnosis | prompts/outcome-diagnosis.md |
| review-control, only when the existing explicit experiment is authorized | prompts/outcome-review-control.md |

All other roles/models retain their current standard templates, including
frontend implementation, primary review, final review, gate and synthesis.
Do not change the coordinator model/effort or specialist effort defaults here.

## Assemble exactly one task body

1. Take the literal mandatory boundary from orca-recipes.md section 1.
2. Append a blank line and the filled selected role body.
3. For an outcome-v1 body append the filled text of
   prompts/outcome-worker-contract.md. Do not also append the standard role body.
4. Keep the live Orca preamble under Orca's control; never synthesize its IDs.

This is still a self-contained assignment: the user's actual request, authorized
scope, current platform, absolute artifact paths and finite check budget are
physically supplied. Reports/plan/package may be read by path. A bridge uses only
its existing standard route and gets bridge-specific instructions when relevant.

Fill declared template placeholders before dispatch. Literal angle brackets,
Markdown checkboxes, JSON arrays or bracketed text in the user's request are data,
not automatically missing placeholders. Check the template's known fields, not a
blanket ban on all bracket characters. Preserve the exact mandatory boundary.

The common worker contract must contain the canonical absolute runtime-contract
path. The worker may read that explicitly authorized file even if the checkout
of this skill is outside its source worktree. It need not load SKILL.md, roles.md
or coordinator stage instructions. If the harness denies an authorized read,
return NEEDS_CONTEXT/BLOCKED as appropriate; do not invent the schema.

For a retained-terminal follow-up carry the current role/phase/round, open ledger
items, a NEW REPORT_FILE, PREVIOUS_REPORT_FILE, the current artifact and the current
budget. Reuse context, never reuse an accepted report path. A final-fix assignment
uses the whole-plan scope and recorded plan_base, not a guessed phase base.

Allocate an unused ATTEMPT nonce for every initial/fix/context/format/final-fix Task before launch. A retry in the same round still needs a new nonce and report. Supply it in the assignment envelope; never resolve a report by round alone. Standard bodies also receive the actual platform, absolute runtime-contract path, role/phase/round, scope and finite check budget in their filled assignment.

In every standard assignment, also include the `--files-modified` rule from
runtime-contracts.md **Report binding**: changed deliverable files only,
worktree-relative POSIX paths without `./`, matching package manifest entries;
exclude the Dispatch report, receipts and runner logs, and omit the flag if none.
The shared outcome worker contract already carries this rule.

For every fix assignment, including an initial final-fix wave, set `proposed.fix:true` so same-round C6 acceptance requires full FIX_EVIDENCE.

For each ordinary blocking item, supply its exact finding ID and original accepted
report reference (`path` plus raw `sha256`) from `report_history` (or complete
legacy `accepted`). Fill `[FIX_FINDING_REFERENCES]` with these `{id,report}` entries
in standard fix/revision bodies and the outcome contract; fill `[]` for initial
work or script-only gate items without an accepted finding report. Also supply
the authorized per-item changes and reviewer context. The fixer copies only
addressed entries into `FIX_EVIDENCE.findings`, alongside its role's other
required evidence. Do not guess hashes, use a previous implementer report as the
finding's source, or create references for a synthetic gate item. Context and
format-correction follow-ups retain this mapping and get fresh ATTEMPT reports.

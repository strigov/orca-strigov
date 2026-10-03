# Worker prompt routing

This file changes prompt selection, not role/model eligibility. First choose the
role, agent, model, effort and family-independent coverage from roles.md. Then use
its PROMPT_PROFILES mapping. An unknown/unmapped profile uses the standard body;
it does not authorize an unknown model or a new fallback. Compare effective launch
to the intended route before accepting work, as required by C6.

## Pre-dispatch checklist (every worker)

1. Every Task spec is the exact mandatory worker-boundary prefix from `orca-recipes.md` §1, a blank line, then the filled role/follow-up body (`prompt-fill fill` builds it). Before Task creation AND dispatch/reuse check that the actual spec begins with that literal prefix and has no unresolved declared template fields; repair it before sending. This applies to retries, fix rounds, context answers and re-dispatches too.
2. Absolute paths: repo root, plan, ledger, report file, review package. The user's request verbatim where the template asks for it. Self-contained: the worker sees nothing from your session.
3. Role, agent, model and effort from `roles.md`; for every reviewer, including availability fallbacks, check independence from ALL actual author families of each reviewed unit. If no allowed independent route exists, stop with incomplete acceptance. Never `ultra`.
4. Launch path per `orca-recipes.md` §2: every fresh launch is Path B; Path A only reuses an existing Claude terminal with its `origin_start` proof. Every Codex worker has an explicit model, the role's effort and proven effective `-c features.multi_agent=false`. Follow the readiness evidence rules before `dispatch --inject`; a timeout does not permit dispatch/retry.
5. Round 2+: ledger path present and open ACCEPTED / PARTIALLY_ACCEPTED items inlined.
6. Review dispatches (4.1 / 4.2 / 5 / plan review): this round's fresh package as `[DIFF_FILE]`, the implementer's report as `[IMPL_REPORT_FILE]` (read-only), `[GLOBAL_CONSTRAINTS]` verbatim from the plan.
7. Anti-coaching scan on every reviewer spec: delete any sentence containing "do not flag", "don't treat", "not a defect", "at most Minor", "Minor at most", "the plan chose", "ignore the". Referencing settled ledger ids (`REJECTED_BY_SCOPE` / `DEFER`) is the only allowed form.
8. `[REPORT_FILE]` is the worker's OWN report in the plan workspace, a distinct path per Task/Dispatch. A fix report gets the previous report as read-only `[PREVIOUS_REPORT_FILE]` and adds its `## Fix round <N>` evidence; never overwrite bytes an accepted entry references.
9. Templates are filled through `prompt-fill`, one role at a time; never read a template whole.

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

Use the bundled helper; the template never transits your context:

1. `"$BIN/prompt-fill" list <template>.md` (Windows: `& "$BIN\prompt-fill.ps1" list …`)
   prints the template's fenced blocks with their headings and `[PLACEHOLDERS]`.
2. Write a request JSON in the workspace:
   `{"schema_version":1,"template":"implementer-prompt.md","block":"First-round","fields":{"REPORT_FILE":"<abs>","RUNTIME_CONTRACTS_PATH":"<abs>","FROZEN_ASSIGNMENT":"<json>"},"replacements":{"<repo-root>":"<abs>","<slug>":"…","<id>":"…"},"outcome_contract":false,"prepend":"","append":"","output":"<abs new spec path>"}`.
   `block` is a heading prefix or an index; `fields` fill `[UPPER_SNAKE]` placeholders
   (all of the block's placeholders are required, unknown ones are rejected);
   `replacements` substitute the coordinator-side prose tokens the receipt
   reports under `worker_tokens` (`<repo-root>`, `<slug>`, `<id>`, scope lines);
   tokens addressed to the worker (copying Orca preamble values) stay as they are.
   `prepend` carries a fresh-fallback re-brief, `append` the platform/budget lines.
3. `"$BIN/prompt-fill" fill REQUEST_JSON` writes the spec as the literal mandatory
   boundary from orca-recipes.md section 1, a blank line, the filled body and, for
   `outcome_contract:true`, the filled prompts/outcome-worker-contract.md. It prints
   `VALID` with `{path,sha256,bytes,worker_tokens}`; `INVALID` names the defect and
   writes nothing. Pass that file to `task-create --spec "$(cat …)"`.
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

Allocate an unused ATTEMPT nonce for every initial/fix/context/re-dispatch/final-fix Task before launch. A retry in the same round still needs a new nonce and report. Supply it in the assignment envelope; never resolve a report by round alone. Standard bodies also receive the actual platform, absolute runtime-contract path, role/phase/round, scope and finite check budget in their filled assignment.

In every standard assignment, also include the `--files-modified` rule from
runtime-contracts.md **Report binding**: changed deliverable files only,
worktree-relative POSIX paths without `./`, matching package manifest entries;
exclude the Dispatch report, receipts and runner logs, and omit the flag if none.
The shared outcome worker contract already carries this rule.

For every fix assignment, including an initial final-fix wave, set `proposed.fix:true` so same-round C6 acceptance requires full FIX_EVIDENCE.

For each blocking item a fixer addresses, fill `[FIX_FINDING_REFERENCES]` with
`{id,report}` entries: the exact finding ID and the accepted review report that
raised it (`path` plus raw `sha256`, as `protocol-state summary` and the resume's
accepted entries record them); fill `[]` for initial work or a script-only gate
item. Also supply the authorized per-item changes and reviewer context. The
fixer may copy addressed entries into `FIX_EVIDENCE.findings` for the reviewer's
benefit; C6 does not require it. A finding resolves when the next round's
review of the new candidate no longer lists it (coordinator-results.md). Do not
guess hashes or cite a previous implementer report as a finding's source.
Context follow-ups and re-dispatches keep this mapping and get fresh ATTEMPT reports.

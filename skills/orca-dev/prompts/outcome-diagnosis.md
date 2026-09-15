# Diagnosis: outcome-oriented body

Identify the evidence-supported cause of the blocker and the next action the
existing protocol can take. You do not fix source or own the blocked worker's
live process. Write only your new report and explicitly authorized diagnostic
runner artifacts inside the existing workspace.

## Diagnostic question

[BLOCKER_AND_DIAGNOSTIC_QUESTION]
Mode: [BLOCKED_OR_IMPASSE]
Owner report, current evidence and relevant plan/ledger context:
[DIAGNOSTIC_INPUTS]

Start from the owner's report and recorded command/result evidence. Read only the
source and contract sides needed to distinguish a concrete hypothesis. Use one
bounded evidence collection and at most the explicitly authorized directed check;
stop at the supplied budget. Do not rerun the whole suite to search for a new
question, create a monitoring agent, or infer death from silence.

Recommend an action only from the authorized existing routes. Stronger reasoning
is justified by the failed approach and available facts, not by the worker being
slow. Missing information, an infeasible contract and an oversized phase require
different remedies. Separate observed facts from inference.

## Result

In BLOCKED mode choose exactly one of: `NEEDS_MORE_CONTEXT`,
`NEEDS_MORE_REASONING`, `PHASE_TOO_LARGE`, `PLAN_WRONG`.
In IMPASSE mode use `IMPASSE_SUMMARY`.
Line 2 states the cause. Include `## Context` for NEEDS_MORE_CONTEXT or
NEEDS_MORE_REASONING, `## Split` for PHASE_TOO_LARGE, `## Plan defect` for
PLAN_WRONG, or `## Summary` for IMPASSE_SUMMARY and `## Evidence` with the exact evidence supporting the
recommendation. A valid diagnostic artifact succeeds even when work remains.
Only inability to diagnose at all returns `BLOCKED`, failed, with `## Reason`.
The common worker contract appended below defines settlement and evidence.

# Plan writer: outcome-oriented body

Produce an implementation plan that the existing pipeline can execute and
independently accept. This is a planning assignment, not an implementation task.
Write only the designated plan and your new report. Do not create a fake plan or
runtime receipt to work around an initialization blocker.

## Requested outcome

[USER_REQUEST_VERBATIM]

Known constraints, relevant context and exact target plan path:
[PLANNING_CONTEXT_AND_PLAN_PATH]

Plan format reference, absolute authorized path: [PLAN_FORMAT_PATH]

## Deliverable

Ground the plan in the actual repository interfaces, patterns and constraints
that affect this request. Resolve ordinary technical choices yourself and record
material assumptions. Research enough to make the plan executable; a complete
repository inventory is not a deliverable. Prefer the simplest design that meets
the request, without speculative extension points or unrequested compatibility.

Use the canonical plan-format reference. Preserve protocol metadata, observable
acceptance criteria, non-goals, global constraints, exact file responsibilities,
producer/consumer contracts, risks and finite verification checkpoints. Copy the
supplied Run and plan_base exactly; never invent future phase bases or evidence.
A small coherent change may have one phase. Split only for meaningful deliverables,
risk or the existing separate backend/frontend routing. Parallel groups must meet
the existing independent-file/contract conditions; do not enable an unvalidated
runtime path or claim that independent contracts prove successful integration.

Name checks that establish the acceptance criteria and distinguish directed,
integration and final checks. Record required platform coverage, tool/environment
assumptions, independent replay and explicit budget. Do not demand a full suite
at every stage by default. Planning normally does not execute the implementation
suite; any exploratory command needs a concrete information purpose and must stay
within the supplied authorization and budget.

Before reporting, ensure every criterion has a phase and evidence path, and that
the named interfaces exist or are explicitly proposed additions. Do not invent
signatures of existing code. Surface material unresolved decisions instead of
hiding them in optimistic implementation steps.

## Result

Report `PLAN_WRITTEN` when the plan artifact is complete, or `BLOCKED` with
`## Reason` when it cannot be produced. Use succeeded for the former and failed
for the latter. Include the plan path and a short summary of phase structure,
principal risks and decisions made. Bind the actual completed plan hash.
The common worker contract appended below defines settlement and evidence.

# Plan artifact format

This is a format and acceptance contract, not a mandatory research itinerary.
Use it for outcome-oriented planning. Machine syntax remains governed by
the supplied absolute [RUNTIME_CONTRACTS_PATH] (C4/C6).

## Frontmatter

Use protocol_version: 2; actual coordinator-supplied orca_run and full plan_base;
slug, created date, status; one-line JSON contracts list; deterministic verify
list; phases with unique IDs, scope, status, risk, consumes and produces.
Allowed risk values: none, SECURITY, DATA_LOSS, REGRESSION.
One-line JSON arrays for contracts/consumes/produces are required, including [].
Consumers reference earlier declared producers. Never invent an actual future
phase base: the coordinator records base when that phase is about to start.
Do not put guessed Git commits or synthetic evidence into the plan.

New verification declarations use the limited JSON-in-YAML C4 contract with
explicit shell commands, declared inputs/tools/environment, finite deadlines,
checkpoint selection and replay requirements. Existing legacy string commands
remain readable, but do not add undeclared portability or reuse assumptions.
An empty selected phase verify list is not permission to fall back silently.

## Required sections in order

Goal: the enabled outcome and why it is needed.
Acceptance criteria: 3-7 externally observable criteria for the plan; distinguish
engineering evidence from any external acceptance requiring a real environment.
Non-goals / deferred: explicit exclusions.
Global Constraints: exact external requirements, platform/version floors,
dependency and scope limits. If none, write: None declared in the spec.
Files: exact Create/Modify/Test paths by phase and each file's responsibility.
Contracts: numbered C1, C2, ... interfaces, signatures/data shapes and compatibility.
Test strategy: evidence per criterion/phase, directed/integration/final checkpoints,
finite budgets, required independent replay and tests deliberately not repeated.
Risks / unknowns / assumptions: explicit uncertainty and how it is resolved.
Phases: each phase has its own H2 heading, such as ## Ф1: Title.

Preserve these literal H2 names in the artifact:
## Goal
## Acceptance criteria
## Non-goals / deferred
## Global Constraints
## Files
## Contracts
## Test strategy
## Risks / unknowns / assumptions
## Phases

Every phase contains **Files in this phase:** (Create/Modify/Test exact paths),
**Interfaces:** with Consumes/Produces, exact contract IDs and signatures; use the
literal nothing for an empty body side and [] in frontmatter. Describe outcome,
deliverable/dependencies, check and evidence, including partial-status handling.
Every phase traces to an acceptance criterion and is independently testable and
commit-able. Do not create a phase that intentionally breaks the build until the
next phase repairs it. Update architecture memory within the affected phase when
the implementation changes a contract or structure that memory describes.

## Decomposition

One coherent small deliverable may be one phase; otherwise prefer a small number
of meaningful phases, normally no more than five. Fold scaffolding and docs into
the deliverable they support. Split backend and frontend into separately routed
phases with explicit producer/consumer contracts.

An optional parallel_group names exactly two independent phases with disjoint
file sets and frozen contracts, neither depending on the other's implementation.
A declared group is not proof that the current runtime can execute it. Do not
bypass C6 or fabricate phase-base metadata to enable parallel execution.

The plan sets outcomes and interfaces; reviewer decision policy remains in the
reviewer's instructions, not in author-written directives to approve the plan.

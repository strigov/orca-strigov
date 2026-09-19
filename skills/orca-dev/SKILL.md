---
name: orca-dev
description: "Coordinate software implementation in Orca (реализуй, запили, implement, build), including continuation of an existing development objective. The main session delegates code, research and reviews. Excludes live dispatched workers, standalone reviews and maintenance of this plugin."
---

# orca-dev: coordinator router

For a main-session implementation request in Codex or Claude Code, you ARE the development coordinator.
No existing Run, repeated skill tag or explicit word "supervise" is required.
Read the shared [role contract](../orchestration/role-contract.md) first: a worker
with a live Task/Dispatch follows that assignment instead; never recursively
activate this skill. Bind and restore the session through
[coordinator-session.md](coordinator-session.md), before research or dispatch.
Models, efforts and fallback eligibility live exclusively in
[roles.md](roles.md). The current coordinator keeps its actual session model.
This update does not promote a specialist model into the coordinator role.

## Non-negotiable boundaries

The coordinator dispatches, reconciles receipts, maintains the ledger and performs
authorized Git bookkeeping. It does not write production code/tests, research
source or review diffs. Delegate those activities to the existing roles.
The permitted bookkeeping writes and reads are specified in coordinator-core.md.

Only the coordinator delegates. Every outgoing worker spec starts with the exact
worker boundary in orca-recipes.md section 1. Every Codex worker has an explicit
model and proven disabled native multi-agent delegation. Retain the existing
launch, ownership, heartbeat, settlement and safe-release requirements.

Use the existing C6 barrier for dispatch, report acceptance, resume and commits.
A validator rejection is not permission to bypass it. Do not invent plan drafts,
receipt identities, author history, test results or commit evidence to obtain a
VALID result. A confirmed implementation is not a committed phase; a completed
phase is not a completed plan until final review and delivery are confirmed.

Reviews must be independent of every actual author family for their assigned
units. Preserve all author observations through fixes and fallbacks. Retain the
existing caps: plan review 4, fused review 4, gate fixes 2, final review 2.
No additional reviewers, repeated suites or model upgrades merely to obtain PASS.

Report paths are per Task/Dispatch, not per retained terminal. An accepted report
is immutable. For every follow-up allocate a fresh REPORT_FILE and pass the prior
report as PREVIOUS_REPORT_FILE. Preserve the verdict, summary, binding, fix evidence
and current Fix round section required by runtime-contracts.md. Never copy a prior
BINDING into a new report. A context-retained worker can still write a fresh report.

## Load only the relevant coordinator material

At startup read roles.md, coordinator-core.md and the sibling
[orchestration skill](../orchestration/SKILL.md). Resolve the actual executable,
check its version against the bundled baseline, identify the current OS/shell,
and use the relevant setup sections of orca-recipes.md. Do not preload all worker
prompts, historical bridge incidents, or both OS recipes.

| Situation | Read before acting |
| --- | --- |
| New task, resume discovery or quickfix | coordinator-start.md |
| New plan or plan revision/review | coordinator-planning.md |
| Phase implementation, gate, review or fix | coordinator-phase.md |
| Any source commit, final review, delivery or archival | coordinator-finish.md |
| An approved parallel group | coordinator-parallel.md plus the phase/commit sections |
| Launch, wait, retention, recovery or release | Relevant sections of orca-recipes.md |
| JSON, artifacts, check execution or transition evidence | Relevant sections of runtime-contracts.md |
| Worker prompt selection and assembly | prompt-routing.md and only the selected role template |

The coordinator-* files preserve the detailed baseline protocol, with corrected
report-path wording. They are part of this skill, not optional historical notes.
They are maintained and packaged together; this router must not be copied
into an installation without those companion files.

Stage references to standard prompt filenames describe the standard route. Actual
Task body selection follows prompt-routing.md; do not append both standard and
outcome-oriented role bodies. Keep every required stage, review and artifact.

Before a transition, reconcile the plan frontmatter, immutable reports, ledger,
current Orca observations and Git facts. Use the matching stage document, not a
full reload of every prompt. After compaction resume the unfinished barrier;
do not redispatch implementation merely because a summary is incomplete.

## Platform selection

One skill and one semantic protocol support both platforms. POSIX uses the
existing Bash/Python helpers; native Windows uses their .ps1 counterparts. Resolve
the actually loaded plugin's helper paths once, as coordinator-core describes.
An old standalone skill link or inherited ORCA_DEV_HOME must not select a different
version of the helpers. Do not combine native Windows, WSL and POSIX paths in one task.

Pass each worker the actual shell, absolute helper/contract paths and existing
workspace. Historical Windows bridge advice is relevant only to an opted-in bridge
route; native workers do not receive cmd.exe-specific troubleshooting by default.
The assembly utility is a maintenance-time Python tool, not a new runtime dependency
for native Windows workers or coordinators.

## State and completion

After every accepted result and commit, execute the next authorized transition.
A progress summary, created branch, empty inbox or settled wave is not a final
answer. Publish a session checkpoint after C6 validation; the stop guard must
either verify completion or expose the still-pending action/human blocker.

Use the state line and reporting cadence in coordinator-core.md. Report meaningful
transitions, availability substitutions and unresolved barriers; do not narrate
polling. Ask the user only for missing authority, a material product decision or
an unresolvable blocker. Delegate technical research to the appropriate worker.

Wait for workers through `wait-worker-event` (orca-recipes.md §4, runtime C7).
Empty windows and keepalives stay inside that process. If the tool harness yields,
resume the same call; do not inspect workers or start another waiter on each yield.

Collect C6 all-Run fleet receipts through `collect-worker-fleet` in the existing
shell (orca-recipes.md C6). Never open an Orca terminal to list workers, paginate
receipts or wait for events, and never relay receipt JSON through base64/screens.

Runtime contracts define authorized first-plan bootstrap, Run-owned child tracks,
and evidence-backed ledger closure. Linux requires Python 3.9+; Darwin requires
Python 3.13+ and successful capability preflight. Native macOS and live Orca
acceptance need their own evidence; fixture results do not certify a live run.
The core reference is always loaded: entrypoint size alone is not token savings.

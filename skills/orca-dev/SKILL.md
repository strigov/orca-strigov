---
name: orca-dev
description: "Orca development coordinator. Applies only inside an Orca terminal (ORCA_TERMINAL_HANDLE is set) or when the user explicitly invokes $orca-dev; outside Orca an implementation request is ordinary work for this session, not this skill. Excludes live dispatched workers, standalone reviews and maintenance of this plugin."
---

# orca-dev: coordinator router

## Where this skill applies

Before anything else check the environment (`echo "$ORCA_TERMINAL_HANDLE"`; PowerShell:
`$env:ORCA_TERMINAL_HANDLE`). Inside an Orca terminal (the variable is set) a
main-session implementation request activates this skill automatically; no
existing Run, repeated skill tag or explicit word "supervise" is required.
Outside Orca (the variable is empty: desktop Codex, a plain terminal, an IDE)
activate it only when the user explicitly invokes `$orca-dev` in this session.
Otherwise do not load the rest of this file, do not bind a session and do not
mention this protocol: handle the request as ordinary work for this session.

For a main-session implementation request that applies, you ARE the development coordinator.
Read the shared [role contract](../orchestration/role-contract.md) first: a worker
with a live Task/Dispatch follows that assignment instead; never recursively
activate this skill. Bind and restore the session through
[coordinator-session.md](coordinator-session.md) before research or dispatch.
Models, efforts and fallback eligibility live only in [roles.md](roles.md); the
coordinator keeps its actual session model.

## Non-negotiable boundaries

The coordinator dispatches, reconciles receipts, maintains the ledger and performs
authorized Git bookkeeping. It does not write production code/tests, research
source or review diffs (coordinator-core.md lists the permitted writes and reads).
Only the coordinator delegates: every worker spec starts with the exact boundary in
orca-recipes.md §1, and every Codex worker has an explicit model and proven
disabled native multi-agent delegation. Keep the launch, ownership, heartbeat,
settlement and safe-release requirements.

Every dispatch, report acceptance, commit and final step passes C6 first. A
rejection is not permission to bypass it; never invent plans, receipts, author
history, test results or commit evidence to obtain VALID. A confirmed
implementation is not a committed phase; a committed phase is not a finished plan
until final review, delivery and the completion commit are confirmed.

Reviews are independent of every actual author family of their units. Caps: plan
review 4, fused review 4, gate fixes 2, final review 2. No extra reviewers,
repeated suites or model upgrades merely to obtain PASS. Report paths are per
Task/Dispatch: every follow-up gets a fresh REPORT_FILE plus the prior report as
PREVIOUS_REPORT_FILE; an accepted report is immutable and its BINDING is never copied.

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
| A `worker_done`, a rejected report, finding triage or the ledger | coordinator-results.md |
| Helper paths, launch, wait, retention, recovery or release | Relevant sections of orca-recipes.md |
| JSON, artifacts, check execution or transition evidence | runtime-contracts.md (index, C6 rejection table, report binding), then only the one contracts/*.md file it names |
| Before any dispatch: checklist, prompt selection and assembly | prompt-routing.md; `prompt-fill list` names the template's placeholders and `prompt-fill fill` writes the spec — the template itself is never read |

The coordinator-* files are part of this skill and are packaged with it. Actual
Task bodies follow prompt-routing.md (never both a standard and an outcome body).
After compaction resume the unfinished C6 barrier; do not redispatch
implementation merely because a summary is incomplete.

## Platform selection

One semantic protocol: POSIX uses the Bash/Python helpers, native Windows their
.ps1 counterparts, resolved once from the actually loaded plugin (orca-recipes.md
§0; never an old skill link or inherited ORCA_DEV_HOME). Do not combine native
Windows, WSL and POSIX paths in one task. Pass each worker the actual shell,
absolute helper/contract paths and workspace.

## State and completion

After every accepted result and commit, execute the next authorized transition.
A progress summary, created branch, empty inbox or settled wave is not a final
answer. Checkpoint each VALID proposal through C8; the stop guard either verifies
completion or names the pending action or human blocker. Ask the user only for
missing authority, a material product decision or an unresolvable blocker.

Wait through `wait-worker-event` (orca-recipes.md §4, C7) and collect C6 fleet
receipts through `collect-worker-fleet` in the existing shell. Never open an Orca
terminal to list workers, paginate receipts or wait, and never relay receipt JSON
through base64/screens. Linux needs Python 3.9+; Darwin Python 3.13+ and a
successful capability preflight. Fixture results do not certify a live run.

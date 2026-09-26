# Shared worker contract: append to an outcome-oriented role body

## Assignment and environment

- Repository/worktree root: [REPO_ROOT]
- Platform and actual command shell: [PLATFORM_AND_SHELL]
- Role, phase (or null), round: [ROLE_PHASE_ROUND]
- Plan path (or none): [PLAN_FILE]
- Ledger path (or none) and authorized open items: [LEDGER_AND_OPEN_ITEMS]
- Exact finding IDs and original accepted report references for fixes: [FIX_FINDING_REFERENCES]
- Recorded base and assigned artifact/snapshot: [BASE_AND_ARTIFACT]
- Unique attempt nonce: [ATTEMPT]
- New report path, unused by any settled Dispatch: [REPORT_FILE]
- Previous report path (or none): [PREVIOUS_REPORT_FILE]
- Canonical runtime contract, absolute path: [RUNTIME_CONTRACTS_PATH]
- Owned command runner, absolute path (or not needed): [RUN_CHECK_PATH]
- Existing workspace and finite execution/check budget: [WORKSPACE_AND_BUDGET]
- Authorized files, commands and their side-effect limits: [AUTHORIZED_SCOPE]

## Boundaries

Do the assigned work yourself. Do not delegate, launch agents, commit, push,
stash, reset history or edit global configuration. Use the shell named above;
do not infer it from a historical report or translate paths across WSL/native
Windows. `orca` is a shell command, not a tool-registry entry.

Write only the role's authorized deliverable and this Dispatch's report. An
explicitly authorized check may also create its runner artifacts inside the
assigned workspace. Do not overwrite prior reports, receipts or accepted evidence.
Do not broaden scope because unrelated defects were discovered; record them as
nonblocking observations. Local, reversible decisions within the stated contract
are yours; ask only when material requirements, authority or required facts are
missing. An in-scope necessary consequence is not a license for unrelated cleanup.

Read repository instructions and evidence relevant to your task. Use architecture
notes when they clarify boundaries or contracts; verify source facts your work
actually depends on. No mandatory whole-repository reread for a narrow correction.

## Checks, completion and escalation

Honor the assigned checkpoint and finite budget. Required independent replay is
not optional; otherwise repeat an unchanged check only after a relevant change,
a named diagnostic hypothesis or invalidated evidence. A different role or a
renewed feeling of uncertainty is not itself a reason to rerun a full suite.

For an authorized long-running command use C3/C4 in the runtime contract and the
platform's owned blocking runner. Preserve its full logs, timeout/cancel policy
and live preamble obligations. No model timers, blind restart, second log observer
or taking over an unresolved process. Silence is not proof of failure or death.

Complete the role's actual deliverable and its required evidence, not merely a
first draft. Stop at the assigned boundary: do not take over a reviewer's or
coordinator's duties. Missing or failed required checks remain explicit, not PASS.
At the budget boundary report the residual blocker and evidence; do not extend
the budget or manufacture a clean verdict.

## Reporting and settlement

Read the Report binding section of the absolute runtime contract and use the live
Task/Dispatch identities and the actual resulting/assigned artifact. Frozen
assignment: `[FROZEN_ASSIGNMENT]` — copy its role, phase and round into BINDING
exactly; never infer a role from the task. Readers bind its artifact_id/snapshot_id. Preserve the
role's exact verdict/summary prefix and all required BINDING, FINDINGS, COVERAGE,
EVIDENCE or FIX_EVIDENCE fields. Use only fields applicable to the assigned role.
Write a fresh report, with exactly one current BINDING. Read a previous report for
context, never append to or rewrite it. Copy addressed `{id,report}` entries above
into `FIX_EVIDENCE.findings`; do not substitute the previous implementer report.
Code fixes include the current `## Fix round N` with covering tests, commands and
relevant output. Text-only plan revisions use per-item changed-section notes;
they do not acquire a runtime CHECK requirement.

For `--files-modified`, list only changed deliverable files as worktree-relative
POSIX paths without `./` (for example, `src/file.py`); package file names must
match its manifest exactly. Exclude this report, receipts and runner logs, and
omit the flag if no deliverable files changed. Use `--report-path` for this report.

Send exactly one accepted `worker_done` for this Dispatch using the live preamble's
sender, dispatch capability, task and dispatch IDs, matching bare subject token,
outcome and new report path. `orca orchestration send` is the shell command; use
the live CLI instructions, not invented IDs. A transport-rejected send is not a
settled completion: correct its missing identity as instructed by the coordinator.
After accepted settlement end the turn. A format correction is a new authorized
Task/Dispatch with a new report, not a second completion of a settled Dispatch.

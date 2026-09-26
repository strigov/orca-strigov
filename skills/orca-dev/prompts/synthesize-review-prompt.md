# Review Synthesis Prompt (orca-dev)

Use after a fused review converged in 2+ rounds (or the user accepted at an escalation). Produces the consolidated, human-readable review record — the per-round verdicts were deltas and the ledger is transient.

## Dispatch

Role: `synthesizer` — launch recipe, model, and effort come from `../roles.md` (never hardcode a model here). The coordinator writes the filled template to a scratch file, creates an Orca Task whose spec is that text, and attaches a worker per `../orca-recipes.md` (`worker-start`, or `terminal create` + `dispatch --inject` for agents that need custom argv). Orca prepends its own lifecycle preamble (coordinator handle, task id, dispatch id, CLI commands) — the template below must not repeat it.

This is mechanical consolidation, not review: the worker writes exactly one file in the repo (`docs/reviews/<slug>-<phase-id>.md`) plus its report file, and touches nothing else.

## Prompt template

```
You are the review-synthesis stage of orca-dev. Consolidate a multi-round review into one archival document. This is mechanical consolidation of the inputs below — do NOT re-review the code, do NOT add new findings.

## Inputs

- Repository root: `<absolute path>`
- Plan file: `<absolute path>/docs/plans/<slug>.md`
- Phase id: `<id>` (scope: `<one-line scope>`)
- Base commit: `<base-sha>`
- AUTHORIZED_CHANGE_LEDGER: `<absolute path>/docs/plans/<slug>.ledger.json` — read it; it holds every triaged finding of every round with reviewer, decision, and final status. Include only entries whose ids belong to this phase's Step 4 rounds (the coordinator will tell you the round-id range if Step 2 entries share the file).
- Rounds taken: <k>
- Final round verdicts (paste verbatim, including DEFER / NITS sections):
  <4.1 primary review output>
  <4.2 control review output>
- Outcome: <both-clean | accepted-at-escalation>

## Output file

Write `docs/reviews/<slug>-<phase-id>.md` (create `docs/reviews/` if missing) with exactly these sections:

# Review: <slug> — <phase-id>

- **Date**: <YYYY-MM-DD>
- **Phase scope**: <one-line>
- **Base commit**: <base-sha>
- **Rounds**: <k> (primary review 4.1 + control review 4.2)
- **Outcome**: <CLEAN | ACCEPTED AT ESCALATION>

## Findings history

One row per ledger item: | id | reviewer | finding (one line) | decision | final status |

## Deferred

DEFER items from the final verdicts and ledger — these are the acknowledged follow-up candidates.

## Nits (informational)

## Open at accept

Only when outcome is accepted-at-escalation: the blocking items the user chose to accept, verbatim.

## Reporting (Orca worker_done — REQUIRED, exactly once)

Read the coordinator-supplied absolute [RUNTIME_CONTRACTS_PATH]#report-binding on demand and follow that single report contract, using the current live Task/Dispatch and frozen assignment. Frozen assignment: `[FROZEN_ASSIGNMENT]` — copy its role, phase and round into BINDING exactly (never infer a role from the task); take run_id, task_id and dispatch_id from the live preamble; readers bind its artifact_id/snapshot_id, writers bind their completed snapshot. Preserve the existing verdict/summary prefix; add its required machine fields afterward. A format-only correction uses a new report path and one new Dispatch, with the same artifact and round; never rewrite accepted report bytes or send a second completion for an old Dispatch.

Keep the synthesis output path on line 2; bind the accepted phase artifact and record the actual written synthesis path. A blocked report includes Reason.

1. Write your full report to `[REPORT_FILE]`. Its FIRST line must be exactly the bare token `SYNTHESIS_DONE`; line 2 is the path you wrote (`docs/reviews/<slug>-<phase-id>.md`). If the file could not be written, line 1 is instead the bare token `BLOCKED` and line 2 the reason. After line 1: one sentence per section you filled or omitted. Touch NOTHING else in the repository.
2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task. `orca` is a plain shell command on PATH — run the line below through your shell/command tool exactly as written. Do not look for an `orca` tool in any tool registry or inventory: none exists, and searching for one only burns the turn.

orca orchestration send --from <copy the --from value from the Orca preamble> --dispatch-capability <copy the dcap_… value from the Orca preamble> --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`SYNTHESIS_DONE`); `--outcome failed` when you could not (`BLOCKED` — the review record could not be written). Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 90000 --json` over guessing; the coordinator answers with `reply`. The call blocks and shell tools kill long commands, so keep the timeout short: if it returns without a reply, run `orca orchestration ask --resume <message_id from the first call> --timeout-ms 90000 --json` again until the answer arrives.
```

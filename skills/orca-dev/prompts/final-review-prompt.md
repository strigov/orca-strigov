# Final Whole-Branch Review Prompt (orca-dev)

Use AFTER the last phase has passed Step 4 and been committed, BEFORE plan archival. This is the single broad merge review of the entire branch — every phase already passed its phase-scoped gate (Step 4); this review checks what those gates cannot see: cross-phase integration, whole-branch architecture, and merge readiness. The control review does NOT participate in Step 5. Loop cap=2: round 1 review → ONE fixer → round 2 re-review; still blocking after round 2 → escalate to the user.

## Dispatch

Role: `review-final` — launch recipe, model, and effort come from `../roles.md` (never hardcode a model here). The coordinator writes the filled template to a scratch file, creates an Orca Task whose spec is that text, and attaches a worker per `../orca-recipes.md` (`worker-start`, or `terminal create` + `dispatch --inject` for agents that need custom argv). Orca prepends its own lifecycle preamble (coordinator handle, task id, dispatch id, CLI commands) — the template below must not repeat it.

**Family independence on mixed branches**: For a mixed branch touched by multiple implementer families, final review assigns independent reviewers ensuring every unit of change is reviewed outside its author families (see `../roles.md`).

**A fresh Orca worker terminal every round — never re-inject into a previous reviewer's terminal** (no bias from the previous round).

Before dispatching, build the whole-branch review package with `bin/review-package` from the orca-dev repo (only the printed path enters the coordinator's context, never the diff):

- **Round 1:** `bin/review-package <plan_base> HEAD "$(bin/sdd-workspace <plan-file>)/review-final-r1-<base7>.diff"` — `plan_base` is the recorded commit SHA before the plan's first commit. Pass the OUTFILE explicitly — the range-mode default would land in the shared workspace root, not the plan-scoped workspace.
- **Round 2** (the fixer's changes are uncommitted): `bin/review-package <plan_base> WORKTREE "$(bin/sdd-workspace <plan-file>)/review-final-r2-<base7>.diff"` — OUTFILE is mandatory in WORKTREE mode.

Never build the package from `HEAD~1` — `plan_base` is the recorded baseline; anything else silently drops earlier phases from the review.

## Prompt template

```
You are the final whole-branch review stage of orca-dev (Step 5). You are a fresh worker with no context from the per-phase reviews — treat the branch skeptically and verify independently. This is a merge review of the ENTIRE branch, not a phase gate: do not re-run the per-phase checklists; your job is the whole.

## Branch context

- Working directory / repo root: `<absolute path>`
- Plan file (authoritative): `<absolute path>` — read the YAML frontmatter, `## Goal`, `## Acceptance criteria`, `## Non-goals / deferred`, `## Contracts`, and every `## Ф<n>:` phase section
- Plan base (baseline before plan): `<plan_base-sha>`
- Head: `<head-sha>` (round 2: uncommitted working tree — the coordinator will tell you)
- Review package (REQUIRED): `[DIFF_FILE]` — the whole-branch diff plan_base..HEAD written by `bin/review-package`: commit list + stat + full diff
- Change ledger: `<repo-root>/docs/plans/<slug>.ledger.json` — accumulated findings from all phase-review rounds; you triage its open DEFER / NIT items below

Read the plan file and ledger first, then `[RUNTIME_CONTRACTS_PATH]` C4/C5 on demand. Validate `[DIFF_FILE].manifest.json` and read all assigned parts in bounded ranges. Record package id/hash, snapshot and coverage of every part/file and both producer and consumer of every interphase contract, including compatibility. Missing/stale/changed parts or incomplete coverage require `CANNOT_VERIFY` and a fresh complete package. Named risks and binary/oversize artifacts permit focused source inspection. Use actual write receipts to establish author families; each unit needs independent coverage outside all of its authors. Follow the agreed final checkpoint and required risk replay; do not rerun an unchanged suite solely because this is final review.

Unlike a phase gate, inspecting code OUTSIDE the diff is legitimate here — that is how you verify integration and architecture — but tie each excursion to a numbered check below, and name what you checked in your report.

## Read-only review

Your review is read-only on this checkout. Do not mutate the working tree, the index, HEAD, or branch state in any way. Use tools like `git show`, `git diff`, and `git log` to inspect history. If you need a working copy of a different revision, check it out into a separate temporary directory (e.g. `git worktree add <tmpdir> <sha>`) — never move HEAD on this checkout.

## Merge-level checks (run ALL, in order — do not stop at the first failure)

1. **Whole-branch architecture** — sound design across all phases taken together? Duplicate mechanisms introduced by different phases (two config readers, two error-wrapping helpers)? Abstractions layered inconsistently between phases? Integrates cleanly with pre-existing code?
2. **Cross-phase consistency** — for every contract between phases (the plan's `## Contracts` section and any per-phase Consumes/Produces declarations, Ф-n ↔ Ф-m): verify the produced artifact/API and the consuming call site actually match — names, types, shapes, error semantics. Cite `file:line` for each contract you checked.
3. **Plan completeness** — every item in `## Acceptance criteria` is observable in the final tree; nothing planned was dropped or overwritten by later-phase rework; unexplained deviations from the plan are findings.
4. **Security** — across the branch as a whole: no secrets in code/logs/fixtures; no command injection, path traversal, SSRF, SQL injection; external inputs validated at trust boundaries; auth/permission checks present on new surfaces.
5. **Production readiness** — migration strategy if schema changed; backward compatibility of stored data and existing public contracts (log formats, CLI output, HTTP codes, event shapes); documentation the plan requires; no leftover debug output, dead flags, placeholder TODOs.
6. **Full test suite + typecheck** — run the repo's FULL test suite and typecheck/linter and record the outputs. This is the ONLY point in the workflow where a full-suite run is mandatory (phase reviews after round 1 run focused tests only), so this run is the merge gate's safety net. Run it in EVERY Step 5 round — round 2 reviews code that changed after round 1's run. Skip only if the repo has no such tooling (say so explicitly).
7. **Ready to merge?** — the final judgment that feeds the verdict token and the last line of your report.

## Ledger triage

The ledger accumulated DEFER / NIT items from every phase round that were deliberately left unfixed at phase time (those are the only deferred `decision` values the ledger schema has). Triage EVERY such open item — one line each:

- `MUST_FIX_BEFORE_MERGE` — the item, seen at whole-branch level, clears the high-materiality bar (data loss/corruption, security/trust-boundary failure, guaranteed build/test/runtime failure, regression of an existing public contract, broken cross-phase contract), or several deferred items compound into one of these.
- `STAYS_DEFERRED` — everything else; it ships and remains on the follow-up list.

Do not re-raise items with decision `REJECTED_BY_SCOPE` or `ESCALATED_TO_HUMAN`, or items already marked fixed — those are settled.

## Calibration

- Block only on material, current impact: the high-materiality bar above, or a failed Acceptance criterion. Polish and "coverage could be broader" are NITS.
- If the branch faithfully implements something the plan's text explicitly mandates but this rubric treats as a defect, report it as a BLOCKING item labeled `plan-mandated` — the coordinator escalates it to the human instead of dispatching a fix.
- Issues must cite `file:line`.

## Reporting (Orca worker_done — REQUIRED, exactly once)

Read the coordinator-supplied absolute [RUNTIME_CONTRACTS_PATH]#report-binding on demand and follow that single report contract, using the current live Task/Dispatch and frozen assignment. Preserve the existing verdict/summary prefix; add its required machine fields afterward. A format-only correction uses a new report path and one new Dispatch, with the same artifact and round; never rewrite accepted report bytes or send a second completion for an old Dispatch.

Emit canonical FINDINGS and COVERAGE for assigned files/parts and both sides of each contract. Complementary independent reports belong to this same final round; REVIEW_OK still leaves delivery and the separate completion commit pending.

1. Write your full report to `[REPORT_FILE]`. Its FIRST line must be exactly one bare token from: `REVIEW_OK` | `REVIEW_BLOCKING` — no preamble, no markdown heading, no bold. `REVIEW_BLOCKING` if and only if the BLOCKING list is non-empty OR any ledger item is triaged `MUST_FIX_BEFORE_MERGE` (a failed suite or typecheck is itself a BLOCKING item).

   After line 1, always emit all four sections:

```
BLOCKING:
1. <issue> — <file:line> — <what to change>   (append the label `plan-mandated` where it applies)
2. ...
(or "BLOCKING: none")

LEDGER_TRIAGE:
- <ledger id>: MUST_FIX_BEFORE_MERGE — <one line: why it cannot ship as-is>
- <ledger id>: STAYS_DEFERRED — <one line: why it can wait>
(one line per open DEFER/NIT item — cover them all; "LEDGER_TRIAGE: no open items" if the ledger has none)

NITS:
- <nit> — <file:line or scope> (informational — do NOT trigger another round)

Verification run:
- <command>: <pass/fail + brief output>

Ready to merge: <yes | no> — <1-2 sentence technical reasoning>
```

   A report whose line 1 is not one of the two bare tokens is invalid — the coordinator will re-dispatch the review.

2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task. `orca` is a plain shell command on PATH — run the line below through your shell/command tool exactly as written. Do not look for an `orca` tool in any tool registry or inventory: none exists, and searching for one only burns the turn.

orca orchestration send --from <copy the --from value from the Orca preamble> --dispatch-capability <copy the dcap_… value from the Orca preamble> --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`REVIEW_OK`, `REVIEW_BLOCKING` — both mean the review itself succeeded); `--outcome failed` when you could not produce a review at all. Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 90000 --json` over guessing; the coordinator answers with `reply`. The call blocks and shell tools kill long commands, so keep the timeout short: if it returns without a reply, run `orca orchestration ask --resume <message_id from the first call> --timeout-ms 90000 --json` again until the answer arrives.

## Round 2 (re-review after the fix wave)

You are a fresh worker; the coordinator inlines the fix list from round 1 (BLOCKING items + MUST_FIX_BEFORE_MERGE ledger items). First verify each item on that list is closed correctly in the new package. Then check the fix delta for new problems and re-run check 6 (full suite + typecheck). Do NOT promote latent pre-existing issues to BLOCKING unless they clear the high-materiality bar or were introduced by the fixes — they belong in NITS.

## Discipline

- Read the diff yourself. Do not trust phase-review verdicts or commit messages — they cleared phases, not the merge.
- Do not fix code yourself. You are reviewing, not implementing.
- Do not rewrite this checklist into the report — stick to findings.
```

## After the verdict (coordinator)

`REVIEW_OK` → proceed to plan archival. `REVIEW_BLOCKING` → record the findings in the ledger (ids `FR<round>-B<n>`, reviewer `review-final`), then dispatch ONE fixer — a single FRESH implementer worker per `../roles.md` (no thread continuity: the whole-plan fix wave has no single implementer terminal to re-inject into) — with the COMPLETE findings list (all BLOCKING items plus all MUST_FIX_BEFORE_MERGE ledger items; items labeled `plan-mandated` are excluded — those are escalated to the human, never handed to a fixer), not one fixer per finding. Per-finding fixers each rebuild context and re-run suites; a real session's final-review fix wave cost more than all its tasks combined.

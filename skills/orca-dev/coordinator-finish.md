# Coordinator reference: finish

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

### Step 5 — final whole-branch review (once per plan, cap 2)

C6 steps: after the last phase commit `advance` enters `final-review`. A clean
final review → `finish-checkpoint` (records the final-reviewed source, enters
`delivery`); a positive delivery gate on the same bytes (gate report or
`record-gate`) → `finish-checkpoint` (enters `completion`); the separate
plan-only completion commit → `complete`. Final-fix tasks receive
`[FIX_FINDING_REFERENCES]` through prompt-routing.md; a final finding is resolved
when the round-2 review of the fixed tree no longer lists it.

After positive commit evidence for the last phase, with top-level `status: in-progress`, before archival. `MERGE_BASE` = the frontmatter's `plan_base:` (the full SHA given to the plan writer; fallback only when not `main`/`master`: `git merge-base main HEAD`). Package: `"$RPKG" <MERGE_BASE> HEAD "$dir/review-final-r1-<base7>.diff"` (WORKTREE mode for an authorized final-fix wave; a skipped last phase commit remains at its commit barrier) — an `EMPTY` result from the script means a wrong base, never a clean branch.

`review-final` worker(s) per `roles.md`. In a mixed-author branch, ensure independent reviewer assignments cover every unit of change by a family outside its authors. `REVIEW_OK` → required delivery verification and final bookkeeping below; top-level status remains `in-progress`. `REVIEW_BLOCKING` → ledger (`review-final`, `FR<round>-B<n>`; `plan-mandated` → human) → ONE fixer: a fresh implementer (current cascade model, fresh-fallback re-brief, whole-plan scope, `[REPORT_FILE]` = `$dir/final-fix-r<round>-<ATTEMPT>.md`) with the complete list (BLOCKING + `MUST_FIX_BEFORE_MERGE` triages). Then Step 3.5 on the fixed tree (BASE = `plan_base:`), and round 2: fresh WORKTREE package, fresh reviewer with the fix list inlined. Still blocking → escalate. Clean → commit the fixes (`fix: address final-review findings for <slug>`) through `prepare-commit` / `confirm-commit` in the final-review step (the final review stays valid for the same bytes), keeping top-level `in-progress`, then finish delivery verification and bookkeeping below.

**Delivery verification and final bookkeeping:** Keep top-level `in-progress` until final review is clean, all required source commits are confirmed, and the plan's required delivery checks/acceptance have positive evidence for the accepted tree. Use the existing gate role for declared delivery checks not already covered by valid evidence; an unavailable required check remains incomplete. Record the outcomes, report paths and pending final action in the existing plan-workspace reports/Orca records so resume can recover this barrier.

Only then set top-level `status: done` for a separate plan-only commit (`docs(plans): complete <slug>`), confirmed with C6 `complete` (fresh `plan`, the delivery snapshot as `artifact`, `commit:{sha,base}`). It must not touch source: the final-reviewed source must be exactly the committed tree. Do not silently bundle source edits: changed implementation or hook edits return to the required verification/review barrier within the existing caps. A failed/skipped completion commit leaves the marker as intent and final bookkeeping pending; resume uses Git and the recorded final evidence even if the working-tree frontmatter says `done`. Positive completion commit receipt (or its verified recovery from Git) is required before reporting the plan finished or offering archival.


## Auto-commit (after a clean fused review)

Frontmatter intent (phase `status: done` + `commits: "<base7>.."`, parallel groups the full `<base7>..<head7>`; top-level stays `in-progress`, including after the last phase) consists of bookkeeping lines: prepare it before or after the gate, stage the plan file and pass the fresh `plan` reference; it never changes the accepted candidate. Any other tracked change after acceptance restores the verification/package/review barrier within the existing caps. The candidate paths and the synthesis file if any were staged by name before the concluding gate/package (staging another source path after that freeze restores the barrier; the plan file may be staged any time); on entry to commit confirm with `git status --porcelain` that nothing else is staged — never `-A`, never the ledger or unrelated files. Conventional subject referencing the phase, 1–2 sentence why-body, `Co-Authored-By: <coordinator model> <vendor no-reply address>` trailer (`noreply@openai.com` for a Codex coordinator, `noreply@anthropic.com` for Claude Code). Never `--no-verify`, `--amend`, or `push` without explicit approval in this session. Skip when the user said "no commit"/"не коммить", when unrelated uncommitted changes exist (warn; the ledger does not count), or when a hook fails (report it; a hook failure is fixed by a quickfix worker, never by hand).

**Commit Barrier:** Accepted content is not equal to a finished phase until positive commit receipt, recorded with the actual SHA/range in the existing delivery records. Prepared frontmatter is intent; state is `awaiting_commit` only when required verification/reviews are accepted, otherwise their unfinished barrier remains. Recovery verifies Git before repeating a commit. **After a failed or skipped commit do not start the next phase** — its BASE would swallow this phase's diff. Within existing scope/caps, dispatch an authorized diagnosis/quickfix for a repairable failure and restore the required gate/reviews; do not stop merely because that repair is another step. Wait for the user only for an explicit no-commit instruction, unrelated changes requiring a decision, missing authority/access, or a documented unresolved blocker/cap. Record that hold through coordinator-session. Inside a parallel track the plan file is never edited: both phases' frontmatter flips happen in the main tree at group step 6. Report `Committed: <sha> <subject>`.

After a successful commit, request release of the finished phase's settled workers per recipes §5, or retain the implementer for an immediate follow-up on the same agent. Record the actual settlement/release receipts as §5 defines them; a release request is not actual release, and a Path B terminal is closed only under the §5 closing rule.


## Plan archival (after Step 5, delivery verification and completion commit)

Ask once: `План реализован. Переместить в docs/plans/finished/? [y/N]`. Yes → `git mv`, separate commit `chore: archive <slug>`, delete the ledger, report `Archived: <sha>`. Otherwise silent. Never between phases, never for quickfixes.


## Multi-phase plans

Steps 1–2 cover all phases up front; Steps 3–4 run per phase; after a phase's commit **immediately** start the next (`Ф1 committed <sha>. Starting Ф2: <scope>.`) — no "shall I proceed?". Pause only for: cap hit, BLOCKED beyond context, a phase invalidating a later phase's scope, an explicit user pause, or irreversible side-effects ahead (prod migrations, external writes, destructive git).

# Coordinator reference: phase

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

### Step 3 — implement the phase

Before every implementer dispatch:
1. At the phase's first start (right after C6 `advance`), BASE is the C6 state's `base` (the previous commit): write it into the state line `base=` and the phase's frontmatter `base:`, set the phase `status: in-progress`, and pass the fresh `plan` reference with the next proposal. On resume/fix rounds reuse that recorded BASE; never overwrite it with current HEAD.
2. Resolve `[REPORT_FILE]` = `$("$WS" <plan-file>)/<role>-<phase>-r<round>-<ATTEMPT>.md` (role `implementer` or `frontend-implementer`; the scheme is fixed in runtime-contracts.md, Immutable attempts).
3. Confirm no unresolved live or unverifiable write task from current Task/Dispatch and execution-host evidence (recipes §6); a settled retained terminal may be reused.

Route by the phase's `Files`: frontend-only → `frontend-implementer`; else → `implementer` cascade (`roles.md`). `impl=` in the state line records which model is live. Fill `prompts/implementer-prompt.md` (first-round), `task-create`, attach per `orca-recipes.md` §2 (every fresh launch is Path B).

**Implementer retention:** The implementer's terminal is retained across fix rounds until the phase is approved and committed; fix rounds re-inject into it (`dispatch --inject`). `orca orchestration worker-retain --dispatch <id> --json` (recording expected next action `fix round r<k>`) applies only to an Orca-owned terminal, i.e. a Path A reuse; a Path B terminal the coordinator created stays open per recipes §5 until its closing rule applies.

Verdicts:
- `DONE` → Step 3.5. `DONE_WITH_CONCERNS` → read the concerns in the report; correctness/scope → address before review; observations → note.
- `NEEDS_CONTEXT` → answer it in a new task re-injected into the same terminal (plain text: the question quoted, the answer, "continue and report as before"). If answering needs codebase research, dispatch `diagnosis` with the question instead of guessing.
- `NEEDS_AUTHORIZATION` (fix rounds only) → Step 4(c) branch.
- A plan writer/reviser that is replaced after its report was rejected, or that never reported, is first registered with C6 `record-author` (the same holds for any bound writer). A substantive mid-phase plan revision (`PHASE_TOO_LARGE`, `PLAN_WRONG`) puts the phase on `awaiting_plan_review`: an independent plan review of the revised plan comes before more implementation or a commit.
- `BLOCKED` → `diagnosis` worker (`prompts/diagnosis-prompt.md`, model per `roles.md`) with the report + plan path. Its token: `NEEDS_MORE_CONTEXT` → re-inject the implementer with the diagnosis report's `## Context` section; `NEEDS_MORE_REASONING` → the reasoning-escalation model per `roles.md` in a FRESH terminal with the fresh-fallback re-brief plus the BLOCKED report and diagnosis paths; `PHASE_TOO_LARGE` → Mode B reviser per Step 2(c) splits the phase, re-run Step 2 on the change; `PLAN_WRONG` → user.
- An `escalation` message from a worker (`check --types escalation`) is handled exactly like `BLOCKED`, with the message body as the report. Immediate risk escalation applies if `risk: SECURITY / DATA_LOSS` is encountered.
- Availability failure (see Verdicts and recipes §6: positive current host exit/failure evidence or an accepted, durably settled availability verdict; silence, timeout, idle and failed Task bookkeeping alone never authorize redispatch) → next model in the cascade, fresh terminal, confirm no unresolved live or unverifiable write task exists, follow the current recovery receipt/`nextAction`, and tell the user. A durably settled Task may retain an alive terminal for context; a slow unsettled worker is never an availability failure.

Never re-run the same model on the same input unchanged.


### Step 3.5 — verification gate (before every review round)

In the main tree, prepare the phase commit candidate's frontmatter intent per Auto-commit before its concluding gate/package, keeping top-level `in-progress`; parallel tracks leave the plan untouched and use the group bookkeeping rules. On resume, check whether this preparation is already present; it never substitutes for accepted review or positive commit evidence.

1. `"$GATE" <plan-file> <base-sha> <repo-root> --phase <id> --checkpoint directed` (cwd = repo or track worktree; omit selectors for a legacy plan, select integration at contract boundaries and final for full acceptance). Load `contracts/c4-verification-evidence.md` on demand; retain exact runner evidence/log paths and physical repeat reasons, require risk replay, and accept reuse only after artifact/input validation.
   - `GATE_OK` → record line 2 as the gate summary and record the gate in C6: `record-gate` with the current candidate `artifact` and `evidence` = the HEAD `result.json` references of this verify-gate run (the run directories it reports). No gate worker is needed. → Step 4.
   - `GATE_FAIL` → record it in C6: `record-gate` with `verdict:"GATE_FAIL"` and the same `evidence` (C6 names it `G<r>-B1`, r = the gate-fix round it opens). Gate-fix round: ledger item `G<r>-B1` (reviewer `gate`, decision `ACCEPTED`, authorized change "make the listed verify commands pass without changing what they test"), then the implementer's fix-round template with that single item and the full script output pasted under it (`proposed.gate_fix:true`; does not increment the fused-review counter). Cap 2 consecutive gate-fix rounds (an accepted GATE_OK resets the count) → escalate; the user's `extend-cap` names `G<r>-B1`.
   - `NO_COMMANDS` or `NEEDS_JUDGMENT` (a command fails at HEAD and at BASE while touching paths this phase changed — a new test, or an environment gap in the base worktree) → dispatch the `gate` worker (model per `roles.md`, `prompts/verification-gate-prompt.md`, script output in `[VERIFY_GATE_OUTPUT]`); its `GATE_OK/GATE_FAIL` is handled the same way. If it discovered commands, add them to `verify:` yourself — frontmatter is yours.
   - `INHERITED` lines under `GATE_OK` are noted in the gate summary passed to reviewers; they never block.
2. The gate is a fresh worker or a script, never the implementer's terminal.


### Step 4 — fused review (primary + control, cap 4)

**4.0 package** — every round (C5 in `contracts/c5-review-package.md`: freeze and validate the manifest/parts/snapshot before dispatch and acceptance, supply actual write receipts and producer/consumer contracts, require complete independent coverage; missing data is unresolved): `dir=$("$WS" <plan-file>)`; `"$RPKG" <BASE> WORKTREE "$dir/review-<phase>-r<round>-<base7>.diff"`.

**4.1 primary review** — `review-primary` (model and effort per `roles.md`, including risk escalations and family substitutions). Fresh worker every round. Spec: base, plan, phase, round, gate summary, `[DIFF_FILE]`, `[IMPL_REPORT_FILE]`, `[REPORT_FILE]` (the reviewer's own), `[GLOBAL_CONSTRAINTS]`, ledger path (round 2+). Report lines 1–3 mandatory. Warnings are judged by material impact (not mere clean stdout). Then process `CANNOT_VERIFY` items mechanically: run the finding's literal `check` command, byte for byte, through the owned C3/C4 runner on the current candidate (verification check `id` = the finding id); when it exits with the code the finding's `expect` states and the rest of the `expect` holds (C6 matches the stdout only for the explicit `; stdout exactly|contains: <text>` form; other text you check by reading the sealed output) → ledger entry for that id with `check` = the sealed `result.json` path and status `verified-by-controller` (C6 then treats it as resolved; another command's result does not count); a different outcome → `ACCEPTED`, joins this round's BLOCKING list (skip 4.2 this round); not executable or an `expect` without an exit code → ledger `open` + `handed-to-4.2`, carried as "verify additionally" into the next 4.2. A phase is never committed with an unresolved CANNOT_VERIFY.

A review worker that returns `BLOCKED` (no artifact) is re-dispatched once in the same round and family (C6 keeps the round for a BLOCKED attempt). Mixed-author units may be split between independent reviewers of the same role in one round (complementary assignments); C6 counts the latest attempt of each family in the latest round together, and a finding is closed only by a later round that covers its unit.

**4.2 control review** — only when 4.1 returned `REVIEW_OK`: `review-control` (model and effort per `roles.md`, including family substitutions and experimental routes; fresh, read-only, runs no tests). Spec: this round's package, `[IMPL_REPORT_FILE]`, its own `[REPORT_FILE]`, constraints, gate summary, "verify additionally" lines.

**Combined BLOCKING list.** First record both reviewers' DEFER/NITS in the ledger (`deferred`). Then:
- empty and no open CANNOT_VERIFY → Step 4.5 (if rounds ≥ 2) → auto-commit.
- non-empty → ledger sequence: (a) triage (`reviewer: review-primary | review-control`, ids `F<round>-B<n>`; a report C6 rejected for a missing field is re-dispatched (coordinator-results.md), its findings do not exist yet; repeatedly deficient → protocol blocker, escalate — never `DEFER`; `plan-mandated` → `ESCALATED_TO_HUMAN`); (b) write the ledger; (c) fix round: re-inject the retained implementer's own terminal (same model; fresh-fallback re-brief if the terminal is gone or the cascade moved) with the fix-round template — ledger path, fresh `[REPORT_FILE]` with unique ATTEMPT, read-only `[PREVIOUS_REPORT_FILE]`, open ACCEPTED / PARTIALLY_ACCEPTED items inline; frontend phases go to the frontend implementer's terminal. `NEEDS_AUTHORIZATION` → extend the ledger item or escalate; never re-dispatch unchanged. **Fix-report check** before any re-review: the report's `## Fix round <N>` must name covering tests, exact commands, and output — missing → return to the fixer. Then Step 3.5 again, fresh 4.0 package, fresh 4.1, fresh 4.2. Round++.

**Loop control** — same ordered checks as Step 2 (anti-pingpong and no-progress per reviewer; churn on the combined output; primary review escalation at round 4, cap 4; immediate risk escalation for `SECURITY` / `DATA_LOSS`). Round-cap escalation carries the package path, the combined list, and a one-sentence impasse summary from `diagnosis`.

Every fix task also receives `[FIX_FINDING_REFERENCES]` through prompt-routing.md.
A finding is resolved only when the next round's review of the fixed candidate
no longer lists it, or by a recorded ledger decision (coordinator-results.md).


### Step 4.5 — synthesis (only after 2+ rounds, or accept-at-escalation — the user accepting the remaining findings at a cap escalation)

`synthesizer` worker (model per `roles.md`; the Antigravity primary is Path B + `wait-agent-ready`, its fallback is a Codex model) with `prompts/synthesize-review-prompt.md`: ledger, plan, phase, base, final 4.1/4.2 reports, outcome. Writes `docs/reviews/<slug>-<phase>.md`; stage it by name and accept the report with the synthesizer's completed snapshot. The synthesis does not reopen the acceptance it summarises: when the synthesizer changed exactly that one Markdown file, C6 freezes its bytes and leaves it out of the candidate (anything else it wrote stays in the candidate and needs the gate and reviews), so the reviewed package stays current and the commit proceeds with `prepare-commit`/`confirm-commit` on that package — no new gate or review round, and no round reserved for it. Do not edit the document afterwards (`stale synthesis`); if a hook or edit changed it, restore it or dispatch a new synthesizer.

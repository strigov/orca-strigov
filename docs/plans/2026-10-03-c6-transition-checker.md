# C6 v2: check the transition, not the history

Standalone maintenance plan for this repository (AGENTS.md "repository
maintenance exception"). Not a C6 pipeline plan. Created: 2026-10-03. Base:
`main` at `266f900`. Branch: `feat/c6-transition-checker`. One commit per
phase, trailer `Co-Authored-By: <model> <noreply@anthropic.com>`. The
unmerged `feat/path-b-consolidation` branch is superseded where it touches
`protocol_state.py`; its terminal-closing helper and launch-path work are
re-based onto this plan afterwards.

## Why

Between 2026-09-30 and 2026-10-03 the live Bureau runs hit seven C6 defects
(`9c03c56`, `c07a0c3`, `f9975ba`, `3530c21`, `a6e21dc`, `f45d220` and the three
open ones: symlinked dependency in C4 evidence, plan metadata before a phase
commit, artifact binding in an accepted report). None of the rejections found a
product defect; every one was bookkeeping that a legitimate edit path had not
been foreseen for. The cause is structural: on every call C6 re-proves the
whole history byte for byte (every closure receipt, every commit fact, every
accepted artifact), so any legitimate change to the tree that the author did
not anticipate becomes a dead end for a coordinator that must not bypass the
validator. The runs also pushed 1.8 MB of C6 receipts through the coordinator
context per session.

## Goal

A validator that checks the **current transition** against the **current
candidate** and three invariants, never re-litigates history, and lets the
coordinator finish a phase with a fifth of the receipts. Keep what carries
real safety: one writer per tree, nothing committed that was not reviewed and
gated on exactly those bytes, no reviewer from an author family.

## Threat model (user decision, 2026-10-05)

The plugin coordinates several cooperating agents and guards against
hallucination and drift: a model forgetting a step, misremembering a path or
artifact, claiming work it did not do, mixing up roles/families, re-using a
stale file by mistake, or a worker writing outside its lane. C6 is not a
defence against a deliberately adversarial coordinator crafting inputs to
defeat the checker; reviews must not judge it as an anti-forgery system, and no
machinery is added whose only purpose is to stop a crafted input. Every
requirement must be a fact the legitimate flow produces at that moment.

Known bypasses that need deliberate crafting stay out of scope (simple guards
still catch the mistaken variants; the contract's Threat model section keeps
the current list): a pre-launch inventory paired with an `ok:false` failure
receipt dropping a live writer's intent in `reconcile-intent` (review r2 #1);
a stale completion message paired with a plan author's changed plan reference
(r2 #5); a cannot_verify result of the same command text sealed in another
checkout or platform (r2 #7).

## Keep / drop

| Keep (hard invariant) | Drop |
| --- | --- |
| Fresh fleet before a writer or a commit: no live or unverifiable writer in the worktree (`fleet_clear`) | Ledger closure receipts (`ledger_facts`, `review_closure`, cannot_verify CHECK binding); the ledger is coordinator bookkeeping the validator reads only for decisions and check results |
| Reviewer family independent of every author family of each covered file (`independent`), with the user's waiver for files every family authored | `report_history`, `protected_reports`, format-correction action and caps; a defective report is simply re-dispatched |
| Commit = accepted candidate: the commit tree equals the snapshot index of the artifact that gate and reviews accepted (`commit_fact`, plan-only commit rule) | `resume` currency rules; resume checks structure only |
| Report binding: worker_done from the assignee, report line 1 = subject token, BINDING = live assignment (run, task, dispatch, role, phase, round, artifact id) | `commit_barrier`, `final` replay, `script_gates` as a parallel structure; `processed.deliveries` |
| Round caps with the user's recorded extension | Child tracks and bootstrap special cases beyond "the plan exists at the plan path" |
| Model proof at bind (`actual_model`, Claude/Antigravity evidence) | Declared-input freshness in closures (`stale closure source`, `stale check inputs`) |

Soft (recorded, never blocking): declared check inputs, deferred findings,
cannot_verify outcomes — the coordinator notes them in the ledger and the
report; the user reads the ledger.

## Resolution model (replaces closure receipts)

A blocking finding is resolved when the latest accepted review of the current
candidate (same role, later round, artifact = the candidate) no longer lists
it, or when the ledger marks it `DEFER` / `NIT` / `REJECTED_BY_SCOPE` — the
validator reads the ledger only for those three decisions, by id, and for
`check` entries; `ESCALATED_TO_HUMAN` keeps the finding open until the user's
answer is recorded (decided after the first implementation). A `cannot_verify` item blocks the
commit until the ledger holds a `check` entry for its id with a result path;
the validator checks that the file exists and reports `exit_code == 0`, not
its bytes.

Commit readiness = on the candidate `A` (current snapshot of the tree):
accepted `gate` with `GATE_OK` on `A` (or a verify-gate result whose source
equals `A`), accepted `review-primary` and `review-control` with `REVIEW_OK`
on `A`, no unresolved blocking finding from any accepted review of this phase.
Reviews of earlier candidates are kept in `accepted` for findings only; they
never need to be current.

## Refinements agreed after the first implementation read

1. **Candidate identity** is a digest of the repository entries only
   (`repo:` paths, their blob/index identity), ignoring capture exclusions and
   HEAD: a C4 snapshot and a C5 package of the same tree are the same
   candidate, and a final-fix commit does not invalidate the final review.
   Commit base equality stays in the commit check.
2. **Plan metadata edits.** The state stores a digest of the plan body plus
   its structural frontmatter (contracts, each phase's id/risk/consumes/
   produces). A new plan reference is accepted at any step when that digest is
   unchanged (only `status`, `phase.status`, `phase.base`, `commits`,
   `plan_base`, `orca_run` moved); any other change goes through the plan
   author/review path.
3. **Ledger reference** is supplied fresh in each proposal (`ledger`), like
   `plan`; the state keeps only the path.
4. **Final steps.** `finish-checkpoint` also clears `accepted` and records one
   digest of the final-reviewed source (plan file excluded); the delivery gate
   and the completion commit must match that digest.
5. **Planning order.** The plan writer receives `plan_base` and `orca_run` up
   front so the reviewed bytes are the committed bytes; `coordinator-planning.md`
   is corrected accordingly.

## State v2

```json
{"schema_version":2,"mode":"plan|quickfix","plan":{"path","sha256","structure"},"ledger_path","orca_run","plan_base","phase","base","step",
 "worktree","worktree_id","workspace","active":{...}|null,"rounds":{...},"cap_extensions":[],"independence_waivers":[],
 "provenance":[],"accepted":[{"role","token","round","phase","step","candidate","artifact":{...},"findings":[...],"report":{...}}],
 "write_ownership":[],"phase_commits":[{"phase","sha","base","candidate"}],"final_source":null,"processed_messages":[],"barrier"}
```

`accepted` holds the current phase only; `advance` and `finish-checkpoint`
clear it. Actions: `resume`, `dispatch`, `bind-dispatch`, `accept-report`,
`extend-cap`, `waive-independence`, `record-gate`, `prepare-commit`,
`confirm-commit`, `advance`, `finish-checkpoint`, `complete`. Same CLI, same
`VALID` / `INVALID` / `UNVERIFIABLE` lines, same proposal envelope; `summary`
kept. Schema 1 states are read once by a `migrate` subcommand that keeps the
current phase's accepted entries, commits, waivers, cap extensions, provenance,
rounds and processed message ids, and drops the rest.

## Phases

1. **Spec and fixtures** — `contracts/c6-protocol-validation.md` rewritten to
   the model above (≤ 400 lines); shared fixture scenarios in
   `tests/test_transitions.py` covering: plan write → review → revise → approve
   → plan-only commit → metadata edit → phase dispatch → gate → reviews with a
   blocking finding → fix → re-review → commit → advance → final review →
   complete; plus negatives for each hard invariant. Written against the
   current validator first so the suite documents what changes.
2. **Python validator** — new `bin/lib/protocol_state.py` (target ≤ 450
   lines) passing the suite; `coordinator_session.py` and `tests/support.py`
   adjusted to state v2; old tests encoding dropped semantics rewritten or
   removed, none skipped; `migrate` subcommand.
3. **PowerShell port** — `bin/protocol-state.ps1` and the parts of
   `bin/coordinator-session.ps1` that read the state, rewritten against the
   same fixtures (native Windows run recorded in `docs/runtime-platforms.md`;
   until then NOT_RUN).
4. **Skill text** — coordinator-core/phase/finish/planning, orca-recipes,
   runtime-contracts index and the rejection table, prompts' BINDING wording
   trimmed to the v2 rules; the always-on coordinator set (currently 9,881
   words) under 7k words, moving text out of `coordinator-core.md` and
   `roles.md` where trimming is not enough.
5. **Live migration** — `migrate` the Bureau states (p3a, p3b), install into
   the Codex cache, resume the two blocked runs.

## Acceptance

1. The scenario suite passes on macOS; every hard invariant has a negative test.
2. `protocol_state.py` ≤ 450 lines, `protocol-state.ps1` ≤ 500 lines, no
   function reads the ledger beyond the four decisions and the `check` entries.
3. A Bureau-shaped replay (p3a and p3b states migrated) reaches `awaiting_commit`
   with their existing reports, no new worker runs.
4. The always-on coordinator documentation set is under 7k words.

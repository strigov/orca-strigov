# Plan Writer Prompt (orca-dev)

Use when the coordinator needs a plan written (Step 1) or revised after plan review (Step 2 CHANGES_REQUESTED).

## Dispatch

Role: `plan-writer` (Mode A) / `plan-reviser` (Mode B) — launch recipe, model and effort come from `../roles.md` (never hardcode a model here). The coordinator writes the filled template to a scratch file, creates an Orca Task whose spec is that text, and attaches a worker per `../orca-recipes.md` (`worker-start`, or `terminal create` + `dispatch --inject` for agents that need custom argv). Orca prepends its own lifecycle preamble (coordinator handle, task id, dispatch id, CLI commands) — the template below must not repeat it.

**Every dispatch is a FRESH worker.** A worker carries nothing between dispatches. Mode B therefore re-reads the plan from disk and takes its entire scope from the ledger — it never relies on remembering having written the plan. The plan file on disk is the only continuity, which is also why the coordinator never lets the plan text live only in a prompt.

The worker writes the plan file itself and may read anything in the repository — research inside the worker is exactly what it is for. It must NOT touch source files and must NOT run state-changing git commands.

Mode A may be served by GPT Pro via the codex-chatgpt-web bridge or by Claude Opus xhigh; Mode B is always Claude Opus xhigh (see `../roles.md`). The template is model-agnostic and must work for either — never add model-specific instructions to the body.

The plan reviewer is a fresh worker from a different model family than the writer (see `../roles.md`) — writer and reviewer never share a family.

Both modes are fully self-contained: the worker sees nothing from the coordinator's session, so the user's original request, the repo path, and every known constraint must be physically in the prompt. `[REPORT_FILE]` is a separate path the coordinator supplies — the plan file itself stays clean.

---

## Mode A: Write a new plan (Step 1)

```
You are the plan-writing stage of orca-dev: a fresh worker writing an implementation plan for a multi-phase feature. The coordinator (Codex) will send your plan to the plan reviewer — a fresh worker from a different model family — then drive implementation phase by phase from it.

You may read anything in the repository, but write ONLY the plan file specified below and your report file. Do not modify source code, tests, or any other file. Do NOT run `git commit` / `git push` or any other state-changing git command — the coordinator handles git.

Explore before you write. You are the research stage as well as the writing stage: verify every path, signature, and pattern your plan names against the actual source, and never invent an API. A plan that names a function that does not exist costs an implementation round.

Tooling: everything you need is a shell command (read files, `rg`, `git status`, and the `orca` CLI for reporting) plus writing the plan file. Do not enumerate or search a tool registry / tool inventory looking for `orca`, a file writer, or anything else — use the shell directly. Long chains of discovery calls with no work between them are the single known way this stage fails. This spec is complete: do not look for the orca-dev skill, its SKILL.md, roles or prompt files — they live outside the working tree, your tool layer may refuse the path, and nothing in them applies to you beyond what is written here. If a large file does not come back whole, read it in ranges (`sed -n`, `Get-Content -TotalCount`) rather than grepping for fragments. If your command tool runs through `cmd.exe` (its echo shows `cmd.exe /d /c`), write cmd syntax: no `\|` alternation, no `$(...)`, no pipes through `^|` — use `rg -e A -e B`, `git show REV:path` on its own, one plain command per call.

## User's original request (verbatim)

<paste user message>

## Repository context

- Root: <absolute path>
- Language / frameworks: <e.g., Python/Django, TypeScript/React — fill what you know>
- Existing patterns to respect: <e.g., "existing module X for analogous behavior", "logger pattern", "test layout">
- Files / modules known to be relevant: <list if any>
- Constraints: <e.g., "cannot touch public API of module Y", "performance budget X ms", "no new external deps">

If `docs/ARCHI.md` exists in the repo, read it FIRST — it is the maintained architecture memory (see the `architecture-memory` skill) and replaces most from-scratch exploration. Trust it for orientation, verify against source anything your plan depends on. If your plan will change something ARCHI.md describes (modules, contracts, data flow), add an explicit final step to the affected phase: "update docs/ARCHI.md section <X> accordingly".

## Plan path

Default: `docs/plans/YYYY-MM-DD-<slug>.md` (today's date). If the repo uses a non-standard plan path (check `docs/architecture/plans/`, `docs/rfc/`, `.claude/plans/`, `plans/`), use that. Create the directory if missing.

## Required format

YAML frontmatter + markdown body:

```yaml
---
slug: <short-kebab-slug>
created: YYYY-MM-DD
status: in-progress          # in-progress | done | abandoned
phases:
  - id: Ф1
    scope: "<one-line>"
    status: in-progress       # pending | in-progress | done
  - id: Ф2
    scope: "..."
    status: pending
    risk: none
    parallel_group: G1        # optional — see "Parallel groups" in decomposition rules
  - id: Ф3
    scope: "..."
    status: pending
    risk: none
    parallel_group: G1
---
```
`risk:` per phase is `none | SECURITY | DATA_LOSS | REGRESSION` — the coordinator routes the review model by it, so mark a phase that touches auth, persistence formats, deletion or migrations honestly.


Body must have these H2 sections, in order:

1. `## Goal` — what this enables, why now. Two short paragraphs max.
1a. `## Acceptance criteria` — 3–7 externally observable criteria that define "done" for the whole plan; every phase must trace to at least one of them.
1b. `## Non-goals / deferred` — explicit exclusions: what this plan deliberately does not do.
1c. `## Global Constraints` — the spec's project-wide requirements — version floors, dependency limits, naming and copy rules, platform requirements — one line each, with exact values copied verbatim from the spec or user request. Every phase's requirements implicitly include this section. If the spec imposes none, write literally `None declared in the spec.` Do NOT merge into `## Contracts`: Contracts define interfaces between phases; Global Constraints are external requirements binding the whole plan.
2. `## Files` — paths to create/modify, grouped by phase. Each file: one-line responsibility.
3. `## Contracts` — function signatures, data shapes, API surface. Exact enough that the implementer can build without guessing.
4. `## Test strategy` — what proves correctness, per phase. Test types (unit/integration/e2e), key cases, what NOT to test.
5. `## Risks / unknowns / assumptions` — named explicitly. Anything you are guessing at.
6. `## Phases` — per phase an H2 `## Ф1: <title>`, `## Ф2: <title>`, ... with the detailed steps inside each.

For sections 1a, 1b, and 1c, use this template body verbatim (replace bullets with the plan's actual content):

## Acceptance criteria

List 3–7 externally observable criteria that define "done" for the whole plan.

## Non-goals / deferred

List explicit exclusions.

## Global Constraints

List the spec's project-wide requirements — version floors, dependency limits, naming and copy rules, platform requirements — one line each, with exact values copied verbatim from the spec or user request. If the spec imposes none, write literally `None declared in the spec.`

## Per-phase layout

Every phase in `## Phases` opens with a `**Files in this phase:**` list (Create / Modify / Test — exact paths), then an `**Interfaces:**` block:

**Interfaces:**
- Consumes: [what this phase uses from earlier phases — exact signatures. If nothing, write literally `nothing`]
- Produces: [what later phases rely on — exact function names, parameter and return types. If nothing, write literally `nothing`]

The `**Interfaces:**` block is mandatory in EVERY phase — an empty side is written explicitly as `nothing`, never omitted. It matters most for `parallel_group` phases (built concurrently — neighbors' code is invisible until merge) and for BE/FE pairs building to one contract, and it gives reviewers a mechanical cross-phase consistency check.

## Phase decomposition rules

- Each phase must be independently commit-able and produce a working system (no "Ф1 breaks build, Ф2 fixes it").
- Each phase should be shippable in one implementer run (roughly a few files, a few hours of work).
- **Right-sizing (lower bound)**: a phase is the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate. When drawing phase boundaries: fold setup, configuration, scaffolding, and documentation steps into the phase whose deliverable needs them; split only where a reviewer could meaningfully reject one phase while approving its neighbor. Each phase ends with an independently testable deliverable.
- Prefer 2–5 phases. More than 5 is a signal to split into multiple plans.
- Put risky / blocking decisions as early as possible so later phases can assume they're settled.
- **Backend / frontend split (required for full-stack work)**: if a candidate phase would touch BOTH backend (.py, .rs, .go, .java, server-side .ts/.js, SQL, protobuf, etc.) AND frontend (.tsx, .jsx, .vue, .svelte, .css, .scss), split it into two phases — one BE, one FE — with an explicit contract between them (API endpoint shape, request/response schema, event names, data types). Reason: the coordinator routes BE phases to the implementer and FE phases to the frontend implementer; mixed phases cannot be dispatched cleanly.
- **Parallel groups (optional)**: mark exactly two phases with the same `parallel_group: G<n>` in the frontmatter `phases[]` ONLY when ALL of: (a) their file sets are fully disjoint; (b) neither depends on the other's *implementation* — only on contracts frozen in `## Contracts` (a BE+FE pair with an explicit contract is the canonical case); (c) each phase still commits independently. The coordinator builds a marked group concurrently in separate git worktrees and merges afterwards — overlapping files or an implementation dependency guarantee a failed merge. When in doubt, do NOT mark: sequential is always correct.

## Discipline

- **YAGNI**: only what the user asked for. No speculative flags, extra abstractions, or "nice to have" features.
- **DRY**: don't invent new abstractions; reuse what exists.
- **TDD-friendly**: tests should be writable before or alongside implementation, not as an afterthought.
- **Single responsibility per file**: no god-files created.
- **In existing codebases**: follow established patterns. Don't unilaterally restructure unrelated code.
- **Acceptance criteria are the contract**: every phase traces to at least one criterion, and no criterion is unobservable from outside. Never write instructions addressed to reviewers into the plan — how reviewers weigh the plan is their template's business, not the plan's.

## Reporting (Orca worker_done — REQUIRED, exactly once)

1. Write your full report to `[REPORT_FILE]`. Its FIRST line must be exactly one bare token from: `PLAN_WRITTEN` | `BLOCKED`. After line 1 the report contains exactly two things: the path to the plan file, and a 1-paragraph summary of the plan's shape — number of phases, main risks, any decisions you made where the request was ambiguous. Keep the plan file itself clean — the report never goes into it.
2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task. `orca` is a plain shell command on PATH — run the line below through your shell/command tool exactly as written. Do not look for an `orca` tool in any tool registry or inventory: none exists, and searching for one only burns the turn.

orca orchestration send --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`PLAN_WRITTEN`); `--outcome failed` when you could not (`BLOCKED`). Never encode failure only in prose.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 90000 --json` over guessing; the coordinator answers with `reply`. The call blocks and shell tools kill long commands, so keep the timeout short: if it returns without a reply, run `orca orchestration ask --resume <message_id from the first call> --timeout-ms 90000 --json` again until the answer arrives.

That's it. Do NOT commit — the coordinator handles git.
```

---

## Mode B: Revise a plan (Step 2 CHANGES_REQUESTED — fresh worker)

The coordinator dispatches Mode B after the plan reviewer returned `CHANGES_REQUESTED` and the coordinator has triaged the findings into the AUTHORIZED_CHANGE_LEDGER (see `orca-dev/SKILL.md` "## Authorized Change Ledger"). The ledger is the single authoritative input for this dispatch — work only on its open ACCEPTED / PARTIALLY_ACCEPTED items.

```
You are the plan-revision stage of orca-dev: a fresh worker revising an implementation plan after a plan review returned blocking findings. You did NOT write this plan and you have no memory of it — read it from disk first. Do not rewrite it from scratch: apply only the changes the coordinator has authorized via the ledger below.

You may read anything in the repository, but write ONLY the plan file below and your report file. Do not modify source code or tests. Do NOT run `git commit` / `git push` — the coordinator handles git.

## Plan file to revise

`<absolute path>`

Read it in full (including frontmatter) before editing — the file on disk is authoritative.

## AUTHORIZED_CHANGE_LEDGER

`<absolute path to docs/plans/<slug>.ledger.json>`

<paste open ledger items inline — the coordinator inlines ACCEPTED / PARTIALLY_ACCEPTED entries so you don't need to re-parse JSON>

The ledger is the authoritative scope for this revision. Items not appearing as ACCEPTED / PARTIALLY_ACCEPTED here are NOT authorized — do not act on them.

## Reviewer findings behind these items (context only, verbatim)

<paste the reviewer's BLOCKING lines for the ledger items above — they explain WHY each change is required>

These lines are context for understanding the authorized changes. They do NOT widen scope: where a finding suggests more than its ledger item authorizes, the ledger wins.

## Revision scope contract

Apply only open ACCEPTED / PARTIALLY_ACCEPTED ledger items.

For each edit, preserve a narrow causal chain:

  accepted blocker → required plan change → exact sections touched.

Do NOT:

- act on NITs;
- perform a general consistency pass;
- add new requirements, guards, flags, diagnostics, APIs, tests, dependencies, or edge-case handling unless they are necessary to fix an accepted blocker;
- rewrite unrelated sections for clarity;
- restructure phases/tasks unless the accepted blocker explicitly requires it.

If a ledger item appears wrong or already fixed:
return `rejected — <reason>` or `already_fixed — <section>` for that ledger id.

If fixing an accepted blocker requires broader scope than the ledger lists:
do NOT apply the broader change silently. Stop the revision and return
`NEEDS_AUTHORIZATION: <ledger id> requires <extra change> because <reason>`
so the coordinator can extend the ledger before you continue.

Preserve the existing frontmatter structure; update only what this revision actually changes.

## Reporting (Orca worker_done — REQUIRED, exactly once)

1. Write your full report to `[REPORT_FILE]`. Its FIRST line must be exactly one bare token from: `REVISED` | `NEEDS_AUTHORIZATION` | `BLOCKED`. After line 1 the report contains, in order: the updated plan file path (same file); per ledger item one line `<id>: fixed | rejected | already_fixed | needs_authorization — <one-line note + sections_changed list>`; `no_nits_applied: true|false` (MUST be `true` unless the coordinator explicitly authorized a NIT in the ledger); `deferred_observations: [<unrelated issue you noticed but did NOT edit>, ...]` — empty list if none; and a one-sentence summary of the revision shape (e.g., "fixed Ф2 contract gap; deferred two cosmetic observations"). Keep the plan file itself clean.
2. Then, from your own terminal, send exactly one `worker_done` using the task id and dispatch id from the Orca preamble at the top of this task. `orca` is a plain shell command on PATH — run the line below through your shell/command tool exactly as written. Do not look for an `orca` tool in any tool registry or inventory: none exists, and searching for one only burns the turn.

orca orchestration send --type worker_done --subject "<the same token>" --body "<3 sentences: what you did, what you found, what is left>" --task-id <task_id> --dispatch-id <dispatch_id> --outcome <succeeded|failed> --report-path "[REPORT_FILE]" --files-modified "<comma-separated paths you changed; omit the flag if none>" --json

3. `--outcome succeeded` when you produced the requested artifact (`REVISED`); `--outcome failed` when you could not (`NEEDS_AUTHORIZATION`, `BLOCKED`). Never encode failure only in prose. If the token is `NEEDS_AUTHORIZATION`, the worker_done body must carry the `NEEDS_AUTHORIZATION: <ledger id> requires <extra change> because <reason>` line verbatim.
4. After sending worker_done, end your turn and idle. Do not start more work. If you are blocked before completion, prefer `orca orchestration ask --question "<specific question>" --timeout-ms 90000 --json` over guessing; the coordinator answers with `reply`. The call blocks and shell tools kill long commands, so keep the timeout short: if it returns without a reply, run `orca orchestration ask --resume <message_id from the first call> --timeout-ms 90000 --json` again until the answer arrives.
```

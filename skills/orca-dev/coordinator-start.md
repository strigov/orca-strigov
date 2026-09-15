# Coordinator reference: start

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

## Triage

```
Frontend-only task (.tsx/.jsx/.vue/.svelte/.css/.scss, or "UI", "дизайн", "компонент", "страница", screenshot with UI intent)?
  new UI / redesign → frontend-implementer; simple tweak → frontend-implementer — models and routes in roles.md
  → still the full protocol: a one-phase plan on the default profile is cheap, and there is no plan-less path (Steps 3–5 key off the plan file).
Else single-file change, <~20 lines, no architectural judgment? → quickfix (cascade in roles.md) — see `## Quickfix path`
Else → full protocol.
Ambiguous → ask once.
```

Full-stack requests always go through the full protocol; the plan writer splits BE and FE into separate phases with an explicit contract.


## Quickfix path

No plan, no review workers, one worker. 1. Branch check as in Step 2 (never commit to `main` without the user's words). 2. `run-create` if no run is bound; `[REPORT_FILE]` = `$("$WS" --name quickfix-<slug>)/quickfix-<ATTEMPT>.md` (a plan-less workspace). 3. Fill `prompts/quickfix-prompt.md` (the ONE file path, the user's words verbatim), `task-create`, attach (Antigravity = Path B). 4. Verdicts: `DONE` → check only the report's `## Tests` section is non-empty and `payload.filesModified` ⊆ the listed path; both true → commit those files by name (unless the user opted out), report `Committed:`. `DONE_WITH_CONCERNS`, files outside the path, or an empty test section → do not commit; tell the user and offer the full protocol. `BLOCKED` / `NEEDS_CONTEXT` → same handling as Step 3. You never read the diff (Rule 2).


## Before Step 1 — in-progress plans

Inspect `docs/plans/*.md` (or the repo's plan dir) for top-level `status: in-progress`, including plans whose phases are all committed. A top-level `done` is excluded only when final-review/delivery evidence and the completion commit are confirmed per Durable progress; prepared or unproven markers still count as unfinished. None → Step 1. One → "Found in-progress plan: <slug> (phase <id> — <scope>). Continue or start new?" — wait. Several → list, ask. On continue: `run-use --id <orca_run>` (or `run-create` if missing, then record it), skip Steps 1–2, apply Durable-progress checks, resume at the right step.

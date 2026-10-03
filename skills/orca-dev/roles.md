# orca-dev — role matrix

The single source of truth for **who does what, on which model, at which effort**. Everything else refers to roles by name. Launch mechanics live in `orca-recipes.md`.

Model ids pass through Orca (`--model` / `--effort`) or custom argv (`-c model_reasoning_effort=<effort>` for Codex). Never `ultra` unless the user says the word; `max` only where the table says so or the user asks by name (it bills ×1.5). Antigravity Flash carries its level in the id and takes no `--effort`; Pro ignores effort. Fable has no pipeline role.

## Families

[C6](contracts/c6-protocol-validation.md) reads these exact model-to-family facts
for actual launches; an unknown model stays unverifiable and grants no role or
fallback. The actual model counts, not the agent CLI.

FAMILY_MODELS: {"gpt-6-luna":"OpenAI","gpt-6-astra":"OpenAI","gpt-5.6-luna":"OpenAI","gpt-5.6-sol":"OpenAI","chatgpt-web/pro":"OpenAI","opus":"Anthropic","fable":"Anthropic","sonnet":"Anthropic","gemini-3.8-flash-high":"Google","gemini-3.7-flash-high":"Google"}

A model id absent above gets a family only from one exact provider prefix (a full
Claude id such as `claude-opus-5-5` from a verified transcript). A Claude CLI alias
in an assignment matches an actual full id starting with its listed prefix.

FAMILY_PREFIXES: {"claude-":"Anthropic"}

MODEL_ALIASES: {"opus":"claude-opus-","sonnet":"claude-sonnet-","fable":"claude-fable-","haiku":"claude-haiku-"}

| family | agent CLI | Orca agent id | models used here |
|---|---|---|---|
| OpenAI | `codex` | `codex` | `gpt-6-astra`, `gpt-6-luna` (`gpt-5.6-luna`, `gpt-5.6-sol` and `chatgpt-web/pro` stay listed only so recorded launches of earlier runs keep their family; they are assigned to no role) |
| Anthropic | `claude` | `claude` | `opus`, `sonnet` |
| Google | `agy` (Antigravity CLI) | `antigravity` | `gemini-3.8-flash-high` |

`agy` can also run Anthropic models (`claude-opus-4-6-thinking`, `claude-sonnet-4-6`); for the family rule the **model's** actual family counts, not the CLI's.

**Family rule.** A reviewer must be outside ALL actual author families of each reviewed unit (files and both contract sides), including contributors from earlier revisions, fixes and fallbacks. Check it before every reviewer dispatch, including every availability fallback, risk escalation, substitution and experiment below; a different CLI or fresh terminal does not change the family. Same family across *different* artifacts is fine. For a mixed branch, split assignments only where each unit is fully covered by an independent reviewer; complementary assignments share one capped round. A fallback is allowed only if independent for its units; otherwise use another already allowed independent route or stop with incomplete acceptance. A unit every known family authored has no independent reviewer: only the user may release it, in their own words, through C6 `waive-independence` for one named reviewer family and step. Never add a model, invent a fallback, downgrade a planner or exceed the caps to obtain approval.

Only the coordinator dispatches; workers never delegate (orca-recipes.md §0–§1). Every Codex worker has an explicit model, the effort below and proven `-c features.multi_agent=false`, so Codex always uses custom Path B.

## Roles

| role | step | primary | fallback / escalation | write? | freshness |
|---|---|---|---|---|---|
| `coordinator` | all | the main Codex or Claude Code session running this skill, on its actual model; a new Codex coordinator is recommended as `gpt-6-astra` `high` with explicit `-m` (never `chatgpt-web/pro`) | — | bookkeeping only (Rule 1) | one session |
| `plan-writer` | 1 (all complexities) | **claude `opus` `xhigh`** | Opus availability failure: one retry in a fresh terminal, then stop and ask the user — no automatic downgrade | plan file only | fresh |
| `plan-reviser` | 2 | **claude `opus` `high`** (reuse the author's terminal) | author context lost: claude `opus` `high` fresh with announced full handoff, no downgrade | plan file only | retained reviser; actual context loss → fresh full handoff |
| `plan-reviewer` | 2 | codex `gpt-6-astra` `xhigh` (ordinary and complex plans) | Astra unavailable → stop and ask the user (the only other family, Gemini, is not a plan reviewer here); never Opus — it authored the plan | no | fresh every substantive round (cap 4) |
| `implementer` | 3, 4 fix rounds | **antigravity `gemini-3.8-flash-high`** (level `high` in the id; no `--effort`) | availability fallback → codex `gpt-6-luna` `max`; reasoning escalation (BLOCKED + diagnosis `NEEDS_MORE_REASONING`) → codex `gpt-6-astra` `high` in a FRESH terminal; justified hard implementation route: codex `gpt-6-astra` `xhigh` (explicit choice, announced) | yes | same terminal across fix rounds; a model change is always a new terminal |
| `frontend-implementer` | 3, 4 fix rounds (frontend-only phases) | claude `opus` `high` for new UI / redesign; claude `sonnet` `medium` for simple tweaks | availability fallback → antigravity `gemini-3.8-flash-high` — announced | yes | same terminal across fix rounds |
| `gate` | 3.5 | `bin/verify-gate` script (no model) | script `NO_COMMANDS` / `NEEDS_JUDGMENT` → antigravity `gemini-3.8-flash-high` `high` (a script `GATE_FAIL` goes back to the implementer, not to a worker) | no | fresh |
| `review-primary` | 4.1 | claude `opus` `high` | claude `opus` `xhigh` on `risk: SECURITY / DATA_LOSS` phases or in fused-loop round 4 (the last round before the cap; rounds > 4 do not exist); Opus unavailable → codex `gpt-6-astra` `high` only if independent of all authors — announced, otherwise an already allowed independent route or incomplete acceptance. Frontend phases (Claude wrote the code): see substitutions below | no | fresh every round |
| `review-control` | 4.2 | codex `gpt-6-astra` `high` | implementer was a Codex model (Luna/Astra) → claude `opus` `high` (Astra never reviews OpenAI-written code; 4.1 and 4.2 are then both Opus in fresh terminals); Astra unavailable → claude `opus` `high` only if independent of all authors of the reviewed unit — announced, otherwise an already allowed independent route or incomplete acceptance | no | fresh every round |
| `synthesizer` | 4.5 | antigravity `gemini-3.8-flash-high` `high` | codex `gpt-6-luna` `max` | `docs/reviews/*` only | fresh |
| `review-final` | 5 | claude `opus` `high` | every phase written only by Claude (frontend-only plan) → codex `gpt-6-astra` `high`; Opus unavailable → codex `gpt-6-astra` `high` only if independent of all authors of each reviewed unit — announced, otherwise an already allowed independent route or incomplete acceptance. Mixed-author branch: independent assignments covering every unit | no | fresh every round (cap 2) |
| `diagnosis` | BLOCKED / impasse summaries (`prompts/diagnosis-prompt.md`) | claude `opus` `high` | justified hard diagnosis route: codex `gpt-6-astra` `xhigh` (explicit choice, announced) | no | fresh |
| `quickfix` | trivial path | antigravity `gemini-3.8-flash-high` `high` | codex `gpt-6-luna` `max` | yes | fresh |
| `integration-check` | parallel groups | `bin/verify-gate` script → antigravity `gemini-3.8-flash-high` `high` | — | no | fresh |

## Family-rule substitutions

The defaults assume Gemini-written code. When the cascade or the frontend route puts an author in a reviewer's family, substitute and say so in the state line. Rows cover units authored only by the named family; mixed units follow the Family rule. Fallbacks never override these exclusions (no Astra/Luna review of OpenAI-authored units, no Opus/Sonnet review of Anthropic-authored units).

| code written by | 4.1 primary | 4.2 control | Step 5 final |
|---|---|---|---|
| Gemini (Flash) — default | claude `opus` `high` (`xhigh` per the 4.1 risk / last-round rule) | codex `gpt-6-astra` `high` | claude `opus` `high` |
| Codex (Luna / Astra, after fallback or escalation) | claude `opus` `high` (`xhigh` per the 4.1 risk / last-round rule) | claude `opus` `high` | claude `opus` `high` |
| Claude (frontend phases, or a Gemini→Claude fallback) | codex `gpt-6-astra` `high` | codex `gpt-6-astra` `high` | codex `gpt-6-astra` `high` for these units; split mixed-branch assignments under the Family rule (never Opus on a Claude-authored unit) |

## Planning profiles

- **`opus` (the only profile, 2026-10-04):** Claude `opus` `xhigh` writes; Claude `opus` `high` revises in the author's terminal (context loss → fresh Opus `high`, announced full handoff); Codex `gpt-6-astra` `xhigh` reviews.
- The former `astra` and `pro` profiles are retired: with Opus as the author, an OpenAI plan written by Pro would leave no independent reviewer. `--planner pro` is refused with that explanation; the bridge notes stay in `references/bridge-incidents.md` for history.

State the profile in the Step 1 status line.

## Implementer cascade — transition rules

1. antigravity `gemini-3.8-flash-high`.
2. On an availability failure — positive current host launch/exit/failure evidence, or an accepted, durably settled `worker_done --outcome failed` naming quota / rate limit / auth / launch (recipes §6; silence, timeout or idle never prove it), after confirming no unresolved writer and telling the user → codex `gpt-6-luna` `max` in a fresh terminal; its fix rounds continue in that terminal.
3. On `BLOCKED` + diagnosis `NEEDS_MORE_REASONING` → codex `gpt-6-astra` `high`, always in a FRESH terminal (the model is fixed at launch), with the fresh-fallback re-brief carrying the BLOCKED and diagnosis reports by path.

A justified hard route `codex gpt-6-astra xhigh` may be chosen explicitly for complex tasks, announced with rationale. No model change on other diagnoses, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `NEEDS_AUTHORIZATION`, `GATE_FAIL` or `REVIEW_BLOCKING`. After a fallback the ledger and reports carry the context (`prompts/implementer-prompt.md` fresh-fallback re-brief). A retained terminal whose Task is durably settled is not an active writer.

## Provider notes

Every Codex launch passes an explicit `--model`: the user's `~/.codex/config.toml` defaults to `chatgpt-web/pro`, and an unqualified `codex` would route through the bridge. Bridge mechanics and incidents: [references/bridge-incidents.md](references/bridge-incidents.md), only when `--planner pro` is opted in. Antigravity's timer and login-race behaviour: orca-recipes.md §2 and §6.

## Prompt profile selection

Prompt profiles change only instruction shape, never roles, efforts, families or
fallback eligibility. Selection and assembly live in prompt-routing.md.

PROMPT_PROFILES: {"gpt-6-astra":"outcome-v1"}

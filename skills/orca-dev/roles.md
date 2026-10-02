# orca-dev — role matrix

The single source of truth for **who does what, on which model, at which effort**. `SKILL.md` and every prompt template refer to roles by name; nothing else hardcodes a model. Launch mechanics (how a role becomes an Orca worker) live in `orca-recipes.md`.

Model ids are provider-opaque strings passed through Orca (`--model` / `--effort`) or through custom argv. Effort values are provider-specific: Codex `low|medium|high|xhigh|max` (never `ultra` unless the user says the word); Claude `low|medium|high|xhigh|max` — **Fable is currently not assigned to any pipeline role; its former roles run on Opus (complex plan review and 4.1 risk/last-round review at `xhigh`, diagnosis at `high`). Opus code review (4.1 ordinary rounds, 4.2 substitution/fallback, 5 final) and diagnosis use `high`; plan review, the 4.1 risk/last-round escalation, the explicit `opus` planning profile and frontend implementation use `xhigh`. Codex Astra runs at `xhigh` in every role. `max` is billed at ×1.5 since the September 2026 pricing change — never use it unless the user asks for it by name**; Antigravity `low|medium|high`.

## Families

C6 validates actual launch model families and the minimum independent coverage
against [runtime-contracts.md](runtime-contracts.md#c6--protocol-validation-and-resume).
All author families for each changed unit survive fallback/fix waves; a reviewer
must be outside every author family for its assigned files and both contract
sides. Complementary final assignments share one capped round. Unknown origin
cannot establish independence; agent CLI family does not override its actual model.

The C6 validator reads the following exact model-to-family facts for saved launch
receipts. Unknown model identities remain unverifiable; this record grants no
new role assignment or fallback. Compare the actual model, including when an
agent CLI can launch a model from another family.

FAMILY_MODELS: {"gpt-5.6-luna":"OpenAI","gpt-5.6-sol":"OpenAI","gpt-6-astra":"OpenAI","chatgpt-web/pro":"OpenAI","opus":"Anthropic","fable":"Anthropic","sonnet":"Anthropic","gemini-3.8-flash-high":"Google","gemini-3.7-flash-high":"Google"}

A model id absent above gets a family only from one exact provider prefix
(a full Claude id such as `claude-opus-5-5` read from a verified transcript);
any other unknown id stays unverifiable. A Claude CLI alias in an assignment
matches an actual full id that starts with its listed prefix.

FAMILY_PREFIXES: {"claude-":"Anthropic"}

MODEL_ALIASES: {"opus":"claude-opus-","sonnet":"claude-sonnet-","fable":"claude-fable-","haiku":"claude-haiku-"}

| family | agent CLI | Orca agent id | models used here |
|---|---|---|---|
| OpenAI | `codex` | `codex` | `gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-6-astra`, `chatgpt-web/pro` (GPT Pro via the codex-chatgpt-web bridge — opt-in planning alternative only) |
| Anthropic | `claude` | `claude` | `opus`, `sonnet` |
| Google | `agy` (Antigravity CLI) | `antigravity` | `gemini-3.8-flash-high` |

`agy` can also run Anthropic models (`claude-opus-4-6-thinking`, `claude-sonnet-4-6`); for the family rule the **model's** actual family counts, not the CLI's.

**Family rule.** A reviewer must be outside ALL actual author families of each reviewed unit, including contributors from earlier revisions/fixes. Check this before every reviewer dispatch, including every availability fallback, risk escalation, substitution and experiment below; a different CLI or a fresh terminal does not change the model family. Same-family across *different* artifacts is fine (Opus may write an explicitly selected legacy-profile plan revision and, as a separate fresh worker, review independently authored code). For a mixed branch, split assignments only where each unit can be fully covered by an independent reviewer; no unit may be left unreviewed. A fallback below is allowed only if independent for its assigned units; otherwise announce another already allowed independent route for that role, preserving its stated selection conditions, or stop with incomplete acceptance. A unit already authored by every known family has no independent reviewer: only the user may release it, in their own words, through C6 `waive-independence` for one named reviewer family and step. Do not add a model, invent a fallback, downgrade a planner, or exceed the existing caps to obtain approval.

**No worker multi-agent fanout.** All modeling roles are dispatched by the coordinator via Orca. Every actual Task spec must carry the literal mandatory boundary from `orca-recipes.md` §1 and pass its pre-dispatch presence check; a reference to this file is insufficient. Dispatched workers must not delegate to native subagents or Orca workers. Independently, every Codex worker launch/reuse must prove native multi-agent delegation disabled (`-c features.multi_agent=false`, verified on codex-cli 0.154.0), with model/effort from this matrix. The documented `worker-start` path cannot carry/prove the setting, so use the supported custom Path B even with trusted hooks; do not edit user configuration or rely on defaults.

## Roles

| role | step | primary | fallback / escalation | write? | freshness |
|---|---|---|---|---|---|
| `coordinator` | all | The main Codex or Claude Code terminal running this skill; it keeps its actual existing session/model. For a new Codex coordinator, native Sol medium (`gpt-5.6-sol` `medium`) is recommended with explicit `-m` (never `chatgpt-web/pro`: the bridge is never for the coordinator). Claude Code support does not change worker roles or select a new coordinator model | — | bookkeeping only (Rule 1) | one session |
| `plan-writer` | 1 (all complexities) | **codex `gpt-6-astra` `xhigh`** | opt-in alternative: codex `chatgpt-web/pro` (explicit `--planner pro`); Astra availability failure: one retry in a fresh terminal, then stop and ask the user — no automatic downgrade; `--planner opus` is an explicit user override only | plan file only | fresh |
| `plan-reviser` | 2 | **codex `gpt-6-astra` `xhigh`** (reuse the native author; after a `pro` initial plan the FIRST revision uses a fresh native terminal with announced full handoff, then reuses it) | native author context lost: codex `gpt-6-astra` `xhigh` fresh with announced full handoff, no downgrade; explicit `opus` profile: retain claude `opus` `xhigh`, or replace with that same profile and announced full handoff if lost | plan file only | retained reviser; first Pro revision or actual context loss → fresh full handoff |
| `plan-reviewer` | 2 | claude `opus` `xhigh` (ordinary and complex plans) | writer on the explicit `opus` profile → codex `gpt-5.6-sol` `max`, only if independent of all authors of the reviewed unit; otherwise another already allowed independent route or incomplete acceptance | no | fresh every substantive round (cap 4) |
| `implementer` | 3, 4 fix rounds | **antigravity `gemini-3.8-flash-high`** (level `high` in the id; no `--effort`) | availability fallback → codex `gpt-5.6-luna` `max`; reasoning escalation (BLOCKED + diagnosis `NEEDS_MORE_REASONING`) → codex `gpt-5.6-sol` `max` in a FRESH terminal; justified hard implementation route: codex `gpt-6-astra` `xhigh` (explicit choice, announced) | yes | same terminal across fix rounds; a model change is always a new terminal |
| `frontend-implementer` | 3, 4 fix rounds (frontend-only phases) | claude `opus` `xhigh` for new UI / redesign; claude `sonnet` `medium` for simple tweaks | availability fallback → codex `gpt-5.6-luna` `max` — announced | yes | same terminal across fix rounds |
| `gate` | 3.5 | `bin/verify-gate` script (no model) | script `NO_COMMANDS` / `NEEDS_JUDGMENT` → antigravity `gemini-3.8-flash-high` `high` (a script `GATE_FAIL` goes back to the implementer, not to a worker) | no | fresh |
| `review-primary` | 4.1 | claude `opus` `high` | claude `opus` `xhigh` on `risk: SECURITY / DATA_LOSS` phases or in fused-loop round 4 (the last round before the cap; rounds > 4 do not exist); Opus unavailable → codex `gpt-5.6-sol` `xhigh` only if independent of all authors — announced, otherwise an already allowed independent route or incomplete acceptance. Frontend phases (Claude wrote the code): see substitutions below | no | fresh every round |
| `review-control` | 4.2 | codex `gpt-5.6-sol` `xhigh` | implementer was a Codex model (Luna/Sol/Astra) → claude `opus` `high` (Sol/Astra never reviews OpenAI-written code; 4.1 and 4.2 are then both Opus in fresh terminals); Sol unavailable → claude `opus` `high` only if independent of all authors of the reviewed unit — announced, otherwise an already allowed independent route or incomplete acceptance. Experimental control review for units with no OpenAI authors: codex `gpt-6-astra` `xhigh` (explicit experiment, announced; never an automatic fallback) | no | fresh every round |
| `synthesizer` | 4.5 | antigravity `gemini-3.8-flash-high` `high` | codex `gpt-5.6-luna` `medium` | `docs/reviews/*` only | fresh |
| `review-final` | 5 | claude `opus` `high` | every phase written only by Claude (frontend-only plan) → codex `gpt-5.6-sol` `xhigh`; Opus unavailable → codex `gpt-5.6-sol` `xhigh` only if independent of all authors of each reviewed unit — announced, otherwise an already allowed independent route or incomplete acceptance. Mixed-author branch: independent assignments covering every unit | no | fresh every round (cap 2) |
| `diagnosis` | BLOCKED / impasse summaries (`prompts/diagnosis-prompt.md`) | claude `opus` `high` | justified hard diagnosis route: codex `gpt-6-astra` `xhigh` (explicit choice, announced) | no | fresh |
| `quickfix` | trivial path | antigravity `gemini-3.8-flash-high` `high` | codex `gpt-5.6-luna` `max` | yes | fresh |
| `integration-check` | parallel groups | `bin/verify-gate` script → antigravity `gemini-3.8-flash-high` `high` | — | no | fresh |

Claude is used in judgment roles (plan review, reviews, diagnosis) and for frontend implementation. Mechanical work (gate, synthesis, quickfix) stays on Google/OpenAI so the Anthropic quota is spent on judgment.

## Family-rule substitutions

The defaults above assume the code was written by Gemini. When the cascade or the frontend route puts an author in a reviewer's family, substitute — and say so in the state line. The rows are for units authored only by the named family; mixed units must satisfy the Family rule above. Availability fallbacks never override these exclusions: OpenAI-authored units cannot fall back to Sol/Astra review; Anthropic-authored units cannot fall back to Opus/Fable review. If all existing independent routes for the role are unavailable, stop with incomplete acceptance.

| code written by | 4.1 primary | 4.2 control | Step 5 final |
|---|---|---|---|
| Gemini (Flash) — default | claude `opus` `high` (`xhigh` per the 4.1 risk / last-round rule) | codex `gpt-5.6-sol` `xhigh` (or experimental Astra `xhigh`) | claude `opus` `high` |
| Codex (Luna / Sol / Astra, after fallback or escalation) | claude `opus` `high` (`xhigh` per the 4.1 risk / last-round rule) | claude `opus` `high` | claude `opus` `high` |
| Claude (frontend phases) | codex `gpt-5.6-sol` `xhigh` | codex `gpt-5.6-sol` `xhigh` | codex `gpt-5.6-sol` `xhigh` for these units; split mixed-branch assignments under the Family rule (never Opus on a Claude-authored unit) |

## Planning profiles

- **`astra` (default for all task complexities):** Initial plan and every revision = Codex `gpt-6-astra` `xhigh`. Revisions reuse the author terminal/context; actual context loss uses the same profile with announced full handoff. Plan review = Claude `opus` `xhigh` for ordinary and complex plans.
- **`pro` (explicit opt-in alternative only):** Selected only when user explicitly specifies `--planner pro` or "план на Pro". Round 1 = Pro (`chatgpt-web/pro`) writes → Claude `opus` `xhigh` reviews. Rounds 2+ = Codex `gpt-6-astra` `xhigh` revises (fresh terminal with announced full handoff, because Pro does not revise) → Claude `opus` `xhigh` reviews; subsequent revisions reuse that retained Astra terminal. Pro is used for the initial plan only — never for revisions. Regular startup/planning does not depend on bridge health.
- **`opus` (legacy explicit user override):** Selected only if the user explicitly specifies `--planner opus`. Claude `opus` `xhigh` writes/revises → Codex `gpt-5.6-sol` `max` reviews, all rounds. This is an explicit override only, never an automatic availability fallback.

Selecting: default is `astra`. The user may explicitly specify `--planner pro|opus` or "план на Pro" / "обычный план". State the profile in the Step 1 status line.

## Implementer cascade — transition rules

```
antigravity gemini-3.8-flash-high (high)
  │  availability failure: positive current execution-host launch/exit/failure evidence,
  │  or an accepted, durably settled worker_done --outcome failed identifying quota / rate
  │  limit / auth / launch error. Follow the recovery receipt and nextAction per recipes §6.
  │  Silence, timeout, idle or uncertain attachment never prove failure. Before retry,
  │  confirm no unresolved live or unverifiable write task remains → tell the user, then:
  ▼
codex gpt-5.6-luna (max)          ← fresh terminal; fix rounds continue in THIS terminal
  │  BLOCKED + diagnosis token NEEDS_MORE_REASONING →
  ▼
codex gpt-5.6-sol (max)           ← always a FRESH terminal (the model is fixed at launch —
                                    `--model` cannot be combined with `--terminal`, and Path B
                                    bakes it into argv); the fresh-fallback re-brief carries the
                                    BLOCKED report and the diagnosis report by path
```

A retained terminal whose Task is durably settled is not an active writer; preserve it for legitimate context reuse. A failed Task status or an attempted stop alone is not proof that an unresolved execution host stopped. Read current host/worker/terminal evidence and `nextAction` before recovery.

Hard implementation route: an explicit justified choice of `codex gpt-6-astra xhigh` is permitted for complex tasks without requiring an extra mandatory cascade step, announced with rationale.

What does **not** trigger a model change: `BLOCKED` with any other diagnosis, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `NEEDS_AUTHORIZATION`, a `GATE_FAIL`, or a `REVIEW_BLOCKING`. Those are handled by the protocol at the same model.

Fix rounds after a fallback: the ledger plus the report file carry the context; a fresh terminal gets the fresh-fallback re-brief block from `prompts/implementer-prompt.md`.

## Pro (`chatgpt-web/pro`) — operational notes

- Every Codex launch in this protocol passes an explicit `--model`: the user's `~/.codex/config.toml` defaults to `chatgpt-web/pro`, and an unqualified `codex` would route the role through the bridge by accident.
- Bridge mechanics, observed failure modes, their diagnosis and retry rule live in
  [references/bridge-incidents.md](references/bridge-incidents.md); read it only when
  the bridge is actually opted in (`--planner pro`).

## Antigravity (`agy`) — operational notes

- **Its timer ("Schedule") is a quota sink, not a wait.** A `Schedule(90s: …)` one-shot timer pings the model every 30 s ("Still waiting. Remaining time …"), and Flash answers each ping with a log read and a new timer. Observed 2026-09-02 on Windows: a worker waiting for `cargo test --workspace` made ~13 `streamGenerateContent` calls per minute for 40 minutes (360 timers in an hour) and drained the five-hour quota from full to 10 % without producing anything. The implementer prompts now tell workers to block inside one shell call (long timeout, or `Start-Sleep`/`sleep` inside the command) instead. If you see a worker's screen cycling `Schedule → Read(task log) → Waiting…`, steer it once with `orca terminal send`: "Stop using the timer; wait for the test with a single blocking shell command (`Start-Sleep 300` then check the process), then continue." A quota exhaustion mid-phase is an availability failure → Codex fallback per the cascade.
- Login race: see `orca-recipes.md` ("Antigravity's login menu is a race, not a logout").

## Effort cheat-sheet

| role | flag |
|---|---|
| Claude Opus code review (4.1 ordinary rounds, 4.2, 5 final) and diagnosis | `--effort high` |
| Claude Opus plan review, 4.1 risk/last-round escalation, `opus` planning profile, frontend implementation | `--effort xhigh` |
| Claude Sonnet frontend tweak | `--effort medium` |
| Codex Astra (plan writer/reviser, hard diagnosis/implementation route, experimental control review) | `--effort xhigh` (`-c model_reasoning_effort=xhigh` in custom argv) |
| Codex Sol (plan fallback review, implementer reasoning escalation) | `--effort max` (`-c model_reasoning_effort=max` in custom argv) |
| Codex Sol (control review, frontend substitution) | `--effort xhigh` (`-c model_reasoning_effort=xhigh` in custom argv) |
| Codex Sol coordinator recommendation | `--effort medium` |
| Codex Luna fallback | `--effort max` (`-c model_reasoning_effort=max` in custom argv) |
| Codex Luna as synthesizer fallback | `--effort medium` |
| Antigravity Flash | none — `gemini-3.8-flash-high` carries the level; agy rejects `--effort` for it |
| Pro | none — the bridge fixes the ChatGPT mode; Codex-side effort flags are ignored |

## Prompt profile selection

Prompt profiles change only instruction shape, not the roles, efforts, families,
experimental opt-ins or fallback eligibility above. Selection and assembly live
in prompt-routing.md. The coordinator recommendation remains unchanged.

PROMPT_PROFILES: {"gpt-6-astra":"outcome-v1"}

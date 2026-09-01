# orca-dev — role matrix

The single source of truth for **who does what, on which model, at which effort**. `SKILL.md` and every prompt template refer to roles by name; nothing else hardcodes a model. Launch mechanics (how a role becomes an Orca worker) live in `orca-recipes.md`.

Model ids are provider-opaque strings passed through Orca (`--model` / `--effort`) or through custom argv. Effort values are provider-specific: Codex `low|medium|high|xhigh|max` (never `ultra` unless the user says the word); Claude `low|medium|high|xhigh|max` — **`high` maps to a low internal setting (25); judgment roles use `xhigh`. `max` is billed at ×1.5 since the September 2026 pricing change — never use it unless the user asks for it by name**; Antigravity `low|medium|high`.

## Families

| family | agent CLI | Orca agent id | models used here |
|---|---|---|---|
| OpenAI | `codex` | `codex` | `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `chatgpt-web/pro` (GPT Pro via the codex-chatgpt-web bridge) |
| Anthropic | `claude` | `claude` | `opus`, `fable`, `sonnet` |
| Google | `agy` (Antigravity CLI) | `antigravity` | `gemini-3.7-flash-high` |

`agy` can also run Anthropic models (`claude-opus-4-6-thinking`, `claude-sonnet-4-6`); for the family rule the **model's** family counts, not the CLI's.

**Family rule.** The writer and the reviewer of the same artifact are never from the same family. The coordinator checks this before every reviewer dispatch by looking up both roles' families in this file; a violation is a protocol bug, not a judgment call. Same-family across *different* artifacts is fine (Opus may write the plan revision and, as a separate fresh worker, review the code).

## Roles

| role | step | primary | fallback / escalation | write? | freshness |
|---|---|---|---|---|---|
| `coordinator` | all | Codex (the terminal running this skill) — model per user's own config | — | bookkeeping only (Rule 1) | one session |
| `plan-writer` | 1 (Mode A) | **codex `chatgpt-web/pro`** (opt-in "strong" profile, see below) | claude `opus` `xhigh` | plan file only | fresh |
| `plan-reviser` | 2 (Mode B) | claude `opus` `xhigh` | — | plan file only | fresh every round |
| `plan-reviewer` | 2 | round 1: claude `fable` `xhigh` when the writer was Pro; otherwise codex `gpt-5.6-sol` `max` | rounds 2+: codex `gpt-5.6-sol` `max` (the reviser is Opus, so the reviewer must leave the Anthropic family) | no | fresh every round |
| `implementer` | 3, 4 fix rounds | **antigravity `gemini-3.7-flash-high` effort `high`** | availability fallback → codex `gpt-5.6-luna` `max`; reasoning escalation (BLOCKED + diagnosis "needs more reasoning") → codex `gpt-5.6-terra` `max` | yes | same terminal across fix rounds |
| `frontend-implementer` | 3, 4 fix rounds (frontend-only phases) | claude `opus` `xhigh` for new UI / redesign; claude `sonnet` for simple tweaks | — | yes | same terminal across fix rounds |
| `gate` | 3.5 | `bin/verify-gate` script (no model) | script red or no `verify:` commands → antigravity `gemini-3.7-flash-high` `high` | no | fresh |
| `review-primary` | 4.1 | claude `opus` `xhigh` | claude `fable` `xhigh` on SECURITY / DATA_LOSS phases or fused-loop round ≥ 3; Opus fallback if Fable unavailable — announced, never silent | no | fresh every round |
| `review-control` | 4.2 | codex `gpt-5.6-sol` `xhigh` | — | no | fresh every round |
| `synthesizer` | 4.5 | antigravity `gemini-3.7-flash-high` `high` | codex `gpt-5.6-luna` `medium` | `docs/reviews/*` only | fresh |
| `review-final` | 5 | claude `opus` `xhigh` | — | no | fresh every round (cap 2) |
| `diagnosis` | BLOCKED / impasse summaries | claude `fable` `xhigh` | claude `opus` `xhigh` — announced | no | fresh |
| `quickfix` | trivial path | antigravity `gemini-3.7-flash-high` `high` | codex `gpt-5.6-luna` `max` | yes | fresh |
| `integration-check` | parallel groups | `bin/verify-gate` script → antigravity `gemini-3.7-flash-high` `high` | — | no | fresh |

Claude is used **only** in judgment roles (plan revision, reviews, diagnosis) and for frontend implementation. Mechanical work (gate, synthesis, quickfix) stays on Google/OpenAI so the Anthropic quota is spent on judgment.

## Planning profiles

- **`strong` (default when the bridge is healthy):** round 1 = Pro writes → Fable xhigh reviews. Rounds 2+ = Opus xhigh revises → Sol max reviews. Pro is used for the initial plan only — never for revisions.
- **`standard`:** Opus xhigh writes → Sol max reviews, all rounds. This is the automatic fallback when Pro is unavailable, and the profile to pick explicitly for small plans (Pro turns run 10–25 minutes each).

Selecting: the user may say `--planner pro|opus` or "план на Pro" / "обычный план". Without a choice, use `strong` if `orca status` is fine AND the bridge preflight in `orca-recipes.md` passes; otherwise `standard`, and say which one you picked in the Step 1 status line.

## Implementer cascade — transition rules

```
antigravity gemini-3.7-flash-high (high)
  │  availability failure: worker-start/dispatch fails to attach, worker_done --outcome failed
  │  whose body names quota / rate limit / auth / launch error, or no heartbeat AND no
  │  worker_done for 20 min with an idle terminal → tell the user, then:
  ▼
codex gpt-5.6-luna (max)          ← fresh terminal; fix rounds continue in THIS terminal
  │  BLOCKED + diagnosis verdict "needs more reasoning" →
  ▼
codex gpt-5.6-terra (max)         ← same terminal as Luna when Luna was the implementer
                                    (thread retained); fresh with the BLOCKED report otherwise
```

What does **not** trigger a model change: `BLOCKED` with any other diagnosis, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `NEEDS_AUTHORIZATION`, a `GATE_FAIL`, or a `REVIEW_BLOCKING`. Those are handled by the protocol at the same model.

Fix rounds after a fallback: the ledger plus the report file carry the context; a fresh terminal gets the fresh-fallback re-brief block from `prompts/implementer-prompt.md`.

## Pro (`chatgpt-web/pro`) — operational notes

- Runs through the `codex-chatgpt-web` bridge (ChatGPT Temporary Chat + tunnel-backed tool calls). One planning turn observed at 9–27 minutes. Bridge cap: 5 concurrent browser turns — the planner is always the only one.
- Failure modes seen: `turn_token invalid, expired, or revoked` mid-turn; ChatGPT DOM drift. Both are availability failures → **one retry in a FRESH terminal** (a new Codex thread = a new Temporary Chat; the same terminal would reuse the retained chat that already contains the failure, and the worker then gives up before its first command — observed 2026-09-01), then fall back to the `standard` profile and tell the user.
- Mechanism of the token failure (bridge 4.0.7, upstream issue miuuyy/codex-chatgpt-web#274): the bridge marks the browser turn completed while the ChatGPT model is still in its tool loop; every later tool claim is rejected. It is triggered by long runs of `codex_tool_inventory` discovery calls between real tool calls — the model hunting for an `orca` tool that does not exist. The prompt templates therefore say explicitly that `orca` is a shell command; keep that line when editing a template. Direct shell/patch calls without discovery chains stayed inside the safe window in every test (single call, 4 sequential calls, resumed thread, `ultra`).
- Telling the two apart: `grep 'valid=false' ~/Library/Application\ Support/Codex\ Web\ GPT/logs/launcher.jsonl` shows the rejected claims with their `retiredTurn`; a worker report claiming the token was rejected "before the first command" with no `valid=false` line at that time is the model giving up, not the bridge.
- Every Codex launch in this protocol passes an explicit `--model`: the user's `~/.codex/config.toml` defaults to `chatgpt-web/pro`, and an unqualified `codex` would route the role through the bridge by accident.

## Effort cheat-sheet

| role | flag |
|---|---|
| any Claude judgment role | `--effort xhigh` |
| Claude Sonnet frontend tweak | `--effort medium` |
| Codex Luna / Terra / Sol (plan) | `--effort max` (`-c model_reasoning_effort=max` in custom argv) |
| Codex Sol control review | `--effort xhigh` |
| Antigravity Flash | `--effort high` |
| Pro | none — the bridge fixes the ChatGPT mode; Codex-side effort flags are ignored |

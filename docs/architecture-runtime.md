# Target runtime architecture: one launch path, one model source per agent

Status: target design, 2026-09-28. Implementation plan:
`docs/plans/2026-09-28-path-b-consolidation.md`. Until that plan is finished the
skills describe the transitional state (Path B default, Path A kept for Claude
terminal reuse) and this document describes where they are going.

## Why

The Bureau run of 2026-09-25/26 (`docs/tasks/2026-09-26-claude-model-evidence.md`)
produced ten C6 incidents in two days. One was external (Orca writes the prompt
before the Claude Code TUI accepts input, `docs/smoke-runs.md`). The other nine
were the plugin contradicting itself: C6 was written for a fresh `worker-start`
receipt with a full `launch.effective`, while the recipes had already moved Codex,
Antigravity and finally Claude to operator-created terminals (Path B) and to
terminal reuse, neither of which carries a model. Each incident was closed by
adding a special case to `protocol_state.py` (now 1166 lines, 272 `require`
calls, mirrored by hand in 918 lines of PowerShell). The coordinator loads about
35k words of instructions per run, with the same rules restated in up to six
files.

The fix is structural: one launch path, one model source per agent, terminals
the coordinator owns outright, and a rule that stops C6 from growing by special
cases.

## Principles

1. **One launch path.** Every worker is created by the coordinator with an explicit
   argv, waited for with `wait-agent-ready`, and given work with
   `dispatch --inject`. Follow-ups inject into the same handle. `worker-start` is
   not used; there is no Path A and no `origin_start` chain.
2. **One verified model source per agent, in a table.** C6 does not choose between
   receipts. For each `provider.id` there is exactly one admissible source; the
   coordinator's word, saved argv and comments are never sources.
3. **Terminals are the coordinator's resource.** The coordinator created them, so
   it records them and closes them when their last Dispatch is accepted. No
   inference from release results.
4. **C6 grows by generalization only.** A false positive is fixed by widening or
   removing a check, never by adding a branch for the case at hand. Every check
   traces to a contract sentence and to a test built from a real artifact.
5. **One canonical place per rule.** A rule lives in one file; other files link to
   it and never restate its numbers or wording.
6. **POSIX and PowerShell change together**, with shared fixtures and explicit
   per-platform results, as `AGENTS.md` already requires.

## Launch

```
orca terminal create --worktree <selector> --command "<argv per roles.md>" --json   → handle h, incarnationId
"$BIN/wait-agent-ready" h <agent>                                                    → TUI drawn, composer ready, idle
orca orchestration dispatch --task <task> --to h --inject --json                     → Dispatch
```

Per-agent argv stays in `orca-recipes.md` §2 (Codex with `features.multi_agent=false`
and hook bypass, Antigravity with the level in the model id, Claude with
`--model/--effort`). `wait-agent-ready claude` waits for the banner **and** the
composer prompt, then idle, so an inject never lands before the TUI accepts input.

Follow-up on the same agent (fix rounds, context answers, plan revisions):
`dispatch --task <next> --to h --inject`. A model change is always a new terminal.

Known Claude Code behaviour: injected input renders as a paste and in a minority
of starts the worker asks whether to run it. The worker boundary prefix says to
begin immediately; if the worker still asks, the coordinator answers once with
`terminal send --text "Yes. Execute the task above now." --enter` and records it.
No second inject, no new Dispatch.

## Model evidence

| `provider.id` | admissible source | builder | C6 result when absent |
|---|---|---|---|
| `codex` | `worker-show` → `projection.provider.model` (Orca reports it) | none | UNVERIFIABLE |
| `claude` | `model_evidence{kind:"claude-transcript"}`: frozen Claude Code session bound by the Orca preamble | `protocol-state claude-model-evidence` | UNVERIFIABLE |
| `antigravity` | `model_evidence{kind:"antigravity-log"}`: frozen conversation transcript plus the CLI log that created it | `protocol-state antigravity-model-evidence` | UNVERIFIABLE |

Rules:
- If Orca reports `provider.model` **and** evidence is supplied, they must agree;
  disagreement is `conflicting actual model facts` (INVALID).
- The observation carries no `start` and no `origin_start`. `bind-dispatch` takes
  `observation` and, for Claude and Antigravity, `model_evidence`.
- Family comes from `roles.md`: `FAMILY_MODELS` for aliases and provider ids,
  `FAMILY_PREFIXES` for full ids from transcripts, `MODEL_ALIASES` to match an
  assignment alias to a full id.
- Binding a transcript to a Dispatch uses the Orca preamble. The preamble
  sentence and the argument patterns live in one constant block with a fixture
  copied from a real preamble; a text mismatch is UNVERIFIABLE with a reason that
  names the expected phrase, never a Python exception and never INVALID.
- Evidence builders copy live files once and hash the copy; C6 verifies the copy.
  A malformed copy (mid-write) is UNVERIFIABLE with "rerun the builder".

## Terminal lifecycle

The coordinator saves every `terminal create` receipt as
`<workspace>/terminal-create-<ATTEMPT>.json`. Those receipts are the registry:
a handle without a saved create receipt is not the coordinator's.

`bin/close-worker-terminal <handle> <workspace>` (with a `.ps1` port) closes a
terminal only when all of these hold, and prints the receipts it used:
- a saved create receipt names the handle and `terminal show` reports the same
  `incarnationId`;
- `worker-list` shows every Dispatch on the handle settled and none pending;
- the caller passes `--after-accept <dispatch>` naming the accepted last Dispatch.

Otherwise it exits non-zero with the failing condition and closes nothing. The
prose rule in recipes §5 is replaced by this helper. `worker-release` remains
for Orca-owned resources; it is not expected to close a Path B terminal.

Retention across rounds is the default for writers (implementer, plan author)
until their phase or plan is committed; readers (reviewers, gate worker,
diagnosis, synthesizer) are closed after their report is accepted.

## C6 shape

Superseded on 2026-10-03 by `docs/plans/2026-10-03-c6-transition-checker.md`: the
validator is three files per backend — `protocol_state` (every decision, ≤ 450
lines), `protocol_facts` (input readers, model sources, evidence) and
`protocol_tools` (`summary`, `migrate`) — with the same split on both sides so
parity is checked file by file. The organisation below described the v1 file:

1. constants and roles facts (preamble block, caps, tokens);
2. model sources (the table above, one function per row) and `family`;
3. artifact identity: `source_files`/`input_files`, snapshot and package comparison
   used identically by evidence, closures, script gates and commit facts;
4. report format and bindings;
5. ledger closure (one rule for code fixes, one for plan fixes);
6. actions.

Removed with Path A: `launched_receipt` as a model source, `reused_model`,
`origin_start`, the `start` field, the incarnation chain checks. Removed as dead:
the "missing effective launch model" check after `reused_model`, the inline copy
of `frozen()`. Fixed: `barrier` counts a script gate only when `covered` would
accept it; code-closure `historical` uses the same `base == head` condition as
the CHECK path.

Tests: `tests/fixtures/orca/` holds sanitized copies of real receipts and
transcripts (a `worker-show`, a `terminal create`, a Claude session, an
Antigravity transcript and log, a Codex `worker-show` with a model). Every model
source has a positive and a negative test on those files. Synthetic fixtures
remain for shape variations only.

Rule for future changes (also in `AGENTS.md`): a C6 rejection observed in a real
run is first reproduced as a fixture test; the fix generalizes or removes a
check; a new `require` needs a new contract sentence.

## Documentation layout

| rule | canonical file | others |
|---|---|---|
| worker boundary prefix | `orca-recipes.md` §1 | link only |
| launch, readiness, inject, follow-up | `orca-recipes.md` §2 | link only |
| waiting, fleet collection | `orca-recipes.md` §4, runtime C7 | link only |
| settlement, retention, closing | `orca-recipes.md` §5 | link only |
| verdict tokens and procedure | `coordinator-core.md` Verdicts | link only |
| caps and format-correction limit | `runtime-contracts.md` C6 | link only, no numbers |
| models, efforts, families, fallbacks | `roles.md` | link only |
| report path scheme | `runtime-contracts.md` Immutable attempts | instances only |
| commit trailer, staging | `coordinator-finish.md` Auto-commit | link only |

`SKILL.md` keeps the hard rules and the map; stage docs keep procedure and
link to the canonical rule instead of restating it. Target: the always-on set
(`SKILL.md`, `coordinator-core.md`, `roles.md`, orchestration `SKILL.md`,
`role-contract.md`, `coordinator-session.md`) under 7k words.

## Migration

- Runs bound before this change carry `start`/`origin_start` in accepted history.
  Resume reads recorded `provenance` families and report hashes only; verify
  this in code before removing the fields, and if resume needs them, keep a
  read-only acceptance of recorded history for one release.
- `docs/smoke-runs.md` records a live run on the new path before the plugin
  version is bumped.
- The Orca upstream report on the fresh `worker-start` race stays a draft until
  the user approves sending it; the plugin no longer depends on that path either way.

## Out of scope

Weakening C6 to accept a model from the coordinator, argv or comments; changing
user CLI configuration; replacing Orca's lifecycle (Run, Task, Dispatch,
`worker_done`) or the C4/C5 runner contracts.

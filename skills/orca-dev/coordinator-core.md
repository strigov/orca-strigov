# Coordinator reference: core

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

## THE HARD RULES (read first, re-read at every step)

### Rule 1 — no writes on the coordinator

You do NOT write production code, tests, or source edits. Not one line, however trivial. Every file change goes through a worker: full protocol → `implementer` / `frontend-implementer`; trivial single-file edit → `quickfix`. If you are about to open an editor tool or `apply_patch` on a source path — STOP and dispatch.

The only writes you perform yourself:
- the plan file's YAML frontmatter (status flips, `commits:` ranges, `orca_run:`, `plan_base:`, per-phase `base:`);
- the ledger `docs/plans/<slug>.ledger.json`;
- immutable original-request records, prompt/spec files, JSON state proposals,
  saved raw Orca receipts, CHECK closure records and resume outputs under the
  plan workspace (`"$WS" --name <slug>` works before the plan exists);
- byte-for-byte plan revision archives in that workspace, before accepting any
  plan report; `artifact.source_path` records the live plan path;
- git bookkeeping: `git add <names>`, `git commit`, `git mv` for archival, worktree/merge/branch commands for parallel groups;
- Orca bookkeeping: `orca orchestration ...`, `orca terminal ...`, `orca worktree ...`.

### Rule 2 — no research on the coordinator

You do NOT read production code, grep the source, run tests/linters/builds "to see what's failing", or perform semantic reviews of the plan body (semantic and simplicity reviews belong to the `plan-reviewer` in Step 2; coordinator performs only fast mechanical structure checks). "Just a quick look" is research — STOP.

Research channels: codebase questions → the plan writer explores the repo itself (that is why planning runs on a strong model); diagnosis of `BLOCKED` / unclear failures → a `diagnosis` worker; plan content → workers read it by path.

Reads you may perform yourself:
- plan-file YAML frontmatter (first ~40 lines); `docs/plans/*.md` listings;
- `git status / log / diff --stat / branch / rev-parse / merge-base / worktree list`;
- the ledger file;
- the plan workspace directory listing (`"$WS"` output) and the one-line stdout of `"$RPKG"` / `"$GATE"`;
- a worker's **report file** — but only the parts each step names (verdict lines, `## Fix round <N>` section, BLOCKING/DEFER/NITS/CANNOT_VERIFY sections). Never a review package (`review-*.diff`) — the diff must not transit your context;
- a `CANNOT_VERIFY` item's literal `CHECK:` command, executed exactly as written;
- Orca receipts and `worker_done` messages.

**Rule 3 — large artifacts never transit your context.** C6 states, resumes and proposals (100–250 KB), fleet receipts, package manifests and sealed check results are files you reference by `{path,sha256}`, not text you read. To know where you are, run `"$BIN/protocol-state" summary <state-or-proposal.json>` (≈20 lines: barrier, active, rounds, open ledger ids, accepted, commits, waivers). To take one field from a receipt, query it (`--json` plus `jq -r .result.dispatch.status`, or a Python one-liner printing only that key). Never `cat`, `sed -n` or `Get-Content` such a file whole, and never paste one into a proposal by value. Build proposals by writing JSON that points at the files. If a helper prints a full state (validate does), do not re-read the file it wrote; use `summary`.

All three rules are model-independent. If you find yourself arguing a rule away, that is the violation.

### Pre-flight gate

On resume restore the unfinished barrier and use its permitted commands. Before
the first writer the closed allowlist permits: reading these skill references and
repository instructions; frontmatter and plan-directory listings; the Git
bookkeeping reads above; bundled orchestration references, `orca --version`, `orca status`,
`orca orchestration run-* / task-create / task-list / worker-list / worker-start /
dispatch / worker-show / check`; `orca terminal create / wait / read`; helper-path
resolution; `sdd-workspace --name <slug>`; `run-check capabilities` on POSIX;
`wait-agent-ready`; `wait-worker-event REQUEST_JSON`; `collect-worker-fleet REQUEST_JSON`; and
`protocol-state validate INPUT_JSON [RESUME_OUT]`; and the C8
`coordinator-session bind / checkpoint / status / hold / resume` commands.
Create the original-request, spec, state and raw receipt files needed by those
commands only in the owned workspace. Hash those files without reading source.
Native Windows uses the equivalent `.ps1` helpers and PowerShell invocation `&`;
`Get-FileHash` and UTF-8 JSON writes are permitted bookkeeping. Read-only installer
checks are `install.sh --check <repo>` / `install.ps1 -Check <repo>`; installation
changes still require existing user authorization. Bridge preflight applies only
to explicit bridge opt-in. C6 bootstrap uses the real supplied task before a plan
exists; it grants no general source search, semantic review or arbitrary tests.


## Role

Triage → resume-check → dispatch → wait → collect verdicts → bookkeeping (ledger, git, frontmatter) → transition → report. Judgment (plans, reviews, diagnosis) is never done here.


## Protocol state line (every turn)

Start every turn with:

`[orca-dev] step=<triage | resume-check | quickfix | 1-plan | 2-plan-review | 3-implement | 3.5-gate | 4-fused-review | synthesize | 4.6-integration | 5-final-review | 5-fix | commit | archive> phase=<Ф-id or —> round=<k>/<cap> base=<base7 or —> run=<orca run id or —> impl=<role/model or —> planner=<profile or —>`

If you cannot fill a field, you have lost protocol state: re-read the plan frontmatter, `git log --oneline -15`, `orca orchestration task-list --brief --json`, and this file before doing anything else.


## Durable progress

Use the deterministic C6 `protocol-state validate` barrier for every dispatch,
report acceptance, commit/advance and resume; read its input/receipt contract in
[runtime-contracts.md](runtime-contracts.md#c6--protocol-validation-and-resume)
on demand. Keep the compact JSON resume in the existing plan workspace. VALID
permits only the proposed action; INVALID/UNVERIFIABLE never permits completion.
Supply fresh complete fleet receipts before new ownership/review/commit, actual
Task/Dispatch observations, report bindings, C4/C5 artifacts and Git commit facts.
Use `collect-worker-fleet` for C6 inventory; it saves all pages without creating
Orca terminals. Copy its manifest's `fleet` array mechanically into the proposal,
not the receipt bodies into the conversation. A scoped/incomplete collection is
a barrier, never permission to create a scratch terminal or weaken C6.
Stage only authorized candidate paths before the gate/package freeze so the
reviewed source and semantic index are the actual commit candidate. Later index
or source changes invalidate that acceptance and require refreshed evidence.
Preserve old artifacts by hash and give each correction/fix report a new path.
Only the common [Report binding](runtime-contracts.md#report-binding) defines the
machine fields; pass its absolute `[RUNTIME_CONTRACTS_PATH]` and fill `[FROZEN_ASSIGNMENT]`
in every role template with the C6-frozen `{role, phase, round, artifact_id, snapshot_id}`
(the assigned artifact for readers; writers bind their completed snapshot instead). A worker never infers its role; a wrong BINDING role cannot be format-corrected. This mechanical check adds no semantic research to the coordinator.

Conversation memory does not survive compaction. Reconcile these durable records; frontmatter records intent and never overrides missing commit or acceptance evidence:

1. **Plan frontmatter** — per-phase `status`, `base:` (full BASE sha recorded before phase begins), `risk:`, `commits:` ranges, top-level `status`, `orca_run:` (the Orca Run id), `plan_base:` (the full commit SHA directly before the first plan commit — Step 5's merge base), `verify:` (the gate commands the writer recorded).
2. **Git history and commit receipts** — verify that the phase commit/range actually exists and matches the accepted delivery. A prepared `done`, an open-ended `commits: "<base7>.."`, or unrelated HEAD movement is not positive commit evidence.
3. **Ledger** `docs/plans/<slug>.ledger.json` — every triaged finding across all loops.
4. **Orca** — `orca orchestration run-use --id <orca_run>` rebinds you; `task-list --brief --json` shows what was dispatched and what settled; `worker-show --dispatch <id>` tells you whether a worker is still alive.

At skill start and after any compaction: read the frontmatter, `git log --oneline -15`, the ledger, and `task-list`; reconcile them with the settled Task/Dispatch receipts and the relevant report sections before choosing the next step.

- A phase is complete only when its accepted delivery and positive commit/range evidence agree. After a crash, recover the matching commit from Git history before attempting another commit; never commit the same delivery twice. Prepared `done`/`commits:` without this evidence remains unfinished and cannot authorize the next phase.
- When implementation is already present, restore the recorded unfinished verification, review, fix or commit barrier using the phase's recorded `base:` and `[IMPL_REPORT_FILE]`. `awaiting_commit` permits only the pending commit once the current candidate has the required accepted gate/reviews and no unresolved findings. Missing or stale verification/review evidence returns to the corresponding barrier (Step 3.5 and a fresh package when the tree changed), within the existing round caps; it never becomes permission to skip review or blindly re-dispatch implementation. Preserve the recorded review history and pending synthesis instead of restarting their loops. If the unfinished step cannot be established, retain the barrier and dispatch diagnosis.
- All phases committed with top-level `in-progress` means resume the unfinished Step 5, delivery verification or final bookkeeping. Even a prepared top-level `done` needs the final-review/delivery evidence and completion commit described below; it must not hide pending final work from resume discovery.
- Before any writer dispatch/reuse, inspect current Task/Dispatch and execution-host evidence per recipes §6. A live or unverifiable **unsettled write task** in this tree blocks another writer. An alive retained terminal whose Task is durably settled is not an active writer; it can preserve context and receive an authorized follow-up. Terminal idleness alone proves neither settlement nor death.


## Verdicts

Every worker ends with exactly one `worker_done`. You read three things from it: `subject` (the verdict token), `payload.outcome`, `payload.reportPath`. The report file's line 1 repeats the token; 4.1 reports also carry `SPEC:` (line 2) and `QUALITY:` (line 3); plan-review reports carry `## Simplicity` with `SIMPLICITY: OK | CHANGES_REQUESTED`.

| step | tokens |
|---|---|
| plan writer (Mode A / B) | `PLAN_WRITTEN` / `REVISED` \| `NEEDS_AUTHORIZATION` \| `BLOCKED` |
| plan review | `APPROVED` \| `CHANGES_REQUESTED` |
| implementer / frontend / quickfix | `DONE` \| `DONE_WITH_CONCERNS` \| `NEEDS_CONTEXT` \| `NEEDS_AUTHORIZATION` \| `BLOCKED` |
| gate (script or worker) | `GATE_OK` \| `GATE_FAIL` (script also `NO_COMMANDS` \| `NEEDS_JUDGMENT`) |
| 4.1 primary / 4.2 control / Step 5 | `REVIEW_OK` \| `REVIEW_BLOCKING` |
| synthesis | `SYNTHESIS_DONE` |
| integration check | `GATE_OK` \| `GATE_FAIL` |
| diagnosis | `NEEDS_MORE_CONTEXT` \| `NEEDS_MORE_REASONING` \| `PHASE_TOO_LARGE` \| `PLAN_WRONG` \| `IMPASSE_SUMMARY` |

Any review, gate or synthesis worker that could not produce its artifact at all returns the bare token `BLOCKED` with `--outcome failed` (its report's `## Reason` says why): one fresh re-dispatch of the same role, then escalate to the user.

Procedure: C6 exact-matches the `subject`'s leading token (text after `:` or a space is ignored), outcome and report line 1. Missing
mandatory binding/role fields → one format-correction Task/Dispatch, normally in
the retained terminal, with the same role/artifact/snapshot/round. Write a new
report and send one worker_done for that new Dispatch; never resend completion
for the settled Dispatch. Prior findings stay unresolved. A repeated defect is a
protocol blocker; conflicting identities or changed artifacts require corrected
facts/fresh substantive review, not a format-only waiver. Never infer approval
from prose or silently DEFER format errors.

A `worker_done` that Orca **rejects** (missing `--from` / `--dispatch-capability`, sender not the dispatch assignee) is not a verdict and not a reason to close the terminal: read the report's line 1 for the token, then re-inject into the same worker terminal "Resend your worker_done with the `--from` and `--dispatch-capability` values from the Orca preamble at the top of your task" — once Orca accepts it, proceed to settlement. Orca's own rule: never release on a rejected/stale `worker_done`, never substitute `terminal close` for release. `outcome: failed` with a valid token is a protocol verdict (`BLOCKED`, `NEEDS_*`); `outcome: failed` whose body names quota / rate limit / auth / launch / bridge errors is an **availability** failure → cascade per `roles.md`.


## Workspace scripts ($WS, $RPKG, $GATE)

Resolve once per session from the **actual loaded plugin**, not an old installed
skill link. Set `PLUGIN_DIR` to the absolute directory two levels above this
loaded file (it contains `plugin.json`, both host manifests, `skills/` and `bin/`).
Inside a Codex hook, `PLUGIN_ROOT` supplies that path; Claude hooks use
`CLAUDE_PLUGIN_ROOT`. Outside hooks use the observed
skill source path. A stale `ORCA_DEV_HOME` must never override it:

```bash
# Substitute the actual absolute plugin path observed when loading this file.
PLUGIN_DIR="<absolute-loaded-plugin-root>"
BIN="$PLUGIN_DIR/bin"
WS="$BIN/sdd-workspace"; RPKG="$BIN/review-package"; GATE="$BIN/verify-gate"
RUN="$BIN/run-check"; STATE="$BIN/protocol-state"
SESSION="$BIN/coordinator-session"
echo "WS=$WS RPKG=$RPKG GATE=$GATE"
```

On Windows (coordinator shell = PowerShell, see `orca-recipes.md` §9) use the native PowerShell ports instead — same names with a `.ps1` suffix, same arguments, exit codes and output shape, no bash / python3 / jq involved:

```powershell
$PluginDir = '<absolute-loaded-plugin-root>'
$BIN = Join-Path $PluginDir 'bin'
$WS = "$BIN\sdd-workspace.ps1"; $RPKG = "$BIN\review-package.ps1"; $GATE = "$BIN\verify-gate.ps1"
$RUN = "$BIN\run-check.ps1"; $STATE = "$BIN\protocol-state.ps1"
$SESSION = "$BIN\coordinator-session.ps1"
& $GATE <plan-file> <base-sha>    # e.g. & $GATE docs\plans\x.md a1b2c3d
```

- `"$WS" <plan-file>` prints the plan-scoped scratch directory (`.superpowers/sdd/<plan-basename>/`, self-ignoring) — home of prompt files, report files, review packages. Run it with cwd inside a track's worktree for parallel tracks. `"$WS" --name quickfix-<slug>` does the same for a plan-less quickfix.
- `"$RPKG" BASE HEAD [OUTFILE]` (committed range) or `"$RPKG" BASE WORKTREE OUTFILE` (working tree vs BASE) writes the review package; only its `wrote <path>: N commit(s), M bytes` line enters your context.
- `"$GATE" <plan-file> <base-sha> [repo-root]` runs the frontmatter's `verify:` commands and classifies failures against BASE; `--phase ID --checkpoint directed|integration|final` selects the declared scope. You read its line 1–2 and, on `GATE_FAIL`, pass its full output to the implementer.

Keep the plugin and `bin/lib/` together. Plugin-relative paths work after the
native skills and the old standalone orca-dev link are removed. Do not repair
global environment or recreate that link. Missing runtime files/dependencies
leave setup incomplete. The runner and state
JSON interfaces remain defined only in [runtime-contracts.md](runtime-contracts.md).


## Pre-dispatch checklist (every worker)

1. Build every Task spec as the exact mandatory worker-boundary prefix in `orca-recipes.md` §1, a blank line, then the filled role/follow-up body. Before Task creation AND dispatch/reuse, mechanically check that the actual spec begins with that literal prefix and has no unresolved declared template fields (literal brackets in user text, JSON or examples are data); missing prefix → repair the spec before sending. This applies to retries, fix rounds, context answers and format corrections too.
2. Absolute paths: repo root, plan, ledger, report file, review package.
3. The user's request verbatim where the template asks for it.
4. Self-contained: the worker sees nothing from your session.
5. Role, agent, model, effort taken from `roles.md`; for every reviewer, including availability fallbacks, check independence from ALL actual author families of each reviewed unit. Use only the existing allowed independent routes/substitutions; if none is available, stop with incomplete acceptance. Never `ultra`.
6. Launch path per `orca-recipes.md` §2: every fresh launch is Path B; Path A only reuses an existing Claude terminal with its `origin_start` proof. Every Codex worker requires an explicit model and the role's effort policy from `roles.md`, plus proven effective `-c features.multi_agent=false`, separately from the spec boundary. The documented Path A cannot carry/prove that setting, so use Path B even after hooks are trusted; verify launch evidence before reusing a Codex terminal. Follow the readiness evidence rules before `dispatch --inject`; a timeout does not permit dispatch/retry.
7. Round 2+: ledger path present and open ACCEPTED / PARTIALLY_ACCEPTED items inlined.
8. Review dispatches (4.1 / 4.2 / 5 / plan review): this round's freshly generated package path as `[DIFF_FILE]`, the implementer's report as `[IMPL_REPORT_FILE]` (read-only input), `[GLOBAL_CONSTRAINTS]` copied verbatim from the plan.
9. Anti-coaching scan on every reviewer spec: delete any sentence containing "do not flag", "don't treat", "not a defect", "at most Minor", "Minor at most", "the plan chose", "ignore the". Referencing settled ledger ids (`REJECTED_BY_SCOPE` / `DEFER`) is the only allowed form.
10. `[REPORT_FILE]` is always the worker's OWN report in the plan workspace, with
    a distinct path per Task/Dispatch. An implementer fix report includes the
    previous report as read-only context and its new `## Fix round <N>` evidence;
    do not overwrite bytes already referenced by an accepted hash.
11. Prompts are loaded on demand: read each template only when dispatching that specific role.


## Authorized Change Ledger

`docs/plans/<slug>.ledger.json` — one flat JSON array, transient (never committed), deleted at archival. Written only by the coordinator. `sdd-workspace <plan>` adds its path to the repository's local `.git/info/exclude`, so C4 snapshots and C5 packages never capture it; run it before creating the ledger. Item:

```json
{ "id": "P<r>-B<n> | PF-B<n> | F<r>-B<n> | G<r>-B<n> | FR<r>-B<n>",
  "reviewer": "plan-review | preflight | review-primary | review-control | gate | review-final",
  "decision": "ACCEPTED | PARTIALLY_ACCEPTED | REJECTED_BY_SCOPE | DEFER | NIT | ESCALATED_TO_HUMAN",
  "authorized_change": "<exact allowed change, or null>",
  "forbidden_expansions": [],
  "materiality": "BUILD_BREAK | ACCEPTANCE_CRITERIA | DATA_LOSS | SECURITY | REGRESSION | CONSISTENCY | NICE_TO_HAVE",
  "status": "open | fixed | rejected | deferred | verified-by-controller" }
```

Fixers receive only open ACCEPTED / PARTIALLY_ACCEPTED items; reviewers receive the ledger path. Reviewer classes (`MUST_FIX_NOW`, `REGRESSION_FROM_AUTHORIZED_FIX`, `DEFER`, `NIT`, `REJECTED_BY_SCOPE`) map to decisions at triage; only the first two are valid in a BLOCKING list. `ESCALATED_TO_HUMAN` is for `plan-mandated` findings and out-of-scope `NEEDS_AUTHORIZATION` — never handed to a fixer, never counted in loop control.


## Reporting cadence

One commentary line entering each step (`Plan ready → plan review r1/4 (plan-reviewer, model per roles.md)`), one per loop iteration with the verdict, no polling narration. Final answers are only for verified completion, an evidenced human hold or an explicitly status-only request, as defined in coordinator-session.md. A routine phase report does not end the turn. Availability fallbacks and family-rule substitutions are always stated.

Wait through recipes §4/C7. An empty CLI window, keepalive or tool-harness yield
is not a protocol iteration or a reason for `worker-show`/`worker-read`/screen
reads. Keep the same pending waiter; use the longest tool wait permitted by the
host. Inspect workers when the waiter returns a delivery, attention or error.


## Red flags — never

- Write source or tests yourself; research the codebase yourself; run tests yourself except via `"$GATE"`; read a diff (not even "a quick sanity check" after a quickfix).
- Launch/reuse a Codex worker without an explicit role model and proven effective `features.multi_agent=false`, or send any Task spec without the mandatory no-delegation prefix.
- Re-inject into a previous reviewer's terminal — reviewers are fresh every round; the only terminal reuse is the author/implementer thread (a model change/escalation is always a fresh terminal).
- Use `ultra` anywhere without explicit user request.
- Skip 4.1 and go to 4.2; run 4.2 after a blocking 4.1; review without this round's fresh package; review without a `GATE_OK` on the current tree.
- Pair a writer and a reviewer from the same model family for the same artifact.
- Tell a reviewer what not to flag; triage a `plan-mandated` item into ACCEPTED / REJECTED.
- Re-dispatch a phase with verified completion; treat prepared `done` as commit evidence; advance after failed/skipped commit or unresolved review; accept a phase with an open CANNOT_VERIFY; one fixer per finding in Step 5; report the whole plan done before final review, delivery verification and completion commit.
- Two writers in one working tree, more than two tracks, or parallelizing phases the plan did not group.
- Stop, close, retry or cascade because of timeout/idle alone. Forget to record a settled worker's reuse, retention or actual release result; retained/external/uncertain ownership is a reason to preserve an open terminal.
- Open a terminal per bookkeeping command, fleet page or wait; base64/copy receipt bodies through terminal reads. Use the existing shell helpers, keeping raw stdout in files.
- Resolve merge conflicts between tracks; delete a worktree with unmerged work; push, force-push, skip hooks, `--amend`; start on `main` without consent.
- Let a nit block progress.


## Files

- `./roles.md` — who runs what (models, efforts, cascades, family rule, planning profiles)
- `./orca-recipes.md` — launch paths A/B, blockers, waiting, release, retries
- `./prompts/plan-writer-prompt.md` (Mode A / Mode B), `plan-reviewer-prompt.md`, `implementer-prompt.md`, `frontend-implementer-prompt.md`, `verification-gate-prompt.md`, `review-primary-prompt.md`, `review-control-prompt.md`, `synthesize-review-prompt.md`, `final-review-prompt.md`, `quickfix-prompt.md`, `diagnosis-prompt.md`
- `../../bin/verify-gate`, `../../bin/review-package`, `../../bin/sdd-workspace`, `../../bin/wait-agent-ready`, `../../bin/wait-worker-event`, `../../bin/collect-worker-fleet` (+ their `.ps1` ports for Windows)

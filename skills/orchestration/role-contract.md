# Shared role and continuation contract

This is the one role-routing policy for all three Orca Strigov skills. It
governs workflow choice, not provider permissions or Orca lifecycle authority.
Read it before choosing a route. It never overrides the user's current scope,
pause, cancellation, permissions or a worker's authentic live assignment.

## Choose once, then restore

Apply in this order:

1. A live injected Task/Dispatch assignment makes this session a **worker**.
   Follow that assignment and its exact capability. Do not load orca-dev as a
   coordinator, spawn children or inherit the parent's coordinator binding.
2. A session already bound to a coordinator objective remains **coordinator**
   across messages, compaction, empty inboxes and phase boundaries. Restore its
   durable binding and pending barrier. "Continue", "what next?", "дальше" and
   "чего стоим?" do not reset its role. A question about status requests a
   status answer, not a new implementation or cancellation of existing work.
3. Select **full handoff** only when the user actually transfers ownership and
   does not want supervision/results from this session. "Another agent" or
   "another worktree" alone is not evidence of that transfer. A user's explicit
   transfer can change an existing objective's ownership, but is not proof that
   its implementation completed: preserve assignments and record that incomplete
   handoff before ending supervision.
4. In an unassigned main session, an implementation request or explicit
   orca-dev invocation selects **development coordinator**: load the sibling
   orca-dev/SKILL.md, bind the objective, then delegate. No pre-existing Run,
   Dispatch or extra word "supervise" is required. Create the Run during
   bootstrap. Standalone maintenance of this plugin follows its AGENTS.md.
5. Other requests to supervise agents, coordinate dependencies, monitor or
   collect results select **general coordinator** through orchestration.
6. Standalone terminal/worktree/browser/automation operations use orca-cli.
   Standalone explanations and reviews do not activate development coordination.

If intent is genuinely ambiguous, ask the smallest necessary question. Never
use absence of a Run, skill tag or repeated supervision request to demote an
established coordinator. Do not auto-resume an unrelated plan in a new session:
match the user's request, repository and recorded objective first.

## Authority boundaries

- orca-dev owns its development stages, role/model policy and acceptance gates.
- orchestration owns supervised Task/Dispatch/mailbox/resource mechanics.
- orca-cli owns direct terminal, worktree and other runtime operations.
- The authentic live worker preamble owns that worker's lifecycle credentials.
- Bundled references describe the supported Orca version. CLI --help and actual
  receipts establish syntax and current runtime facts, not a replacement role
  policy. Do not load the stock skills through `orca skills get` at runtime.

## Continue within the authorized objective

Settled workers are not the same as a finished phase; a committed phase is not
the same as a finished plan. After each accepted result, reconcile the durable
barrier and perform its next authorized action: dispatch, wait, fix, review,
commit, advance or finish. Never end merely with "next we should ..." when that
next action is already authorized. Progress messages are commentary, not final
answers. A live worker means wait on the existing delivery, not another launch.

Pause for an explicit user instruction, missing authority/access, a material
product choice, or a documented unresolved blocker/cap. Do not bypass acceptance
barriers to keep moving. A bounded no-progress escalation reports incomplete
work; it never marks the objective complete. User interruption always wins.

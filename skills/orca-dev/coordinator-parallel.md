# Coordinator reference: parallel

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

## Parallel groups (two tracks max)

Two pending phases sharing `parallel_group` run concurrently. Preconditions: plan approved, clean `git status` (the untracked ledger excepted), no live write task.

1. Flip both to `in-progress` and record the group-start HEAD as both phases' `base:`, commit `docs(plans): start parallel group <G>`.
2. Create both child worktrees with `orca worktree create --name <slug>-<phase>
   --setup run --json` before launching workers. C6 v2 has no group record: each
   track is an ordinary C6 phase state in its own worktree (its own workspace,
   actual `worktree_id`, `phase`, `base` = the group-start commit, the same plan
   bytes and a local ledger). You keep the group preconditions C6 no longer
   checks: two tracks at most, disjoint files, no producer/consumer dependency
   between them. Do the platform's installer check and any authorized trust
   setup before dispatch; native Windows uses `.ps1`. Launch only after each
   track's C6 proposal is VALID. A child never edits the shared plan.
3. Steps 3 → 3.5 → 4 per track independently; commit per track inside its worktree (source and test files only — the plan file stays untouched in the track).
4. Merge sequentially in the main tree: `git merge --no-ff <track-branch>` twice (branch name: `git -C <track-path> branch --show-current`); a conflict falsifies the plan's independence claim → `git merge --abort`, escalate.
5. Integration check (state `4.6-integration`): `"$GATE" <plan-file> <pre-merge-sha>` on the merged tree → `GATE_FAIL` → repair rounds, cap 2: fresh implementer repair (ledger item `G<r>-B1`) → Step 3.5 → one 4.1 round on the repair diff → commit `fix: repair integration of group <G>`.
6. Merge track ledgers into the main ledger (suffix colliding ids with the phase id), flip both phases `done` with full ranges, commit `docs(plans): complete parallel group <G>`, then `orca worktree rm` both tracks — only after `git branch --merged` lists both track branches.
7. Asymmetry: one track passes, the other escalates → merge the passing one, keep the failed worktree, escalate with its path. Never delete a worktree with unmerged work.

Each track's phase commit is confirmed by its own C6 state. After both merges,
the integration check and step 6, continue the main tree with a fresh C6 state
at the next unstarted phase (`base` = the group-completion commit); keep the
track states and reports in their workspaces as evidence.

State line during a group: append `tracks=<id>:<step>-r<k>,<id>:<step>-r<k>`.

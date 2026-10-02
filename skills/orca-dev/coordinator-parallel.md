# Coordinator reference: parallel

Detailed baseline protocol. Read with SKILL.md and prompt-routing.md.
REPORT_FILE always names the current Dispatch's fresh report; previous
reports are immutable. Standard template references do not override
role/profile selection. No runtime barrier is waived by this split.

## Parallel groups (two tracks max)

Two pending phases sharing `parallel_group` run concurrently. Preconditions: plan approved, clean `git status` (the untracked ledger excepted), no live write task.

1. Flip both to `in-progress`, commit `docs(plans): start parallel group <G>`.
2. Create both child worktrees with `orca worktree create --name <slug>-<phase>
   --setup run --json` before launching workers. Record their actual paths/IDs
   and the group-start parent HEAD in the immutable C6 `track_group` record
   (contracts/c6-protocol-validation.md, Child tracks and BASE). C6 verifies the plan content in
   parent history and each child, BASE ancestry, Run ownership registration and
   at most two active child tracks. The parent and unrelated trees consume no
   slots. Do the platform's installer check and any already-authorized trust
   setup before dispatch; native Windows uses `.ps1`. Launch with the existing
   settings/Path rules only after each C6 proposal is VALID. All helper calls use
   the child's cwd/workspace and local ledger. A child never edits the shared
   plan; its sealed group BASE and `state.base` are identical.
3. Steps 3 → 3.5 → 4 per track independently; commit per track inside its worktree (source and test files only — the plan file stays untouched in the track).
4. Merge sequentially in the main tree: `git merge --no-ff <track-branch>` twice (branch name: `git -C <track-path> branch --show-current`); a conflict falsifies the plan's independence claim → `git merge --abort`, escalate.
5. Integration check (state `4.6-integration`): `"$GATE" <plan-file> <pre-merge-sha>` on the merged tree → `GATE_FAIL` → repair rounds, cap 2: fresh implementer repair (ledger item `G<r>-B1`) → Step 3.5 → one 4.1 round on the repair diff → commit `fix: repair integration of group <G>`.
6. Merge track ledgers into the main ledger (suffix colliding ids with the phase id), flip both phases `done` with full ranges, commit `docs(plans): complete parallel group <G>`, then `orca worktree rm` both tracks — only after `git branch --merged` lists both track branches.
7. Asymmetry: one track passes, the other escalates → merge the passing one, keep the failed worktree, escalate with its path. Never delete a worktree with unmerged work.

After each verified merge, record its `track_commits` fact. Resume checks the
real accepted commit/tree and merge ancestry before freeing that slot. Keep the
group record and both completed/incomplete histories until group completion.

State line during a group: append `tracks=<id>:<step>-r<k>,<id>:<step>-r<k>`.

# orca-dev — native Windows differences (no WSL)

Companion to [orca-recipes.md](orca-recipes.md) §9. Load only on a native Windows
coordinator.

Load the complete plugin (see `docs/install-plugin.md` and `docs/install-windows.md`). Differences from macOS that the coordinator must apply:

- Your shell is PowerShell (Windows PowerShell 5.1 or pwsh 7). Every workspace script has a native PowerShell port: `& "$BIN\<script>.ps1" …` (`sdd-workspace.ps1`, `review-package.ps1`, `verify-gate.ps1`, `wait-agent-ready.ps1`, `wait-worker-event.ps1`, `collect-worker-fleet.ps1`, `run-check.ps1`, `protocol-state.ps1`, `coordinator-session.ps1`), with the same contracts as the POSIX originals. Keep `bin/lib/` dependencies. For Path B inspect `$LASTEXITCODE` immediately after readiness and inject only on success; otherwise follow §6. Never call `bash` or the extension-less originals on native Windows: `bash` can be the WSL launcher. `verify-gate.ps1` executes native PowerShell commands. Pass workers absolute Windows paths. Contract parity does not substitute for the platform results in `docs/plugin-validation.md`.
- `orca orchestration check --types "worker_done,escalation,question"` — quote comma-separated lists in PowerShell. Where a recipe pipes `--json` into `jq -r .result.terminal.handle`, use `(… --json | ConvertFrom-Json).result.terminal.handle` instead.
- Claude follows the same Path B default as on macOS (the fresh-start race is Orca/Claude Code timing, not platform-specific evidence; Windows is unmeasured); `claude-model-evidence` has a native port. Codex still requires Path B for proven native multi-agent disabling, independent of hook trust. Path B argv is the same text; Antigravity (`agy`) on native Windows is unverified — if `agy` is missing, the implementer cascade continues with its fallback per `roles.md` and the gate/synthesizer fallbacks apply; say so once.
- Resolve `$BIN` from the actual loaded plugin path, not a standalone skill junction or inherited `ORCA_DEV_HOME`. `install.ps1 -Check <repo>` is a read-only prerequisite/conflict check, not plugin registration. The explicit `-LegacySkill` option is for old installations only and must not be used alongside this plugin.
- The GPT Pro bridge (`codex-chatgpt-web`) has a native Windows build: available when opted into. Preflight per §7.
- Trust files live in the same places under `%USERPROFILE%` (`.claude.json`, `.gemini\antigravity-cli\settings.json`, `.codex\config.toml`); Claude Code keys `projects[]` with forward slashes (`C:/repo`), Antigravity's `trustedWorkspaces` with backslashes — `install.ps1` handles both. `install.ps1 -Repo <path>` handles the repo and its git worktrees; a parallel track's child worktree still needs `install.ps1 -Repo <track-path>` before the first dispatch (same rule as macOS).


For phase/checkpoint selection and exact reuse, load [runtime-contracts.md](runtime-contracts.md#c4--exact-inputs-and-verification-evidence) C4 on demand. Pass runner evidence paths and snapshot/origin ids; preserve required independent replay and record each new hypothesis. For review packages, C5 defines manifest validation, bounded part reads, real write-receipt provenance and producer/consumer coverage. Freeze identity before dispatch and verify it again before accepting a report; missing/stale/incomplete artifacts remain unresolved.


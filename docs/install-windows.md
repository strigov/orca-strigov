# Installing orca-dev on Windows

**Native** is the layout `install.ps1` sets up; **WSL2** reuses the Linux installer inside a distro. Native PowerShell 5.1/7 and isolated Ubuntu WSL helper tests are recorded in [controlled-pipeline-validation.md](controlled-pipeline-validation.md). WSL helper execution does not prove Orca can launch every model CLI inside that distro.

## A. Native Windows (PowerShell + Git for Windows)

Prerequisites, all on `PATH`:

| tool | how | note |
|---|---|---|
| Orca (Windows build) with orchestration enabled | orca.dev | `orca status --json` must report `runtime.state = ready` |
| Git for Windows | `winget install Git.Git` | provides `git`. Bash is **not** needed: the workspace scripts have native PowerShell ports (`bin\*.ps1`). `bash` on a stock Windows `PATH` is the WSL launcher in `System32` — the protocol never calls it |
| Codex CLI | `npm i -g @openai/codex` | coordinator and Codex workers; `%USERPROFILE%\.codex\` |
| Claude Code | `npm i -g @anthropic-ai/claude-code` or the native installer | judgment roles; `%USERPROFILE%\.claude.json` |
| Antigravity CLI (`agy`) | Google's installer | selected routes and fallbacks in `roles.md` |
| Python 3.9+ | test driver only | the `.ps1` helpers do not use it; a plan's own `verify:` commands may |
| jq | optional | the `.ps1` scripts and `install.ps1` parse JSON with `ConvertFrom-Json`; recipes' `jq` one-liners have PowerShell equivalents (`orca-recipes.md` §9) |

Install:

```powershell
git clone git@github.com:strigov/orca-strigov.git $HOME\orca-strigov
cd $HOME\orca-strigov
.\install.ps1                              # links the skill, sets ORCA_DEV_HOME, checks CLIs and hooks
.\install.ps1 -Repo C:\path\to\your\repo   # pre-trusts the repo and its git worktrees for Claude Code and Antigravity
.\install.ps1 -Check C:\path\to\your\repo  # read-only report; exit 1 on any WARN
```

If PowerShell refuses to run the script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (or `powershell -ExecutionPolicy Bypass -File .\install.ps1`).

What it does differently from `install.sh`:

- The skill link is a **symbolic link** when allowed (Developer Mode or an elevated shell), otherwise a **directory junction**. Canonical source and target are compared, including stale/dangling links. Only the leaf link can be removed, without recursion; its old target remains intact. An ordinary directory or an unknown reparse point is refused. Writes through linked parent directories or linked trust files are refused too.
- The installer writes User `ORCA_DEV_HOME` only after verifying the installed link points to this checkout. It reports User and Process values separately and does not change Process or Machine environment. Restart Orca to inherit User changes. For an explicitly authorized checkout in an existing terminal, use a process-only assignment such as `$env:ORCA_DEV_HOME = 'D:/Projects/orca-strigov'`; this example is this delivery's location, not an installer default. `-Check` diagnoses differences without repairing them.
- All six native entry points ship together with `bin\lib\`: `sdd-workspace.ps1`, `review-package.ps1`, `verify-gate.ps1`, `wait-agent-ready.ps1`, `run-check.ps1`, `protocol-state.ps1`. Runtime needs PowerShell and Git, with no Bash/python3/jq dependency. Gate commands run through the same owned runner with stdin closed, durable full logs and explicit deadlines. Packages preserve raw Git bytes. CLI interfaces and supported verification declarations are defined in [runtime-contracts.md](../skills/orca-dev/runtime-contracts.md).
- Per-repo trust: under pwsh 7 the installer parses `.claude.json` with `ConvertFrom-Json -AsHashtable`, because real files contain project keys that differ only in case (`D:/x` vs `d:/x`) and the default PSCustomObject form rejects them (Windows PowerShell 5.1 does too — run `install.ps1 -Repo` under pwsh if you hit that WARN). Claude Code on Windows keys `projects[]` with forward slashes (`C:/repo`); older builds used backslashes — the installer accepts either as trusted and writes the forward-slash key. Antigravity's `trustedWorkspaces` uses backslashes (verified on a real settings.json).
- Codex is not upgraded automatically (no Homebrew); an "Update available" prompt blocks worker input — keep Codex current yourself.
- The ChatGPT Pro bridge (`codex-chatgpt-web`) has a native Windows build (4.0.8 verified 2026-09-02, `%USERPROFILE%\.codex-chatgpt-web`, daemon `bun.exe … cli.js serve`): the opt-in `--planner pro` route is available when it is running; `install.ps1` reports it. Inside Orca the bridge doctor must be run with `CODEX_HOME` cleared (Orca points that variable at its own Codex home and the doctor then calls the integration "inconsistent") — the exact preflight is in `skills/orca-dev/orca-recipes.md` §7. Its log is `%APPDATA%\Codex Web GPT\logs\launcher.jsonl`.
- Repo paths with spaces produce a WARN: the bash scripts quote paths, but Orca argv and agy's trust matching are unverified with spaces.

Coordinator usage is the same (`$orca-dev <task>` in a Codex terminal inside Orca) with the differences listed in `skills/orca-dev/orca-recipes.md` §9: `.ps1` script calls, quoted `--types` lists, `ConvertFrom-Json` instead of `jq`, absolute Windows paths in worker prompts.

## B. WSL2

Everything runs inside the Linux distro; Windows stays a window manager. Requirements: Orca must be able to open its terminals **inside WSL** (not verified — check `orca terminal create` from a WSL shell), and every CLI (orca, codex, claude, agy, git, python3, jq) is installed in the distro. Then it is the macOS/Linux path:

```bash
git clone git@github.com:strigov/orca-strigov.git ~/orca-strigov && cd ~/orca-strigov
./install.sh && ./install.sh --repo /path/to/repo
```

`install.sh` uses Bash 3.2+ and Python 3.9+ stdlib. Homebrew update checks and bridge probes are optional; it never upgrades packages. It writes no persistent environment or shell profiles. Bash 3.2 compatibility has source-level evidence; the current POSIX runtime evidence uses Ubuntu Bash, not a macOS host.

## Isolated tests and evidence

Tests set `ORCA_DEV_TEST_HOME` only in a child environment, to an existing owned absolute directory. Both installers redirect trust/skill files there and skip external runtime/version/registration probes. PowerShell additionally reads/writes the simulated User value in `<test-home>/.orca-dev-user-environment.json`, preserving other keys; it never writes the real registry in this mode. Tests do not override HOME/USERPROFILE, and compare actual settings/registry digests before and after. A redirected test-home link is rejected. Temporary cleanup verifies ownership and never follows symlinks/junctions.

Check helpers independently from model routing. Use `orca skills get orchestration` for the Run's executable and preserve actual launch/release receipts; a retained process, timeout or old successful smoke is not current certification. The delivery evidence names missing platforms/capabilities explicitly and leaves the independent final suite pending until its owner records a real result.

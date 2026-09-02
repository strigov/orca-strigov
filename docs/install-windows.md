# Installing orca-dev on Windows

Two supported layouts. **Native** is the one `install.ps1` sets up; **WSL2** reuses the macOS/Linux installer inside a Linux distro. Both are untested by the author on real Windows hardware as of 2026-09-02 — the notes mark every assumption.

## A. Native Windows (PowerShell + Git for Windows)

Prerequisites, all on `PATH`:

| tool | how | note |
|---|---|---|
| Orca (Windows build) with orchestration enabled | orca.dev | `orca status --json` must report `runtime.state = ready` |
| Git for Windows | `winget install Git.Git` | provides `git`. Bash is **not** needed: the workspace scripts have native PowerShell ports (`bin\*.ps1`). `bash` on a stock Windows `PATH` is the WSL launcher in `System32` — the protocol never calls it |
| Codex CLI | `npm i -g @openai/codex` | coordinator and Codex workers; `%USERPROFILE%\.codex\` |
| Claude Code | `npm i -g @anthropic-ai/claude-code` or the native installer | judgment roles; `%USERPROFILE%\.claude.json` |
| Antigravity CLI (`agy`) | Google's installer | **unverified on native Windows.** Without it the implementer cascade starts at Codex Luna (`roles.md`) — the protocol still runs |
| Python 3 as `python3` | optional | the `.ps1` scripts do not use it; a plan's own `verify:` commands may |
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

- The skill link is a **symbolic link** when allowed (Developer Mode or an elevated shell), otherwise a **directory junction** (verified: Codex-side directory listing, Git Bash `readlink -f` and PowerShell all follow it). The installer also sets the user environment variable `ORCA_DEV_HOME` to the checkout; `SKILL.md` resolves `bin\` through it. Restart Orca after the first install so its terminals inherit the variable.
- The workspace scripts are native PowerShell ports: `bin\sdd-workspace.ps1`, `bin\review-package.ps1`, `bin\verify-gate.ps1`, `bin\wait-agent-ready.ps1` (PowerShell 5.1 and 7; no bash, python3 or jq). Same arguments, exit codes and stdout shape as the bash originals. `verify-gate.ps1` runs each `verify:` command in a child PowerShell with stdin closed (write them as PowerShell / native commands), junctions `node_modules` / `.venv` / `venv` into the BASE worktree instead of symlinking, and copies git output to review packages as raw bytes so the console code page never re-encodes a diff.
- Per-repo trust: under pwsh 7 the installer parses `.claude.json` with `ConvertFrom-Json -AsHashtable`, because real files contain project keys that differ only in case (`D:/x` vs `d:/x`) and the default PSCustomObject form rejects them (Windows PowerShell 5.1 does too — run `install.ps1 -Repo` under pwsh if you hit that WARN). Claude Code on Windows keys `projects[]` with forward slashes (`C:/repo`); older builds used backslashes — the installer accepts either as trusted and writes the forward-slash key. Antigravity's `trustedWorkspaces` uses backslashes (verified on a real settings.json).
- Codex is not upgraded automatically (no Homebrew); an "Update available" prompt blocks worker input — keep Codex current yourself.
- The GPT Pro bridge (`codex-chatgpt-web`) has a native Windows build (4.0.8 verified 2026-09-02, `%USERPROFILE%\.codex-chatgpt-web`, daemon `bun.exe … cli.js serve`): the `strong` planning profile works when it is running; `install.ps1` reports it. Inside Orca the bridge doctor must be run with `CODEX_HOME` cleared (Orca points that variable at its own Codex home and the doctor then calls the integration "inconsistent") — the exact preflight is in `skills/orca-dev/orca-recipes.md` §7. Its log is `%APPDATA%\Codex Web GPT\logs\launcher.jsonl`.
- Repo paths with spaces produce a WARN: the bash scripts quote paths, but Orca argv and agy's trust matching are unverified with spaces.

Coordinator usage is the same (`$orca-dev <task>` in a Codex terminal inside Orca) with the differences listed in `skills/orca-dev/orca-recipes.md` §9: `.ps1` script calls, quoted `--types` lists, `ConvertFrom-Json` instead of `jq`, absolute Windows paths in worker prompts.

## B. WSL2

Everything runs inside the Linux distro; Windows stays a window manager. Requirements: Orca must be able to open its terminals **inside WSL** (not verified — check `orca terminal create` from a WSL shell), and every CLI (orca, codex, claude, agy, git, python3, jq) is installed in the distro. Then it is the macOS/Linux path:

```bash
git clone git@github.com:strigov/orca-strigov.git ~/orca-strigov && cd ~/orca-strigov
./install.sh && ./install.sh --repo /path/to/repo
```

`install.sh` is macOS-first: the Homebrew Codex-update check and the `pgrep` bridge check are skipped when the tools are absent (INFO lines), everything else is portable bash 3.2 + python3.

## Known unknowns (verify on first use)

1. Does Orca on Windows open native PowerShell terminals, and does `worker-start --agent codex|claude` attach to them? (Path A)
2. Is `agy` installable on native Windows; if not, is the Luna-first cascade acceptable for the workload?
3. Does Antigravity on Windows key `trustedWorkspaces` with backslash paths (the installer assumes so, mirroring Claude Code's `projects` keys)?
4. Junction vs symlink for `%USERPROFILE%\.codex\skills\orca-dev`: does Codex's skill loader follow junctions? If not, enable Developer Mode and re-run `install.ps1` to get a real symlink.

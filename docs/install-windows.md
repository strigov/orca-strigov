# Installing orca-dev on Windows

Two supported layouts. **Native** is the one `install.ps1` sets up; **WSL2** reuses the macOS/Linux installer inside a Linux distro. Both are untested by the author on real Windows hardware as of 2026-09-02 — the notes mark every assumption.

## A. Native Windows (PowerShell + Git for Windows)

Prerequisites, all on `PATH`:

| tool | how | note |
|---|---|---|
| Orca (Windows build) with orchestration enabled | orca.dev | `orca status --json` must report `runtime.state = ready` |
| Git for Windows | `winget install Git.Git` | provides `git` **and `bash.exe`** — the protocol's `bin/` scripts are bash. Put `C:\Program Files\Git\bin` on `PATH` *before* `System32` (whose `bash.exe` is the WSL launcher) |
| Codex CLI | `npm i -g @openai/codex` | coordinator and Codex workers; `%USERPROFILE%\.codex\` |
| Claude Code | `npm i -g @anthropic-ai/claude-code` or the native installer | judgment roles; `%USERPROFILE%\.claude.json` |
| Antigravity CLI (`agy`) | Google's installer | **unverified on native Windows.** Without it the implementer cascade starts at Codex Luna (`roles.md`) — the protocol still runs |
| Python 3 as `python3` | python.org installer, tick "python3.exe alias", or `winget install Python.Python.3.12` | `bin/verify-gate` / `install.sh` call `python3` |
| jq | `winget install jqlang.jq` | used by the recipes' one-liners |

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

- The skill link is a **symbolic link** when allowed (Developer Mode or an elevated shell), otherwise a **directory junction**. Git Bash's `readlink -f` does not resolve junctions, so the installer also sets the user environment variable `ORCA_DEV_HOME` to the checkout; `SKILL.md` resolves `bin/` through it. Restart Orca after the first install so its terminals inherit the variable.
- Codex is not upgraded automatically (no Homebrew); an "Update available" prompt blocks worker input — keep Codex current yourself.
- The GPT Pro bridge (`codex-chatgpt-web`) is macOS-only: the planning profile is always `standard` (Opus → Sol).
- Repo paths with spaces produce a WARN: the bash scripts quote paths, but Orca argv and agy's trust matching are unverified with spaces.

Coordinator usage is the same (`$orca-dev <task>` in a Codex terminal inside Orca) with the differences listed in `skills/orca-dev/orca-recipes.md` §9: bash-prefixed script calls, quoted `--types` lists, absolute Windows paths in worker prompts.

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

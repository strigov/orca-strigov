# Installing the Orca Strigov plugin on Windows

Follow [plugin registration and migration](install-plugin.md) first. This is a
three-skill plugin with native PowerShell helpers and hooks, not a standalone
skill link. `install.ps1` checks prerequisites; `-Repo` explicitly grants repo
trust. Prior helper results in [controlled-pipeline-validation.md](controlled-pipeline-validation.md)
do not certify the new plugin/C8 guard. Current limits are recorded in
[plugin-validation.md](plugin-validation.md). WSL is a separate Linux runtime,
not evidence of native Windows behavior.

## A. Native Windows (PowerShell + Git for Windows)

The C3 runner requires Windows 10 1709 or newer and a filesystem supporting
`FileRenameInfoEx` with POSIX rename semantics (NTFS). This publishes a complete
JSON record without a missing-name window while compatible readers retain the
previous record. Readers denying DELETE sharing still block publication; the
runner retries only within its existing bounded allowance and fails closed,
retaining the complete temporary file. Unsupported filesystems do not fall back
to a multi-step replacement. See Microsoft's
[rename flags](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information).

Prerequisites, all on `PATH`:

| tool | how | note |
|---|---|---|
| Orca (Windows build) with orchestration enabled | orca.dev | `orca status --json` must report `runtime.state = ready` |
| Git for Windows 2.36+ | `winget install Git.Git` | provides `git`, including `worktree list --porcelain -z`. Bash is **not** needed: the workspace scripts have native PowerShell ports (`bin\*.ps1`). `bash` on a stock Windows `PATH` is the WSL launcher in `System32` — the protocol never calls it |
| Codex CLI | `npm i -g @openai/codex` | coordinator and Codex workers; `%USERPROFILE%\.codex\` |
| Claude Code | `npm i -g @anthropic-ai/claude-code` or the native installer | coordinator or worker roles; `%USERPROFILE%\.claude.json` |
| Node.js 18+ | Node.js installer | required only for the Claude coordinator hook adapter; it invokes native PowerShell without Bash/Python |
| Antigravity CLI (`agy`) | Google's installer | selected routes and fallbacks in `roles.md` |
| Python 3.9+ | test driver only | the `.ps1` helpers do not use it; a plan's own `verify:` commands may |
| jq | optional | the `.ps1` scripts and `install.ps1` parse JSON with `ConvertFrom-Json`; recipes' `jq` one-liners have PowerShell equivalents (`orca-recipes.md` §9) |

Install:

```powershell
git clone git@github.com:strigov/orca-strigov.git $HOME\orca-strigov
cd $HOME\orca-strigov
.\install.ps1                              # checks plugin source, duplicate skills and prerequisites
.\install.ps1 -Repo C:\path\to\your\repo   # pre-trusts the repo and its git worktrees for Claude Code and Antigravity
.\install.ps1 -Check C:\path\to\your\repo  # read-only report; exit 1 on any WARN
```

If PowerShell refuses to run the script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (or `powershell -ExecutionPolicy Bypass -File .\install.ps1`).

What it does differently from `install.sh`:

- Default mode writes no standalone skill link or User environment. Helpers
  resolve from the actual loaded plugin. Ignore stale `ORCA_DEV_HOME`; never use
  it to select a different helper version. Plugin registration and explicit
  hook trust remain separate from this prerequisite script.
- Only explicit `-LegacySkill` retains old symlink/junction installation and
  User `ORCA_DEV_HOME` behavior. It refuses ordinary directories and foreign
  linked parents, replaces only an inspected leaf link, and leaves the old
  target intact. Do not enable legacy and plugin installations together.
- All eight native entry points ship together with `bin\lib\`: `sdd-workspace.ps1`, `review-package.ps1`, `verify-gate.ps1`, `wait-agent-ready.ps1`, `wait-worker-event.ps1`, `collect-worker-fleet.ps1`, `run-check.ps1`, `protocol-state.ps1`. Runtime needs PowerShell and Git, with no Bash/python3/jq dependency. Gate commands run through the same owned runner with stdin closed, durable full logs and explicit deadlines. Packages preserve raw Git bytes. The fleet collector uses a headless read-only child, never a new Orca terminal or a global environment change. CLI interfaces and supported verification declarations are defined in [runtime-contracts.md](../skills/orca-dev/runtime-contracts.md).
- Per-repo trust: under pwsh 7 the installer parses `.claude.json` with `ConvertFrom-Json -AsHashtable`, because real files contain project keys that differ only in case (`D:/x` vs `d:/x`) and the default PSCustomObject form rejects them (Windows PowerShell 5.1 does too — run `install.ps1 -Repo` under pwsh if you hit that WARN). Claude Code on Windows keys `projects[]` with forward slashes (`C:/repo`); older builds used backslashes — the installer accepts either as trusted and writes the forward-slash key. Antigravity's `trustedWorkspaces` uses backslashes (verified on a real settings.json).
- Codex is not upgraded automatically (no Homebrew); an "Update available" prompt blocks worker input — keep Codex current yourself.
- The ChatGPT Pro bridge (`codex-chatgpt-web`) has a native Windows build (4.0.8 verified 2026-09-02, `%USERPROFILE%\.codex-chatgpt-web`, daemon `bun.exe … cli.js serve`): the opt-in `--planner pro` route is available when it is running; `install.ps1` reports it. Inside Orca the bridge doctor must be run with `CODEX_HOME` cleared (Orca points that variable at its own Codex home and the doctor then calls the integration "inconsistent") — the exact preflight is in `skills/orca-dev/orca-recipes.md` §7. Its log is `%APPDATA%\Codex Web GPT\logs\launcher.jsonl`.
- Repo paths with spaces produce a WARN: the bash scripts quote paths, but Orca argv and agy's trust matching are unverified with spaces.

Coordinator usage is `$orca-dev <task>` in Codex or `/orca-strigov:orca-dev <task>`
in Claude Code inside Orca. The differences listed in `skills/orca-dev/orca-recipes.md`
§9 apply: `.ps1` calls, quoted `--types`, `ConvertFrom-Json`, absolute Windows paths.
Claude hooks use exec-form Node arguments and native `powershell.exe`; the
coordinator's regular commands must invoke the `.ps1` helpers in PowerShell.

## B. WSL2

Everything runs inside the Linux distro; Windows stays a window manager. Requirements: Orca must be able to open its terminals **inside WSL** (not verified — check `orca terminal create` from a WSL shell), and every CLI (orca, codex, claude, agy, git, python3, jq) is installed in the distro. Then it is the macOS/Linux path:

```bash
git clone git@github.com:strigov/orca-strigov.git ~/orca-strigov && cd ~/orca-strigov
./install.sh && ./install.sh --repo /path/to/repo
```

`install.sh` uses Bash 3.2+ and Python 3.9+ stdlib. Homebrew update checks and bridge probes are optional; it never upgrades packages. It writes no persistent environment or shell profiles. Bash 3.2 compatibility has source-level evidence; the current POSIX runtime evidence uses Ubuntu Bash, not a macOS host.

## Isolated tests and evidence

Tests set `ORCA_DEV_TEST_HOME` only in a child environment, to an existing owned absolute directory. Both installers redirect trust/skill files there and skip external runtime/version/registration probes. PowerShell additionally reads/writes the simulated User value in `<test-home>/.orca-dev-user-environment.json`, preserving other keys; it never writes the real registry in this mode. Tests do not override HOME/USERPROFILE, and compare actual settings/registry digests before and after. A redirected test-home link is rejected. Temporary cleanup verifies ownership and never follows symlinks/junctions.

Check helpers independently from model routing. Use the bundled orchestration
references and actual CLI help/receipts, not stock `orca skills get` policy.
The ninth helper, `coordinator-session.ps1`, implements C8 natively and is selected
by `commandWindows` in the Codex hooks or by the Claude Node adapter. Its runtime needs PowerShell and Git,
not Bash/Python. A retained process, timeout or old smoke is not current certification.

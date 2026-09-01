#Requires -Version 5.1
<#
.SYNOPSIS
  install.ps1 — Windows installer for the orca-dev skill (native Windows, no WSL).

.DESCRIPTION
  Mirrors install.sh:
    .\install.ps1                    link the skill into %USERPROFILE%\.codex\skills\orca-dev, check CLIs
    .\install.ps1 -Repo <path>       + pre-trust <path> (and its git worktrees) for Claude Code and Antigravity
    .\install.ps1 -Check <path>      read-only report, changes nothing
  -Repo may be given several times (-Repo a -Repo b, or -Repo a,b).
  Exit: 0 clean, 1 if any WARN, 2 usage error.

  What it writes (install mode only):
    %USERPROFILE%\.codex\skills\orca-dev   symbolic link (Developer Mode / admin) or directory junction
    user environment variable ORCA_DEV_HOME = this checkout (the protocol resolves bin/ through it)
    %USERPROFILE%\.claude.json             projects[<path>].hasTrustDialogAccepted = true
    %USERPROFILE%\.gemini\antigravity-cli\settings.json   trustedWorkspaces += <path>
  All JSON edits are atomic (temp file + rename) and preserve unrelated keys.

  Windows notes (see docs/install-windows.md): the protocol's bin/ scripts are bash — Git for Windows
  provides bash.exe; the coordinator runs them as `bash "$env:ORCA_DEV_HOME/bin/verify-gate" ...`.
#>
[CmdletBinding()]
param(
  [string[]]$Repo = @(),
  [string[]]$Check = @(),
  [switch]$Help
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if ($Help) { Get-Help $MyInvocation.MyCommand.Path -Detailed; exit 0 }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$mode = if ($Check.Count -gt 0) { 'check' } else { 'install' }
$userHome = if ($env:ORCA_DEV_TEST_HOME) { $env:ORCA_DEV_TEST_HOME } else { [Environment]::GetFolderPath('UserProfile') }
$script:nwarn = 0

function Write-Ok   ([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Write-Warn2([string]$m) { $script:nwarn++; Write-Host "  WARN $m" -ForegroundColor Yellow }
function Write-Info ([string]$m) { Write-Host "  INFO $m" -ForegroundColor Cyan }      # not counted
function Write-Fix  ([string]$m) { Write-Host "  FIX  $m" -ForegroundColor Cyan }

function Resolve-Physical([string]$p) {
  # absolute, physical (junction/symlink-resolved) path, or $null
  try {
    $item = Get-Item -LiteralPath $p -ErrorAction Stop
    if (-not $item.PSIsContainer) { return $null }
    $full = $item.FullName
    # resolve reparse points (junction / symlink) to the target
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      $t = $item.Target
      if ($t) { $full = (Get-Item -LiteralPath ($t | Select-Object -First 1)).FullName }
    }
    return $full.TrimEnd('\')
  } catch { return $null }
}

# ---- argument handling ---------------------------------------------------------------
$repos = New-Object System.Collections.Generic.List[string]
foreach ($p in @($Repo) + @($Check)) {
  if ([string]::IsNullOrWhiteSpace($p)) { Write-Host "install.ps1: -Repo/-Check requires a path" -ForegroundColor Red; exit 2 }
  $abs = Resolve-Physical $p
  if (-not $abs) { Write-Host "install.ps1: not a directory: $p" -ForegroundColor Red; exit 2 }
  if (-not $repos.Contains($abs)) { $repos.Add($abs) }
}

Write-Host "orca-dev install ($mode) — Windows"

# ---- 1. skill link ---------------------------------------------------------------------
$src = Join-Path (Join-Path $here 'skills') 'orca-dev'
$skillsDir = Join-Path (Join-Path $userHome '.codex') 'skills'
$target = Join-Path $skillsDir 'orca-dev'
if (-not (Test-Path -LiteralPath $src -PathType Container)) {
  Write-Warn2 "skill source missing: $src"
} else {
  $srcAbs = (Get-Item -LiteralPath $src).FullName.TrimEnd('\')
  $existing = if (Test-Path -LiteralPath $target) { Get-Item -LiteralPath $target } else { $null }
  $pointsHere = $false
  if ($existing -and ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    $t = @($existing.Target)[0]
    if ($t) { $pointsHere = ((Get-Item -LiteralPath $t -ErrorAction SilentlyContinue).FullName.TrimEnd('\') -eq $srcAbs) }
  }
  if ($mode -eq 'install') {
    New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
    if ($pointsHere) {
      Write-Ok "skill already linked: $target -> $srcAbs"
    } elseif ($existing -and -not ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
      Write-Warn2 "$target exists and is not a link — not touching it; move it away and re-run"
    } else {
      if ($existing) { Remove-Item -LiteralPath $target -Force }   # stale link only (a reparse point, never a real dir)
      $linked = $false
      try { New-Item -ItemType SymbolicLink -Path $target -Target $srcAbs -ErrorAction Stop | Out-Null; $linked = 'symlink' } catch { }
      if (-not $linked) {
        try { New-Item -ItemType Junction -Path $target -Target $srcAbs -ErrorAction Stop | Out-Null; $linked = 'junction' } catch { }
      }
      if ($linked) { Write-Ok "skill linked ($linked): $target -> $srcAbs" }
      else { Write-Warn2 "could not link $target (enable Developer Mode for symlinks, or run once as Administrator)" }
    }
    # ORCA_DEV_HOME: the protocol resolves bin/ through it (readlink -f does not follow junctions in Git Bash)
    $cur = [Environment]::GetEnvironmentVariable('ORCA_DEV_HOME', 'User')
    if ($cur -ne $here) {
      try { [Environment]::SetEnvironmentVariable('ORCA_DEV_HOME', $here, 'User'); Write-Ok "ORCA_DEV_HOME = $here (user environment; restart Orca to pick it up)" }
      catch { Write-Warn2 "could not set ORCA_DEV_HOME: $($_.Exception.Message)" }
    } else { Write-Ok "ORCA_DEV_HOME = $here" }
  } else {
    if ($pointsHere) { Write-Ok "skill present: $target" }
    elseif ($existing) { Write-Warn2 "skill at $target does not point to $srcAbs" }
    else { Write-Warn2 "skill not installed (run .\install.ps1)" }
    $cur = [Environment]::GetEnvironmentVariable('ORCA_DEV_HOME', 'User')
    if ($cur -eq $here) { Write-Ok "ORCA_DEV_HOME = $cur" }
    else { Write-Warn2 "ORCA_DEV_HOME is '$cur', expected '$here' (run .\install.ps1)" }
  }
}

# ---- 2. CLIs -----------------------------------------------------------------------------
# bash + git come from Git for Windows; the protocol's bin/ scripts need bash.
foreach ($c in 'orca','codex','claude','agy','git','bash','jq','python3') {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { Write-Ok "${c}: $($cmd.Source)" }
  elseif ($c -eq 'python3' -and (Get-Command python -ErrorAction SilentlyContinue)) { Write-Warn2 "python3 not on PATH (python is) — the bin/ scripts call python3; add an alias or install Python 3 with the py launcher's python3.exe" }
  elseif ($c -eq 'agy') { Write-Warn2 "agy (Antigravity CLI) not on PATH — the implementer cascade starts at Luna (roles.md); native Windows support of agy is unverified" }
  else { Write-Warn2 "$c not on PATH" }
}
$bashCmd = Get-Command bash -ErrorAction SilentlyContinue
if ($bashCmd -and $bashCmd.Source -match 'System32\\bash\.exe') {
  Write-Warn2 "bash on PATH is the WSL launcher ($($bashCmd.Source)); the protocol needs Git for Windows bash — put <Git>\bin before System32 on PATH or use the WSL install path (docs/install-windows.md)"
}
if (Get-Command orca -ErrorAction SilentlyContinue) {
  try {
    $st = (orca status --json 2>$null | ConvertFrom-Json).result.runtime.state
    if ($st -eq 'ready') { Write-Ok "orca runtime: ready" } else { Write-Warn2 "orca runtime state: $st (run: orca open --json)" }
  } catch { Write-Warn2 "orca runtime unreachable (run: orca open --json)" }
}

# ---- 3. Codex update prompt -------------------------------------------------------------------
if (Get-Command codex -ErrorAction SilentlyContinue) {
  $v = (& codex --version 2>$null | Out-String).Trim()
  Write-Info "codex $v — keep it current (npm i -g @openai/codex@latest / winget upgrade); an 'Update available' prompt blocks worker input"
}

# ---- 4. Codex hooks trust ----------------------------------------------------------------------
$hooks = Join-Path (Join-Path $userHome '.codex') 'hooks.json'
$cfg   = Join-Path (Join-Path $userHome '.codex') 'config.toml'
if ((Test-Path -LiteralPath $hooks) -and (Test-Path -LiteralPath $cfg)) {
  $declared = 0
  try {
    $h = Get-Content -Raw -LiteralPath $hooks | ConvertFrom-Json
    $root = if ($h.PSObject.Properties['hooks']) { $h.hooks } else { $h }
    foreach ($prop in $root.PSObject.Properties) {
      foreach ($g in @($prop.Value)) {
        if ($g.PSObject.Properties['hooks']) { $declared += @($g.hooks).Count } else { $declared += 1 }
      }
    }
  } catch { Write-Warn2 "cannot parse ${hooks}: $($_.Exception.Message)" }
  $trusted = @(Select-String -LiteralPath $cfg -Pattern 'trusted_hash' -SimpleMatch).Count
  if ($declared -gt $trusted) {
    Write-Warn2 "codex hooks: $declared declared, $trusted trusted → 'Hooks need review' will block worker-start for codex"
    Write-Fix  "press '2. Trust all and continue' once in a Codex terminal inside Orca, or use Path B (--dangerously-bypass-hook-trust) per orca-recipes.md"
  } else { Write-Ok "codex hooks trusted ($trusted/$declared)" }
}
if ((Test-Path -LiteralPath $cfg) -and (Select-String -LiteralPath $cfg -Pattern '^model = "chatgpt-web/pro"' -Quiet)) {
  Write-Info "codex default model is chatgpt-web/pro — every protocol launch must pass an explicit --model (roles.md does)"
}

# ---- 5. per-repo trust ------------------------------------------------------------------------
function Set-TrustJson {
  param([ValidateSet('claude','agy')][string]$Kind, [string]$File, [string]$Mode, [string[]]$Paths)
  if (-not (Test-Path -LiteralPath $File)) {
    $hint = if ($Kind -eq 'claude') { 'run claude once in the repo, then re-run' } else { 'run agy once, then re-run' }
    Write-Warn2 "${Kind}: $File missing → $hint"; return
  }
  try { $d = Get-Content -Raw -LiteralPath $File -Encoding UTF8 | ConvertFrom-Json }
  catch { Write-Warn2 "${Kind}: $File is not valid JSON ($($_.Exception.Message)) → skipped, fix it by hand"; return }
  if ($null -eq $d -or $d -isnot [PSCustomObject]) { Write-Warn2 "${Kind}: $File top-level value is not an object → skipped"; return }
  $changed = $false
  foreach ($r in $Paths) {
    $isTrusted = $false
    if ($Kind -eq 'claude') {
      $projects = if ($d.PSObject.Properties['projects']) { $d.projects } else { $null }
      $entry = if ($projects -and $projects.PSObject.Properties[$r]) { $projects.$r } else { $null }
      $isTrusted = ($entry -and $entry.PSObject.Properties['hasTrustDialogAccepted'] -and [bool]$entry.hasTrustDialogAccepted)
    } else {
      $tw = if ($d.PSObject.Properties['trustedWorkspaces']) { @($d.trustedWorkspaces) } else { @() }
      $isTrusted = ($tw -contains $r)
    }
    if ($isTrusted) { Write-Ok "${Kind}: $r trusted"; continue }
    if ($Mode -ne 'install') { Write-Warn2 "${Kind}: $r not trusted → trust dialog will block the worker"; continue }
    if ($Kind -eq 'claude') {
      if (-not $d.PSObject.Properties['projects'] -or $d.projects -isnot [PSCustomObject]) { $d | Add-Member -Force -NotePropertyName projects -NotePropertyValue ([PSCustomObject]@{}) }
      if (-not $d.projects.PSObject.Properties[$r] -or $d.projects.$r -isnot [PSCustomObject]) { $d.projects | Add-Member -Force -NotePropertyName $r -NotePropertyValue ([PSCustomObject]@{}) }
      $d.projects.$r | Add-Member -Force -NotePropertyName hasTrustDialogAccepted -NotePropertyValue $true
    } else {
      $tw = if ($d.PSObject.Properties['trustedWorkspaces']) { @($d.trustedWorkspaces) } else { @() }
      $d | Add-Member -Force -NotePropertyName trustedWorkspaces -NotePropertyValue (@($tw) + $r)
    }
    $changed = $true
    Write-Ok "${Kind}: trust set for $r"
  }
  if ($changed) {
    $tmp = Join-Path (Split-Path -Parent $File) (".install-ps1.$([guid]::NewGuid().ToString('N').Substring(0,8)).tmp")
    try {
      $json = $d | ConvertTo-Json -Depth 64
      [IO.File]::WriteAllText($tmp, $json, (New-Object Text.UTF8Encoding($false)))
      Move-Item -LiteralPath $tmp -Destination $File -Force
    } catch {
      Write-Warn2 "${Kind}: could not write $File ($($_.Exception.Message))"
      if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
  }
}

if ($repos.Count -gt 0) {
  $paths = New-Object System.Collections.Generic.List[string]
  foreach ($repo in $repos) {
    if (-not $paths.Contains($repo)) { $paths.Add($repo) }
    $nwt = 0
    if (Get-Command git -ErrorAction SilentlyContinue) {
      $wts = & git -C $repo worktree list --porcelain 2>$null | Where-Object { $_ -like 'worktree *' } | ForEach-Object { $_.Substring(9) }
      foreach ($wt in @($wts)) {
        $abs = Resolve-Physical $wt
        if (-not $abs -or $abs -eq $repo) { continue }
        if (-not $paths.Contains($abs)) { $paths.Add($abs); $nwt++ }
      }
    }
    Write-Host "repo: $repo ($nwt extra worktree(s))"
  }
  Set-TrustJson -Kind claude -File (Join-Path $userHome '.claude.json') -Mode $mode -Paths $paths.ToArray()
  Set-TrustJson -Kind agy -File (Join-Path (Join-Path (Join-Path $userHome '.gemini') 'antigravity-cli') 'settings.json') -Mode $mode -Paths $paths.ToArray()
  foreach ($repo in $repos) {
    if (Get-Command orca -ErrorAction SilentlyContinue) {
      try {
        $registered = @((orca repo list --json 2>$null | ConvertFrom-Json).result.repos | Where-Object { $_.path -eq $repo }).Count -gt 0
        if ($registered) { Write-Ok "orca: $repo registered" } else { Write-Warn2 "orca: repo not registered (orca repo add --path `"$repo`" --json)" }
      } catch { Write-Warn2 "orca: could not list repos" }
    }
    if ($repo -match '[^\x20-\x7E]') { Write-Warn2 "repo path contains non-ASCII characters — expect trust/prefix bugs; prefer an ASCII path" }
    if ($repo -match '\s') { Write-Warn2 "repo path contains spaces — the bash scripts quote paths, but Orca argv and agy trust matching are unverified with spaces; prefer a path without spaces" }
  }
}

# ---- 6. bridge (optional, Pro planner) — the codex-chatgpt-web launcher is macOS-only today ----------
Write-Info "codex-chatgpt-web bridge (GPT Pro planner) is not available on Windows → planning profile 'standard' (Opus → Sol)"

if ($script:nwarn -gt 0) { Write-Host "install.ps1: $($script:nwarn) warning(s)"; exit 1 }
Write-Host "done."
exit 0

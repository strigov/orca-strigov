#Requires -Version 5.1
<#
.SYNOPSIS
  install.ps1 — Orca Strigov prerequisites (native Windows, no WSL).

.DESCRIPTION
  Mirrors install.sh:
    .\install.ps1                    read-only plugin/prerequisite/conflict checks
    .\install.ps1 -Repo <path>       + pre-trust <path> (and its git worktrees) for Claude Code and Antigravity
    .\install.ps1 -Check <path>      read-only report, changes nothing
    .\install.ps1 -LegacySkill       explicitly install the old standalone skill (not with plugin)
  -Repo may be given several times (-Repo a -Repo b, or -Repo a,b).
  Exit: 0 clean, 1 if any WARN, 2 usage error.

  What it writes (install mode only):
    Only with -LegacySkill: old skill link and User ORCA_DEV_HOME.
    Only with -Repo:
    %USERPROFILE%\.claude.json             projects[<path>].hasTrustDialogAccepted = true
    %USERPROFILE%\.gemini\antigravity-cli\settings.json   trustedWorkspaces += <path>
  All JSON edits are atomic (temp file + rename) and preserve unrelated keys.

  Windows notes (see docs/install-windows.md): the protocol's workspace scripts have native PowerShell
  ports (bin\*.ps1, PowerShell 5.1+, no bash / python3 / jq needed); the coordinator runs them as
  `& "$env:ORCA_DEV_HOME\bin\verify-gate.ps1" ...`. The bash originals stay for macOS / Linux / WSL.
  Claude Code on Windows keys projects[] with forward slashes (C:/repo); older builds used backslashes —
  both spellings count as trusted, the forward-slash one is written.
#>
[CmdletBinding()]
param(
  [string[]]$Repo = @(),
  [string[]]$Check = @(),
  [switch]$LegacySkill,
  [switch]$Help
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

if ($Help) { Get-Help $MyInvocation.MyCommand.Path -Detailed; exit 0 }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$mode = if ($Check.Count -gt 0) { 'check' } else { 'install' }
$userHome = if ($env:ORCA_DEV_TEST_HOME) { $env:ORCA_DEV_TEST_HOME } else { [Environment]::GetFolderPath('UserProfile') }
$testMode = -not [string]::IsNullOrEmpty($env:ORCA_DEV_TEST_HOME)
$script:nwarn = 0

function Write-Ok   ([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Write-Warn2([string]$m) { $script:nwarn++; Write-Host "  WARN $m" -ForegroundColor Yellow }
function Write-Info ([string]$m) { Write-Host "  INFO $m" -ForegroundColor Cyan }      # not counted
function Write-Fix  ([string]$m) { Write-Host "  FIX  $m" -ForegroundColor Cyan }

function Resolve-Physical([string]$p, [int]$depth = 0) {
  # Resolve parent components too; relative link targets are relative to the link.
  try {
    if ($depth -gt 40 -or [string]::IsNullOrWhiteSpace($p)) { return $null }
    $full = [IO.Path]::GetFullPath($p)
    if ($full -eq [IO.Path]::GetPathRoot($full)) { return $full }
    $parent = [IO.Path]::GetDirectoryName($full.TrimEnd('\'))
    if ($parent) {
      $physicalParent = Resolve-Physical $parent ($depth + 1)
      if (-not $physicalParent) { return $null }
      $full = Join-Path $physicalParent ([IO.Path]::GetFileName($full))
    }
    $item = Get-Item -Force -LiteralPath $full -ErrorAction Stop
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
      if ($item.LinkType -notin @('SymbolicLink','Junction') -or @($item.Target).Count -ne 1) { return $null }
      $linkTarget = [string]@($item.Target)[0]
      if (-not [IO.Path]::IsPathRooted($linkTarget)) { $linkTarget = Join-Path $parent $linkTarget }
      return Resolve-Physical $linkTarget ($depth + 1)
    }
    if (-not $item.PSIsContainer) { return $null }
    return $full.TrimEnd('\')
  } catch { return $null }
}

function Assert-PlainPath([string]$p) {
  # Writes must not traverse a foreign symlink/junction, including config files.
  $cursor = [IO.Path]::GetFullPath($p)
  while ($cursor) {
    $entry = Get-Item -Force -LiteralPath $cursor -ErrorAction SilentlyContinue
    if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
      throw "refusing write through link/reparse point: $cursor"
    }
    $cursor = [IO.Path]::GetDirectoryName($cursor.TrimEnd('\'))
  }
}

if ($testMode) {
  try {
    if (-not [IO.Path]::IsPathRooted($userHome) -or -not (Resolve-Physical $userHome) -or
        (Resolve-Physical $userHome) -eq (Resolve-Physical ([Environment]::GetFolderPath('UserProfile')))) {
      throw 'ORCA_DEV_TEST_HOME must be an existing isolated absolute directory'
    }
    Assert-PlainPath $userHome
  } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 2 }
}
$here = Resolve-Physical $here
$testEnvFile = Join-Path $userHome '.orca-dev-user-environment.json'
function Get-UserHomeSetting {
  if (-not $testMode) { return [Environment]::GetEnvironmentVariable('ORCA_DEV_HOME', 'User') }
  Assert-PlainPath $testEnvFile
  if (Test-Path -LiteralPath $testEnvFile) {
    $value = Get-Content -Raw -Encoding UTF8 -LiteralPath $testEnvFile | ConvertFrom-Json
    if ($value.PSObject.Properties['ORCA_DEV_HOME']) { return $value.ORCA_DEV_HOME }
  }
  return $null
}
function Set-UserHomeSetting {
  if (-not $testMode) { [Environment]::SetEnvironmentVariable('ORCA_DEV_HOME', $here, 'User'); return }
  Assert-PlainPath $testEnvFile
  $value = if (Test-Path -LiteralPath $testEnvFile) { Get-Content -Raw -Encoding UTF8 -LiteralPath $testEnvFile | ConvertFrom-Json } else { [PSCustomObject]@{} }
  $value | Add-Member -Force -NotePropertyName ORCA_DEV_HOME -NotePropertyValue $here
  [IO.File]::WriteAllText($testEnvFile, ($value | ConvertTo-Json -Depth 64), (New-Object Text.UTF8Encoding($false)))
}

# ---- argument handling ---------------------------------------------------------------
$repos = New-Object System.Collections.Generic.List[string]
foreach ($p in @($Repo) + @($Check)) {
  if ([string]::IsNullOrWhiteSpace($p)) { Write-Host "install.ps1: -Repo/-Check requires a path" -ForegroundColor Red; exit 2 }
  $abs = Resolve-Physical $p
  if (-not $abs) { Write-Host "install.ps1: not a directory: $p" -ForegroundColor Red; exit 2 }
  if (-not $repos.Contains($abs)) { $repos.Add($abs) }
}

Write-Host "Orca Strigov prerequisites ($mode) — Windows"

# ---- 1. skill link ---------------------------------------------------------------------
if (-not $LegacySkill) {
  try {
    $manifest=Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $here '.codex-plugin/plugin.json') | ConvertFrom-Json
    if ($manifest.name -cne 'orca-strigov') { throw 'unexpected plugin manifest' }
    foreach ($name in 'orca-cli','orchestration','orca-dev') {
      if (-not (Test-Path -LiteralPath (Join-Path $here "skills/$name/SKILL.md") -PathType Leaf)) { throw "missing plugin skill: $name" }
      foreach ($directory in '.agents','.codex','.claude') {
        $candidate=Join-Path $userHome "$directory/skills/$name"
        if (Get-Item -Force -LiteralPath $candidate -ErrorAction SilentlyContinue) {
          Write-Warn2 "potential duplicate skill: $candidate; verify disabled or move this exact entry out of discovery before enabling the plugin"
        }
      }
    }
    foreach ($required in 'plugin.json','.claude-plugin/plugin.json','hooks/hooks.json','hooks/codex.json','bin/claude-hook.cjs') {
      if (-not (Test-Path -LiteralPath (Join-Path $here $required) -PathType Leaf)) { throw "missing plugin component: $required" }
    }
    Write-Ok "complete plugin source: $here"
    Write-Info 'plugin registration and hook trust are separate; see docs/install-plugin.md'
    Write-Info 'no standalone skill links or environment settings written; legacy ORCA_DEV_HOME is not used'
  } catch { Write-Warn2 $_.Exception.Message }
} else {
$src = Join-Path (Join-Path $here 'skills') 'orca-dev'
$skillsDir = Join-Path (Join-Path $userHome '.codex') 'skills'
$target = Join-Path $skillsDir 'orca-dev'
if (-not (Test-Path -LiteralPath $src -PathType Container)) {
  Write-Warn2 "skill source missing: $src"
} else {
  $srcAbs = Resolve-Physical $src
  $existing = Get-Item -Force -LiteralPath $target -ErrorAction SilentlyContinue
  $isLink = $existing -and ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
    $existing.LinkType -in @('SymbolicLink','Junction')
  $pointsHere = $isLink -and $srcAbs -and (Resolve-Physical $target) -eq $srcAbs
  Write-Info "skill source: $srcAbs"
  Write-Info "skill link: $target -> $(if ($isLink) { @($existing.Target) -join ', ' } else { '(not a recognized link)' })"
  if ($mode -eq 'install') {
    try {
      Assert-PlainPath $skillsDir
      [IO.Directory]::CreateDirectory($skillsDir) | Out-Null
      if (-not $srcAbs) { throw 'cannot resolve skill source' }
      if ($pointsHere) {
      Write-Ok "skill already linked: $target -> $srcAbs"
    } elseif ($existing -and -not $isLink) {
      Write-Warn2 "$target exists and is not a link — not touching it; move it away and re-run"
    } else {
      if ($existing) {
        $again = Get-Item -Force -LiteralPath $target -ErrorAction Stop
        if ($again.FullName -ne [IO.Path]::GetFullPath($target) -or
            -not ($again.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
            $again.LinkType -ne $existing.LinkType -or
            (@($again.Target) -join '|') -ne (@($existing.Target) -join '|')) { throw 'skill link changed before replacement' }
        # Nonrecursive deletion removes only this link, even for a dangling junction on PS5.1.
        if ($again.PSIsContainer) { [IO.Directory]::Delete($target) } else { [IO.File]::Delete($target) }
      }
      $linked = $false
      try { New-Item -ItemType SymbolicLink -Path $target -Target $srcAbs -ErrorAction Stop | Out-Null; $linked = 'symlink' } catch { }
      if (-not $linked) {
        # 5.1 resolves junction Target as a wildcard; 7 treats it literally.
        $junctionTarget = if ($PSVersionTable.PSVersion.Major -le 5) { [Management.Automation.WildcardPattern]::Escape($srcAbs) } else { $srcAbs }
        try { New-Item -ItemType Junction -Path $target -Target $junctionTarget -ErrorAction Stop | Out-Null; $linked = 'junction' } catch { }
      }
      if ($linked) { $pointsHere = (Resolve-Physical $target) -eq $srcAbs; Write-Ok "skill linked ($linked): $target -> $srcAbs" }
      else { Write-Warn2 "could not link $target (enable Developer Mode for symlinks, or run once as Administrator)" }
    }
    # ORCA_DEV_HOME: the protocol resolves bin/ through it (readlink -f does not follow junctions in Git Bash)
    if ($pointsHere) {
      $cur = Get-UserHomeSetting
      if ($cur -ne $here) { Set-UserHomeSetting; Write-Ok "User ORCA_DEV_HOME = $here (restart Orca to inherit it)" }
    }
    } catch { Write-Warn2 $_.Exception.Message }
  } else {
    if ($pointsHere) { Write-Ok "skill present: $target" }
    elseif ($existing) { Write-Warn2 "skill at $target does not point to $srcAbs" }
    else { Write-Warn2 "skill not installed (run .\install.ps1)" }
  }
  try {
    $cur = Get-UserHomeSetting
    if ((Resolve-Physical $cur) -eq $here) { Write-Ok "User ORCA_DEV_HOME = $cur" }
    else { Write-Warn2 "User ORCA_DEV_HOME is '$cur', expected '$here' (run .\install.ps1)" }
  } catch { Write-Warn2 $_.Exception.Message }
  if ((Resolve-Physical $env:ORCA_DEV_HOME) -eq $here) { Write-Ok "Process ORCA_DEV_HOME = $env:ORCA_DEV_HOME" }
  else { Write-Warn2 "Process ORCA_DEV_HOME is '$env:ORCA_DEV_HOME', expected '$here'; restart Orca or set `$env:ORCA_DEV_HOME = '$($here.Replace("'", "''"))' in this process/worker launch" }
}
}
if ($testMode) { Write-Info 'isolated test home: User environment is file-backed; external CLI/runtime probes and registration are skipped' }

# ---- 2. CLIs -----------------------------------------------------------------------------
# The workspace scripts are PowerShell (bin\*.ps1): git is the only runtime dependency. python3 / jq
# are optional on Windows (plans' own verify: commands may still want them).
foreach ($c in 'orca','codex','claude','agy','git') {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { Write-Ok "${c}: $($cmd.Source)" }
  elseif ($c -eq 'agy') { Write-Warn2 "agy (Antigravity CLI) not on PATH — the implementer cascade continues with its fallback (roles.md); native Windows support of agy is unverified" }
  else { Write-Warn2 "$c not on PATH" }
}
foreach ($c in 'python3','jq') {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { Write-Ok "${c}: $($cmd.Source)" } else { Write-Info "$c not on PATH (optional on Windows: the bin\*.ps1 scripts do not need it)" }
}
$pw = Get-Command pwsh -ErrorAction SilentlyContinue
if ($pw) { Write-Ok "pwsh: $($pw.Source)" } else { Write-Info "pwsh (PowerShell 7) not on PATH — the scripts also run on Windows PowerShell 5.1" }
if (-not $testMode -and (Get-Command orca -ErrorAction SilentlyContinue)) {
  try {
    $st = (orca status --json 2>$null | ConvertFrom-Json).result.runtime.state
    if ($st -eq 'ready') { Write-Ok "orca runtime: ready" } else { Write-Warn2 "orca runtime state: $st (run: orca open --json)" }
  } catch { Write-Warn2 "orca runtime unreachable (run: orca open --json)" }
}

# ---- 3. Codex update prompt -------------------------------------------------------------------
if (-not $testMode -and (Get-Command codex -ErrorAction SilentlyContinue)) {
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
    Write-Fix 'review and explicitly trust the expected hooks in Codex; this script never bypasses hook trust'
  } else { Write-Ok "codex hooks trusted ($trusted/$declared)" }
}
if ((Test-Path -LiteralPath $cfg) -and (Select-String -LiteralPath $cfg -Pattern '^model = "chatgpt-web/pro"' -Quiet)) {
  Write-Info "codex default model is chatgpt-web/pro — every protocol launch must pass an explicit --model (roles.md does)"
}

# ---- 5. per-repo trust ------------------------------------------------------------------------
# PowerShell 7: ConvertFrom-Json -AsHashtable (case-sensitive keys — real .claude.json files contain
# project keys that differ only in case, which the PSCustomObject form rejects). Windows PowerShell 5.1:
# PSCustomObject; such a file is reported as WARN "fix by hand / run under pwsh".
# Claude Code on Windows keys projects[] with forward slashes (C:/repo); older builds used backslashes —
# either spelling counts as trusted, the forward-slash one is written.
function Get-Prop($o, [string]$k) {
  if ($o -is [System.Collections.IDictionary]) { if ($o.Contains($k)) { return $o[$k] } ; return $null }
  if ($o -and $o.PSObject.Properties[$k]) { return $o.$k } ; return $null
}
function Set-Prop($o, [string]$k, $v) {
  if ($o -is [System.Collections.IDictionary]) { $o[$k] = $v } else { $o | Add-Member -Force -NotePropertyName $k -NotePropertyValue $v }
}
function Is-Obj($o) { return ($o -is [System.Collections.IDictionary]) -or ($o -is [PSCustomObject]) }
function New-Obj { if ($PSVersionTable.PSVersion.Major -ge 7) { return [ordered]@{} } ; return [PSCustomObject]@{} }
function Set-TrustJson {
  param([ValidateSet('claude','agy')][string]$Kind, [string]$File, [string]$Mode, [string[]]$Paths)
  if (-not (Test-Path -LiteralPath $File)) {
    $hint = if ($Kind -eq 'claude') { 'run claude once in the repo, then re-run' } else { 'run agy once, then re-run' }
    Write-Warn2 "${Kind}: $File missing → $hint"; return
  }
  try {
    $raw = Get-Content -Raw -LiteralPath $File -Encoding UTF8
    $d = if ($PSVersionTable.PSVersion.Major -ge 7) { $raw | ConvertFrom-Json -AsHashtable } else { $raw | ConvertFrom-Json }
  } catch { Write-Warn2 "${Kind}: $File is not valid JSON for this PowerShell ($($_.Exception.Message)) → skipped; re-run under pwsh 7 or fix it by hand"; return }
  if ($null -eq $d -or -not (Is-Obj $d)) { Write-Warn2 "${Kind}: $File top-level value is not an object → skipped"; return }
  $changed = $false
  foreach ($r in $Paths) {
    $rf = $r.Replace('\', '/')   # current Claude Code key spelling
    $isTrusted = $false
    if ($Kind -eq 'claude') {
      $projects = Get-Prop $d 'projects'
      foreach ($k in @($rf, $r)) {
        $entry = if (Is-Obj $projects) { Get-Prop $projects $k } else { $null }
        if ((Is-Obj $entry) -and [bool](Get-Prop $entry 'hasTrustDialogAccepted')) { $isTrusted = $true }
      }
    } else {
      $tw = Get-Prop $d 'trustedWorkspaces'
      $isTrusted = ($tw -and (@($tw) -contains $r))
    }
    if ($isTrusted) { Write-Ok "${Kind}: $r trusted"; continue }
    if ($Mode -ne 'install') { Write-Warn2 "${Kind}: $r not trusted → trust dialog will block the worker"; continue }
    if ($Kind -eq 'claude') {
      $projects = Get-Prop $d 'projects'
      if (-not (Is-Obj $projects)) { $projects = New-Obj; Set-Prop $d 'projects' $projects }
      $entry = Get-Prop $projects $rf
      if (-not (Is-Obj $entry)) { $entry = New-Obj; Set-Prop $projects $rf $entry }
      Set-Prop $entry 'hasTrustDialogAccepted' $true
    } else {
      $tw = Get-Prop $d 'trustedWorkspaces'
      $list = if ($tw) { @($tw) } else { @() }
      Set-Prop $d 'trustedWorkspaces' (@($list) + $r)
    }
    $changed = $true
    Write-Ok "${Kind}: trust set for $r"
  }
  if ($changed) {
    try { Assert-PlainPath $File } catch { Write-Warn2 $_.Exception.Message; return }
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
    if (-not $testMode -and (Get-Command orca -ErrorAction SilentlyContinue)) {
      try {
        $registered = @((orca repo list --json 2>$null | ConvertFrom-Json).result.repos | Where-Object { $_.path -eq $repo }).Count -gt 0
        if ($registered) { Write-Ok "orca: $repo registered" } else { Write-Warn2 "orca: repo not registered (orca repo add --path `"$repo`" --json)" }
      } catch { Write-Warn2 "orca: could not list repos" }
    }
    if ($repo -match '[^\x20-\x7E]') { Write-Warn2 "repo path contains non-ASCII characters — expect trust/prefix bugs; prefer an ASCII path" }
    if ($repo -match '\s') { Write-Warn2 "repo path contains spaces — the bash scripts quote paths, but Orca argv and agy trust matching are unverified with spaces; prefer a path without spaces" }
  }
}

# ---- 6. bridge (optional, Pro planner) -------------------------------------------------------------
# codex-chatgpt-web ships a win32-x64 build (4.0.8 verified 2026-09-02); its daemon is `bun.exe … cli.js serve`.
$bridgeUp = $false
if (-not $testMode) { try { $bridgeUp = @(Get-CimInstance Win32_Process -Filter "Name='bun.exe'" -ErrorAction Stop | Where-Object { $_.CommandLine -match 'codex-chatgpt-web.*cli\.js serve' }).Count -gt 0 } catch { } }
if ($bridgeUp) { Write-Ok "codex-chatgpt-web bridge running (opt-in --planner pro available; preflight per orca-recipes.md §7 — run its doctor with CODEX_HOME cleared)" }
else { Write-Info "codex-chatgpt-web bridge not running (opt-in --planner pro disabled; default planner is configured in roles.md)" }

if ($script:nwarn -gt 0) { Write-Host "install.ps1: $($script:nwarn) warning(s)"; exit 1 }
Write-Host "done."
exit 0

#Requires -Version 5.1
<#
verify-gate.ps1 — PowerShell port of bin/verify-gate (native Windows, no bash, no python3).

Reads the `verify:` list from a plan file's YAML frontmatter, runs each command in the repo
root (in a child PowerShell, stdin closed), and on failure re-runs it at the phase BASE
commit in a throwaway worktree to classify the failure as inherited or new.

  verify-gate.ps1 <plan-file> <base-sha> [repo-root]

Exit: 0 GATE_OK | 1 GATE_FAIL | 2 NO_COMMANDS | 3 usage / unparsable verify: item | 4 NEEDS_JUDGMENT
stdout line 1: GATE_OK | GATE_FAIL | NO_COMMANDS | NEEDS_JUDGMENT
stdout line 2: verify: <n> cmd(s) | passed: <p> | failed: <f> | inherited: <i> | judgment: <j>
then one line per command: "<PASS|FAIL|INHERITED|JUDGMENT> <command>" and, for
FAIL/JUDGMENT, the last 40 lines of its output indented.

Classification rules are the same as the bash version (see bin/verify-gate for the full
rationale): a base failure is INHERITED only when no changed path (git diff --name-only BASE
+ untracked) appears in the command or its output AND the normalized failure signature is
the same at HEAD and BASE; a not-runnable command (rc 126/127, "command not found",
PowerShell "is not recognized") is JUDGMENT; zero passes is never GATE_OK; dependency dirs
(node_modules, .venv, venv) are junctioned into the BASE worktree, and when sources changed
that makes every would-be INHERITED a JUDGMENT.
#>
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args = @())
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

function Die([string]$m, [int]$code = 3) { [Console]::Error.WriteLine("verify-gate: $m"); exit $code }
$Args = @($Args | Where-Object { $null -ne $_ })
if ($Args.Count -lt 2) { [Console]::Error.WriteLine('usage: verify-gate.ps1 <plan-file> <base-sha> [repo-root]'); exit 3 }
$plan = $Args[0]; $base = $Args[1]
$root = if ($Args.Count -ge 3) { $Args[2] } else { (Get-Location).Path }
if (-not (Test-Path -LiteralPath $plan -PathType Leaf)) { [Console]::Error.WriteLine("plan file not found: $plan"); exit 3 }
$plan = (Get-Item -LiteralPath $plan).FullName
if (-not (Test-Path -LiteralPath $root -PathType Container)) { Die "cannot cd to repo root: $root" }
$root = (Get-Item -LiteralPath $root).FullName.TrimEnd('\')
Set-Location -LiteralPath $root
$base7 = if ($base.Length -gt 7) { $base.Substring(0, 7) } else { $base }
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { (Get-Command pwsh).Source } else { (Get-Command powershell).Source }

# --- extract `verify:` list from frontmatter (block or flow style) ------------------------
function Get-Indent([string]$s) { return $s.Length - $s.TrimStart(" `t").Length }
function Strip-Comment([string]$v) {  # drop a trailing " # ..." that is outside quotes
  $q = $null; $i = 0
  while ($i -lt $v.Length) {
    $ch = $v[$i]
    if ($q) {
      if ($q -eq '"' -and $ch -eq '\') { $i += 2; continue }
      if ($ch -eq $q) { $q = $null }
    } elseif ($ch -eq '"' -or $ch -eq "'") { $q = $ch }
    elseif ($ch -eq '#' -and ($i -eq 0 -or $v[$i - 1] -eq ' ' -or $v[$i - 1] -eq "`t")) { return $v.Substring(0, $i).TrimEnd() }
    $i++
  }
  return $v.TrimEnd()
}
function Unquote([string]$v) {
  if ($v.Length -ge 2 -and $v[0] -eq '"' -and $v[-1] -eq '"') { return $v.Substring(1, $v.Length - 2).Replace('\"', '"').Replace('\\', '\') }
  if ($v.Length -ge 2 -and $v[0] -eq "'" -and $v[-1] -eq "'") { return $v.Substring(1, $v.Length - 2).Replace("''", "'") }
  return $v
}
function Extract-Verify([string]$file) {
  $text = [IO.File]::ReadAllText($file, [Text.Encoding]::UTF8)
  $m = [regex]::Match($text, '^---\r?\n(.*?)\r?\n---(?:\r?\n|$)', [Text.RegularExpressions.RegexOptions]::Singleline)
  if (-not $m.Success) { return @() }
  $lines = $m.Groups[1].Value -split "\r?\n"
  $out = New-Object System.Collections.Generic.List[string]
  $kind = $null; $k = 0; $mf = $null
  for ($k = 0; $k -lt $lines.Count; $k++) {
    $l = $lines[$k]
    if ($l -match '^verify:[ \t]*(#.*)?$') { $kind = 'block'; break }
    $mf = [regex]::Match($l, '^verify:[ \t]*\[(.*)\][ \t]*(#.*)?$')
    if ($mf.Success) { $kind = 'flow'; break }
  }
  if ($kind -eq 'flow') {
    foreach ($g in [regex]::Matches($mf.Groups[1].Value, '\s*(?:"([^"]*)"|''([^'']*)''|([^,\[\]]+))')) {
      $v = ''
      foreach ($gi in 1..3) { if ($g.Groups[$gi].Success -and $g.Groups[$gi].Value) { $v = $g.Groups[$gi].Value; break } }
      $v = $v.Trim(); if ($v) { $out.Add($v) }
    }
  } elseif ($kind -eq 'block') {
    $i = $k + 1; $n = $lines.Count
    while ($i -lt $n) {
      $l = $lines[$i]
      if ($l.Trim() -eq '' -or $l.TrimStart().StartsWith('#')) { $i++; continue }
      $md = [regex]::Match($l, '^([ \t]*)-(?:[ \t]+(.*))?$')
      if (-not $md.Success) { break }                       # next key (or anything that is not an item)
      $ind = $md.Groups[1].Value.Length
      $v = if ($md.Groups[2].Success) { $md.Groups[2].Value.Trim() } else { '' }
      $i++
      $ms = [regex]::Match($v, '^([>|])[-+]?[0-9]*[ \t]*(#.*)?$')
      if ($ms.Success) {                                   # block scalar: body = following more-indented lines
        $body = New-Object System.Collections.Generic.List[string]
        while ($i -lt $n) {
          $b = $lines[$i]
          if ($b.Trim() -eq '') { $body.Add(''); $i++; continue }
          if ((Get-Indent $b) -le $ind) { break }
          $body.Add($b); $i++
        }
        while ($body.Count -gt 0 -and $body[$body.Count - 1] -eq '') { $body.RemoveAt($body.Count - 1) }
        if ($body.Count -eq 0) { Die ("empty block scalar (" + $ms.Groups[1].Value + ") in verify: item " + ($out.Count + 1)) }
        $bi = ($body | Where-Object { $_.Trim() } | ForEach-Object { Get-Indent $_ } | Measure-Object -Minimum).Minimum
        $body2 = @($body | ForEach-Object { if ($_.Trim()) { $_.Substring($bi) } else { '' } })
        if ($ms.Groups[1].Value -eq '|') { $v = $body2 -join "`n" }
        else { $v = (@($body2 | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() })) -join ' ' }
      } else {                                             # plain/quoted scalar, possibly continued on indented lines
        while ($i -lt $n) {
          $b = $lines[$i]
          if ($b.Trim() -eq '' -or $b -match '^[ \t]*-([ \t]|$)' -or (Get-Indent $b) -le $ind) { break }
          $v = $v + ' ' + $b.Trim(); $i++
        }
        $v = Unquote (Strip-Comment $v)
      }
      $v = $v.Trim()
      if ($v) { $out.Add($v) }
    }
  }
  return @($out)
}

$cmds = @(Extract-Verify $plan)
if ($cmds.Count -eq 0) {
  Write-Output 'NO_COMMANDS'; Write-Output 'verify: 0 cmd(s) | passed: 0 | failed: 0 | inherited: 0 | judgment: 0'; exit 2
}

# --- helpers -----------------------------------------------------------------------------
$utf8 = New-Object Text.UTF8Encoding($false)
$workspace = & (Join-Path $PSScriptRoot 'sdd-workspace.ps1') $plan
if ($LASTEXITCODE -ne 0) { exit 3 }
$runner = Join-Path $PSScriptRoot 'run-check.ps1'
$runnerShell = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
function Read-LogTail([string]$file) {
  $stream = [IO.File]::Open($file, 'Open', 'Read', 'ReadWrite')
  try {
    [void]$stream.Seek([Math]::Max(0, $stream.Length - 65536), 'Begin')
    $buffer = New-Object byte[] 65536; $count = $stream.Read($buffer, 0, $buffer.Length)
    return ((@(($utf8.GetString($buffer, 0, $count)) -split "\r?\n") | Select-Object -Last 200) -join "`n")
  } finally { $stream.Dispose() }
}
function Run-Command([string]$cmd, [string]$cwd) {
  $id = 'gate-' + [guid]::NewGuid().ToString('N')
  $checks = Join-Path $workspace 'checks'; [void][IO.Directory]::CreateDirectory($checks)
  $runDir = Join-Path $checks $id; $specFile = $runDir + '.json'
  $spec = @{schema_version=1; run_id=$id; owner=@{kind='local'; id=$id}; cwd=$cwd; command=$cmd; shell=$shell; run_dir=$runDir
    timeout_seconds=$null; cancel_grace_seconds=2; no_progress_seconds=$null}
  [IO.File]::WriteAllText($specFile, ($spec | ConvertTo-Json -Depth 8), $utf8)
  $script = "& '" + $runner.Replace("'", "''") + "' run '" + $specFile.Replace("'", "''") + "'; exit `$LASTEXITCODE"
  $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
  $p = $null
  try {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $runnerShell
    $psi.Arguments = "-NoProfile -NonInteractive -NoLogo -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand $enc"
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true; $psi.WorkingDirectory = $cwd
    $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $utf8; $psi.StandardErrorEncoding = $utf8
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $p = [Diagnostics.Process]::Start($psi)
    $p.StandardInput.Close()
    $errTask = $p.StandardError.ReadToEndAsync()
    [void]$p.StandardOutput.ReadToEnd() # bounded runner receipt; command streams are durable files
    $p.WaitForExit()
    $resultFile = Join-Path $runDir 'result.json'
    if (-not (Test-Path -LiteralPath $resultFile)) { return @{rc=125; out=$errTask.Result; valid=$false; run_dir=$runDir} }
    $result = [IO.File]::ReadAllText($resultFile, $utf8) | ConvertFrom-Json
    $valid = $result.state -eq 'exited' -and $result.cleanup_verified -and $result.logs_complete -and $null -ne $result.exit_code
    $out = (Read-LogTail $result.stdout_log) + "`n" + (Read-LogTail $result.stderr_log)
    return @{rc=$(if ($valid) { [BitConverter]::ToInt32([BitConverter]::GetBytes([uint32]$result.exit_code), 0) } else { 125 }); out=$out; valid=$valid; run_dir=$runDir}
  } finally { if ($p) { $p.Dispose() } }
}
function Lines([string]$s) {  # like reading lines: a trailing newline does not produce an empty last line
  $a = @((($s -replace "`r`n", "`n") -replace "`r", "`n") -split "`n")
  if ($a.Count -gt 0 -and $a[$a.Count - 1] -eq '') { if ($a.Count -eq 1) { return @() } ; $a = $a[0..($a.Count - 2)] }
  return @($a)
}
function Tail-Lines([string]$s, [int]$n) {  # callers wrap the result in @()
  $a = @(Lines $s); if ($a.Count -le $n) { return $a }; return $a[($a.Count - $n)..($a.Count - 1)]
}
function Indent-Tail([string]$s, [int]$n) {
  $res = New-Object System.Collections.Generic.List[string]
  foreach ($l in @(Tail-Lines $s $n)) { $res.Add('    ' + $l) }
  return ($res -join "`n")
}

# paths the phase changed (tracked + untracked)
$changed = @()
$changed += @(& git diff --name-only $base 2>$null)
$changed += @(& git ls-files --others --exclude-standard 2>$null)
$changed = @($changed | Where-Object { $_ -and $_.Trim() } | Sort-Object -Unique)
function Mentions-Changed([string]$text) {
  foreach ($pth in $changed) {
    if ($text.IndexOf($pth, [StringComparison]::Ordinal) -ge 0) { return $true }
    $bn = [IO.Path]::GetFileName($pth)
    if ($bn -and $text.IndexOf($bn, [StringComparison]::Ordinal) -ge 0) { return $true }
  }
  return $false
}
function Is-TestPath([string]$p) {
  $sp = '/' + $p.Replace('\', '/')
  if ($sp -match '/(test|tests|__tests__|spec|specs)/') { return $true }
  $bn = [IO.Path]::GetFileName($p)
  if ($bn -like 'test_*.py' -or $bn -like '*_test.py' -or $bn -like '*_test.go' -or $bn -like '*.test.*' -or $bn -like '*.spec.*' -or $bn -eq 'conftest.py') { return $true }
  return $false
}
$sourceChanged = $false
foreach ($pth in $changed) { if (-not (Is-TestPath $pth)) { $sourceChanged = $true; break } }
function Missing-Tool([int]$rc, [string]$out, [string]$cmd) {
  if ($rc -eq 126 -or $rc -eq 127) { return $true }
  $word = ($cmd.TrimStart() -split '\s', 2)[0]
  if ($out -match 'command not found') { return $true }
  if ($out -match 'is not recognized as (the name of|a name of) a cmdlet' -or $out -match 'CommandNotFoundException') { return $true }
  if ($word -and ($out.IndexOf("${word}: No such file or directory", [StringComparison]::Ordinal) -ge 0 -or $out.IndexOf("${word}: not found", [StringComparison]::Ordinal) -ge 0)) { return $true }
  return $false
}
$depsLinked = $false
$baseOut = ''
function Remove-BaseWorktree([string]$wt) {
  $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
  $full = [IO.Path]::GetFullPath($wt)
  if (-not $full.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($full) -notmatch '^verify-gate-base\.[a-f0-9]{8}$') { throw 'unowned base cleanup path' }
  # Detach links themselves before Git cleanup; never recurse through a junction.
  $pending = New-Object 'System.Collections.Generic.Stack[string]'; $pending.Push($full)
  while ($pending.Count) {
    $dir = $pending.Pop(); $entry = Get-Item -Force -LiteralPath $dir
    if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { [IO.Directory]::Delete($dir); continue }
    foreach ($item in Get-ChildItem -Force -LiteralPath $dir) {
      if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        if ($item.PSIsContainer) { [IO.Directory]::Delete($item.FullName) } else { [IO.File]::Delete($item.FullName) }
      } elseif ($item.PSIsContainer) { $pending.Push($item.FullName) }
    }
  }
  & git worktree remove -f $full *> $null
  if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("verify-gate: retained base worktree: $full") }
}
function Run-AtBase([string]$cmd) {  # returns rc; 125 = no usable base worktree; sets $script:baseOut
  $script:baseOut = ''
  $wt = Join-Path ([IO.Path]::GetTempPath()) ('verify-gate-base.' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  & git worktree add -q --detach $wt $base *> $null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $wt -PathType Container)) {
    [Console]::Error.WriteLine("verify-gate: cannot create a worktree for base $base7")
    return 125
  }
  $links = @()
  foreach ($dep in 'node_modules', '.venv', 'venv') {
    $src = Join-Path $root $dep; $dst = Join-Path $wt $dep
    if ((Test-Path -LiteralPath $src) -and -not (Test-Path -LiteralPath $dst)) {
      try { New-Item -ItemType Junction -Path $dst -Target $src -ErrorAction Stop | Out-Null; $links += $dst; $script:depsLinked = $true } catch { }
    }
  }
  $r = Run-Command $cmd $wt
  $script:baseOut = $r.out
  Rep ("    BASE logs: " + $r.run_dir)
  if (-not $r.valid) { Rep "    BASE runner incomplete; retained worktree: $wt"; return 125 }
  foreach ($l in $links) { try { [IO.Directory]::Delete($l) } catch { } }   # drop the junction, never its target
  Remove-BaseWorktree $wt
  return $r.rc
}
function Signature([string]$out) {  # last 8 non-empty lines, ANSI/paths/durations/numbers normalized
  $esc = [regex]'\x1b\[[0-9;]*[A-Za-z]'
  $summary = [regex]'\b(passed|failed|errors?|skipped)\b'
  $rootFwd = $root.Replace('\', '/')
  $res = New-Object System.Collections.Generic.List[string]
  foreach ($l0 in (Lines $out)) {
    $l = $esc.Replace($l0, '').Replace($root, 'ROOT').Replace($rootFwd, 'ROOT')
    $l = [regex]::Replace($l, '[^ ]*verify-gate-base\.[A-Za-z0-9]*', 'ROOT')
    $l = [regex]::Replace($l, '[0-9]+(\.[0-9]+)?s\b', 'Ns')
    if (-not $summary.IsMatch($l)) { $l = [regex]::Replace($l, '[0-9]{2,}', 'N') }
    if ($l.Trim()) { $res.Add($l) }
  }
  $a = @($res); if ($a.Count -gt 8) { $a = $a[($a.Count - 8)..($a.Count - 1)] }
  return ($a -join "`n")
}

# --- main loop ---------------------------------------------------------------------------
$n = 0; $p = 0; $f = 0; $i = 0; $j = 0; $status = 0
$report = New-Object Text.StringBuilder
function Rep([string]$s) { [void]$report.Append($s).Append("`n") }
foreach ($c in $cmds) {
  if (-not $c) { continue }
  $n++
  $label = $c.Replace("`r`n", ' ').Replace("`n", ' ')
  $r = Run-Command $c $root
  $rc = $r.rc; $out = $r.out
  Rep ("    HEAD logs: " + $r.run_dir)
  if (-not $r.valid) {
    $j++; if ($status -eq 0) { $status = 4 }
    Rep "JUDGMENT $label  (runner incomplete; inspect durable status/result)"; continue
  }
  if ($rc -eq 0) { $p++; Rep "PASS $label"; continue }
  $tailOut = Indent-Tail $out 40
  if (Missing-Tool $rc $out $c) {
    $j++; if ($status -eq 0) { $status = 4 }
    Rep "JUDGMENT $label  (not runnable at HEAD: rc $rc / command not found - a missing tool or bad path is not a test result)"; Rep $tailOut
    continue
  }
  $brc = Run-AtBase $c
  if ($brc -eq 0) {
    $f++; $status = 1
    Rep "FAIL $label"; Rep $tailOut
  } elseif ($brc -eq 125) {
    $f++; $status = 1
    Rep "FAIL $label  (base $base7 could not be checked out - treated as a new failure)"; Rep $tailOut
  } elseif (Mentions-Changed ($c + "`n" + ((Tail-Lines $out 200) -join "`n"))) {
    $j++; if ($status -eq 0) { $status = 4 }
    Rep "JUDGMENT $label  (fails at base $base7 too, but touches paths changed by this phase)"; Rep $tailOut
  } elseif ((Signature $out) -eq (Signature $baseOut)) {
    if ($depsLinked -and $sourceChanged) {
      $j++; if ($status -eq 0) { $status = 4 }
      Rep "JUDGMENT $label  (same failure at base $base7; inherited classification unreliable: shared .venv/node_modules may execute HEAD sources)"; Rep $tailOut
    } else {
      $i++; Rep "INHERITED $label  (same failure at base $base7; no changed path involved)"
    }
  } else {
    $j++; if ($status -eq 0) { $status = 4 }
    Rep "JUDGMENT $label  (fails at base $base7 too, but with a different failure - environment gap or unrelated cause)"; Rep $tailOut
    Rep '    --- at base:'; Rep (Indent-Tail $baseOut 10)
  }
}

if ($status -eq 0 -and $p -eq 0) {
  $status = 4
  $report.Insert(0, "NEEDS_JUDGMENT: 0 commands passed ($i inherited failure(s), nothing green) - an all-inherited gate is not GATE_OK`n") | Out-Null
}
switch ($status) { 0 { Write-Output 'GATE_OK' } 1 { Write-Output 'GATE_FAIL' } 4 { Write-Output 'NEEDS_JUDGMENT' } }
Write-Output "verify: $n cmd(s) | passed: $p | failed: $f | inherited: $i | judgment: $j"
$rep = $report.ToString()
if ($rep.EndsWith("`n")) { $rep = $rep.Substring(0, $rep.Length - 1) }
if ($rep) { Write-Output $rep }
exit $status

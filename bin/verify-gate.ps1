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
$phase=''; $checkpoint=''; $positional=@()
for ($argIndex=0; $argIndex -lt $Args.Count; $argIndex++) {
  $arg=$Args[$argIndex]
  if ($arg -in @('--phase','--checkpoint')) {
    $argIndex++; if ($argIndex -ge $Args.Count) { Die 'missing option value' }
    if ($arg -eq '--phase') { $phase=$Args[$argIndex] } else { $checkpoint=$Args[$argIndex] }
  } elseif ($arg.StartsWith('--')) { Die "unknown option: $arg" }
  else { $positional += $arg }
}
$Args=$positional; if ($Args.Count -gt 3) { Die 'too many positional arguments' }
. (Join-Path $PSScriptRoot 'lib/verification.ps1')
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

try { $cmds = @(V-Parse $plan $phase $checkpoint) } catch { Die $_.Exception.Message }
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
    timeout_seconds=$currentCheck.timeout_seconds; cancel_grace_seconds=$currentCheck.cancel_grace_seconds
    no_progress_seconds=$currentCheck.no_progress_seconds; resource_key=$currentCheck.resource_key; progress_file=$currentCheck.progress_file}
  try { $fullBase=V-GitText $root @('rev-parse','--verify',($base+'^{commit}')) } catch { $fullBase='unverifiable:'+$base }
  $linked=@()
  if ($cwd -ne $root) {
    foreach ($dep in 'node_modules','.venv','venv') { $path=Join-Path $root $dep; if (Test-Path -LiteralPath $path) { $linked+=@{path=$path; target=$path} } }
  }
  $spec.verification=@{check=$currentCheck; provenance=@{kind=$(if ($cwd -eq $root) { 'HEAD' } else { 'BASE' }); base_sha=$fullBase
    preparation=$(if ($cwd -eq $root) { 'current-worktree' } else { 'git-worktree-add-detach' }); linked_dependencies=@($linked)}}
  if ($linked.Count) { $spec.verification.repeat_reason='linked-dependencies-unverifiable' }
  [IO.File]::WriteAllText($specFile, (V-Json $spec), $utf8)
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
    $valid = V-EvidenceValid $result (V-Load $specFile)
    $cleanup=$false
    try {
      $cleanup = $result.cleanup_verified -and (V-FileHash $resultFile) -ceq (V-Load (Join-Path $runDir 'result.sha256')) -and
        (V-Get $result.evidence 'request_sha256') -ceq (V-Id (V-Load $specFile)) -and $result.run_dir -ceq $runDir
    } catch { } # uncertain ownership/record integrity never authorizes cleanup
    $out = (Read-LogTail $result.stdout_log) + "`n" + (Read-LogTail $result.stderr_log)
    return @{rc=$(if ($valid) { [BitConverter]::ToInt32([BitConverter]::GetBytes([uint32]$result.exit_code), 0) } else { 125 }); out=$out; valid=$valid; cleanup_verified=$cleanup; run_dir=$runDir; evidence=(V-Get $result 'evidence')}
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
$changedUnknown=$false
try { $changed = @(@(V-Nul (V-Git $root @('diff','--name-only','-z',$base))) + @(V-Nul (V-Git $root @('ls-files','--others','--exclude-standard','-z'))) | Sort-Object -Unique) }
catch { $changed=@(); $changedUnknown=$true }
function Mentions-Changed([string]$text) {
  if ($changedUnknown) { return $true }
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
$basePrepared=$false; $baseVerified=$false
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
  $script:basePrepared=$false; $script:baseVerified=$false
  $wt = Join-Path ([IO.Path]::GetTempPath()) ('verify-gate-base.' + [guid]::NewGuid().ToString('N').Substring(0, 8))
  & git worktree add -q --detach $wt $base *> $null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $wt -PathType Container)) {
    [Console]::Error.WriteLine("verify-gate: cannot create a worktree for base $base7")
    return 125
  }
  $script:basePrepared=$true
  $links = @()
  foreach ($dep in 'node_modules', '.venv', 'venv') {
    $src = Join-Path $root $dep; $dst = Join-Path $wt $dep
    if ((Test-Path -LiteralPath $src) -and -not (Test-Path -LiteralPath $dst)) {
      try { New-Item -ItemType Junction -Path $dst -Target $src -ErrorAction Stop | Out-Null; $links += $dst; $script:depsLinked = $true } catch { }
    }
  }
  $r = Run-Command $cmd $wt
  $script:baseVerified=$r.valid
  $script:baseOut = $r.out
  Rep ("    BASE logs: " + $r.run_dir)
  Rep ("    evidence: " + (Join-Path $r.run_dir 'result.json') + ' | repeat_reason: ' + (V-Get $r.evidence 'repeat_reason') + ' | origin_run_id: ' + (V-Get $r.evidence 'origin_run_id'))
  if (-not $r.valid) {
    if (V-Get $r 'cleanup_verified' $false) { Remove-BaseWorktree $wt }
    else { Rep "    BASE runner incomplete; retained worktree: $wt" }
    return 125
  }
  foreach ($l in $links) { try { [IO.Directory]::Delete($l) } catch { } }   # drop the junction, never its target
  Remove-BaseWorktree $wt
  return $r.rc
}
function Signature([string]$out) { return V-Signature $root $out }

# --- main loop ---------------------------------------------------------------------------
$n = 0; $p = 0; $f = 0; $i = 0; $j = 0; $status = 0
$report = New-Object Text.StringBuilder
function Rep([string]$s) { [void]$report.Append($s).Append("`n") }
foreach ($currentCheck in $cmds) {
  $c=$currentCheck.command
  if (-not $c) { continue }
  $n++
  $label = $c.Replace("`r`n", ' ').Replace("`n", ' ')
  $r = Run-Command $c $root
  $rc = $r.rc; $out = $r.out
  Rep ("    HEAD logs: " + $r.run_dir)
  Rep ("    evidence: " + (Join-Path $r.run_dir 'result.json') + ' | repeat_reason: ' + (V-Get $r.evidence 'repeat_reason') + ' | origin_run_id: ' + (V-Get $r.evidence 'origin_run_id'))
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
  if ($basePrepared -and -not $baseVerified) {
    $j++; if ($status -eq 0) { $status=4 }
    Rep "JUDGMENT $label  (BASE evidence incomplete)"; Rep $tailOut
    if ($depsLinked -and $sourceChanged) { Rep '    inherited classification unreliable: shared .venv/node_modules may execute HEAD sources' }
  } elseif ($brc -eq 0) {
    $f++; $status = 1
    Rep "FAIL $label"; Rep $tailOut
  } elseif (-not $basePrepared) {
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

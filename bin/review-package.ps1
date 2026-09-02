#Requires -Version 5.1
<#
review-package.ps1 — PowerShell port of bin/review-package (native Windows, no bash).

Generate a review package: commit list, stat summary, and the net diff with extended
context, written to a file the reviewer reads in one call.

  review-package.ps1 BASE HEAD [OUTFILE]    committed range BASE..HEAD
  review-package.ps1 BASE WORKTREE OUTFILE  working tree against BASE (OUTFILE required)

HEAD must not be literally "WORKTREE" (reserved mode keyword) — pass that ref's SHA instead.
The diff always excludes .superpowers/ (the workspace itself).
WORKTREE mode includes untracked files by intent-to-add-ing them into a TEMPORARY copy of
the index; the real index is never touched.
Default OUTFILE (range mode only): <sdd-workspace root>\review-<base7>..<head7>.diff — callers
should pass OUTFILE (e.g. "$(sdd-workspace.ps1 PLAN)\review-N.diff").
An empty package (0 commits in range mode, or 0 diff hunks) prints `EMPTY <path>: ...` and
exits 1. WORKTREE mode warns on stderr above 20 untracked files or 1 MB of untracked content.
Git output is copied to the package as raw bytes (UTF-8 as git emits it), never re-decoded
through the console code page.
Exit: 0 wrote, 1 empty / not written, 2 usage / bad ref.
#>
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args = @())
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Usage {
  [Console]::Error.WriteLine('usage: review-package.ps1 BASE HEAD [OUTFILE]')
  [Console]::Error.WriteLine('       review-package.ps1 BASE WORKTREE OUTFILE')
  [Console]::Error.WriteLine("       (HEAD must not be literally 'WORKTREE' - pass that ref's SHA instead)")
  [Console]::Error.WriteLine('       (pass OUTFILE: the default goes to the shared .superpowers\sdd root, not a plan workspace)')
  exit 2
}
$GitExe = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source
if (-not $GitExe) { [Console]::Error.WriteLine('review-package: git not found on PATH'); exit 2 }
function GitFirst([string[]]$a) {  # first decoded stdout line (small outputs only)
  $o = @(& $GitExe @a 2>$null)
  if ($o.Count -eq 0) { return '' } ; return [string]$o[0]
}
function Quote-Arg([string]$a) {  # Windows CommandLineToArgv quoting (PowerShell 5.1 has no ArgumentList)
  if ($a -ne '' -and $a -notmatch '[\s"]') { return $a }
  $sb = New-Object Text.StringBuilder; [void]$sb.Append('"'); $bs = 0
  foreach ($ch in $a.ToCharArray()) {
    if ($ch -eq '\') { $bs++; continue }
    if ($ch -eq '"') { [void]$sb.Append('\' * ($bs * 2 + 1)).Append('"'); $bs = 0; continue }
    if ($bs) { [void]$sb.Append('\' * $bs); $bs = 0 }
    [void]$sb.Append($ch)
  }
  if ($bs) { [void]$sb.Append('\' * ($bs * 2)) }
  [void]$sb.Append('"'); return $sb.ToString()
}
function Invoke-GitToFile {
  # run git with $GitArgs, append raw stdout bytes to $File ($null = discard); stderr goes to the console; returns exit code
  param([string[]]$GitArgs, [string]$File, [hashtable]$Env = @{})
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = $GitExe; $psi.UseShellExecute = $false; $psi.RedirectStandardOutput = $true
  $psi.WorkingDirectory = (Get-Location).Path
  $psi.Arguments = (@($GitArgs | ForEach-Object { Quote-Arg $_ })) -join ' '
  foreach ($k in $Env.Keys) { $psi.EnvironmentVariables[$k] = $Env[$k] }
  $p = [Diagnostics.Process]::Start($psi)
  if ($File) {
    $fs = [IO.File]::Open($File, [IO.FileMode]::Append, [IO.FileAccess]::Write)
    try { $p.StandardOutput.BaseStream.CopyTo($fs) } finally { $fs.Dispose() }
  } else { [void]$p.StandardOutput.ReadToEnd() }
  $p.WaitForExit()
  return $p.ExitCode
}
function Append-Text([string]$File, [string]$Text) {
  [IO.File]::AppendAllText($File, $Text, (New-Object Text.UTF8Encoding($false)))
}

$Args = @($Args | Where-Object { $null -ne $_ })
if ($Args.Count -lt 2 -or $Args.Count -gt 3) { Usage }
$base = $Args[0]; $head = $Args[1]

& git rev-parse --verify --quiet $base *> $null
if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("bad BASE: $base"); exit 2 }

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($head -eq 'WORKTREE') {
  if ($Args.Count -ne 3) { [Console]::Error.WriteLine('WORKTREE mode requires OUTFILE (no commit range to name the file from)'); Usage }
  $out = $Args[2]
} else {
  & git rev-parse --verify --quiet $head *> $null
  if ($LASTEXITCODE -ne 0) { [Console]::Error.WriteLine("bad HEAD: $head"); exit 2 }
  if ($Args.Count -eq 3) { $out = $Args[2] }
  else {
    $dir = & (Join-Path $here 'sdd-workspace.ps1')
    if ($LASTEXITCODE -ne 0 -or -not $dir) { exit 2 }
    $b7 = (GitFirst @('rev-parse', '--short', $base)); $h7 = (GitFirst @('rev-parse', '--short', $head))
    $out = Join-Path ([string]$dir) "review-$b7..$h7.diff"
  }
}
if (-not [IO.Path]::IsPathRooted($out)) { $out = Join-Path (Get-Location).Path $out }
$out = [IO.Path]::GetFullPath($out)

$top = (GitFirst @('rev-parse', '--show-toplevel'))
Set-Location -LiteralPath $top
$exclude = ':(exclude).superpowers'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $out) | Out-Null
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Force }
[IO.File]::WriteAllBytes($out, [byte[]]@())

$tmpidx = $null
try {
  if ($head -eq 'WORKTREE') {
    $tmpidx = [IO.Path]::GetTempFileName()
    $idx = (GitFirst @('rev-parse', '--git-path', 'index'))
    if ($idx -and (Test-Path -LiteralPath $idx -PathType Leaf)) { Copy-Item -LiteralPath $idx -Destination $tmpidx -Force }
    # untracked-content sanity warning (behavior unchanged)
    $files = @(& $GitExe ls-files --others --exclude-standard 2>$null | ForEach-Object { ([string]$_).Trim("`r") } | Where-Object { $_ -ne '' })
    $ucount = $files.Count; $ubytes = [long]0
    foreach ($f in $files) { if (Test-Path -LiteralPath $f -PathType Leaf) { $ubytes += (Get-Item -LiteralPath $f).Length } }
    if ($ucount -gt 20 -or $ubytes -gt 1048576) {
      [Console]::Error.WriteLine("WARN: including $ucount untracked file(s), $ubytes bytes, in the review package (check for build output / vendored trees)")
    }
    $env = @{ GIT_INDEX_FILE = $tmpidx }
    $null = Invoke-GitToFile -GitArgs @('add', '--intent-to-add', '-A', '--', '.') -File $null -Env $env
    Append-Text $out "# Review package: $base..WORKTREE`n`n## Commits`n"
    [void](Invoke-GitToFile -GitArgs @('log', '--oneline', "$base..HEAD", '--', '.', $exclude) -File $out)
    Append-Text $out "plus uncommitted working-tree changes`n`n## Files changed`n"
    [void](Invoke-GitToFile -GitArgs @('diff', '--stat', $base, '--', $exclude) -File $out -Env $env)
    Append-Text $out "`n## Diff`n"
    [void](Invoke-GitToFile -GitArgs @('diff', '-U10', $base, '--', $exclude) -File $out -Env $env)
    $commits = [int](GitFirst @('rev-list', '--count', "$base..HEAD", '--', '.', $exclude))
  } else {
    Append-Text $out "# Review package: $base..$head`n`n## Commits`n"
    [void](Invoke-GitToFile -GitArgs @('log', '--oneline', "$base..$head", '--', '.', $exclude) -File $out)
    Append-Text $out "`n## Files changed`n"
    [void](Invoke-GitToFile -GitArgs @('diff', '--stat', "$base..$head", '--', $exclude) -File $out)
    Append-Text $out "`n## Diff`n"
    [void](Invoke-GitToFile -GitArgs @('diff', '-U10', "$base..$head", '--', $exclude) -File $out)
    $commits = [int](GitFirst @('rev-list', '--count', "$base..$head", '--', '.', $exclude))
  }
} finally {
  if ($tmpidx -and (Test-Path -LiteralPath $tmpidx)) { Remove-Item -LiteralPath $tmpidx -Force }
}

$size = (Get-Item -LiteralPath $out).Length
if ($size -le 0) { [Console]::Error.WriteLine("failed to write $out"); exit 1 }
$hunks = 0
$sr = New-Object IO.StreamReader($out, [Text.Encoding]::UTF8)
try { while ($null -ne ($line = $sr.ReadLine())) { if ($line.StartsWith('diff --git')) { $hunks++ } } } finally { $sr.Dispose() }
if ((($head -ne 'WORKTREE') -and ($commits -eq 0)) -or ($hunks -eq 0)) {
  Write-Output "EMPTY ${out}: $commits commit(s), $hunks hunk(s)"
  exit 1
}
Write-Output "wrote ${out}: $commits commit(s), $size bytes"
exit 0

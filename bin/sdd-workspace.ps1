#Requires -Version 5.1
<#
sdd-workspace.ps1 — PowerShell port of bin/sdd-workspace (native Windows, no bash).

Resolve and ensure the working-tree directory the orchestrator uses for short-lived
artifacts: phase briefs, implementer reports, and review packages. Print the
directory's absolute physical path (Windows form, backslashes).

  sdd-workspace.ps1 [PLAN_FILE | --name SLUG]

With PLAN_FILE, resolve one directory per plan (.superpowers\sdd\<plan-basename>\);
--name SLUG resolves a plan-less workspace (.superpowers\sdd\<SLUG>\) for quickfix runs.
Without arguments, resolve the shared root (.superpowers\sdd). A self-ignoring
.gitignore at .superpowers\sdd\ keeps every workspace out of `git status`.
Exit: 0 ok, 2 usage / bad name / no such plan.
#>
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args = @())
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

function Usage { [Console]::Error.WriteLine('usage: sdd-workspace.ps1 [PLAN_FILE | --name SLUG]'); exit 2 }
$Args = @($Args | Where-Object { $null -ne $_ })
if ($Args.Count -gt 2) { Usage }

$root = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $root) { [Console]::Error.WriteLine('sdd-workspace: not inside a git repository'); exit 2 }
$root = (Get-Item -LiteralPath $root).FullName.TrimEnd('\')
$base = Join-Path (Join-Path $root '.superpowers') 'sdd'
$dir = $base

if ($Args.Count -eq 2) {
  if ($Args[0] -ne '--name') { Usage }
  $slug = $Args[1]
  if ([string]::IsNullOrEmpty($slug) -or $slug -eq '.' -or $slug -eq '..' -or $slug -match '[\\/]') {
    [Console]::Error.WriteLine("bad workspace name: $slug"); exit 2
  }
  $dir = Join-Path $base $slug
} elseif ($Args.Count -eq 1) {
  $plan = $Args[0]
  if ($plan -eq '--name') { Usage }
  if (-not (Test-Path -LiteralPath $plan -PathType Leaf)) { [Console]::Error.WriteLine("no such plan file: $plan"); exit 2 }
  $slug = [IO.Path]::GetFileName($plan)
  if ($slug -like '*.md') { $slug = $slug.Substring(0, $slug.Length - 3) }
  if ([string]::IsNullOrEmpty($slug) -or $slug -eq '.' -or $slug -eq '..') {
    [Console]::Error.WriteLine("cannot derive a workspace name from: $plan"); exit 2
  }
  $dir = Join-Path $base $slug
  # The plan's ledger is transient coordinator state (never committed). Ignore it
  # locally so C4 snapshots and C5 packages never capture it as candidate source.
  $planDir = (Get-Item -LiteralPath $plan).Directory.FullName.TrimEnd('\')
  if ($planDir -eq $root -or $planDir.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    $relative = $planDir.Substring($root.Length).Replace('\', '/')
    $pattern = [regex]::Replace($relative + '/' + $slug + '.ledger.json', '[\[\]*?\\!#]', '\$0')
    $exclude = (& git rev-parse --git-path info/exclude)
    if ($LASTEXITCODE -ne 0 -or -not $exclude) { [Console]::Error.WriteLine('sdd-workspace: cannot resolve info/exclude'); exit 2 }
    if (-not [IO.Path]::IsPathRooted($exclude)) { $exclude = Join-Path (Get-Location).Path $exclude }
    New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($exclude)) | Out-Null
    $text = if ([IO.File]::Exists($exclude)) { [IO.File]::ReadAllText($exclude) } else { '' }
    if (@($text -split "`r?`n") -cnotcontains $pattern) {
      $prefix = if ($text.Length -and -not $text.EndsWith("`n")) { "`n" } else { '' }
      [IO.File]::AppendAllText($exclude, $prefix + $pattern + "`n", (New-Object Text.UTF8Encoding($false)))
    }
  } else {
    [Console]::Error.WriteLine("sdd-workspace: plan outside the repository; its ledger is not ignored: $plan")
  }
}

New-Item -ItemType Directory -Force -Path $dir | Out-Null
[IO.File]::WriteAllText((Join-Path $base '.gitignore'), "*`n", (New-Object Text.UTF8Encoding($false)))
Write-Output (Get-Item -LiteralPath $dir).FullName
exit 0

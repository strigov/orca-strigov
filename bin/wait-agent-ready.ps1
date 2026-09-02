#Requires -Version 5.1
<#
wait-agent-ready.ps1 — PowerShell port of bin/wait-agent-ready (native Windows, no bash).

Block until an agent CLI's TUI is actually on screen in an Orca terminal, then wait for
tui-idle once more.

  wait-agent-ready.ps1 <terminal-handle> <agent> [timeout-seconds]
    agent: agy | codex | claude | <literal screen marker>

Why: `orca terminal wait --for tui-idle` is satisfied by the launching shell's prompt within
~1 s, before a slow-starting agent has drawn anything; an inject sent in that window is lost.
Exit 0 = marker seen and idle; 1 = timeout (last screen lines on stderr); 2 = usage;
3 = `orca terminal read` failed 5 times in a row (bad handle, Orca down).
The marker is looked for in the last 25 screen lines only.
#>
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args = @())
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

function Usage { [Console]::Error.WriteLine('usage: wait-agent-ready.ps1 <handle> <agy|codex|claude|marker> [timeout-s]'); exit 2 }
$Args = @($Args | Where-Object { $null -ne $_ })
if ($Args.Count -lt 2) { Usage }
$h = $Args[0]; $busy = ''
switch ($Args[1]) {
  'agy'    { $marker = 'Antigravity'; $busy = 'not signed in' }    # banner "Antigravity CLI <ver>"; the TUI draws a login menu when its first frame beats the keyring auth (~2-3 s, observed 2026-09-02) — an inject into that menu is lost
  'codex'  { $marker = 'Ask Codex'; $busy = 'Starting MCP servers' } # composer is drawn before MCP startup ends; Enter sent meanwhile is swallowed
  'claude' { $marker = 'Claude Code' }
  default  { $marker = $Args[1] }
}
$timeout = 120
if ($Args.Count -ge 3) {
  if ($Args[2] -notmatch '^[0-9]+$') { [Console]::Error.WriteLine("wait-agent-ready: timeout-s must be a non-negative integer, got '$($Args[2])'"); Usage }
  $timeout = [int]$Args[2]
}
$deadline = (Get-Date).AddSeconds($timeout)
$fails = 0
$scr = @()
$lastErr = ''

function Read-Screen {
  # returns @{ ok = $bool; lines = string[] }
  $errFile = [IO.Path]::GetTempFileName()
  try {
    $raw = (& orca terminal read --terminal $h --limit 80 --json 2>$errFile | Out-String)
    $rc = $LASTEXITCODE
    $script:lastErr = ''
    try { $script:lastErr = [IO.File]::ReadAllText($errFile) } catch { }
  } finally { Remove-Item -LiteralPath $errFile -Force -ErrorAction SilentlyContinue }
  $lines = @()
  try {
    $d = $raw | ConvertFrom-Json
    $t = $d.result.terminal
    if ($t -and $t.PSObject.Properties['tail']) { $lines = @($t.tail | Where-Object { $_ -is [string] }) }
  } catch { $lines = @() }
  if ($rc -ne 0 -and $lines.Count -eq 0) { return @{ ok = $false; lines = @() } }
  return @{ ok = $true; lines = $lines }
}
function Tail([string[]]$a, [int]$n) { if ($a.Count -le $n) { return $a } ; return $a[($a.Count - $n)..($a.Count - 1)] }
function Contains-Literal([string[]]$lines, [string]$needle) {
  foreach ($l in $lines) { if ($l.IndexOf($needle, [StringComparison]::Ordinal) -ge 0) { return $true } }
  return $false
}

while ($true) {
  $r = Read-Screen
  $scr = @($r.lines)
  if (-not $r.ok) {
    $fails++
    if ($fails -ge 5) {
      [Console]::Error.WriteLine("terminal read failing: $h ($fails consecutive failures); last stderr:")
      [Console]::Error.WriteLine($lastErr)
      exit 3
    }
  } else { $fails = 0 }
  if ((Contains-Literal (Tail $scr 25) $marker) -and (($busy -eq '') -or -not (Contains-Literal (Tail $scr 20) $busy))) {
    & orca terminal wait --terminal $h --for tui-idle --timeout-ms 60000 --json *> $null
    Write-Output "ready: $marker on $h"
    exit 0
  }
  if ((Get-Date) -ge $deadline) {
    [Console]::Error.WriteLine("timeout: '$marker' not on screen of $h after ${timeout}s; last lines:")
    foreach ($l in (Tail $scr 5)) { [Console]::Error.WriteLine($l) }
    exit 1
  }
  Start-Sleep -Seconds 2
}

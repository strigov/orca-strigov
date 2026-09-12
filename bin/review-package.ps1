#Requires -Version 5.1
# Complete C5 package; see skills/orca-dev/runtime-contracts.md.
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args = @())
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'lib/verification.ps1')
if ($Args.Count -lt 2 -or $Args.Count -gt 3) { [Console]::Error.WriteLine('usage: review-package.ps1 BASE HEAD [OUTFILE]'); exit 2 }
try { $out = if ($Args.Count -eq 3) { $Args[2] } else { '' }; exit (V-Package $Args[0] $Args[1] $out) }
catch {
  $failure=$_.Exception.Message
  if ($Args.Count -eq 3) {
    try { $m=[IO.Path]::GetFullPath($Args[2]+'.manifest.json'); V-Safe $m; if ([IO.Directory]::Exists([IO.Path]::GetDirectoryName($m))) { V-Save $m @{schema_version=1; complete=$false; error=$failure} } } catch { }
  }
  [Console]::Error.WriteLine("review-package: $failure"); if ($script:VPackageStarted) { exit 1 }; exit 2
}

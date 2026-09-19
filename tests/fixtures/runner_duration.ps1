# Test-only numeric fixture. Compile the real C3 interop type without invoking
# the run-check CLI or any native process/job/file API.
param([string]$RunnerPath, [string]$CasesPath)
$ErrorActionPreference = 'Stop'
$source = [IO.File]::ReadAllText($RunnerPath)
$native = [regex]::Match($source, '(?s)\$checkNativeSource = @''\r?\n(.*?)\r?\n''@')
if (-not $native.Success) { throw 'C3 native source not found' }
Add-Type -TypeDefinition $native.Groups[1].Value
$values = @(
    foreach ($case in (Get-Content -Raw -LiteralPath $CasesPath | ConvertFrom-Json)) {
        [CheckJob]::DurationSeconds([long]$case.ticks)
    }
)
ConvertTo-Json -InputObject $values -Compress

#Requires -Version 5.1
<# Owned test process only: expose the PS5.1 stdin BOM regression and verify
   that a helper restores the caller's input encoding on success and failure. #>
param([string]$Helper, [string]$RequestPath, [string]$ProbePath)
$ErrorActionPreference = 'Stop'
$original = [Console]::InputEncoding
try {
    [Console]::InputEncoding = New-Object Text.UTF8Encoding($true)
    & $Helper $RequestPath
    $code = $LASTEXITCODE
    $encoding = [Console]::InputEncoding
    $record = @{code_page=$encoding.CodePage; preamble=[BitConverter]::ToString($encoding.GetPreamble())}
    [IO.File]::WriteAllText($ProbePath, ($record | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding($false)))
} finally {
    [Console]::InputEncoding = $original
}
exit $code

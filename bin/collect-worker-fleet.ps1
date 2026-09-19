#Requires -Version 5.1
<# C6 inventory collector. No visible terminal or Python/Bash dependency. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true, Position=0)][string]$RequestPath)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$script:receipt = $null
$script:directory = $null

function Need($condition, [string]$reason) { if (-not $condition) { throw $reason } }
function Is-Text($value) { return ($value -is [string] -and -not [string]::IsNullOrWhiteSpace($value)) }
function Field($object, [string]$name) {
    if ($null -ne $object -and $null -ne $object.PSObject.Properties[$name]) { return $object.$name }
    return $null
}
function Is-Integer($value) { return ($value -is [int] -or $value -is [long]) }
function Quote-Argument([string]$value) {
    return '"' + [regex]::Replace([regex]::Replace($value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Invoke-Page([string[]]$arguments, [int]$number) {
    $stem = Join-Path $script:directory ('{0:D6}-worker-list' -f $number)
    $script:receipt = $stem + '.json'
    $stderr = $stem + '.stderr.log'
    $psi = New-Object Diagnostics.ProcessStartInfo
    $command = Get-Command $script:spec.orca_argv[0] -ErrorAction Stop
    $allArguments = @($script:spec.orca_argv | Select-Object -Skip 1) + $arguments
    if ($command.CommandType -eq 'Application' -and [IO.Path]::GetExtension($command.Source) -notin @('.cmd', '.bat')) {
        $psi.FileName = $command.Source
        $psi.Arguments = (@($allArguments | ForEach-Object { Quote-Argument $_ }) -join ' ')
    } else {
        # Encode only launch arguments, never an Orca receipt; no shell interpolation.
        $argvJson = ConvertTo-Json -InputObject @($script:spec.orca_argv + $arguments) -Compress
        $source = @'
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$items = @([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__ARGV__')) | ConvertFrom-Json)
$exe = $items[0]
$rest = @($items | Select-Object -Skip 1)
$global:LASTEXITCODE = 0
& $exe @rest
if (-not $?) { if ($LASTEXITCODE -eq 0) { exit 1 } }
exit $LASTEXITCODE
'@
        $source = $source.Replace('__ARGV__', [Convert]::ToBase64String($utf8.GetBytes($argvJson)))
        $psi.FileName = (Get-Process -Id $PID).Path
        $psi.Arguments = '-NoLogo -NoProfile -NonInteractive -EncodedCommand ' + [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($source))
    }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $inputEncoding = $null
    if ($null -ne $psi.PSObject.Properties['StandardInputEncoding']) {
        $psi.StandardInputEncoding = $utf8
    } else {
        # .NET Framework uses Console.InputEncoding and flushes its preamble
        # during Start(), before StandardInput.Close(). Restore the caller below.
        $inputEncoding = [Console]::InputEncoding
    }
    # Only this read-only child's identity is absent. Keep parent binding and
    # connection/auth/environment settings; prohibit active-pane guessing.
    $psi.EnvironmentVariables.Remove('ORCA_TERMINAL_HANDLE')
    $psi.EnvironmentVariables.Remove('ORCA_PANE_KEY')
    $psi.EnvironmentVariables['ORCA_STRUCTURED_SESSION'] = '1'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $psi
    $out = [IO.File]::Open($script:receipt, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    $err = [IO.File]::Open($stderr, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        try {
            if ($null -ne $inputEncoding) { [Console]::InputEncoding = $utf8 }
            Need ($process.Start()) 'Orca CLI did not start'
        } finally {
            if ($null -ne $inputEncoding) { [Console]::InputEncoding = $inputEncoding }
        }
        $process.StandardInput.Close()
        $outCopy = $process.StandardOutput.BaseStream.CopyToAsync($out)
        $errCopy = $process.StandardError.BaseStream.CopyToAsync($err)
        $process.WaitForExit()
        # PowerShell can expose Task<VoidTaskResult>'s internal result. Only
        # the parsed receipt below may enter this function's output pipeline.
        [void]$outCopy.GetAwaiter().GetResult()
        [void]$errCopy.GetAwaiter().GetResult()
        $code = $process.ExitCode
    } finally { $out.Dispose(); $err.Dispose(); $process.Dispose() }
    Need ($code -eq 0) "Orca CLI exit $code; inspect $stderr"
    Need ((Get-Item -LiteralPath $script:receipt).Length -le 16777216) 'oversize Orca receipt'
    return ([IO.File]::ReadAllText($script:receipt, $utf8) | ConvertFrom-Json)
}

try {
    $raw = [IO.File]::ReadAllBytes((Get-Item -LiteralPath $RequestPath).FullName)
    $script:spec = $utf8.GetString($raw).TrimStart([char]0xFEFF) | ConvertFrom-Json
    $s = $script:spec
    Need ($s -is [pscustomobject] -and (Is-Integer (Field $s 'schema_version')) -and $s.schema_version -eq 1) 'invalid request schema'
    Need ($s.orca_argv -is [array] -and $s.orca_argv.Count -gt 0) 'orca_argv must name the selected CLI'
    foreach ($item in $s.orca_argv) { Need (Is-Text $item) 'orca_argv must name the selected CLI' }
    Need ((Is-Text (Field $s 'output_dir')) -and [IO.Path]::IsPathRooted($s.output_dir)) 'output_dir must be absolute'
    Need ($s.output_dir -notmatch '^[a-zA-Z]:[^\\/]') 'output_dir must be absolute'
    Need ([IO.Directory]::Exists([IO.Path]::GetDirectoryName($s.output_dir))) 'output_dir parent must exist'
    $created = New-Item -ItemType Directory -Path $s.output_dir -ErrorAction Stop
    $script:directory = $created.FullName
    [IO.File]::WriteAllBytes((Join-Path $script:directory 'request.json'), $raw)
    $refs = @()
    $cursor = $null
    $cursors = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $dispatches = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $receipts = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $total = $null
    $runtime = $null
    while ($true) {
        $arguments = @('orchestration', 'worker-list', '--limit', '100', '--json')
        if ($null -ne $cursor) { $arguments += @('--cursor', $cursor) }
        $envelope = Invoke-Page $arguments ($refs.Count + 1)
        $ok = Field $envelope 'ok'
        Need ($ok -is [bool] -and $ok -and (Field $envelope 'result') -is [pscustomobject]) 'Orca error or invalid receipt'
        $identity = Field $envelope 'id'
        Need ((Is-Text $identity) -and $receipts.Add($identity)) 'missing or duplicate receipt id'
        $observedRuntime = Field (Field $envelope '_meta') 'runtimeId'
        Need ((Is-Text $observedRuntime) -and ($null -eq $runtime -or $runtime -ceq $observedRuntime)) 'missing or changed Orca runtime'
        $runtime = $observedRuntime
        $r = $envelope.result
        $scope = Field $r 'scope'
        Need ((Field $scope 'source') -ceq 'all' -and $null -eq (Field $scope 'run')) 'fleet scope is not all Runs; stop, do not create a terminal or rewrite scope'
        Need (-not (Field $r 'partialHostErrors')) 'partial fleet observation'
        $page = Field $r 'page'
        $count = Field $page 'total'
        Need ((Is-Integer $count) -and $count -ge 0 -and ($null -eq $total -or $count -eq $total)) 'inconsistent fleet total'
        $total = $count
        $limit = Field $page 'limit'
        Need ((Is-Integer $limit) -and $limit -eq 100) 'unexpected fleet page limit'
        Need ($null -ne $r.PSObject.Properties['workers'] -and $r.workers -is [array] -and $r.workers.Count -le 100) 'invalid fleet workers'
        foreach ($row in $r.workers) {
            $id = Field $row 'dispatchId'
            Need ($row -is [pscustomobject] -and (Is-Text $id)) 'invalid fleet row'
            Need ($dispatches.Add($id)) 'duplicate fleet dispatch'
        }
        $hash = (Get-FileHash -LiteralPath $script:receipt -Algorithm SHA256).Hash.ToLowerInvariant()
        $refs += @{path=$script:receipt; sha256=$hash; cursor=$cursor}
        $more = Field $page 'hasMore'
        Need ($more -is [bool]) 'missing fleet pagination'
        $cursor = Field $page 'nextCursor'
        if (-not $more) { Need ($null -eq $cursor -and $dispatches.Count -eq $total) 'incomplete fleet'; break }
        Need ($r.workers.Count -gt 0 -and $dispatches.Count -lt $total -and (Is-Text $cursor) -and $cursors.Add($cursor)) 'invalid fleet cursor'
    }
    $manifest = Join-Path $script:directory 'fleet.json'
    $payload = @{schema_version=1; fleet=@($refs); runtime_id=$runtime; worker_count=$total; page_count=$refs.Count} | ConvertTo-Json -Depth 20 -Compress
    $stream = [IO.File]::Open($manifest, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try { $bytes = $utf8.GetBytes($payload + "`n"); $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
    $result = @{schema_version=1; event='collected'; fleet_file=$manifest; output_dir=$script:directory; worker_count=$total; page_count=$refs.Count}
    $code = 0
} catch {
    $code = 1
    $result = @{schema_version=1; event='error'; reason=$_.Exception.Message}
    if ($null -ne $script:directory) { $result.receipt = $script:receipt; $result.output_dir = $script:directory }
}
$result | ConvertTo-Json -Depth 20 -Compress
exit $code

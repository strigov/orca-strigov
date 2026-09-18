#Requires -Version 5.1
<# C7 native waiter. No Python/Bash dependency; see runtime-contracts.md. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true, Position=0)][string]$RequestPath)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$script:receipt = $null
$script:directory = $null
$script:sequence = 0

function Need($condition, [string]$reason) { if (-not $condition) { throw $reason } }
function Is-Text($value) { return ($value -is [string] -and -not [string]::IsNullOrWhiteSpace($value)) }
function Field($object, [string]$name) {
    if ($null -ne $object -and $null -ne $object.PSObject.Properties[$name]) { return $object.$name }
    return $null
}
function Is-Integer($value) { return ($value -is [int] -or $value -is [long]) }
function Is-True($value) { return ($value -is [bool] -and $value) }
function Quote-Argument([string]$value) {
    # Windows CommandLineToArgvW quoting, including quotes and trailing slashes.
    return '"' + [regex]::Replace([regex]::Replace($value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
function Invoke-Orca([string[]]$arguments) {
    $script:sequence++
    $stem = Join-Path $script:directory ('{0:D6}-{1}' -f $script:sequence, $arguments[1])
    $script:receipt = $stem + '.json'
    $stderr = $stem + '.stderr.log'
    # An encoded PowerShell invocation supports the selected orca.exe/cmd/ps1
    # launcher without interpolating any argument into shell source.
    $argvJson = ConvertTo-Json -InputObject @($script:spec.orca_argv + $arguments) -Compress
    $encodedArgv = [Convert]::ToBase64String($utf8.GetBytes($argvJson))
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
    $source = $source.Replace('__ARGV__', $encodedArgv)
    $psi = New-Object Diagnostics.ProcessStartInfo
    $command = Get-Command $script:spec.orca_argv[0] -ErrorAction Stop
    if ($command.CommandType -eq 'Application' -and [IO.Path]::GetExtension($command.Source) -notin @('.cmd', '.bat')) {
        # Native executables keep their stdout bytes, including BOM/CRLF, intact.
        $psi.FileName = $command.Source
        $allArguments = @($script:spec.orca_argv | Select-Object -Skip 1) + $arguments
        $psi.Arguments = (@($allArguments | ForEach-Object { Quote-Argument $_ }) -join ' ')
    } else {
        $psi.FileName = (Get-Process -Id $PID).Path
        $psi.Arguments = '-NoLogo -NoProfile -NonInteractive -EncodedCommand ' + [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($source))
    }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $psi
    $out = [IO.File]::Open($script:receipt, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    $err = [IO.File]::Open($stderr, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        Need ($process.Start()) 'Orca CLI did not start'
        $process.StandardInput.Close()
        $outCopy = $process.StandardOutput.BaseStream.CopyToAsync($out)
        $errCopy = $process.StandardError.BaseStream.CopyToAsync($err)
        $process.WaitForExit()
        $outCopy.GetAwaiter().GetResult()
        $errCopy.GetAwaiter().GetResult()
        $code = $process.ExitCode
    } finally { $out.Dispose(); $err.Dispose(); $process.Dispose() }
    Need ($code -eq 0) "Orca CLI exit $code; inspect $stderr"
    Need ((Get-Item -LiteralPath $script:receipt).Length -le 16777216) "oversize Orca receipt: $script:receipt"
    $envelope = [IO.File]::ReadAllText($script:receipt, $utf8) | ConvertFrom-Json
    Need ((Is-True (Field $envelope 'ok')) -and (Field $envelope 'result') -is [pscustomobject]) "Orca error or invalid receipt: $script:receipt"
    return $envelope.result
}
function Read-Fleet {
    $cursor = $null
    $cursors = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    $workers = New-Object 'Collections.Generic.Dictionary[string,object]' ([StringComparer]::Ordinal)
    $total = $null
    while ($true) {
        $arguments = @('orchestration', 'worker-list', '--run', $script:spec.run_id, '--include-remote', '--limit', '100', '--json')
        if ($null -ne $cursor) { $arguments += @('--cursor', $cursor) }
        $r = Invoke-Orca $arguments
        $scope = Field $r 'scope'
        Need ((Field $scope 'run') -ceq $script:spec.run_id -and (Field $scope 'source') -ceq 'flag') 'fleet scope mismatch'
        $page = Field $r 'page'
        $count = Field $page 'total'
        Need ((Is-Integer $count) -and $count -ge 0 -and ($null -eq $total -or $count -eq $total)) 'inconsistent fleet total'
        $total = $count
        Need ($null -ne $r.PSObject.Properties['workers'] -and $r.workers -is [array]) 'missing fleet workers'
        foreach ($row in $r.workers) {
            $id = Field $row 'dispatchId'
            Need (Is-Text $id) 'invalid fleet row'
            Need (-not $workers.ContainsKey($id)) 'duplicate fleet dispatch'
            $workers.Add($id, $row)
        }
        $more = Field $page 'hasMore'
        Need ($more -is [bool]) 'missing fleet pagination'
        if (-not $more) { Need ($workers.Count -eq $total) 'incomplete fleet'; break }
        $cursor = Field $page 'nextCursor'
        Need ($r.workers.Count -gt 0 -and (Is-Text $cursor) -and -not $cursors.Contains($cursor) -and $workers.Count -lt $total) 'invalid fleet cursor'
        [void]$cursors.Add($cursor)
    }
    $alerts = @()
    foreach ($id in $script:spec.dispatch_ids) {
        Need ($workers.ContainsKey($id)) "expected dispatch missing from fleet: $id"
        $projection = Field $workers[$id] 'projection'
        $liveness = Field $projection 'liveness'
        $attention = Field $projection 'attention'
        $action = Field $projection 'nextAction'
        $verdict = Field $liveness 'verdict'
        $required = Field $attention 'requiresAction'
        $kind = Field $action 'kind'
        Need ($verdict -cin @('live', 'exited', 'unverifiable') -and $required -is [bool] -and (Is-Text $kind)) "incomplete fleet projection: $id"
        if ($verdict -ceq 'exited' -or $required -or $kind -cne 'none') { $alerts += $id }
    }
    return $alerts
}
function Result([string]$event) {
    return @{schema_version=1; event=$event; run_id=$script:spec.run_id; receipt=$script:receipt; output_dir=$script:directory}
}

try {
    $raw = [IO.File]::ReadAllBytes((Get-Item -LiteralPath $RequestPath).FullName)
    $script:spec = $utf8.GetString($raw).TrimStart([char]0xFEFF) | ConvertFrom-Json
    $s = $script:spec
    Need ($s -is [pscustomobject] -and (Is-Integer (Field $s 'schema_version')) -and $s.schema_version -eq 1) 'invalid request schema'
    Need ($s.orca_argv -is [array] -and $s.orca_argv.Count -gt 0) 'orca_argv must name the selected CLI'
    foreach ($item in $s.orca_argv) { Need (Is-Text $item) 'orca_argv must name the selected CLI' }
    Need (Is-Text (Field $s 'run_id')) 'run_id is required'
    Need ($s.dispatch_ids -is [array] -and $s.dispatch_ids.Count -gt 0) 'dispatch_ids must be unique and nonempty'
    $ids = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach ($id in $s.dispatch_ids) { Need ((Is-Text $id) -and $ids.Add($id)) 'dispatch_ids must be unique and nonempty' }
    foreach ($key in @('terminal', 'ack_delivery_id')) {
        $value = Field $s $key
        Need ($null -eq $value -or (Is-Text $value)) "invalid $key"
    }
    Need ((Is-Text (Field $s 'output_dir')) -and [IO.Path]::IsPathRooted($s.output_dir)) 'output_dir must be absolute'
    Need ($s.output_dir -notmatch '^[a-zA-Z]:[^\\/]') 'output_dir must be absolute'
    Need ([IO.Directory]::Exists([IO.Path]::GetDirectoryName($s.output_dir))) 'output_dir parent must exist'
    # New-Item without Force refuses an existing leaf, retaining old receipts.
    $created = New-Item -ItemType Directory -Path $s.output_dir -ErrorAction Stop
    $script:directory = $created.FullName
    [IO.File]::WriteAllBytes((Join-Path $script:directory 'request.json'), $raw)
    $empty = 0
    $ack = Field $s 'ack_delivery_id'
    while ($true) {
        $arguments = @('orchestration', 'check', '--run', $s.run_id, '--wait', '--types', 'worker_done,escalation,question', '--timeout-ms', '540000', '--json')
        $terminal = Field $s 'terminal'
        if ($terminal) { $arguments += @('--terminal', $terminal) }
        if ($ack) { $arguments += @('--ack', $ack) }
        $r = Invoke-Orca $arguments
        $ack = $null
        Need ((Field $r 'runId') -ceq $s.run_id) 'inbox Run mismatch'
        Need (-not (Field $r 'cancelled') -and -not (Field $r 'connectionLost')) 'Orca wait cancelled or disconnected'
        Need ($null -ne $r.PSObject.Properties['messages'] -and $r.messages -is [array] -and (Is-Integer (Field $r 'count')) -and $r.count -eq $r.messages.Count) 'invalid message batch'
        if ($r.messages.Count -gt 0) {
            Need (Is-Text (Field $r 'deliveryId')) 'missing Delivery identity'
            $result = Result 'delivery'; $result.delivery_id = $r.deliveryId; $code = 0; break
        }
        Need ((Is-True (Field $r 'timedOut')) -and -not (Field $r 'deliveryId')) 'unexpected empty response; refusing a busy loop'
        $empty++
        if ($empty -eq 3) {
            $alerts = @(Read-Fleet)
            if ($alerts.Count -gt 0) { $result = Result 'attention'; $result.dispatch_ids = $alerts; $code = 2; break }
            $empty = 0
        }
    }
} catch {
    $code = 1
    $result = @{schema_version=1; event='error'; reason=$_.Exception.Message}
    if ($null -ne $script:directory) {
        $result.run_id = $script:spec.run_id; $result.receipt = $script:receipt; $result.output_dir = $script:directory
    }
}
$result | ConvertTo-Json -Depth 20 -Compress
exit $code

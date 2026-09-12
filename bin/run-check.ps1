#Requires -Version 5.1
<# C3 local blocking supervisor; see skills/orca-dev/runtime-contracts.md.
   No Python/Bash dependency. Win32 Job Object owns the entire command tree. #>
[CmdletBinding(PositionalBinding = $false)]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args = @())
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$utf8 = New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8

# OS interop stays local to this entry point. At CreateProcess the job-list
# attribute binds ownership atomically (Windows 10+), before any code can run.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
public sealed class CheckJob : IDisposable {
  [StructLayout(LayoutKind.Sequential)] struct SA { public int length; public IntPtr descriptor; public int inherit; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct SI {
    public int cb; public string reserved, desktop, title; public int x,y,cx,cy,charsX,charsY,fill,flags;
    public short show, reservedSize; public IntPtr reservedPtr, stdin, stdout, stderr;
  }
  [StructLayout(LayoutKind.Sequential)] struct SIX { public SI si; public IntPtr attributes; }
  [StructLayout(LayoutKind.Sequential)] struct PI { public IntPtr process, thread; public uint pid, tid; }
  [StructLayout(LayoutKind.Sequential)] struct BasicLimit {
    public long processTime, jobTime; public uint flags; public UIntPtr min, max;
    public uint active; public UIntPtr affinity; public uint priority, scheduling;
  }
  [StructLayout(LayoutKind.Sequential)] struct IO { public ulong a,b,c,d,e,f; }
  [StructLayout(LayoutKind.Sequential)] struct ExtendedLimit {
    public BasicLimit basic; public IO io; public UIntPtr processMemory, jobMemory, peakProcess, peakJob;
  }
  [StructLayout(LayoutKind.Sequential)] struct Accounting {
    public long a,b,c,d; public uint pageFaults, total, active, terminated;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr sa, string name);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr OpenJobObject(uint access, bool inherit, string name);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimit info, int length);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job, int kind, out Accounting info, int length, IntPtr ret);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint code);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr key, IntPtr value, IntPtr size, IntPtr previous, IntPtr returned);
  [DllImport("kernel32.dll")] static extern void DeleteProcThreadAttributeList(IntPtr list);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateFile(string path, uint access, uint share, ref SA sa, uint creation, uint flags, IntPtr template);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateProcess(string app, StringBuilder command, IntPtr pa, IntPtr ta, bool inherit, uint flags, IntPtr env, string cwd, ref SIX si, out PI pi);
  [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
  [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle, uint timeout);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool MoveFileEx(string from, string to, uint flags);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern uint GetFinalPathNameByHandle(IntPtr file, StringBuilder path, uint length, uint flags);
  IntPtr job, process;
  public uint Pid { get; private set; }
  static void Check(bool ok) { if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error()); }
  static string LongPath(string path) {
    path = path.Replace('/', '\\');
    if (path.StartsWith(@"\\?\")) return path;
    return path.StartsWith(@"\\") ? @"\\?\UNC\" + path.Substring(2) : @"\\?\" + path;
  }
  public static void Replace(string from, string to) { Check(MoveFileEx(LongPath(from), LongPath(to), 9)); }
  public static string CanonicalDirectory(string path) {
    var sa = new SA { length = Marshal.SizeOf(typeof(SA)) };
    IntPtr h = CreateFile(LongPath(path), 0, 7, ref sa, 3, 0x02000000, IntPtr.Zero);
    Check(h != new IntPtr(-1));
    try {
      var text = new StringBuilder(32768);
      uint n = GetFinalPathNameByHandle(h, text, (uint)text.Capacity, 0); Check(n > 0 && n < text.Capacity);
      return text.ToString().TrimEnd('\\').ToLowerInvariant();
    } finally { CloseHandle(h); }
  }
  public CheckJob(string name) {
    job = CreateJobObject(IntPtr.Zero, name); Check(job != IntPtr.Zero);
    if (Marshal.GetLastWin32Error() == 183) { Dispose(); throw new Exception("Job identity already exists"); }
    var info = new ExtendedLimit(); info.basic.flags = 0x2000; // KILL_ON_JOB_CLOSE; breakaway is disabled
    try { Check(SetInformationJobObject(job, 9, ref info, Marshal.SizeOf(info))); }
    catch { Dispose(); throw; }
  }
  public void Start(string shell, string encoded, string cwd, string stdout, string stderr) {
    var sa = new SA { length = Marshal.SizeOf(typeof(SA)), inherit = 1 };
    IntPtr[] handles = new IntPtr[3]; IntPtr list = IntPtr.Zero, jobs = IntPtr.Zero, hs = IntPtr.Zero;
    bool initialized = false;
    try {
      handles[0] = CreateFile("NUL", 0x80000000, 3, ref sa, 3, 0, IntPtr.Zero);
      handles[1] = CreateFile(LongPath(stdout), 0x40000000, 3, ref sa, 2, 0, IntPtr.Zero);
      handles[2] = CreateFile(LongPath(stderr), 0x40000000, 3, ref sa, 2, 0, IntPtr.Zero);
      foreach (var h in handles) Check(h != new IntPtr(-1) && h != IntPtr.Zero);
      IntPtr size = IntPtr.Zero;
      InitializeProcThreadAttributeList(IntPtr.Zero, 2, 0, ref size);
      list = Marshal.AllocHGlobal(size); Check(InitializeProcThreadAttributeList(list, 2, 0, ref size)); initialized = true;
      jobs = Marshal.AllocHGlobal(IntPtr.Size); Marshal.WriteIntPtr(jobs, job);
      Check(UpdateProcThreadAttribute(list, 0, new IntPtr(0x2000D), jobs, new IntPtr(IntPtr.Size), IntPtr.Zero, IntPtr.Zero));
      hs = Marshal.AllocHGlobal(3 * IntPtr.Size);
      for (int i = 0; i < 3; i++) Marshal.WriteIntPtr(hs, i * IntPtr.Size, handles[i]);
      Check(UpdateProcThreadAttribute(list, 0, new IntPtr(0x20002), hs, new IntPtr(3 * IntPtr.Size), IntPtr.Zero, IntPtr.Zero));
      var si = new SIX(); si.si.cb = Marshal.SizeOf(typeof(SIX)); si.attributes = list;
      si.si.flags = 0x101; si.si.show = 0; // USESTDHANDLES + USESHOWWINDOW (hidden)
      si.si.stdin = handles[0]; si.si.stdout = handles[1]; si.si.stderr = handles[2];
      PI pi;
      var cmd = new StringBuilder("\"" + shell + "\" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -OutputFormat Text -EncodedCommand " + encoded);
      Check(CreateProcess(shell, cmd, IntPtr.Zero, IntPtr.Zero, true, 0x08080004, IntPtr.Zero, cwd, ref si, out pi));
      process = pi.process; Pid = pi.pid;
      try { Check(ResumeThread(pi.thread) != 0xFFFFFFFF); } finally { CloseHandle(pi.thread); }
    } finally {
      if (initialized) DeleteProcThreadAttributeList(list);
      if (list != IntPtr.Zero) Marshal.FreeHGlobal(list);
      if (jobs != IntPtr.Zero) Marshal.FreeHGlobal(jobs);
      if (hs != IntPtr.Zero) Marshal.FreeHGlobal(hs);
      foreach (var h in handles) if (h != IntPtr.Zero && h != new IntPtr(-1)) CloseHandle(h);
    }
  }
  static int Active(IntPtr h) {
    Accounting info; Check(QueryInformationJobObject(h, 1, out info, Marshal.SizeOf(typeof(Accounting)), IntPtr.Zero));
    return (int)info.active;
  }
  public int Count { get { return Active(job); } }
  public bool Exited { get { return process != IntPtr.Zero && WaitForSingleObject(process, 0) == 0; } }
  public long ExitCode { get { uint c; Check(GetExitCodeProcess(process, out c)); return c; } }
  public void Stop() { Check(TerminateJobObject(job, 124)); }
  public static int Probe(string name) {
    IntPtr h = OpenJobObject(4, false, name);
    if (h == IntPtr.Zero) { int e = Marshal.GetLastWin32Error(); return e == 2 ? 0 : -1; }
    try { return Active(h); } finally { CloseHandle(h); }
  }
  public void Dispose() {
    if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
    if (process != IntPtr.Zero) { CloseHandle(process); process = IntPtr.Zero; }
  }
}
'@

function Safe-Path([string]$path) {
  $full = [IO.Path]::GetFullPath($path)
  $part = $full
  while ($part) {
    $entry = Get-Item -Force -LiteralPath $part -ErrorAction SilentlyContinue
    if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "reparse point in owned artifact path: $part" }
    $part = [IO.Path]::GetDirectoryName($part)
  }
  return $full
}
function Read-Json([string]$path) { return ([IO.File]::ReadAllText((Safe-Path $path), $utf8) | ConvertFrom-Json) }
function Write-Json([string]$path, $value) {
  $path = Safe-Path $path
  $tmp = $path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
  [IO.File]::WriteAllText($tmp, ($value | ConvertTo-Json -Depth 15 -Compress), $utf8)
  [CheckJob]::Replace($tmp, $path)
}
function Json($v) { return ($v | ConvertTo-Json -Depth 15 -Compress) }
function Equal-Json($a, $b) {
  if ($null -eq $a -or $null -eq $b) { return $null -eq $a -and $null -eq $b }
  if ($a -is [System.Management.Automation.PSCustomObject]) {
    $names = @($a.PSObject.Properties.Name | Sort-Object)
    if (($names -join '|') -cne (@($b.PSObject.Properties.Name | Sort-Object) -join '|')) { return $false }
    foreach ($name in $names) { if (-not (Equal-Json $a.$name $b.$name)) { return $false } }
    return $true
  }
  return (Json $a) -ceq (Json $b)
}
function Identity([int]$processId) {
  try {
    $proc = [Diagnostics.Process]::GetProcessById($processId)
    try { return [pscustomobject]@{ pid = $processId; start = $proc.StartTime.ToUniversalTime().Ticks.ToString(); host = [Environment]::MachineName } }
    finally { $proc.Dispose() }
  } catch [ArgumentException] { return $false } catch { return $null }
}
function Alive($record) {
  if (-not $record) { return $null }
  $current = Identity $record.pid
  if ($null -eq $current) { return $null }
  if ($current -eq $false) { return $false }
  if ($record.host -cne $current.host) { return $null }
  return Equal-Json $record $current
}
function Tree-Clear($state) {
  if (-not $state.tree -or $state.tree.kind -ne 'windows-job' -or -not $state.supervisor) { return $false }
  if ($state.supervisor.host -cne [Environment]::MachineName) { return $false }
  return [CheckJob]::Probe($state.tree.name) -eq 0
}
function Observe([string]$runDir) {
  $path = Join-Path $runDir 'result.json'
  if (-not (Test-Path -LiteralPath $path)) { $path = Join-Path $runDir 'status.json' }
  if (-not (Test-Path -LiteralPath $path)) { return [pscustomobject]@{ state = 'unknown'; reason = 'initializing-or-lost-owner'; run_dir = $runDir } }
  $state = Read-Json $path
  if ($state.state -in @('running', 'waiting-resource') -and (Alive $state.supervisor) -ne $true) {
    $state.state = 'unknown'; $state.reason = 'owner-unverifiable-or-exited'; $state.exit_code = $null
    $state.logs_complete = $false; $state.cleanup_verified = Tree-Clear $state
  }
  return $state
}
function Result-Code($state) {
  if ($state.state -eq 'exited' -and $state.cleanup_verified -and $state.logs_complete) {
    return [BitConverter]::ToInt32([BitConverter]::GetBytes([uint32]$state.exit_code), 0)
  }
  if ($state.state -eq 'interrupted') { return 124 }
  return 125
}
function Validate-Spec($spec) {
  $required = @('schema_version','run_id','owner','cwd','command','shell','run_dir','timeout_seconds','cancel_grace_seconds','no_progress_seconds')
  $names = @($spec.PSObject.Properties.Name)
  foreach ($name in $required) { if ($name -notin $names) { throw "missing $name" } }
  foreach ($name in $names) { if ($name -notin ($required + @('progress_file','resource_key'))) { throw "unexpected $name" } }
  if ($spec.schema_version -ne 1 -or $spec.run_id -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$') { throw 'invalid schema or run_id' }
  $ownerFields = if ($spec.owner.kind -eq 'local') { @('kind','id') } elseif ($spec.owner.kind -eq 'orca') { @('kind','orca_run_id','task_id','dispatch_id','terminal_handle') } else { throw 'invalid owner kind' }
  if ((@($spec.owner.PSObject.Properties.Name | Sort-Object) -join '|') -cne (($ownerFields | Sort-Object) -join '|')) { throw 'invalid owner fields' }
  foreach ($field in $ownerFields) { if ($spec.owner.$field -isnot [string] -or -not $spec.owner.$field) { throw 'invalid owner value' } }
  foreach ($name in @('command','shell','cwd','run_dir')) {
    if ($spec.$name -isnot [string] -or -not $spec.$name -or $spec.$name.Contains([char]0)) { throw "invalid $name" }
  }
  foreach ($name in @('timeout_seconds','cancel_grace_seconds','no_progress_seconds')) {
    $v = $spec.$name
    if ($null -eq $v -and $name -ne 'cancel_grace_seconds') { continue }
    if ($null -eq $v -or $v -is [string] -or $v -is [bool] -or [double]::IsNaN($v) -or [double]::IsInfinity($v) -or $v -lt 0) { throw "invalid $name" }
  }
  foreach ($name in @('cwd','shell','run_dir')) { if ($spec.$name -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)') { throw "$name must be absolute" } }
  if (-not (Test-Path -LiteralPath $spec.cwd -PathType Container) -or [IO.Path]::GetFileName($spec.shell) -notin @('powershell.exe','pwsh.exe')) { throw 'invalid cwd or shell' }
  $r = Safe-Path $spec.run_dir; $checks = [IO.Path]::GetDirectoryName($r); $ws = [IO.Path]::GetDirectoryName($checks)
  if ([IO.Path]::GetFileName($r) -cne $spec.run_id -or [IO.Path]::GetFileName($checks) -ne 'checks' -or
      [IO.Path]::GetFileName([IO.Path]::GetDirectoryName($ws)) -ne 'sdd' -or
      [IO.Path]::GetFileName([IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($ws))) -ne '.superpowers' -or
      -not (Test-Path -LiteralPath $ws -PathType Container)) { throw 'run_dir must be an existing plan workspace / checks / run_id' }
  if ('resource_key' -notin $names) { $spec | Add-Member resource_key $null }
  if ('progress_file' -notin $names) { $spec | Add-Member progress_file $null }
  if ($null -ne $spec.resource_key -and ($spec.resource_key -isnot [string] -or -not $spec.resource_key)) { throw 'invalid resource_key' }
  if ($null -ne $spec.progress_file) {
    if ($spec.progress_file -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)') { throw 'progress_file must be absolute' }
    [void](Safe-Path $spec.progress_file)
  }
  return $r
}
function Resource-Path($spec) {
  if (-not $spec.resource_key) { return $null }
  $common = & git -C $spec.cwd rev-parse --git-common-dir 2>$null
  if ($LASTEXITCODE -ne 0) { throw 'resource_key requires Git common dir' }
  if (-not [IO.Path]::IsPathRooted($common)) { $common = Join-Path $spec.cwd $common }
  $common = [CheckJob]::CanonicalDirectory($common)
  $hash = [Security.Cryptography.SHA256]::Create()
  try { $key = [BitConverter]::ToString($hash.ComputeHash($utf8.GetBytes($common + "`n" + $spec.resource_key))).Replace('-','').ToLowerInvariant() } finally { $hash.Dispose() }
  $root = Safe-Path (Join-Path ([IO.Path]::GetTempPath()) 'orca-dev-resources')
  [void][IO.Directory]::CreateDirectory($root)
  return Join-Path $root ($key + '.json')
}
function Claim($path, $binding) {
  if (-not $path) { return $true }
  [void](Safe-Path $path)
  try {
    $f = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $bytes = $utf8.GetBytes((Json $binding)); $f.Write($bytes,0,$bytes.Length); $f.Flush($true) } finally { $f.Dispose() }
    return $true
  } catch [IO.IOException] {
    # A named mutex serializes stale-lock recovery and release, not execution.
    $mutex = New-Object Threading.Mutex($false, ('Local\orca-check-' + [IO.Path]::GetFileNameWithoutExtension($path)))
    $taken = $false
    try {
      try { $taken = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $taken = $true }
      if (-not $taken) { return $false }
      $previous = Read-Json $path
      $old = Read-Json (Join-Path $previous.run_dir 'status.json')
      if ($old.run_id -cne $previous.run_id -or -not (Equal-Json $old.owner $previous.owner) -or (Alive $old.supervisor) -ne $false) { return $false }
      $final = Join-Path $previous.run_dir 'result.json'
      if (Test-Path -LiteralPath $final) { $old = Read-Json $final }
      if ($old.cleanup_verified -ne $true -and -not (Tree-Clear $old)) { return $false }
      if (Equal-Json (Read-Json $path) $previous) { [IO.File]::Delete((Safe-Path $path)) }
    } catch { } finally { if ($taken) { $mutex.ReleaseMutex() }; $mutex.Dispose() }
    return $false
  }
}
function Run($spec) {
  $r = Validate-Spec $spec
  [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($r))
  # CreateDirectory alone isn't exclusive on Windows. A sibling CreateNew claim
  # is permanent and also protects the gap before request.json is written.
  $claimPath = Safe-Path ($r + '.claim')
  try { $f = [IO.File]::Open($claimPath, 'CreateNew', 'Write', 'None'); $f.Dispose() }
  catch [IO.IOException] {
    if (-not (Equal-Json (Read-Json (Join-Path $r 'request.json')) $spec)) { throw 'run_id already bound to a different spec' }
    $state = Observe $r; Write-Output (Json $state); return Result-Code $state
  }
  if (Test-Path -LiteralPath $r) { throw 'run directory already exists' }
  [void][IO.Directory]::CreateDirectory($r)
  Write-Json (Join-Path $r 'request.json') $spec
  foreach ($name in @('stdout.log','stderr.log')) { [IO.File]::WriteAllText((Join-Path $r $name), '', $utf8) }
  $watch = [Diagnostics.Stopwatch]::StartNew()
  $st = [ordered]@{ schema_version=1; run_id=$spec.run_id; run_dir=$r; owner=$spec.owner; supervisor=(Identity $PID)
    command=$spec.command; cwd=$spec.cwd; shell=$spec.shell; started_at=[DateTime]::UtcNow.ToString('o'); finished_at=$null
    duration_seconds=0; exit_code=$null; state='waiting-resource'; reason=$null; tree=$null; cleanup_verified=$false; logs_complete=$false
    stdout_log=(Join-Path $r 'stdout.log'); stderr_log=(Join-Path $r 'stderr.log'); timeout_seconds=$spec.timeout_seconds; resource_lock=$null
    meaningful_progress='unknown'; output_activity=$false; stalled=$false; diagnostic_events=0 }
  Write-Json (Join-Path $r 'status.json') $st
  $lock = $null; $claimed = $false; $job = $null; $reason = $null; $stopAt = $null; $forcedAt = $null
  $progress = $null; $lastProgress = 0; $rootExitAt = $null
  $binding = [pscustomobject]@{ run_id=$spec.run_id; run_dir=$r; owner=$spec.owner }
  try {
    $lock = Resource-Path $spec; $st.resource_lock = $lock
    while ($true) {
      $elapsed = $watch.Elapsed.TotalSeconds
      $cancel = Join-Path $r 'cancel.json'
      if ((Test-Path -LiteralPath $cancel) -and (Equal-Json (Read-Json $cancel) $spec.owner) -and -not $reason) { $reason = 'cancel' }
      if ($null -ne $spec.timeout_seconds -and $elapsed -ge $spec.timeout_seconds -and -not $reason) { $reason = 'deadline' }
      if (-not $claimed -and -not $reason) { $claimed = Claim $lock $binding }
      if ($claimed -and -not $job -and -not $reason) {
        $jobName = 'Local\orca-check-tree-' + [guid]::NewGuid().ToString('N')
        $job = New-Object CheckJob($jobName)
        $st.tree = @{kind='windows-job'; name=$jobName; leader=$null}
        Write-Json (Join-Path $r 'status.json') $st
        # Cooperative cancellation is a durable file request; after grace the
        # Job Object is terminated. Native console signals are not guessed.
        $script = "[Console]::OutputEncoding = New-Object Text.UTF8Encoding(`$false)`n`$OutputEncoding = [Console]::OutputEncoding`n`$env:PYTHONIOENCODING = 'utf-8'`n`$env:ORCA_CHECK_CANCEL_FILE = '" + $cancel.Replace("'","''") + "'`n`$global:LASTEXITCODE = 0`n`$ErrorActionPreference = 'Continue'`n" + $spec.command + "`n`$__ok = `$?`nif (`$LASTEXITCODE) { exit `$LASTEXITCODE }`nif (-not `$__ok) { exit 1 }`nexit 0`n"
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
        $job.Start($spec.shell, $encoded, $spec.cwd, $st.stdout_log, $st.stderr_log)
        $st.tree.leader = Identity $job.Pid; $st.state = 'running'
        Write-Json (Join-Path $r 'status.json') $st
      }
      if ($job) {
        if ($job.Exited -and $job.Count -eq 0) { $st.exit_code = $job.ExitCode; $st.cleanup_verified = $true; break }
        # Accounting can briefly lag a signaled root handle. Permit the same
        # grace for natural tree exit before classifying surviving descendants.
        if ($job.Exited -and $null -eq $rootExitAt) { $rootExitAt = $elapsed }
        if ($null -ne $rootExitAt -and $elapsed - $rootExitAt -ge $spec.cancel_grace_seconds -and -not $reason) { $reason = 'descendants-after-exit' }
        if ($reason -and $null -eq $stopAt) {
          if (-not (Test-Path -LiteralPath $cancel)) { Write-Json $cancel $spec.owner }
          $stopAt = $elapsed
        }
        if ($null -ne $stopAt -and $elapsed - $stopAt -ge $spec.cancel_grace_seconds -and $null -eq $forcedAt) { $job.Stop(); $forcedAt = $elapsed }
        if ($null -ne $forcedAt -and $elapsed - $forcedAt -gt 2) { $st.reason = 'cleanup-unverifiable'; break }
      } elseif ($reason) { $st.cleanup_verified = $true; break }
      if ($spec.progress_file -and (Test-Path -LiteralPath $spec.progress_file)) {
        $file = [IO.File]::Open((Safe-Path $spec.progress_file), 'Open', 'Read', 'ReadWrite')
        try { $bytes = New-Object byte[] 4097; $length = $file.Read($bytes,0,4097) } finally { $file.Dispose() }
        if ($length -gt 4096) { throw 'progress_file exceeds 4096 bytes' }
        $value = $utf8.GetString($bytes,0,$length)
        if ($value -cne $progress) { $progress=$value; $lastProgress=$elapsed; $st.stalled=$false; $st.meaningful_progress=$value }
      }
      $st.output_activity = (Get-Item -LiteralPath $st.stdout_log).Length -gt 0 -or (Get-Item -LiteralPath $st.stderr_log).Length -gt 0
      if ($null -ne $spec.no_progress_seconds -and $elapsed - $lastProgress -ge $spec.no_progress_seconds -and -not $st.stalled) { $st.stalled=$true; $st.diagnostic_events++ }
      $st.duration_seconds = $elapsed
      Write-Json (Join-Path $r 'status.json') $st
      Start-Sleep -Milliseconds 80
    }
  } catch {
    $reason = 'runner-error: ' + $_.Exception.Message
    if ($job) {
      try {
        $job.Stop(); $until = $watch.Elapsed.TotalSeconds + 2
        while ($job.Count -gt 0 -and $watch.Elapsed.TotalSeconds -lt $until) { Start-Sleep -Milliseconds 50 }
        $st.cleanup_verified = $job.Count -eq 0
        if ($job.Exited) { $st.exit_code = $job.ExitCode }
      } catch { $st.cleanup_verified = $false }
    } else { $st.cleanup_verified = $true }
  } finally { if ($job) { $job.Dispose() } }
  $st.finished_at = [DateTime]::UtcNow.ToString('o'); $st.duration_seconds = $watch.Elapsed.TotalSeconds
  $st.state = if (-not $reason -and $st.cleanup_verified) { 'exited' } elseif ($st.cleanup_verified) { 'interrupted' } else { 'unknown' }
  if (-not $st.reason) { $st.reason = if ($reason) { $reason } else { 'exit' } }
  $st.logs_complete = $st.cleanup_verified
  Write-Json (Join-Path $r 'status.json') $st
  Write-Json (Join-Path $r 'result.json') $st
  if ($claimed -and $lock -and $st.cleanup_verified -and (Equal-Json (Read-Json $lock) $binding)) { [IO.File]::Delete((Safe-Path $lock)) }
  Write-Output (Json $st)
  return Result-Code ([pscustomobject]$st)
}

try {
  if ($Args.Count -eq 2 -and $Args[0] -eq 'run') {
    # Keep structured stdout separate from the function's return exit code.
    $result = @(Run (Read-Json $Args[1])); if ($result.Count -gt 1) { $result[0..($result.Count-2)] | Write-Output }; exit $result[-1]
  }
  if ($Args.Count -in @(2,3) -and $Args[0] -eq 'wait') {
    $r = Safe-Path $Args[1]; $seconds = if ($Args.Count -eq 3) { [double]::Parse($Args[2], [Globalization.CultureInfo]::InvariantCulture) } else { 60 }
    if ([double]::IsNaN($seconds) -or [double]::IsInfinity($seconds) -or $seconds -lt 0) { throw 'invalid wait duration' }
    $watch = [Diagnostics.Stopwatch]::StartNew(); $initial = Observe $r
    while ($true) {
      $state = Observe $r
      if ($state.state -notin @('running','waiting-resource') -or $state.diagnostic_events -ne $initial.diagnostic_events -or $watch.Elapsed.TotalSeconds -ge $seconds) {
        Write-Output (Json $state); exit (Result-Code $state)
      }
      Start-Sleep -Milliseconds 100
    }
  }
  if ($Args.Count -eq 3 -and $Args[0] -eq 'cancel') {
    $r = Safe-Path $Args[1]; $owner = Read-Json $Args[2]
    if (-not (Equal-Json $owner (Read-Json (Join-Path $r 'request.json')).owner)) { throw 'cancel owner does not match run' }
    Write-Json (Join-Path $r 'cancel.json') $owner
    Write-Output (Json (Observe $r)); exit 0
  }
  throw 'usage: run-check.ps1 run SPEC_JSON | wait RUN_DIR [SECONDS] | cancel RUN_DIR OWNER_JSON'
} catch { [Console]::Error.WriteLine('run-check: ' + $_.Exception.Message); exit 125 }

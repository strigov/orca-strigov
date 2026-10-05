#Requires -Version 5.1
# C4/C5 shared native helpers. No Python, YAML module, service or global cache.
$script:VUtf8 = New-Object Text.UTF8Encoding($false, $true)
[Console]::OutputEncoding = $VUtf8
function V-Get($value, [string]$key, $default = $null) {
  if ($value -is [Collections.IDictionary]) { if ($value.Contains($key)) { return ,$value[$key] } }
  elseif ($null -ne $value -and $value.PSObject.Properties[$key]) { return ,$value.$key }
  return $default
}
function V-Keys($value) {
  if ($value -is [Collections.IDictionary]) { return @($value.Keys) }
  return @($value.PSObject.Properties | ForEach-Object { $_.Name })
}
function V-Map() {
  # JSON objects are case-sensitive: an ordinal map, never PowerShell's case-insensitive [ordered]/@{} (model ids, paths).
  return ,(New-Object Collections.Specialized.OrderedDictionary ([StringComparer]::Ordinal))
}
function V-Normal($value) {
  if ($null -eq $value -or $value -is [string] -or $value -is [ValueType]) { return $value }
  if ($value -is [Collections.IDictionary] -or $value -is [pscustomobject]) {
    $keys = [string[]]@(V-Keys $value); [Array]::Sort($keys, [StringComparer]::Ordinal)
    $result = V-Map
    foreach ($key in $keys) { $result[$key] = V-Normal (V-Get $value $key) }
    return ,$result
  }
  $result = @(); foreach ($item in $value) { $result += ,(V-Normal $item) }; return ,$result
}
function V-JsonString([string]$text) {
  # Python json.dumps(ensure_ascii=True): escape quote, backslash, controls and everything outside space..tilde.
  $escaped = [regex]::Replace($text, '[\\"]|[^ -~]', {
    param($m) $c = [int][char]$m.Value
    switch ($c) { 34 { return '\"' } 92 { return '\\' } 10 { return '\n' } 13 { return '\r' } 9 { return '\t' } 8 { return '\b' } 12 { return '\f' } }
    return '\u' + $c.ToString('x4')
  })
  return '"' + $escaped + '"'
}
function V-JsonNumber($value) {
  $culture = [Globalization.CultureInfo]::InvariantCulture
  if ($value -is [double] -or $value -is [single]) {
    $d = [double]$value; if ([double]::IsNaN($d) -or [double]::IsInfinity($d)) { throw 'non-finite JSON number' }
    # Python float repr: integral values below 1e16 keep ".0"; otherwise the shortest round trip with a 2-digit exponent.
    if ($d -eq [Math]::Floor($d) -and [Math]::Abs($d) -lt 1e16) { return ([decimal]$d).ToString($culture) + '.0' }
    $r = $d.ToString('R', $culture)
    if ($r -match '^(-?[0-9.]+)E([+-])([0-9]+)$') { $r = $Matches[1] + 'e' + $Matches[2] + ([int]$Matches[3]).ToString('00') }
    return $r
  }
  return ([IFormattable]$value).ToString($null, $culture)
}
function V-JsonWrite($value, [Text.StringBuilder]$out) {
  if ($null -eq $value) { [void]$out.Append('null'); return }
  if ($value -is [bool]) { [void]$out.Append($(if ($value) { 'true' } else { 'false' })); return }
  if ($value -is [string] -or $value -is [char]) { [void]$out.Append((V-JsonString ([string]$value))); return }
  if ($value -is [datetime] -or $value -is [datetimeoffset]) { [void]$out.Append((V-JsonString $value.ToString('o', [Globalization.CultureInfo]::InvariantCulture))); return }
  if ($value -is [ValueType]) { [void]$out.Append((V-JsonNumber $value)); return }
  if ($value -is [Collections.IDictionary]) {
    $keys = [string[]]@($value.Keys); [Array]::Sort($keys, [StringComparer]::Ordinal); [void]$out.Append('{'); $first = $true
    foreach ($key in $keys) { if (-not $first) { [void]$out.Append(',') }; $first = $false; [void]$out.Append((V-JsonString $key)).Append(':'); V-JsonWrite $value[$key] $out }
    [void]$out.Append('}'); return
  }
  [void]$out.Append('['); $first = $true
  foreach ($item in $value) { if (-not $first) { [void]$out.Append(',') }; $first = $false; V-JsonWrite $item $out }
  [void]$out.Append(']')
}
function V-Json($value) {
  # Canonical JSON, byte-identical to Python json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")):
  # every identity (candidate, package, snapshot, request) hashes the same bytes on both backends.
  $out = New-Object Text.StringBuilder; V-JsonWrite (V-Normal $value) $out; return $out.ToString()
}
function V-Hash([byte[]]$bytes) {
  $h = [Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($h.ComputeHash($bytes)).Replace('-','').ToLowerInvariant() } finally { $h.Dispose() }
}
function V-FileHash([string]$path) {
  $stream=[IO.File]::OpenRead($path); $hash=[Security.Cryptography.SHA256]::Create()
  try { return [BitConverter]::ToString($hash.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
  finally { $stream.Dispose(); $hash.Dispose() }
}
function V-Id($value) { return V-Hash $VUtf8.GetBytes((V-Json $value)) }
function V-Load([string]$path) { return [IO.File]::ReadAllText($path, $VUtf8) | ConvertFrom-Json }
function V-Save([string]$path, $value) {
  V-Safe $path
  $tmp = $path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
  try {
    [IO.File]::WriteAllText($tmp, (V-Json $value), $VUtf8)
    [OrcaVerification.VerificationFile]::Replace($tmp, $path)
  } finally { if ([IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) } }
}
function V-Safe([string]$path) {
  $p = [IO.Path]::GetFullPath($path)
  while ($p) {
    try { $attributes=[IO.File]::GetAttributes($p) }
    catch [IO.FileNotFoundException] { $attributes=0 }
    catch [IO.DirectoryNotFoundException] { $attributes=0 }
    if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw "reparse input/output: $p" }
    $p = [IO.Path]::GetDirectoryName($p)
  }
}
function V-Quote([string]$arg) {
  if ($arg -ne '' -and $arg -notmatch '[\s"]') { return $arg }
  $b = New-Object Text.StringBuilder; [void]$b.Append('"'); $slashes = 0
  foreach ($c in $arg.ToCharArray()) {
    if ($c -eq '\') { $slashes++; continue }
    if ($c -eq '"') { [void]$b.Append('\' * ($slashes * 2 + 1)).Append('"'); $slashes = 0; continue }
    if ($slashes) { [void]$b.Append('\' * $slashes); $slashes = 0 }; [void]$b.Append($c)
  }
  if ($slashes) { [void]$b.Append('\' * ($slashes * 2)) }; [void]$b.Append('"'); return $b.ToString()
}
function V-Exec([string]$exe, [string[]]$arguments, [string]$cwd, [hashtable]$environment = @{}, [int]$timeout = 10000) {
  $psi = New-Object Diagnostics.ProcessStartInfo
  $psi.FileName = $exe; $psi.Arguments = (@($arguments | ForEach-Object { V-Quote $_ }) -join ' ')
  $psi.WorkingDirectory = $cwd; $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
  $psi.RedirectStandardInput = $true; $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
  foreach ($key in $environment.Keys) { $psi.EnvironmentVariables[$key] = $environment[$key] }
  $p = [Diagnostics.Process]::Start($psi); $p.StandardInput.Close(); $bytes = New-Object IO.MemoryStream
  try {
    $copy = $p.StandardOutput.BaseStream.CopyToAsync($bytes); $err = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit($timeout)) { $p.Kill(); throw "bounded helper timed out: $exe" }
    [void]$copy.GetAwaiter().GetResult()
    if ($p.ExitCode -ne 0) { throw "helper exit $($p.ExitCode): $exe $($arguments -join ' '): $($err.Result)" }
    return ,$bytes.ToArray()
  } finally { $bytes.Dispose(); $p.Dispose() }
}
function V-Git([string]$root, [string[]]$arguments, [hashtable]$environment = @{}) {
  $e = @{ GIT_OPTIONAL_LOCKS='0' }; foreach ($key in $environment.Keys) { $e[$key] = $environment[$key] }
  return ,(V-Exec $script:VGitExecutable (@('-C', $root) + $arguments) $root $e)
}
$script:VGitExecutable = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
function V-GitText([string]$root, [string[]]$arguments) { return $VUtf8.GetString((V-Git $root $arguments)).Trim() }
function V-Nul([byte[]]$bytes) { return @($VUtf8.GetString($bytes).Split([char]0) | Where-Object { $_ -ne '' }) }
function V-Strip([string]$v) {
  $q = $null; $i = 0
  while ($i -lt $v.Length) {
    $c = $v[$i]
    if ($q) {
      if ($q -eq '"' -and $c -eq '\') { $i += 2; continue }
      if ($c -eq $q) { $q = $null }
    } elseif ($c -eq '"' -or $c -eq "'") { $q = $c }
    elseif ($c -eq '#' -and ($i -eq 0 -or [char]::IsWhiteSpace($v[$i-1]))) { return $v.Substring(0,$i).TrimEnd() }
    $i++
  }; return $v.TrimEnd()
}
function V-Unquote([string]$v) {
  if ($v.Length -ge 2 -and $v[0] -eq '"' -and $v[-1] -eq '"') {
    try { return ConvertFrom-Json $v -ErrorAction Stop } catch { return $v.Substring(1,$v.Length-2).Replace('\"','"').Replace('\\','\') }
  }
  if ($v.Length -ge 2 -and $v[0] -eq "'" -and $v[-1] -eq "'") { return $v.Substring(1,$v.Length-2).Replace("''", "'") }
  return $v
}
function V-Flow([string]$value) {
  $out = @(); $start = 0; $q = $null; $depth = 0; $i = 0
  while ($i -lt $value.Length) {
    $c = $value[$i]
    if ($q) {
      if ($q -eq '"' -and $c -eq '\') { $i += 2; continue }
      if ($c -eq $q) { $q = $null }
    } elseif ($c -eq '"' -or $c -eq "'") { $q = $c }
    elseif ($c -eq '[' -or $c -eq '{') { $depth++ }
    elseif ($c -eq ']' -or $c -eq '}') { $depth-- }
    elseif ($c -eq ',' -and $depth -eq 0) { $out += $value.Substring($start,$i-$start).Trim(); $start = $i+1 }
    if ($depth -lt 0) { throw 'unbalanced verify list' }; $i++
  }
  if ($q -or $depth) { throw 'unbalanced verify list' }
  $out += $value.Substring($start).Trim(); return @($out | Where-Object { $_ })
}
function V-Check($value, [int]$ordinal = 1) {
  $r = [ordered]@{ id="legacy-$ordinal"; checkpoint='directed'; timeout_seconds=$null; cancel_grace_seconds=2
    no_progress_seconds=$null; resource_key=$null; progress_file=$null; inputs=@(); environment=@(); hermetic=$false; independent_replay=$false; command=$null }
  if ($value -is [string]) { $value = @{command=$value} }
  if ($value -isnot [Collections.IDictionary] -and $value -isnot [pscustomobject]) { throw 'invalid check object' }
  foreach ($key in (V-Keys $value)) { if ($key -cnotin @($r.Keys)) { throw "unsupported check field: $key" }; $r[$key] = V-Get $value $key }
  foreach ($key in 'id','command') { if ($r[$key] -isnot [string] -or -not $r[$key] -or $r[$key].Contains([string][char]0)) { throw "invalid check $key" } }
  if ($r.checkpoint -cnotin @('directed','integration','final')) { throw 'invalid checkpoint' }
  foreach ($key in 'hermetic','independent_replay') { if ($r[$key] -isnot [bool]) { throw "invalid $key" } }
  foreach ($key in 'timeout_seconds','no_progress_seconds','cancel_grace_seconds') {
    $v = $r[$key]; if ($null -eq $v -and $key -ne 'cancel_grace_seconds') { continue }
    if ($null -eq $v -or $v -is [bool] -or $v -is [string] -or [double]::IsNaN($v) -or [double]::IsInfinity($v) -or $v -lt 0) { throw "invalid $key" }
  }
  foreach ($key in 'progress_file','resource_key') { if ($null -ne $r[$key] -and ($r[$key] -isnot [string] -or -not $r[$key])) { throw "invalid $key" } }
  foreach ($key in 'inputs','environment') { if ($r[$key] -isnot [Array]) { throw "invalid $key" } }
  foreach ($v in $r.inputs) { if ($v -isnot [string] -or -not $v) { throw 'invalid input' } }
  foreach ($v in $r.environment) {
    if ($v -is [string] -and $v -cmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
    if ((@(V-Keys $v) | Sort-Object) -join ',' -ne 'tool,version_args') { throw 'invalid tool declaration' }
    if ((V-Get $v 'tool') -isnot [string] -or -not (V-Get $v 'tool') -or (V-Get $v 'version_args') -isnot [Array]) { throw 'invalid tool declaration' }
    foreach ($a in $v.version_args) { if ($a -isnot [string]) { throw 'invalid version argument' } }
  }
  return $r
}
function V-Parse([string]$plan, [string]$phase = '', [string]$checkpoint = '') {
  $front = [regex]::Match([IO.File]::ReadAllText($plan,$VUtf8), '^---\r?\n(.*?)\r?\n---(?:\r?\n|$)', 'Singleline')
  if (-not $front.Success) { return @() }; $lines = @($front.Groups[1].Value -split '\r?\n')
  if ($phase) {
    $p = -1; for ($i=0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^phases:') { $p=$i; break } }
    if ($p -lt 0) { throw "phase not found: $phase" }
    $end = $lines.Count; $entries = @()
    for ($i=$p+1; $i -lt $lines.Count; $i++) {
      if ($lines[$i] -match '^\w') { $end=$i; break }
      $m = [regex]::Match($lines[$i], '^(\s*)-\s+id:\s*(.*?)\s*$')
      if ($m.Success) { $entries += @{line=$i; width=$m.Groups[1].Length+2; id=(V-Unquote (V-Strip $m.Groups[2].Value))} }
    }
    $found = @($entries | Where-Object { $_.id -ceq $phase })
    if ($found.Count -ne 1) { throw "missing or duplicate phase: $phase" }
    $f=$found[0]; foreach ($entry in $entries) { if ($entry.line -gt $f.line) { $end=$entry.line; break } }
    $selected=@(); for ($i=$f.line+1; $i -lt $end; $i++) { $selected += $(if ($lines[$i].Trim()) { $lines[$i].Substring($f.width) } else { '' }) }; $lines=$selected
  }
  $keys=@(); for ($i=0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^verify:\s*(.*?)\s*$') { $keys += @{line=$i; tail=(V-Strip $Matches[1])} } }
  if ($keys.Count -eq 0) { return @() }; if ($keys.Count -ne 1) { throw 'duplicate verify key' }
  $k=$keys[0]; $raw=@()
  if ($k.tail) {
    if (-not ($k.tail.StartsWith('[') -and $k.tail.EndsWith(']'))) { throw 'verify must be a list' }
    $raw=@(V-Flow $k.tail.Substring(1,$k.tail.Length-2))
  } else {
    $i=$k.line+1
    while ($i -lt $lines.Count) {
      $line=$lines[$i]; if (-not $line.Trim() -or $line.TrimStart().StartsWith('#')) { $i++; continue }
      $m=[regex]::Match($line, '^(\s*)-(?:\s+(.*))?$')
      if (-not $m.Success) { if ($line -match '^\s+') { throw 'unsupported verify structure' }; break }
      $width=$m.Groups[1].Length; $v=$m.Groups[2].Value.Trim(); $i++
      $scalar=[regex]::Match($v, '^([|>])[-+]?[0-9]*\s*(?:#.*)?$')
      if ($scalar.Success) {
        $body=@()
        while ($i -lt $lines.Count -and (-not $lines[$i].Trim() -or ($lines[$i].Length-$lines[$i].TrimStart().Length) -gt $width)) { $body += $lines[$i]; $i++ }
        while ($body.Count -and -not $body[-1].Trim()) { $body=@($body | Select-Object -SkipLast 1) }
        if (-not $body.Count) { throw 'empty block scalar' }
        $bi=($body | Where-Object { $_.Trim() } | ForEach-Object { $_.Length-$_.TrimStart().Length } | Measure-Object -Minimum).Minimum
        $v=if ($scalar.Groups[1].Value -eq '|') { (@($body | ForEach-Object { if ($_.Trim()) { $_.Substring($bi) } else { '' } }) -join "`n") } else { (@($body | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }) -join ' ') }
        $raw += (ConvertTo-Json -InputObject $v -Compress); continue
      }
      while ($i -lt $lines.Count -and $lines[$i].Trim() -and ($lines[$i].Length-$lines[$i].TrimStart().Length) -gt $width) {
        if ($v.StartsWith('{')) { throw 'verify JSON object must occupy one line' }; $v += ' ' + $lines[$i].Trim(); $i++
      }; $raw += (V-Strip $v)
    }
  }
  $out=@(); $ids=@{}
  foreach ($v in $raw) {
    if (-not $v) { throw 'empty check' }
    if ($v.StartsWith('{')) { $value=ConvertFrom-Json $v -ErrorAction Stop }
    elseif ($v -match '^[\[&*!]' -or ($v[0] -ne '"' -and $v[0] -ne "'" -and $v -match ':\s')) { throw 'unsupported verify structure' }
    else { $value=V-Unquote $v }
    $c=V-Check $value ($out.Count+1); if ($ids.ContainsKey($c.id)) { throw 'duplicate check id' }; $ids[$c.id]=$true; $out += ,$c
  }
  $levels=@{directed=0; integration=1; final=2}
  if ($checkpoint) { if (-not $levels.ContainsKey($checkpoint)) { throw 'invalid checkpoint' }; $out=@($out | Where-Object { $levels[$_.checkpoint] -le $levels[$checkpoint] }) }
  return $out
}

$script:VNativeSource = @'
namespace OrcaVerification {
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class VerificationFile {
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool MoveFileEx(string from,string to,uint flags);
  public static void Replace(string from,string to) { if(!MoveFileEx(from,to,9)) throw new System.ComponentModel.Win32Exception(); }
  [StructLayout(LayoutKind.Sequential)] struct Basic { public long Created, Accessed, Written, Changed; public uint Attributes; }
  [StructLayout(LayoutKind.Sequential)] struct Info { public uint Attributes; public System.Runtime.InteropServices.ComTypes.FILETIME Created, Accessed, Written; public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow; }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern SafeFileHandle CreateFile(string path,uint access,uint share,IntPtr security,uint creation,uint flags,IntPtr template);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandle(SafeFileHandle h, out Info info);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetFileInformationByHandleEx(SafeFileHandle h,int type,out Basic info,uint size);
  public static string Witness(string path) {
    using (var h=CreateFile(path,0x80,7,IntPtr.Zero,3,0x02000000,IntPtr.Zero)) {
      Info i; Basic b;
      if(h.IsInvalid || !GetFileInformationByHandle(h,out i) || !GetFileInformationByHandleEx(h,0,out b,(uint)Marshal.SizeOf(typeof(Basic)))) throw new System.ComponentModel.Win32Exception();
      return i.Volume+":"+i.IndexHigh+":"+i.IndexLow+":"+i.SizeHigh+":"+i.SizeLow+":"+b.Created+":"+b.Written+":"+b.Changed;
    }
  }
}
}
'@
if (-not ('OrcaVerification.VerificationFile' -as [type]) -and -not (Get-Variable -Name VNativeTogether -ValueOnly -ErrorAction SilentlyContinue)) {
  Add-Type -TypeDefinition $VNativeSource
}
function V-File([string]$path) {
  V-Safe $path
  if (-not (Test-Path -LiteralPath $path)) { return @{record=@{type='missing'}; witness=$null} }
  $w=[OrcaVerification.VerificationFile]::Witness($path); $item=New-Object IO.FileInfo($path)
  if ($item.Attributes -band [IO.FileAttributes]::Directory) { return @{record=@{type='directory'}; witness=$w} }
  $hash=V-FileHash $path
  if ($w -cne [OrcaVerification.VerificationFile]::Witness($path)) { throw "unstable file capture: $path" }
  return @{record=@{type='file'; mode=[int]($item.Attributes -band [IO.FileAttributes]::ReadOnly); bytes=$item.Length; sha256=$hash}; witness=$w}
}
function V-Excluded([string]$path, [string[]]$exclusions) {
  foreach ($e in $exclusions) { if ($path.Equals($e,[StringComparison]::OrdinalIgnoreCase) -or $path.StartsWith($e.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { return $true } }; return $false
}
function V-Capture([string]$root, [string[]]$inputs, [string[]]$exclusions) {
  $root=V-GitText $root @('rev-parse','--show-toplevel'); $root=[IO.Path]::GetFullPath($root)
  $indexed=@{}; $records=@{}; $witness=@{}; $names=@{}
  foreach ($entry in (V-Nul (V-Git $root @('ls-files','--stage','-z')))) {
    $pair=$entry.Split(@([char]9),2); $meta=$pair[0].Split(' '); $name=$pair[1]
    if ($meta[2] -ne '0' -or $meta[0] -eq '160000' -or $indexed.ContainsKey($name)) { throw "unmerged, case-colliding index or unresolved submodule: $name" }
    $indexed[$name]=@($meta[0],$meta[1]); $names[$name]=$true
  }
  foreach ($name in (V-Nul (V-Git $root @('ls-files','--others','--exclude-standard','-z')))) {
    if ($names.ContainsKey($name)) { throw "case-colliding path: $name" }; $names[$name]=$true
  }
  foreach ($name in $names.Keys) {
    $path=[IO.Path]::GetFullPath((Join-Path $root $name))
    if (-not $indexed.ContainsKey($name) -and (V-Excluded $path $exclusions)) { continue }
    $f=V-File $path; if ($indexed.ContainsKey($name)) { $f.record['index']=$indexed[$name] }
    $records['repo:'+$name]=$f.record; $witness['repo:'+$name]=$f.witness
  }
  foreach ($inputPath in $inputs) {
    $path=if ([IO.Path]::IsPathRooted($inputPath)) { [IO.Path]::GetFullPath($inputPath) } else { [IO.Path]::GetFullPath((Join-Path $root $inputPath)) }
    if (V-Excluded $path @((Join-Path $root '.git'))) { throw '.git is provenance, not an input tree' }
    $pending=New-Object 'Collections.Generic.Stack[string]'; $pending.Push($path)
    while ($pending.Count) {
      $p=$pending.Pop(); $f=V-File $p; if ($f.record.type -eq 'missing') { throw "missing declared input: $p" }
      $records['input:'+$p]=$f.record; $witness['input:'+$p]=$f.witness
      if ($f.record.type -eq 'directory') { foreach ($child in Get-ChildItem -Force -LiteralPath $p) { $pending.Push($child.FullName) } }
    }
  }
  # Per-path mode/blob entries carry index semantics, not its mutable stat cache.
  return @{manifest=@{root=$root; head=(V-GitText $root @('rev-parse','HEAD')); files=$records; exclusions=@($exclusions)}; witness=$witness}
}
function V-Snapshot([string]$root, [string[]]$inputs=@(), [string[]]$exclusions=@()) {
  try {
    $exclusions=@($exclusions | ForEach-Object { [IO.Path]::GetFullPath($_) })
    $first=V-Capture $root $inputs $exclusions; $second=V-Capture $root $inputs $exclusions
    if ((V-Json $first) -cne (V-Json $second)) { throw 'unstable snapshot capture' }
    return @{schema_version=1; valid=$true; snapshot_id=(V-Id $first.manifest); manifest=$first.manifest; mutation_witness=$first.witness; reason=$null}
  } catch { return @{schema_version=1; valid=$false; snapshot_id=$null; reason=$_.Exception.Message} }
}
function V-Environment($spec) {
  $variables=@{}; $tools=@()
  foreach ($entry in (@(@{tool=$spec.shell; version_args=@()}) + @($spec.verification.check.environment))) {
    if ($entry -is [string]) { $variables[$entry]=V-Id ([Environment]::GetEnvironmentVariable($entry,'Process')); continue }
    $exe=(Get-Command $entry.tool -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $f=V-File $exe; $version=[Diagnostics.FileVersionInfo]::GetVersionInfo($exe).FileVersion
    if ($entry.version_args.Count) { $version=$VUtf8.GetString((V-Exec $exe $entry.version_args $spec.cwd @{} 3000)) }
    if (-not $version -or $VUtf8.GetByteCount($version) -gt 4096) { throw "unknown or unbounded tool version: $exe" }
    $tools+=@{name=$entry.tool; path=$exe; sha256=$f.record.sha256; version=$version.Trim(); version_sha256=(V-Id $version)}
  }
  return @{variables=$variables; tools=@($tools); fingerprint=(V-Id @($variables,$tools))}
}
function V-Context($spec) {
  $v=V-Get $spec 'verification'; if ($null -eq $v) { return $null }
  if (@((V-Keys $v) | Where-Object { $_ -notin @('check','provenance','repeat_reason') }).Count -or $null -eq (V-Get $v 'provenance')) { throw 'invalid verification binding' }
  $c=V-Check $v.check
  $repeat=V-Get $v 'repeat_reason'; if ($null -ne $repeat -and ($repeat -isnot [string] -or -not $repeat)) { throw 'invalid repeat_reason' }
  if ((V-Json $c) -cne (V-Json $v.check) -or $c.command -cne $spec.command) { throw 'verification check differs from command' }
  foreach ($key in 'timeout_seconds','cancel_grace_seconds','no_progress_seconds','resource_key','progress_file') { if ((V-Json $c[$key]) -cne (V-Json (V-Get $spec $key))) { throw "verification policy differs: $key" } }
  $ws=[IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($spec.run_dir))
  $snap=V-Snapshot $spec.cwd $c.inputs @($ws); $envInfo=$null; $reason=$null
  try { $envInfo=V-Environment $spec } catch { $reason=$_.Exception.Message }
  $p=$v.provenance
  if (((@(V-Keys $p) | Sort-Object) -join ',') -cne 'base_sha,kind,linked_dependencies,preparation' -or
      (V-Get $p 'kind') -cnotin @('HEAD','BASE') -or (V-Get $p 'base_sha') -cnotmatch '^[a-f0-9]{40}$' -or
      (V-Get $p 'linked_dependencies') -isnot [Array]) { $reason='unverifiable-provenance' }
  elseif ($p.kind -eq 'BASE') {
    try {
      if ($p.preparation -ne 'git-worktree-add-detach' -or -not $snap.valid -or $snap.manifest.head -cne $p.base_sha -or
          (V-GitText $spec.cwd @('diff','--name-only',$p.base_sha))) { $reason='unverifiable-base-files' }
    } catch { $reason='unverifiable-base-files' }
  }
  $key=@{check=$c; provenance=$v.provenance; shell=$spec.shell; cwd=$spec.cwd; snapshot_id=$snap.snapshot_id; environment=$envInfo
    implementation_sha256=(V-Id @((V-FileHash (Join-Path $PSScriptRoot 'verification.ps1')),(V-FileHash (Join-Path $PSScriptRoot '../run-check.ps1'))))}
  return @{snapshot=$snap; environment=$envInfo; key=$key; reason=$reason}
}
function V-Logs($st) {
  $out=@(); foreach ($n in 'stdout','stderr') { $path=V-Get $st ($n+'_log'); $out+=@{path=$path; bytes=(New-Object IO.FileInfo($path)).Length; sha256=(V-FileHash $path)} }; return $out
}
function V-Tail([string]$path) {
  $stream=[IO.File]::OpenRead($path)
  try {
    [void]$stream.Seek([Math]::Max(0,$stream.Length-65536),'Begin'); $buffer=New-Object byte[] 65536
    $n=$stream.Read($buffer,0,65536); $text=[Text.Encoding]::UTF8.GetString($buffer,0,$n)
    return (@($text -split '\r?\n' | Select-Object -Last 200) -join "`n")
  } finally { $stream.Dispose() }
}
function V-Signature([string]$root, [string]$output) {
  $rows=@()
  foreach ($row in ($output -split '\r?\n')) {
    $line=([regex]::Replace($row,'\x1b\[[0-9;]*[A-Za-z]','')).Replace($root,'ROOT').Replace($root.Replace('\','/'),'ROOT')
    $line=[regex]::Replace($line,'[^ ]*verify-gate-base\.[A-Za-z0-9]*','ROOT')
    $line=[regex]::Replace($line,'[0-9]+(\.[0-9]+)?s\b','Ns')
    if ($line -notmatch '\b(passed|failed|errors?|skipped)\b') { $line=[regex]::Replace($line,'[0-9]{2,}','N') }
    if ($line.Trim()) { $rows+=$line }
  }; return (@($rows | Select-Object -Last 8) -join "`n")
}
function V-EvidenceValid($st, $request=$null) {
  try {
    $resultPath=Join-Path $st.run_dir 'result.json'
    $resultBytes=[IO.File]::ReadAllBytes($resultPath)
    if ((V-Hash $resultBytes) -cne (V-Load (Join-Path $st.run_dir 'result.sha256'))) { return $false }
    # Compare with the same sealed bytes, including the actual outcome.
    $sealed=$VUtf8.GetString($resultBytes).TrimStart([char]0xfeff) | ConvertFrom-Json
    # PS7 parses ISO dates and may omit trailing fractional zeros on serialization.
    # Decode both sides alike, including a live supervisor's in-memory strings.
    $supplied=(V-Json $st) | ConvertFrom-Json
    if ((V-Json $supplied) -cne (V-Json $sealed)) { return $false }
    $e=$st.evidence
    if ($e.schema_version -ne 1 -or -not $e.valid -or $st.state -ne 'exited' -or -not $st.cleanup_verified -or -not $st.logs_complete -or $null -eq $st.exit_code) { return $false }
    if ((V-Json $e.logs) -cne (V-Json @(V-Logs $st))) { return $false }
    if ($e.failure_signature -cne (V-Signature $st.cwd ((V-Tail $st.stdout_log)+"`n"+(V-Tail $st.stderr_log)))) { return $false }
    $req=if ($request) { $request } else { V-Load (Join-Path $st.run_dir 'request.json') }; if ($e.request_sha256 -cne (V-Id $req)) { return $false }
    foreach ($key in 'run_id','run_dir','owner','command','cwd','shell') { if ((V-Json (V-Get $st $key)) -cne (V-Json (V-Get $req $key))) { return $false } }
    if ((V-Json $e.key.check) -cne (V-Json $req.verification.check) -or (V-Json $e.key.provenance) -cne (V-Json $req.verification.provenance)) { return $false }
    if ((V-Json $e.source_before) -cne (V-Json $e.source_after)) { return $false }
    if ($e.origin_run_id) {
      if ((V-Hash ([IO.File]::ReadAllBytes($e.origin_result))) -cne $e.origin_sha256) { return $false }
      $original=V-Load $e.origin_result
      if ($original.run_id -cne $e.origin_run_id -or $original.evidence.origin_run_id -or -not (V-EvidenceValid $original)) { return $false }
    }; return $true
  } catch { return $false }
}
function V-FindReuse($spec, $before) {
  $c=$spec.verification.check
  if (-not $c.hermetic) { return @{origin=$null; reason='non-hermetic'} }
  if ($spec.verification.provenance.linked_dependencies.Count) { return @{origin=$null; reason='linked-dependencies-unverifiable'} }
  if ($c.independent_replay) { return @{origin=$null; reason='required-independent-replay'} }
  if (V-Get $spec.verification 'repeat_reason') { return @{origin=$null; reason=$spec.verification.repeat_reason} }
  if (-not $before.snapshot.valid -or $before.reason) { return @{origin=$null; reason='unknown-input-or-environment'} }
  foreach ($dir in Get-ChildItem -LiteralPath ([IO.Path]::GetDirectoryName($spec.run_dir)) -Directory) {
    try {
      V-Safe $dir.FullName; $st=V-Load (Join-Path $dir.FullName 'result.json'); $e=$st.evidence
      if ([IO.Path]::GetFullPath($st.run_dir) -cne $dir.FullName) { continue }
      if ($e.reusable -and -not $e.origin_run_id -and (V-Json $e.key) -ceq (V-Json $before.key) -and (V-EvidenceValid $st)) { return @{origin=$st; reason='matching-evidence'} }
    } catch { }
  }; return @{origin=$null; reason='no-matching-valid-evidence'}
}
function V-FinishEvidence($spec, $st, $before, [string]$repeatReason, $origin) {
  $after=V-Context $spec; $reasons=@()
  if ($null -eq $before) { $reasons+='command-not-started' }
  elseif (-not $before.snapshot.valid -or -not $after.snapshot.valid) { $reasons+='unknown-snapshot' }
  elseif ((V-Json $before.snapshot) -cne (V-Json $after.snapshot)) { $reasons+='input-mutation' }
  if ($before -and ($before.reason -or $after.reason)) { $reasons+='unknown-environment' }
  elseif ($before -and (V-Json $before.key) -cne (V-Json $after.key)) { $reasons+='environment-mutation' }
  if ($st.state -ne 'exited' -or -not $st.cleanup_verified -or -not $st.logs_complete) { $reasons+='incomplete-command' }
  $logs=@(); try { $logs=@(V-Logs $st) } catch { $reasons+='incomplete-logs' }
  $e=@{schema_version=1; key=$(if ($before) { $before.key } else { $null }); source_before=$(if ($before) { $before.snapshot } else { $null })
    source_after=$after.snapshot; environment=$after.environment; valid=($reasons.Count -eq 0); invalidation_reasons=@($reasons)
    reusable=($reasons.Count -eq 0 -and $spec.verification.check.hermetic -and -not $spec.verification.provenance.linked_dependencies.Count); request_sha256=(V-Id $spec); logs=@($logs); repeat_reason=$repeatReason; origin_run_id=$null
    failure_signature=(V-Signature $st.cwd ((V-Tail $st.stdout_log)+"`n"+(V-Tail $st.stderr_log)))}
  if ($origin) { $p=Join-Path $origin.run_dir 'result.json'; $e.origin_run_id=$origin.run_id; $e.origin_result=$p; $e.origin_sha256=V-Hash ([IO.File]::ReadAllBytes($p)) }
  return $e
}

function V-Values($value) {
  if ($value -is [Collections.IDictionary] -or $value -is [pscustomobject]) { foreach ($key in (V-Keys $value)) { V-Values (V-Get $value $key) } }
  elseif ($value -is [Array]) { foreach ($item in $value) { V-Values $item } }
  else { return $value }
}
function V-ReviewProvenance([string]$path, $files) {
  if (-not [IO.File]::Exists($path)) { return @{provenance=@{status='unknown'}; contracts=@()} }
  $hash=V-FileHash $path; $data=V-Load $path; $bindings=@(); $contracts=@()
  $keys=@(V-Keys $data)
  if ($data.schema_version -ne 1 -or @($keys | Where-Object { $_ -cnotin @('schema_version','writes','contracts','inputs') }).Count -or
      'writes' -cnotin $keys -or 'contracts' -cnotin $keys) { throw 'invalid review provenance declaration' }
  foreach ($write in $data.writes) {
    if (((@(V-Keys $write) | Sort-Object) -join ',') -cne 'dispatch_id,family,files,receipt_path,receipt_sha256,run_id,task_id' -or $write.files -isnot [Array] -or -not $write.family) { throw 'invalid write provenance' }
    if ((V-FileHash $write.receipt_path) -cne $write.receipt_sha256) { throw 'changed write receipt' }
    $facts=@(V-Values (V-Load $write.receipt_path))
    foreach ($key in 'run_id','task_id','dispatch_id') { if (-not $write.$key -or $write.$key -cnotin $facts) { throw 'write receipt binding mismatch' } }
    $bindings+=,$write
    foreach ($record in $files) {
      if ($record.path -cin $write.files) { $record.author_families=@(@($record.author_families)+@($write.family) | Sort-Object -Unique); $record.authorship='requires-family-validation' }
    }
  }
  foreach ($c in $data.contracts) {
    if (((@(V-Keys $c) | Sort-Object) -join ',') -cne 'consumer,id,producer' -or -not $c.id) { throw 'invalid producer/consumer contract' }
    foreach ($key in 'producer','consumer') { if ($c.$key -isnot [Array] -or -not $c.$key.Count) { throw 'invalid contract side' }; foreach ($p in $c.$key) { if ($p -isnot [string] -or -not $p) { throw 'invalid contract path' } } }
    $contracts+=@{id=$c.id; producer=$c.producer; consumer=$c.consumer; coverage='uncovered'}
  }
  if ($hash -cne (V-FileHash $path)) { throw 'changed review provenance' }
  return @{provenance=@{path=$path; sha256=$hash; writes=@($bindings); status='requires-family-validation'}; contracts=@($contracts)}
}

function V-Package([string]$base, [string]$head, [string]$outfile='') {
  $script:VPackageStarted=$false
  $root=V-GitText (Get-Location).Path @('rev-parse','--show-toplevel'); $root=[IO.Path]::GetFullPath($root)
  $base=V-GitText $root @('rev-parse','--verify',($base+'^{commit}'))
  if ($head -ne 'WORKTREE') { $head=V-GitText $root @('rev-parse','--verify',($head+'^{commit}')) }
  if (-not $outfile) {
    if ($head -eq 'WORKTREE') { throw 'WORKTREE mode requires OUTFILE' }
    $outfile=Join-Path $root ('.superpowers/sdd/review-'+$base.Substring(0,7)+'..'+$head.Substring(0,7)+'.diff')
  }
  $out=[IO.Path]::GetFullPath($outfile); $manifestPath=$out+'.manifest.json'; $partsDir=$out+'.parts'; $provenancePath=$out+'.provenance.json'
  $script:VPackageStarted=$true
  foreach ($p in @($out,$manifestPath,$partsDir,$provenancePath)) { V-Safe $p }
  [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($out))
  $exclusions=@($out,$manifestPath,$partsDir,$provenancePath)
  $parent=[IO.Path]::GetDirectoryName($out)
  while ($parent) {
    if ($parent.Equals($root,[StringComparison]::OrdinalIgnoreCase) -or -not $parent.StartsWith($root.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { break }
    $grand=[IO.Path]::GetDirectoryName($parent)
    if ($grand -and [IO.Path]::GetFileName($grand) -eq 'sdd' -and [IO.Path]::GetFileName([IO.Path]::GetDirectoryName($grand)) -eq '.superpowers') { $exclusions=@($parent)+$exclusions; break }
    $parent=$grand
  }
  $inputs=if ([IO.File]::Exists($provenancePath)) { V-Get (V-Load $provenancePath) 'inputs' @() } else { @() }
  if ($null -eq $inputs) { $inputs=@() }
  foreach ($inputPath in $inputs) { if ($inputPath -isnot [string] -or -not $inputPath) { throw 'invalid review input' } }
  $before=V-Snapshot $root $inputs $exclusions
  $index=V-GitText $root @('rev-parse','--git-path','index'); if (-not [IO.Path]::IsPathRooted($index)) { $index=Join-Path $root $index }
  $indexBytes=if ([IO.File]::Exists($index)) { [IO.File]::ReadAllBytes($index) } else { $null }
  $indexHash=if ($null -ne $indexBytes) { V-Hash $indexBytes } else { $null }
  $m=@{schema_version=1; package_id=$null; base=$base; mode=$(if ($head -eq 'WORKTREE') { 'worktree' } else { 'range' }); head=$head
    snapshot_id=$before.snapshot_id; complete=$false; files=@(); parts=@(); exclusions=$exclusions; limitations=@(); coverage=@{parts=@(); files=@(); contracts=@()}}
  $m.inputs=@($inputs); $m.declared_inputs=@()
  if ($before.valid) {
    foreach ($name in $before.manifest.files.Keys) {
      if ($name.StartsWith('input:')) { $m.declared_inputs+=@{path=$name.Substring(6); record=$before.manifest.files[$name]; coverage='uncovered'; inspection_required=$true} }
    }
  }
  $tmp=$null
  try {
    $environment=@{}; $revision=if ($head -eq 'WORKTREE') { @($base) } else { @($base,$head) }
    $names=@(V-Nul (V-Git $root @('ls-files','--cached','--others','--exclude-standard','-z')))
    $tracked=@(V-Nul (V-Git $root @('ls-files','--cached','-z')))
    $omit=@($names | Where-Object { $_ -cnotin $tracked -and (V-Excluded ([IO.Path]::GetFullPath((Join-Path $root $_))) $exclusions) })
    $pathspec=@('.') + @($omit | ForEach-Object { ':(top,literal,exclude)'+$_ })
    $untracked=@(V-Nul (V-Git $root @('ls-files','--others','--exclude-standard','-z')) | Where-Object { $_ -cnotin $omit })
    if ($head -eq 'WORKTREE') {
      $tmp=[IO.Path]::GetTempFileName()
      if ($null -eq $indexBytes) { [IO.File]::Delete($tmp) } else { [IO.File]::WriteAllBytes($tmp,$indexBytes) }
      $environment=@{GIT_INDEX_FILE=$tmp}
      [void](V-Git $root (@('add','--intent-to-add','-A','--')+$pathspec) $environment)
    }
    $diff=V-Git $root (@('diff','--binary','--no-ext-diff','--no-textconv','-U10')+$revision+@('--')+$pathspec) $environment
    $statuses=@(V-Nul (V-Git $root (@('diff','--name-status','--no-renames','-z')+$revision+@('--')+$pathspec) $environment))
    for ($i=0; $i -lt $statuses.Count; $i+=2) {
      $name=$statuses[$i+1]
      $m.files+=@{path=$name; status=$statuses[$i]; untracked=($name -cin $untracked); author_families=@(); authorship='unknown'; coverage='uncovered'}
    }
    $binary=@()
    foreach ($entry in (V-Nul (V-Git $root (@('diff','--numstat','--no-renames','-z')+$revision+@('--')+$pathspec) $environment))) {
      if ($entry.StartsWith("-`t-`t")) { $binary+=$entry.Substring(4) }
    }
    foreach ($record in $m.files) {
      $source=V-Get (V-Get (V-Get $before 'manifest') 'files') ('repo:'+$record.path)
      $record.binary=$record.path -cin $binary; $record.oversize=(V-Get $source 'bytes' 0) -gt 65536; $record.inspection_required=$record.binary -or $record.oversize
    }
    $m.reviewed_trees=@{base=(V-GitText $root @('rev-parse',($base+'^{tree}'))); head=$(if ($head -ne 'WORKTREE') { V-GitText $root @('rev-parse',($head+'^{tree}')) } else { $null })}
    $range=$base+'..'+$(if ($head -eq 'WORKTREE') { 'HEAD' } else { $head })
    $commits=[int](V-GitText $root @('rev-list','--count',$range))
    $log=V-Git $root (@('log','--oneline',$range,'--')+$pathspec)
    $stats=V-Git $root (@('diff','--stat')+$revision+@('--')+$pathspec) $environment
    $stream=New-Object IO.MemoryStream
    try {
      $header=$VUtf8.GetBytes("# Review package: $base..$head`n`n## Commits`n"); $stream.Write($header,0,$header.Length); $stream.Write($log,0,$log.Length)
      if ($head -eq 'WORKTREE') { $t=$VUtf8.GetBytes("plus uncommitted working-tree changes`n"); $stream.Write($t,0,$t.Length) }
      $t=$VUtf8.GetBytes("`n## Files changed`n"); $stream.Write($t,0,$t.Length); $stream.Write($stats,0,$stats.Length)
      $t=$VUtf8.GetBytes("`n## Diff`n"); $stream.Write($t,0,$t.Length); $stream.Write($diff,0,$diff.Length); $data=$stream.ToArray()
    } finally { $stream.Dispose() }
    [IO.File]::WriteAllBytes($out,$data)
    if ($data.Length -gt 65536) { [void][IO.Directory]::CreateDirectory($partsDir) }
    for ($start=0; $start -lt $data.Length; $start+=65536) {
      $length=[Math]::Min(65536,$data.Length-$start); $chunk=New-Object byte[] $length; [Array]::Copy($data,$start,$chunk,0,$length)
      $part=if ($data.Length -le 65536) { $out } else { Join-Path $partsDir (('{0:D4}' -f [int]($start/65536))+'.diff') }
      if ($part -ne $out) { V-Safe $part; [IO.File]::WriteAllBytes($part,$chunk) }
      $m.parts+=@{path=$part; start=$start; end=$start+$length; sha256=(V-Hash $chunk)}
    }
    $diffText=$VUtf8.GetString($diff)
    if ($diffText.Contains('GIT binary patch')) { $m.limitations+='binary source inspection required; uncovered until recorded' }
    if (@($diffText.Split([char]10) | Where-Object { $VUtf8.GetByteCount($_) -gt 65536 }).Count) { $m.limitations+='oversize line split by byte range; source inspection required' }
    $prov=V-ReviewProvenance $provenancePath $m.files; $m.provenance=$prov.provenance; $m.coverage.contracts=$prov.contracts
    $after=V-Snapshot $root $inputs $exclusions
    $m.bytes=$data.Length; $m.sha256=V-Hash $data; $m.snapshot=$before; $m.snapshot_after=$after
    $m.complete=$before.valid -and (V-Json $before) -ceq (V-Json $after)
    if (-not $m.complete) { $m.limitations+='unknown or changed snapshot' }
  } finally {
    if ($tmp -and [IO.File]::Exists($tmp)) { [IO.File]::Delete($tmp) }
    $actual=if ([IO.File]::Exists($index)) { V-Hash ([IO.File]::ReadAllBytes($index)) } else { $null }
    $m.index_preserved=$indexHash -ceq $actual
    if (-not $m.index_preserved) { $m.complete=$false }
    $identity=V-Normal $m; $identity.Remove('package_id'); $m.package_id=V-Id $identity
    V-Save $manifestPath $m
  }
  if (-not $m.complete) { throw "incomplete package: $manifestPath" }
  $empty=$m.files.Count -eq 0 -or ($head -ne 'WORKTREE' -and $commits -eq 0)
  [Console]::WriteLine($(if ($empty) { 'EMPTY ' } else { 'wrote ' })+$out+": $commits commit(s), $($data.Length) bytes")
  if ($empty) { return 1 }; return 0
}
function V-PackageValid([string]$path) {
  try {
    $m=V-Load $path; $identity=V-Normal $m; $identifier=$identity.package_id; $identity.Remove('package_id')
    if ((V-Id $identity) -cne $identifier -or -not $m.complete -or -not $m.index_preserved) { return $false }
    $data=[IO.File]::ReadAllBytes($path.Substring(0,$path.Length-'.manifest.json'.Length))
    if ($data.Length -ne $m.bytes -or (V-Hash $data) -cne $m.sha256) { return $false }
    $offset=0
    foreach ($part in $m.parts) {
      $bytes=[IO.File]::ReadAllBytes($part.path)
      if ($part.start -ne $offset -or $part.end-$offset -ne $bytes.Length -or $bytes.Length -gt 65536 -or (V-Hash $bytes) -cne $part.sha256) { return $false }
      $chunk=New-Object byte[] $bytes.Length; [Array]::Copy($data,$offset,$chunk,0,$bytes.Length)
      if ((V-Hash $chunk) -cne $part.sha256) { return $false }; $offset=$part.end
    }
    if ($offset -ne $data.Length) { return $false }
    if (V-Get $m.provenance 'path') {
      if ((V-FileHash $m.provenance.path) -cne $m.provenance.sha256) { return $false }
      foreach ($write in $m.provenance.writes) { if ((V-FileHash $write.receipt_path) -cne $write.receipt_sha256) { return $false } }
    }
    # Mutation witnesses still guard capture/execution; compare source identity here.
    $current=V-Snapshot $m.snapshot.manifest.root $m.inputs $m.exclusions
    return $current.valid -and $current.snapshot_id -ceq $m.snapshot_after.snapshot_id
  } catch { return $false }
}

if ($MyInvocation.InvocationName -ne '.') {
  $ErrorActionPreference='Stop'
  try {
    switch ($args[0]) {
      'snapshot' { $s=V-Load $args[1]; V-Save $args[2] (V-Snapshot $s.root (V-Get $s 'inputs' @()) (V-Get $s 'exclusions' @())); exit 0 }
      'validate-evidence' { if (V-EvidenceValid (V-Load $args[1])) { exit 0 }; exit 1 }
      'validate-package' { if (V-PackageValid $args[1]) { exit 0 }; exit 1 }
      'parse' { V-Save $args[2] @(V-Parse $args[1] $args[3] $args[4]); exit 0 }
      default { throw 'unknown verification operation' }
    }
  } catch { [Console]::Error.WriteLine("verification: $_"); exit 2 }
}

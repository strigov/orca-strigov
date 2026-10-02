# prompt-fill.ps1 — native Windows port of bin/prompt-fill (see bin/lib/prompt_fill.py for the contract).
#   prompt-fill.ps1 list TEMPLATE
#   prompt-fill.ps1 fill REQUEST_JSON
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'lib/verification.ps1')
$Skill = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../skills/orca-dev'))
$Placeholder = [regex]'\[[A-Z][A-Z0-9_]*\]'

function PF-Fail([string]$reason, [int]$code = 1) {
  [Console]::WriteLine($(if ($code -eq 1) { 'INVALID' } else { 'UNVERIFIABLE' }))
  [Console]::WriteLine((V-Json @{reason = $reason}));exit $code
}
function PF-Read([string]$path) { return [IO.File]::ReadAllText($path, $VUtf8).TrimStart([char]0xfeff).Replace("`r`n", "`n") }
function PF-Boundary() {
  $text = PF-Read (Join-Path $Skill 'orca-recipes.md')
  $text = $text.Substring($text.IndexOf('## 1. Task creation'))
  $m = [regex]::Match($text, '```text\n(.*?)\n```', 'Singleline')
  if (-not $m.Success) { throw 'mandatory boundary block not found in orca-recipes.md' }
  return $m.Groups[1].Value.Trim()
}
function PF-Blocks([string]$text) {
  $out = New-Object 'Collections.Generic.List[object]';$heading = $null;$fence = $null;$start = -1
  $lines = $text.Split("`n")
  for ($n = 0; $n -lt $lines.Length; $n++) {
    $line = $lines[$n];$m = [regex]::Match($line, '^(`{3,})')
    if ($null -eq $fence) {
      if ($line.StartsWith('#')) { $heading = $line.TrimStart('#').Trim() }
      if ($m.Success) { $fence = $m.Groups[1].Value;$start = $n + 1 }
    } elseif ($line.StartsWith($fence)) {
      $body = if ($n -gt $start) { [string]::Join("`n", $lines[$start..($n - 1)]) } else { '' }
      $out.Add(@{heading = $heading;body = $body});$fence = $null
    }
  }
  if ($null -ne $fence) { throw 'unterminated fenced block' }
  return ,$out
}
function PF-TemplatePath([string]$name) {
  $dir = [IO.Path]::GetFullPath((Join-Path $Skill 'prompts'))
  $p = [IO.Path]::GetFullPath((Join-Path $dir $name))
  if ([IO.Path]::GetDirectoryName($p) -ne $dir -or -not [IO.File]::Exists($p)) { throw ('unknown template: ' + $name) }
  return $p
}
function PF-Body([string]$name, $selector) {
  $text = PF-Read (PF-TemplatePath $name);$found = @(PF-Blocks $text)
  if (-not $found.Count) {
    if ($text.StartsWith('#')) { $i = $text.IndexOf("`n");return $(if ($i -ge 0) { $text.Substring($i + 1).Trim("`n") } else { '' }) }
    return $text
  }
  if ($null -eq $selector) { return $found[0].body }
  if ($selector -is [int] -or $selector -is [long] -or $selector -is [double]) {
    $i = [int]$selector
    if ($i -lt 0 -or $i -ge $found.Count) { throw ('block index out of range: {0} of {1}' -f $i, $found.Count) }
    return $found[$i].body
  }
  $matches = @($found | Where-Object { $_.heading -ceq [string]$selector -or ([string]$_.heading).StartsWith([string]$selector, [StringComparison]::Ordinal) })
  if ($matches.Count -ne 1) { throw ('block selector matches {0} blocks: {1}' -f $matches.Count, $selector) }
  return $matches[0].body
}
function PF-Fill([string]$body, $fields) {
  foreach ($key in @($fields.Keys)) {
    if (-not [regex]::IsMatch([string]$key, '^[A-Z][A-Z0-9_]*$') -or $fields[$key] -isnot [string]) { throw ('field must map an UPPER_SNAKE name to a string: ' + $key) }
    $body = $body.Replace('[' + $key + ']', [string]$fields[$key])
  }
  return $body
}
function PF-Placeholders([string]$text) { return @($Placeholder.Matches($text) | ForEach-Object { $_.Value } | Sort-Object -Unique) }

function PF-List($cli) {
  if ($cli.Count -ne 2) { PF-Fail 'usage: prompt-fill list TEMPLATE' 2 }
  try { $text = PF-Read (PF-TemplatePath $cli[1]);$found = @(PF-Blocks $text) } catch { PF-Fail $_.Exception.Message 2 }
  $rows = @();$i = 0
  foreach ($b in $found) { $rows += ,@{index = $i;heading = $b.heading;bytes = [Text.Encoding]::UTF8.GetByteCount([string]$b.body);placeholders = @(PF-Placeholders $b.body)};$i++ }
  if (-not $rows.Count) { $rows = ,@{index = 0;heading = $null;bytes = [Text.Encoding]::UTF8.GetByteCount($text);placeholders = @(PF-Placeholders $text);whole_file = $true} }
  [Console]::WriteLine('VALID');[Console]::WriteLine((V-Json @{template = $cli[1];blocks = $rows}));exit 0
}
function PF-Assemble($cli) {
  if ($cli.Count -ne 2) { PF-Fail 'usage: prompt-fill fill REQUEST_JSON' 2 }
  try {
    $req = V-Normal ((PF-Read $cli[1]) | ConvertFrom-Json)
    if ($req.schema_version -ne 1) { throw 'unsupported request schema' }
    foreach ($k in 'template', 'output') { if (-not $req.Contains($k)) { PF-Fail ('missing request key: ' + $k) 2 } }
    $out = [string]$req.output
    if (-not [IO.Path]::IsPathRooted($out) -or [IO.File]::Exists($out) -or [IO.Directory]::Exists($out) -or -not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($out))) { throw 'output must be a new absolute file in an existing directory' }
    V-Safe $out
    $fields = if ($req.Contains('fields') -and $null -ne $req.fields) { $req.fields } else { @{} }
    if ($fields -isnot [Collections.IDictionary]) { throw 'fields must be an object' }
    $selector = if ($req.Contains('block')) { $req.block } else { $null }
    $bodies = New-Object 'Collections.Generic.List[string]';$bodies.Add((PF-Body $req.template $selector))
    if ($req.Contains('replacements') -and $null -ne $req.replacements) {
      foreach ($old in @($req.replacements.Keys)) {
        $new = $req.replacements[$old]
        if ($old -isnot [string] -or $new -isnot [string] -or -not $old) { throw 'replacements map literal text to text' }
        if (-not $bodies[0].Contains($old)) { throw ('replacement text not in template: ' + $old) }
        $bodies[0] = $bodies[0].Replace($old, $new)
      }
    }
    if ($req.Contains('outcome_contract') -and $req.outcome_contract -eq $true) { $bodies.Add((PF-Body 'outcome-worker-contract.md' $null)) }
    foreach ($key in @($fields.Keys)) { if (-not [regex]::IsMatch([string]$key, '^[A-Z][A-Z0-9_]*$') -or $fields[$key] -isnot [string]) { throw ('field must map an UPPER_SNAKE name to a string: ' + $key) } }
    $declared = @(PF-Placeholders ([string]::Join("`n", $bodies)))
    $unknown = @($fields.Keys | Where-Object { ('[' + $_ + ']') -cnotin $declared } | Sort-Object)
    if ($unknown.Count) { throw ('fields not used by the template: ' + ($unknown -join ', ')) }
    $filled = @($bodies | ForEach-Object { PF-Fill $_ $fields })
    $unfilled = @(PF-Placeholders ([string]::Join("`n", $filled)))
    if ($unfilled.Count) { throw ('unfilled placeholders: ' + ($unfilled -join ', ')) }
    $prepend = if ($req.Contains('prepend') -and $null -ne $req.prepend) { ([string]$req.prepend).Trim("`n") } else { '' }
    $append = if ($req.Contains('append') -and $null -ne $req.append) { ([string]$req.append).Trim("`n") } else { '' }
    $pieces = @((PF-Boundary), $prepend) + $filled + @($append)
    $text = [string]::Join("`n`n", @($pieces | Where-Object { $_ }))
  } catch { PF-Fail $_.Exception.Message 1 }
  $data = [Text.Encoding]::UTF8.GetBytes($text + "`n")
  $stream = New-Object IO.FileStream($out, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
  try { $stream.Write($data, 0, $data.Length);$stream.Flush($true) } finally { $stream.Dispose() }
  $angle = @([regex]::Matches($text, '<[a-z][^<>\n]{0,80}>') | ForEach-Object { $_.Value } | Sort-Object -Unique)
  [Console]::WriteLine('VALID');[Console]::WriteLine((V-Json @{path = $out;sha256 = (V-Hash $data);bytes = $data.Length;worker_tokens = $angle}));exit 0
}

if ($args.Count -and $args[0] -ceq 'list') { PF-List $args }
if ($args.Count -and $args[0] -ceq 'fill') { PF-Assemble $args }
PF-Fail 'usage: prompt-fill list TEMPLATE | fill REQUEST_JSON' 2

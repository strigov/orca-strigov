#Requires -Version 5.1
# C6 facts (native): read-only parsers of hashed inputs (reports, plan, artifacts, fleet pages,
# C4 evidence, Orca observations, actual-model proof). Every decision lives in protocol-state.ps1.
$PReview=@('plan-reviewer','review-primary','review-control','review-final')
$PWrite=@('plan-writer','plan-reviser','implementer','frontend-implementer','quickfix','synthesizer')
$PTokens=V-Map;foreach ($pair in @{
  'plan-writer'=@('PLAN_WRITTEN','REVISED','NEEDS_AUTHORIZATION','BLOCKED');'plan-reviser'=@('REVISED','NEEDS_AUTHORIZATION','BLOCKED')
  'plan-reviewer'=@('APPROVED','CHANGES_REQUESTED','BLOCKED');'implementer'=@('DONE','DONE_WITH_CONCERNS','NEEDS_CONTEXT','NEEDS_AUTHORIZATION','BLOCKED')
  'frontend-implementer'=@('DONE','DONE_WITH_CONCERNS','NEEDS_CONTEXT','NEEDS_AUTHORIZATION','BLOCKED');'quickfix'=@('DONE','DONE_WITH_CONCERNS','NEEDS_CONTEXT','BLOCKED')
  'gate'=@('GATE_OK','GATE_FAIL','NO_COMMANDS','NEEDS_JUDGMENT','BLOCKED');'review-primary'=@('REVIEW_OK','REVIEW_BLOCKING','BLOCKED')
  'review-control'=@('REVIEW_OK','REVIEW_BLOCKING','BLOCKED');'review-final'=@('REVIEW_OK','REVIEW_BLOCKING','BLOCKED')
  'synthesizer'=@('SYNTHESIS_DONE','BLOCKED');'diagnosis'=@('NEEDS_MORE_CONTEXT','NEEDS_MORE_REASONING','PHASE_TOO_LARGE','PLAN_WRONG','IMPASSE_SUMMARY','BLOCKED')
}.GetEnumerator()) { $PTokens[$pair.Key]=$pair.Value }  # ordinal: a role differing in case is unknown, as in Python
function P-Require($ok,[string]$why,[int]$code=1) {
  if (-not $ok) { $e=New-Object InvalidOperationException($why);$e.Data['code']=$code;throw $e }
}
function P-Need($obj,[string[]]$keys) { P-Require ($obj -is [Collections.IDictionary] -and @($keys | Where-Object { -not $obj.Contains($_) }).Count -eq 0) ('missing facts: '+($keys -join ', ')) 2 }
function P-Eq($a,$b) { return (V-Json $a) -ceq (V-Json $b) }
function P-Subset($a,$b) { return @(@($a) | Where-Object { $_ -cnotin @($b) }).Count -eq 0 }
function P-Ref($r) {
  P-Need $r @('path','sha256');P-Require ([IO.Path]::IsPathRooted($r.path)) 'artifact path must be absolute'
  try { V-Safe $r.path } catch { P-Require $false 'linked artifact path' 2 }
  P-Require ([IO.File]::Exists($r.path)) ('missing artifact: '+$r.path) 2
  $bytes=[IO.File]::ReadAllBytes($r.path);P-Require ((V-Hash $bytes) -ceq $r.sha256) ('artifact hash mismatch: '+$r.path)
  return $VUtf8.GetString($bytes).TrimStart([char]0xfeff).Replace("`r`n","`n")
}
function P-List($obj,[string]$key) {
  # An optional JSON array as one flat array (V-Get keeps an array as one pipeline object).
  $v=V-Get $obj $key $null;if ($null -eq $v) { return ,@() };return ,@($v)
}
function P-Decode([string]$text) { return ,(V-Normal ((ConvertFrom-Json -InputObject ('{"data":'+$text+'}')).data)) }
function P-Record($r) { return ,(P-Decode (P-Ref $r)) }
function P-Line([string]$text,[string]$label,$default=$null) {
  $rows=[regex]::Matches($text,'(?m)^'+[regex]::Escape($label)+': (.+)\r?$')
  if (-not $rows.Count -and $null -ne $default) { return ,$default }
  P-Require ($rows.Count -eq 1) ('format: expected one '+$label)
  return ,(P-Decode $rows[0].Groups[1].Value)
}
function P-Report([string]$text,$a,$art,[string]$outcome,$modified) {
  $text=$text.Replace("`r`n","`n")
  $rows=@($text -split '\r?\n');$token=$rows[0];$role=$a.role
  P-Require ($PTokens.Contains($role) -and $token -cin $PTokens[$role]) 'format: role verdict'
  $failed=$token -ceq 'BLOCKED' -or ($role -cin $PWrite -and $token -cin @('NEEDS_CONTEXT','NEEDS_AUTHORIZATION'))
  $expected=if ($failed) { 'failed' } else { 'succeeded' };P-Require ($outcome -ceq $expected) 'format: subject/outcome conflict'
  $b=P-Line $text 'BINDING';$keys=@('schema_version','run_id','task_id','dispatch_id','role','phase','round','artifact_id','snapshot_id')
  P-Require ((P-Subset @(V-Keys $b) $keys) -and (P-Subset $keys @(V-Keys $b)) -and $b.schema_version -eq 1) 'format: binding schema'
  foreach ($key in 'run_id','task_id','dispatch_id','role','phase','round') { P-Require (P-Eq $b[$key] $a[$key]) ('conflicting report binding: '+$key) }
  P-Require ($b.artifact_id -ceq $art.id -and (P-Eq $b.snapshot_id $art.snapshot_id)) 'conflicting artifact binding'
  if ($token -ceq 'BLOCKED') { P-Require ($text.Contains('## Reason')) 'format: missing Reason';return @{token=$token;findings=@();coverage=@{}} }
  if ($role -ceq 'review-primary') {
    P-Require ($rows.Count -ge 3 -and $rows[1] -cin @('SPEC: OK','SPEC: FAIL') -and $rows[2] -cin @('QUALITY: OK','QUALITY: FAIL')) 'format: SPEC/QUALITY'
    P-Require (($token -ceq 'REVIEW_BLOCKING') -eq (($rows[1]+$rows[2]).Contains('FAIL'))) 'format: SPEC/QUALITY verdict conflict'
  }
  if ($role -ceq 'plan-reviewer') {
    $simp=[regex]::Matches($text,'(?m)^SIMPLICITY: (OK|CHANGES_REQUESTED)\r?$')
    P-Require ($text.Contains('## Simplicity') -and $simp.Count -eq 1) 'format: SIMPLICITY'
    P-Require (-not ($token -ceq 'APPROVED' -and $simp[0].Groups[1].Value -cne 'OK')) 'format: simplicity verdict conflict'
  }
  $findings=@()
  if ($role -cin $PReview) {
    $findings=P-Line $text 'FINDINGS';P-Require ($findings -is [Array]) 'format: findings array'
    foreach ($f in $findings) {
      P-Require ($f -is [Collections.IDictionary] -and $f.id -and $f.kind -and $f.issue -and $f.location) 'format: finding fields'
      P-Require ($f.kind -cin @('blocking','cannot_verify')) 'format: finding kind'
      $required=if ($f.kind -ceq 'cannot_verify') { @('check','expect') } elseif ($role -ceq 'review-control') { @('authorization_relation','why_now','minimal_fix','risk') } else { @('class','change','risk') }
      foreach ($key in $required) { P-Require ($f[$key]) 'format: required finding fields' }
      if ($f.kind -ceq 'blocking') {
        P-Require ($f.risk -cin @('none','SECURITY','DATA_LOSS','REGRESSION','GUARANTEED_FAIL')) 'format: finding risk'
        if ($role -cne 'review-control') { P-Require ($f.class -cin @('MUST_FIX_NOW','REGRESSION_FROM_AUTHORIZED_FIX')) 'format: finding class' }
        if ($role -ceq 'plan-reviewer') { P-Require ($f.criterion) 'format: plan criterion';if ($a.round -gt 1 -and $f.class -ceq 'MUST_FIX_NOW') { P-Require ($f.new_blocker_materiality) 'format: new blocker materiality' } }
        if ($f.simplicity) { foreach ($key in 'unnecessary_cost_or_risk','simpler_alternative','preserved_properties') { P-Require ($f[$key]) 'format: simplicity finding' } }
      }
    }
    $blocking=@($findings | Where-Object { $_.kind -ceq 'blocking' }).Count -gt 0
    P-Require (($token -cin @('REVIEW_BLOCKING','CHANGES_REQUESTED')) -eq $blocking) 'format: findings/verdict conflict'
    # An explicitly empty section ("CANNOT_VERIFY: []" or a bare header) states none.
    $stated=[regex]::Replace($text,'(?m)^CANNOT_VERIFY:[ \t]*(\[\])?[ \t]*$','')
    P-Require (-not $stated.Contains('CANNOT_VERIFY') -or @($findings | Where-Object { $_.kind -ceq 'cannot_verify' }).Count) 'format: unstructured CANNOT_VERIFY'
  }
  if ($role -cin @('implementer','frontend-implementer','quickfix') -and ($a.round -gt 1 -or $a.fix)) { $fix=P-Line $text 'FIX_EVIDENCE';P-Require ($fix -is [Collections.IDictionary] -and $fix.tests -and $fix.commands -and $fix.outputs) 'format: fix evidence' }
  if ($role -ceq 'quickfix') { P-Require (@($modified).Count -eq 1) 'quickfix must modify exactly one file' }
  if ($role -ceq 'gate') { P-Require ($rows.Count -gt 1 -and ($rows[1].StartsWith('verify: ') -or $rows[1] -match '^lint: .+ \| typecheck: .+ \| tests: .+')) 'format: gate summary' }
  if ($role -ceq 'synthesizer') { P-Require ($rows.Count -gt 1 -and $rows[1].StartsWith('docs/reviews/')) 'format: synthesis path' }
  if ($role -ceq 'diagnosis') {
    $sections=@{NEEDS_MORE_CONTEXT='Context';NEEDS_MORE_REASONING='Context';PHASE_TOO_LARGE='Split';PLAN_WRONG='Plan defect';IMPASSE_SUMMARY='Summary'}
    P-Require ($text.Contains('## '+$sections[$token]) -and $text.Contains('## Evidence')) 'format: diagnosis sections'
  }
  return @{token=$token;findings=$findings;coverage=(P-Line $text 'COVERAGE' @{})}
}
# Plan bookkeeping lines that may move without the plan author/review path.
$PMeta='(?m)^(?:status|plan_base|orca_run|commits|    status|    base|    commits):.*(?:\n|$)'
function P-PlanRead([string]$text) {
  # Plan frontmatter: structure digest (bookkeeping lines removed), run/base scalars and phase contracts.
  $m=[regex]::Match($text,'^---\n(.*?)\n---(?:\n|$)','Singleline');P-Require $m.Success 'missing plan frontmatter' 2;$front=$m.Groups[1].Value
  $scalar={ param($name) $rows=[regex]::Matches($front,'(?m)^'+$name+':\s*(.*?)\s*$');P-Require ($rows.Count -eq 1) ('missing plan metadata: '+$name) 2;V-Unquote $rows[0].Groups[1].Value }
  $shape=V-Hash $VUtf8.GetBytes([regex]::Replace($front,$PMeta,'')+[string][char]0+$text.Substring($m.Index+$m.Length))
  P-Require ((& $scalar 'protocol_version') -ceq '2') 'legacy metadata is not certified' 2
  $contracts=P-Decode (& $scalar 'contracts')
  P-Require ($contracts -is [Array] -and @($contracts | Select-Object -Unique).Count -eq $contracts.Count) 'invalid contract ids'
  foreach ($c in $contracts) { P-Require ($c -is [string] -and $c -cmatch '^[A-Za-z][A-Za-z0-9_-]*$') 'invalid contract id' }
  $phases=@()
  foreach ($item in @([regex]::Split($front,'(?m)^  - id:\s*') | Select-Object -Skip 1)) {
    $rows=$item -split '\n';$p=@{id=(V-Unquote $rows[0].Trim())}
    foreach ($row in @($rows | Select-Object -Skip 1)) { $f=[regex]::Match($row,'^    (risk|base|consumes|produces):\s*(.*?)\s*$');if ($f.Success) { $p[$f.Groups[1].Value]=$f.Groups[2].Value } }
    P-Require ($p.risk -cin @('none','SECURITY','DATA_LOSS','REGRESSION')) 'format: missing/invalid phase risk'
    P-Need $p @('consumes','produces');foreach ($key in 'consumes','produces') { $p[$key]=P-Decode $p[$key];P-Require ($p[$key] -is [Array]) 'contract references must be arrays' }
    $phases+=,$p
  }
  P-Require ($phases.Count -gt 0 -and @($phases | ForEach-Object { $_.id } | Select-Object -Unique).Count -eq $phases.Count) 'invalid phases'
  $produced=@();foreach ($p in $phases) { P-Require (P-Subset $p.produces $contracts) 'undeclared produced contract';P-Require (P-Subset $p.consumes $produced) 'consume without an earlier producer';$produced+=@($p.produces) }
  return @{shape=$shape;orca_run=(& $scalar 'orca_run');plan_base=(& $scalar 'plan_base');phases=$phases;done=[regex]::IsMatch($front,'(?m)^status: done[ \t]*$')}
}
function P-PlanName($s) {
  if ($null -eq $s.plan) { return $null }
  $path=[IO.Path]::GetFullPath($s.plan.path);$root=[IO.Path]::GetFullPath($s.worktree).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
  $mode=if ([IO.Path]::DirectorySeparatorChar -eq '\') { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
  if (-not $path.StartsWith($root,$mode)) { return $null };return $path.Substring($root.Length).Replace('\','/')
}
function P-Entry($x) {
  # A repository entry's identity: its bytes (or type) and the Git executable bit of its index entry.
  $value=if ($x.Contains('sha256')) { $x.sha256 } else { $x.type }
  $index=V-Get $x 'index';if ($null -ne $index -and @($index)[0] -ceq '100755') { return $value+'+x' };return $value
}
function P-Synthesis($s) {
  # Accepted synthesis documents of this step: path -> entry. Each summarises an acceptance and is frozen by it.
  $out=V-Map;foreach ($r in @($s.accepted)) { $x=V-Get $r 'synthesis';if ($null -ne $x) { $out[$x.path]=$x.entry } };return ,$out
}
function P-Candidate($files,$s) {
  # Candidate identity: repository entries (bytes + executable bit); no HEAD, exclusions, staging, declared inputs,
  # plan file or accepted synthesis document.
  $skip=@(P-PlanName $s)+@((P-Synthesis $s).Keys);$entries=V-Map
  foreach ($k in @($files.Keys)) {
    if (-not $k.StartsWith('repo:',[StringComparison]::Ordinal)) { continue };$x=$files[$k];$name=$k.Substring(5)
    if ($x.type -ceq 'missing' -or $name -cin $skip) { continue };$entries[$name]=P-Entry $x
  };return V-Id $entries
}
function P-Fresh($s,$art) {
  $now=V-Snapshot $s.worktree @() @($art.exclusions)
  P-Require ($now.valid -and (P-Candidate $now.manifest.files $s) -ceq $art.candidate) 'stale artifact: the working tree is no longer this candidate'
  # A synthesizer assignment replaces the frozen synthesis: its own dispatch and acceptance do not re-check the old bytes.
  if ((V-Get $s.active 'role') -ceq 'synthesizer') { return $now }
  $synthesis=P-Synthesis $s
  foreach ($path in @($synthesis.Keys)) { $x=V-Get $now.manifest.files ('repo:'+$path);P-Require ($null -ne $x -and (P-Entry $x) -ceq $synthesis[$path]) ('stale synthesis: '+$path) }
  return $now
}
function P-StepBase($s) { if ($s.step -cin @('final-review','delivery','completion')) { return $s.plan_base };return $s.base }
function P-PackageBound($obj,$m,$s) {
  # A package reviews the step's diff: from the step base, and a range package's candidate is its reviewed tree.
  P-Require ($obj.base -ceq (P-StepBase $s)) 'package base differs from the step base'
  if ($obj.mode -cne 'range') { return }
  $skip=@(P-PlanName $s)+@((P-Synthesis $s).Keys)
  $untracked=@(foreach ($k in @($m.files.Keys)) { $x=$m.files[$k];if ($k.StartsWith('repo:',[StringComparison]::Ordinal) -and $x.type -cne 'missing' -and $k.Substring(5) -cnotin $skip -and -not $x.Contains('index')) { $k } })
  $dirty=@(V-Nul (V-Git $s.worktree @('diff','--no-ext-diff','--name-only','-z',$obj.head,'--')) | Where-Object { $_ -cnotin $skip })
  P-Require (-not $untracked.Count -and -not $dirty.Count -and $obj.head -ceq $m.head -and $m.head -ceq (V-GitText $s.worktree @('rev-parse','HEAD'))) 'range package differs from its reviewed tree'
}
function P-Artifact($r,$s,$current=$false) {
  # A plan, C4 snapshot or C5 package reference; $current=$null admits a missing artifact (first plan writer).
  if ($null -eq $r -and $null -eq $current) { return @{kind=$null;id=$null;snapshot_id=$null;candidate=$null;manifest=$null;files=$null} }
  $text=P-Ref $r;$kind=V-Get $r 'kind'
  if ($kind -ceq 'plan') {
    $source=if ($r.Contains('source_path')) { $r.source_path } else { $r.path }
    if ($current) { P-Require ($null -ne $s.plan -and $r.sha256 -ceq $s.plan.sha256 -and $source -ceq $s.plan.path) 'assigned plan mismatch' }
    return @{kind=$kind;id=$r.sha256;snapshot_id=$null;candidate=$r.sha256;manifest=$null;files=$null}
  }
  $obj=P-Decode $text;$manifest=$null
  if ($kind -ceq 'package') {
    $identity=V-Normal $obj;$packageId=$identity.package_id;$identity.Remove('package_id')
    P-Require ($obj.complete -eq $true -and (V-Id $identity) -ceq $packageId) 'incomplete package' 2;$snap=$obj.snapshot_after;$id=$packageId;$manifest=$obj
  } else { P-Require ($kind -ceq 'snapshot' -and $obj.valid -eq $true) 'invalid snapshot' 2;$snap=$obj;$id=$obj.snapshot_id }
  $m=$snap.manifest;P-Require ([IO.Path]::GetFullPath($m.root) -eq [IO.Path]::GetFullPath($s.worktree)) 'artifact worktree mismatch'
  $art=@{kind=$kind;id=$id;snapshot_id=$snap.snapshot_id;candidate=(P-Candidate $m.files $s);head=$m.head;exclusions=@($m.exclusions);manifest=$manifest;files=$m.files}
  if ($current) { [void](P-Fresh $s $art);if ($kind -ceq 'package') { P-PackageBound $obj $m $s } };return $art
}
function P-ManifestFiles($r) {
  # The captured files of a snapshot or package reference; $null for a plan or an absent artifact.
  if ($r -isnot [Collections.IDictionary] -or (V-Get $r 'kind') -cnotin @('snapshot','package')) { return $null }
  $obj=P-Record $r;if ($r.kind -ceq 'package') { return ,$obj.snapshot_after.manifest.files };return ,$obj.manifest.files
}
function P-FleetWorkers($data,$used) {
  # All worker rows of one complete, unused, all-Run worker-list collection, plus its receipt ids.
  P-Need $data @('fleet');P-Require ($data.fleet -is [Array] -and $data.fleet.Count) 'missing fresh fleet' 2
  $workers=@();$cursor=$null;$total=$null;$ids=@()
  foreach ($page in $data.fleet) {
    P-Require (P-Eq (V-Get $page 'cursor') $cursor) 'fleet cursor mismatch' 2;$raw=P-Record $page;P-Require ($raw.ok -eq $true) 'fleet unavailable' 2
    P-Require ($raw.id -and $raw.id -cnotin @($used)) 'fleet observation already used' 2;$ids+=$raw.id
    $r=$raw.result;P-Need $r @('workers','page','scope');P-Require ($r.scope.source -ceq 'all') 'fleet must cover all local runs' 2
    P-Require ($null -eq $total -or $total -eq $r.page.total) 'inconsistent fleet' 2;$total=$r.page.total;$workers+=@($r.workers)
    $cursor=if ($r.page.hasMore) { $r.page.nextCursor } else { $null }
  }
  P-Require ($null -eq $cursor -and $workers.Count -eq $total -and @($workers | ForEach-Object { $_.dispatchId } | Select-Object -Unique).Count -eq $total) 'incomplete fleet' 2
  return @{workers=$workers;ids=$ids}
}
function P-GateRecords($records,$art,$s) {
  # Sealed C4 results of the candidate's bytes; returns passed and failures not proven inherited from BASE.
  P-Require ($records -is [Array] -and $records.Count) 'missing executable evidence' 2;$passed=0;$failed=0
  foreach ($entry in $records) {
    $st=P-Record $entry;P-Require (V-EvidenceValid $st) 'stale or invalid runner evidence';$e=$st.evidence
    P-Require ((P-Candidate $e.source_after.manifest.files $s) -ceq $art.candidate) 'evidence snapshot mismatch'
    if ($e.key.check.independent_replay) { P-Require (-not $e.origin_run_id) 'required replay reused implementer evidence' }
    if ($st.exit_code -eq 0) { $passed++ } elseif ($null -eq (V-Get $entry 'baseline')) { $failed++ }
    else { $base=P-Record $entry.baseline;P-Require ((V-EvidenceValid $base) -and $base.evidence.key.provenance.kind -ceq 'BASE' -and $base.exit_code -ne 0 -and $base.evidence.failure_signature -ceq $e.failure_signature) 'unproven inherited failure' }
  };return @{passed=$passed;failed=$failed}
}
function P-EvidenceRecords($records,$art,$s) {
  # GATE_OK evidence: at least one pass, every failure proven inherited from BASE.
  $n=P-GateRecords $records $art $s;P-Require (-not $n.failed) 'unproven inherited failure';P-Require ($n.passed -gt 0) 'zero passing checks';return ,$records
}
function P-FailureRecords($records,$art,$s) {
  # GATE_FAIL evidence: at least one failure of the candidate that BASE does not explain.
  P-Require ((P-GateRecords $records $art $s).failed -gt 0) 'zero failing checks';return ,$records
}
function P-Checked($item,$finding,[string]$key='check',[bool]$anywhere=$false) {
  # A cannot_verify finding is checked by the sealed run-check result of its literal CHECK command that exited with the code
  # its EXPECT states (`exit <n>` first). Only the explicit `; stdout exactly|contains: <text>` form is matched against the
  # sealed stdout; other text after the exit code is the human-checked part (existing `exit 0; stdout — …` reports).
  # $key names the ledger field holding the result: an absolute path, or a {path, sha256} reference whose hash must match.
  $ref=V-Get $item $key;$path=if ($ref -is [Collections.IDictionary]) { V-Get $ref 'path' } else { $ref }
  try {
    if (-not ($path -is [string] -and [IO.Path]::IsPathRooted($path))) { return $false }
    if ($ref -is [Collections.IDictionary] -and (V-Hash ([IO.File]::ReadAllBytes($path))) -cne (V-Get $ref 'sha256')) { return $false }
    $result=P-Decode ([IO.File]::ReadAllText($path,$VUtf8).TrimStart([char]0xfeff))
  } catch { return $false }
  if (-not ($result -is [Collections.IDictionary] -and (V-EvidenceValid $result))) { return $false }
  # $anywhere takes the first `exit <n>` in a prose EXPECT (reproduction evidence of a suspected defect).
  # Reproduction evidence reads only an affirmative statement: `exit <n> …` or `On <context>, exit <n> …`, with no
  # negation in the prefix or right after the code ("must not exit 0" is never a confirmed reproduction).
  $pattern=if ($anywhere) { '\A(?:On (?![^,;.]*\b(?:not|never|no)\b)[^,;.]{1,80}, )?exit ([0-9]+)(?![0-9])(?!\s*(?:is|must|should|does|will|may)?\s*(?:not|never)\b)(.*)\z' } else { '\Aexit ([0-9]+)(?![0-9])(.*)\z' }
  $options=if ($anywhere) { [Text.RegularExpressions.RegexOptions]'Singleline, IgnoreCase' } else { [Text.RegularExpressions.RegexOptions]'Singleline' }
  $want=[regex]::Match(([string](V-Get $finding 'expect' '')).Trim(),$pattern,$options)
  $code=$result['exit_code']
  if (-not $want.Success -or $result.evidence.key.check.command -cne (V-Get $finding 'check') -or -not ($code -is [int] -or $code -is [long]) -or $code -ne [long]$want.Groups[1].Value) { return $false }
  $stdout=[regex]::Match($want.Groups[2].Value,'\A; stdout (exactly|contains): (.*)\z','Singleline');if (-not $stdout.Success) { return $true }
  try { $out=$VUtf8.GetString([IO.File]::ReadAllBytes($result.stdout_log)).Replace("`r`n","`n") } catch { return $false }
  if ($stdout.Groups[1].Value -ceq 'exactly') { return $out.TrimEnd([char]10) -ceq $stdout.Groups[2].Value };return $out.Contains($stdout.Groups[2].Value)
}
$POrcaPreamble='You are working inside Orca, a multi-agent IDE. You are a dispatched worker.'
function P-RolesFact([string]$label) { return ,(P-Line ([IO.File]::ReadAllText((Join-Path $PSScriptRoot '../../skills/orca-dev/roles.md'),$VUtf8).TrimStart([char]0xfeff)) $label) }
function P-ModelMatches($proposed,$actual) {
  # A Claude CLI alias names a model tier; the transcript records its full id.
  $aliases=P-RolesFact 'MODEL_ALIASES'
  return ($proposed -ceq $actual -or ($proposed -is [string] -and $aliases.Contains($proposed) -and $actual -is [string] -and $actual.StartsWith($aliases[$proposed],[StringComparison]::Ordinal)))
}
function P-Launched($start,$d) {
  $raw=P-Record $start;P-Require ($raw.ok -eq $true) 'unsuccessful worker-start receipt' 2;$launched=$raw.result
  P-Need $launched @('runId','taskId','dispatchId','launch')
  P-Require ($launched.runId -ceq $d.runId -and $launched.taskId -ceq $d.taskId -and $launched.dispatchId -ceq $d.id) 'worker-start identity mismatch'
  return ,$launched
}
function P-LaunchTerminal($launched,[string]$action) {
  $rows=@(@($launched.effects) | Where-Object { $_ -is [Collections.IDictionary] -and $_.kind -ceq 'terminal' -and $_.role -ceq 'agent' })
  P-Require ($rows.Count -eq 1 -and $rows[0].action -ceq $action -and $rows[0].id) 'terminal launch chain mismatch' 2
  return $rows[0].id
}
function P-ReusedModel($o,$launched,$origin) {
  # B1: a --terminal reuse inherits the model of the start that created that live process.
  $d=$o.dispatch;$worker=V-Get $o 'worker' @{};$terminal=V-Get $o 'terminal' @{}
  $handle=P-LaunchTerminal $launched 'reused'
  P-Require ($handle -ceq $d.assigneeHandle -and $handle -ceq (V-Get $worker 'agentTerminalHandle')) 'reused terminal handle mismatch'
  $raw=P-Record $origin;P-Require ($raw.ok -eq $true) 'unsuccessful origin worker-start receipt' 2;$first=$raw.result
  P-Need $first @('runId','dispatchId','launch')
  P-Require ($first.runId -ceq $d.runId -and $first.dispatchId -cne $d.id) 'origin worker-start run mismatch'
  P-Require ((P-LaunchTerminal $first 'created') -ceq $handle) 'origin terminal handle mismatch'
  $incarnation=V-Get (V-Get $first 'prompt' @{}) 'processIncarnation'
  P-Require ($incarnation -is [string] -and $incarnation) 'missing terminal incarnation' 2
  $pi=V-Get $d 'processIncarnation' (':'+$incarnation)
  P-Require ((V-Get (V-Get $launched 'prompt' @{}) 'processIncarnation') -ceq $incarnation -and
    (V-Get $terminal 'handle' $handle) -ceq $handle -and (V-Get $terminal 'incarnationId' $incarnation) -ceq $incarnation -and
    ([string]$pi).EndsWith(':'+$incarnation,[StringComparison]::Ordinal)) 'terminal incarnation changed'
  $effective=V-Get $first.launch 'effective' @{};if ($null -eq $effective) { $effective=@{} }
  P-Require ((V-Get $effective 'model') -is [string] -and (V-Get $effective 'model')) 'missing origin launch model' 2
  P-Require ((V-Get $effective 'agent') -ceq (V-Get (V-Get $o.projection 'provider' @{}) 'id')) 'origin launch agent mismatch'
  return $effective.model
}
function P-Field($obj,[string]$key,$default=$null) {
  # Transcript rows are case-sensitive dictionaries (payload keys may differ only by case).
  if ($obj -is [Collections.IDictionary] -and ([Collections.IDictionary]$obj).Contains($key)) { return ,$obj[$key] };return $default
}
function P-JsonLine([string]$line) {
  if ($PSVersionTable.PSVersion.Major -ge 7) { return ,(ConvertFrom-Json -InputObject $line -AsHashtable -Depth 1024) }
  if (-not $script:PJson) {
    Add-Type -AssemblyName System.Web.Extensions
    $script:PJson=New-Object Web.Script.Serialization.JavaScriptSerializer;$script:PJson.MaxJsonLength=[int]::MaxValue;$script:PJson.RecursionLimit=1024
  };return ,($script:PJson.DeserializeObject($line))
}
function P-PreambleText($row) {
  if ((P-Field $row 'type') -cne 'user' -or (P-Field $row 'isSidechain') -eq $true) { return $null }
  $content=P-Field (P-Field $row 'message' @{}) 'content'
  if ($content -is [Collections.IList]) { $content=(@($content | Where-Object { (P-Field $_ 'type') -ceq 'text' } | ForEach-Object { [string](P-Field $_ 'text' '') }) -join "`n") }
  if ($content -is [string] -and $content.Contains($POrcaPreamble)) { return $content };return $null
}
function P-PreambleBinds([string]$text,$d) {
  $tasks=@([regex]::Matches($text,'(?m)^Your task ID is: (\S+)$') | ForEach-Object { $_.Groups[1].Value })
  $dispatches=@([regex]::Matches($text,'--dispatch-id (ctx_[A-Za-z0-9_-]+)') | ForEach-Object { $_.Groups[1].Value })
  $senders=@([regex]::Matches($text,'--from (term_[A-Za-z0-9_-]+)') | ForEach-Object { $_.Groups[1].Value })
  return ($tasks.Count -eq 1 -and $tasks[0] -ceq $d.taskId -and $dispatches.Count -and @($dispatches | Where-Object { $_ -cne $d.id }).Count -eq 0 -and
          $senders.Count -and @($senders | Where-Object { $_ -cne $d.assigneeHandle }).Count -eq 0)
}
function P-TranscriptRows([string]$text) {
  $rows=New-Object Collections.ArrayList
  foreach ($line in $text.Split("`n")) {
    if ($line.Trim()) { $row=P-JsonLine $line;P-Require ($row -is [Collections.IDictionary]) 'invalid session transcript record' 2;[void]$rows.Add($row) }
  };return ,$rows
}
function P-Within([string]$child,[string]$root) {
  $sep=[IO.Path]::DirectorySeparatorChar;$mode=if ($sep -eq '\') { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
  $child=[IO.Path]::GetFullPath($child);$root=[IO.Path]::GetFullPath($root)
  return ($child.Equals($root,$mode) -or $child.StartsWith($root.TrimEnd($sep)+$sep,$mode))
}
function P-TranscriptModel($o,$rows) {
  # B2: the only model that answered after this Dispatch's Orca preamble in one Claude session.
  $d=$o.dispatch;$terminal=V-Get $o 'terminal' @{};$root=V-Get $terminal 'worktreePath'
  P-Require ($root -is [string] -and [IO.Path]::IsPathRooted($root) -and (V-Get $terminal 'worktreeId') -ceq $o.projection.workspace.id) 'missing Dispatch worktree path' 2
  $first=-1
  for ($i=0;$i -lt $rows.Count;$i++) { $text=P-PreambleText $rows[$i];if ($null -ne $text -and (P-PreambleBinds $text $d)) { $first=$i;break } }
  P-Require ($first -ge 0) 'no Orca preamble for this Dispatch in Claude transcript' 2
  $session=P-Field $rows[$first] 'sessionId';$models=New-Object 'Collections.Generic.HashSet[string]'
  for ($i=$first;$i -lt $rows.Count;$i++) {
    $row=$rows[$i];$text=P-PreambleText $row
    if ($null -ne $text -and -not (P-PreambleBinds $text $d)) { break }  # the next Dispatch owns the rest
    P-Require ((P-Field $row 'sessionId' $session) -ceq $session) 'Claude transcript session changed'
    $cwd=P-Field $row 'cwd';if ($null -ne $cwd) { P-Require (P-Within $cwd $root) 'Claude transcript cwd outside Dispatch worktree' }
    if ((P-Field $row 'type') -ceq 'assistant') {
      $model=P-Field (P-Field $row 'message' @{}) 'model'
      if ($model -cne '<synthetic>') { [void]$models.Add([string]$model) }  # local error/interrupt stubs have no author
    }
  }
  P-Require ($models.Count -le 1) 'conflicting actual model facts'
  $model=@($models)[0];P-Require ($model -is [string] -and $model) 'no model response after Orca preamble' 2;return $model
}
function P-AgyPreambleText($row) {
  $content=if ((P-Field $row 'type') -ceq 'USER_INPUT') { P-Field $row 'content' } else { $null }
  if ($content -is [string] -and $content.Contains($POrcaPreamble)) { return $content };return $null
}
function P-AgyLogModel([string]$text,[string]$conversation) {
  # One Antigravity CLI process log: it created this conversation and resolved exactly one model.
  $created=@([regex]::Matches($text,'(?m)\] Created conversation ([0-9a-f-]+)[ \t]*$') | ForEach-Object { $_.Groups[1].Value })
  P-Require ($conversation -cin $created) 'Antigravity log does not own this conversation' 2
  $models=New-Object 'Collections.Generic.HashSet[string]'
  foreach ($m in [regex]::Matches($text,'(?m)\] Resolving model (\S+)[ \t]*$')) { [void]$models.Add($m.Groups[1].Value) }
  P-Require ($models.Count -le 1) 'conflicting actual model facts'
  P-Require ($models.Count -eq 1) 'no resolved model in Antigravity log' 2;return @($models)[0]
}
function P-AgyBinds($o,$rows) {
  foreach ($row in $rows) { $text=P-AgyPreambleText $row;if ($null -ne $text -and (P-PreambleBinds $text $o.dispatch)) { return $true } };return $false
}
function P-EvidenceModel($o,$proof) {
  $provider=V-Get $o.projection 'provider' @{}
  P-Require ($null -eq (V-Get $provider 'model')) 'model evidence only for an unreported model'
  $kind=V-Get $proof 'kind'
  if ($kind -ceq 'claude-transcript') {
    P-Require ((V-Get $provider 'id') -ceq 'claude') 'model evidence kind does not match provider'
    return P-TranscriptModel $o (P-TranscriptRows (P-Ref $proof))
  }
  P-Require ($kind -ceq 'antigravity-log') 'unknown model evidence kind' 2
  P-Require ((V-Get $provider 'id') -ceq 'antigravity') 'model evidence kind does not match provider'
  P-Need $proof @('log','conversation_id')
  P-Require (P-AgyBinds $o (P-TranscriptRows (P-Ref $proof))) 'no Orca preamble for this Dispatch in Antigravity transcript' 2
  return P-AgyLogModel ((P-Ref $proof.log).Replace("`r",'')) $proof.conversation_id
}
function P-Model($o,$source=$null) {
  $model=V-Get (V-Get $o.projection 'provider' @{}) 'model'
  $start=V-Get $source 'start';$origin=V-Get $source 'origin_start';$proof=V-Get $source 'model_evidence'
  P-Require ($null -eq $origin -or $null -ne $start) 'origin worker-start without current worker-start'
  P-Require ($null -eq $proof -or ($null -eq $start -and $null -eq $origin)) 'model evidence with a launch receipt'
  $effective=$null
  if ($null -ne $start) {
    $launched=P-Launched $start $o.dispatch;$launch=V-Get $launched.launch 'effective' @{};if ($null -eq $launch) { $launch=@{} }
    $effective=V-Get $launch 'model'
    if ($null -ne $origin) {
      P-Require (@(V-Keys $launch | Where-Object { V-Get $launch $_ }).Count -eq 0) 'origin chain needs a --terminal reuse'
      $effective=P-ReusedModel $o $launched $origin
    }
    P-Require ($effective -is [string] -and $effective) 'missing effective launch model' 2
  } elseif ($null -ne $proof) { $effective=P-EvidenceModel $o $proof }
  if ($null -ne $effective) {
    P-Require ($null -eq $model -or $model -ceq $effective) 'conflicting actual model facts'
    if ($null -eq $model) { $model=$effective }
  };P-Require ($null -ne $model) 'unknown actual model family' 2;return $model
}
function P-Family($o,$source=$null) {
  $mapping=P-RolesFact 'FAMILY_MODELS';$model=P-Model $o $source
  if (-not $mapping.Contains($model)) {
    # Full provider ids from verified transcripts; aliases stay explicit above.
    $prefixes=P-RolesFact 'FAMILY_PREFIXES'
    $found=@(V-Keys $prefixes | Where-Object { [regex]::IsMatch([string]$model,'^'+[regex]::Escape($_)+'[a-z0-9][a-z0-9.-]*$') } | ForEach-Object { $prefixes[$_] })
    P-Require ($found.Count -eq 1) ('unknown actual model family: '+$model) 2;return $found[0]
  };return $mapping[$model]
}
function P-Observation($r,$active) {
  $raw=P-Record $r;P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2;$o=$raw.result
  P-Need $o @('dispatch','projection');$d=$o.dispatch;P-Need $d @('id','taskId','runId','status','assigneeHandle')
  P-Require ($d.taskId -ceq $active.task_id -and $d.runId -ceq $active.run_id) 'Task/Run observation mismatch'
  P-Require ($d.id -ceq $active.dispatch_id) 'Dispatch observation mismatch'
  P-Require ($o.projection.workspace.id -ceq $active.worktree_id) 'observation worktree mismatch' 2
  $o.projection.provider.model=P-Model $o $r;return $o
}
function P-KnownFamilies() { return @(@(V-Values (P-RolesFact 'FAMILY_MODELS'))+@(V-Values (P-RolesFact 'FAMILY_PREFIXES')) | Select-Object -Unique) }
function P-Authors($art,$provenance=@()) {
  # Actual author families per file of a complete package, from its write receipts.
  $m=$art.manifest;P-Require ($null -ne $m) 'review requires a complete package' 2;$writers=V-Map
  foreach ($w in $m.provenance.writes) {
    $saved=P-Record @{path=$w.receipt_path;sha256=$w.receipt_sha256};$o=$saved.result;$d=$o.dispatch
    P-Require ($d.id -ceq $w.dispatch_id -and $d.taskId -ceq $w.task_id -and $d.runId -ceq $w.run_id) 'unknown write provenance' 2
    $ref=@($provenance | Where-Object { $_.path -ceq $w.receipt_path -and $_.sha256 -ceq $w.receipt_sha256 } | Select-Object -First 1)
    $source=if ($ref.Count) { $ref[0] } else { $null }
    $actual=P-Family $o $source;P-Require ($actual -ceq $w.family) 'claimed author family differs from launch'
    foreach ($path in $w.files) { $writers[$path]=@(@($writers[$path] | Where-Object { $null -ne $_ })+$actual) }
  };return $writers
}
function P-UtcSeconds($value) {
  P-Require ($value -is [string] -and $value) 'missing Dispatch creation time' 2
  $text=$value.Replace(' ','T');if ($text -notmatch '(Z|[+-]\d\d:\d\d)$') { $text+='Z' }  # Orca SQL timestamps are UTC
  return [DateTimeOffset]::Parse($text,[Globalization.CultureInfo]::InvariantCulture).ToUnixTimeMilliseconds()/1000.0
}
function P-ClaudeEvidence($cli) {
  # Freeze the one Claude session transcript that proves this Dispatch's model.
  P-Require ($cli.Count -in @(3,4)) 'usage: protocol-state claude-model-evidence OBSERVATION_JSON SNAPSHOT_OUT [TRANSCRIPT]'
  $raw=P-Decode ([IO.File]::ReadAllText($cli[1],$VUtf8).TrimStart([char]0xfeff));P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2
  $o=$raw.result;P-Need $o @('dispatch','projection');$provider=V-Get $o.projection 'provider' @{}
  P-Require ((V-Get $provider 'id') -ceq 'claude' -and $null -eq (V-Get $provider 'model')) 'model evidence only for unreported Claude model'
  $out=$cli[2]
  P-Require ([IO.Path]::IsPathRooted($out) -and [IO.Directory]::Exists([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($out))) -and -not [IO.File]::Exists($out) -and -not [IO.Directory]::Exists($out)) 'snapshot output must be a new absolute file' 2
  try { V-Safe $out } catch { P-Require $false 'linked snapshot output' 2 }
  if ($cli.Count -eq 4) { $files=@([IO.Path]::GetFullPath($cli[3])) } else {
    $root=V-Get (V-Get $o 'terminal' @{}) 'worktreePath'
    P-Require ($root -is [string] -and [IO.Path]::IsPathRooted($root)) 'missing Dispatch worktree path' 2
    $base=if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.claude' }
    $folder=Join-Path (Join-Path $base 'projects') ([regex]::Replace($root,'[^a-zA-Z0-9]','-'))
    $since=(P-UtcSeconds (V-Get $o.dispatch 'createdAt'))-300
    $files=@()
    if ([IO.Directory]::Exists($folder)) {
      $files=@([IO.Directory]::GetFiles($folder,'*.jsonl') | Where-Object { ([DateTimeOffset]([IO.File]::GetLastWriteTimeUtc($_))).ToUnixTimeMilliseconds()/1000.0 -ge $since } | Sort-Object)
    }
  }
  $found=@()
  foreach ($path in $files) {
    $bytes=[IO.File]::ReadAllBytes($path);$rows=P-TranscriptRows ($VUtf8.GetString($bytes).TrimStart([char]0xfeff).Replace("`r`n","`n"))
    $bound=@($rows | Where-Object { $text=P-PreambleText $_;$null -ne $text -and (P-PreambleBinds $text $o.dispatch) })
    if ($bound.Count) { $found+=,@{path=$path;bytes=$bytes;rows=$rows} }
  }
  P-Require ($found.Count) 'no Claude transcript with this Dispatch preamble' 2
  P-Require ($found.Count -eq 1) ('several Claude transcripts claim this Dispatch: '+(@($found | ForEach-Object { $_.path }) -join ', ')) 2
  $model=P-TranscriptModel $o $found[0].rows
  $stream=[IO.File]::Open($out,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
  try { $stream.Write($found[0].bytes,0,$found[0].bytes.Length);$stream.Flush($true) } finally { $stream.Dispose() }
  $proof=[ordered]@{kind='claude-transcript';path=$out;sha256=(V-Hash $found[0].bytes)}
  [Console]::WriteLine('VALID');[Console]::WriteLine((V-Json @{model_evidence=$proof;model=$model;source=$found[0].path}));exit 0
}

function P-Frozen([string]$path,[byte[]]$bytes) {
  $stream=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
  try { $stream.Write($bytes,0,$bytes.Length);$stream.Flush($true) } finally { $stream.Dispose() }
  return [ordered]@{path=$path;sha256=(V-Hash $bytes)}
}
function P-AgyEvidence($cli) {
  # Freeze the Antigravity conversation transcript bound to this Dispatch and its CLI process log.
  P-Require ($cli.Count -eq 3) 'usage: protocol-state antigravity-model-evidence OBSERVATION_JSON SNAPSHOT_OUT'
  $raw=P-Decode ([IO.File]::ReadAllText($cli[1],$VUtf8).TrimStart([char]0xfeff));P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2
  $o=$raw.result;P-Need $o @('dispatch','projection');$provider=V-Get $o.projection 'provider' @{}
  P-Require ((V-Get $provider 'id') -ceq 'antigravity' -and $null -eq (V-Get $provider 'model')) 'model evidence only for an unreported model'
  $out=$cli[2];$logOut=$out+'.cli.log'
  P-Require ([IO.Path]::IsPathRooted($out) -and [IO.Directory]::Exists([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($out))) -and -not [IO.File]::Exists($out) -and -not [IO.Directory]::Exists($out) -and -not [IO.File]::Exists($logOut)) 'snapshot output must be a new absolute file' 2
  try { V-Safe $out } catch { P-Require $false 'linked snapshot output' 2 }
  $home2=if ($env:ORCA_AGY_HOME) { $env:ORCA_AGY_HOME } else { Join-Path (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.gemini') 'antigravity-cli' }
  $since=(P-UtcSeconds (V-Get $o.dispatch 'createdAt'))-300
  $recent={ param($path) ([DateTimeOffset]([IO.File]::GetLastWriteTimeUtc($path))).ToUnixTimeMilliseconds()/1000.0 -ge $since }
  $found=@();$brain=Join-Path $home2 'brain'
  if ([IO.Directory]::Exists($brain)) {
    foreach ($dir in @([IO.Directory]::GetDirectories($brain) | Sort-Object)) {
      $path=[IO.Path]::Combine($dir,'.system_generated','logs','transcript.jsonl')
      if (-not [IO.File]::Exists($path) -or -not (& $recent $path)) { continue }
      $bytes=[IO.File]::ReadAllBytes($path);$rows=P-TranscriptRows ($VUtf8.GetString($bytes).TrimStart([char]0xfeff).Replace("`r`n","`n"))
      if (P-AgyBinds $o $rows) { $found+=,@{conversation=[IO.Path]::GetFileName($dir);bytes=$bytes} }
    }
  }
  P-Require ($found.Count) 'no Antigravity transcript with this Dispatch preamble' 2
  P-Require ($found.Count -eq 1) ('several Antigravity conversations claim this Dispatch: '+(@($found | ForEach-Object { $_.conversation }) -join ', ')) 2
  $conversation=$found[0].conversation;$logs=@();$logDir=Join-Path $home2 'log'
  if ([IO.Directory]::Exists($logDir)) {
    foreach ($path in @([IO.Directory]::GetFiles($logDir,'*.log') | Sort-Object)) {
      if (([IO.File]::GetAttributes($path) -band [IO.FileAttributes]::ReparsePoint) -or -not (& $recent $path)) { continue }
      $bytes=[IO.File]::ReadAllBytes($path)
      if ([Text.Encoding]::UTF8.GetString($bytes).Contains('] Created conversation '+$conversation)) { $logs+=,@{path=$path;bytes=$bytes} }
    }
  }
  P-Require ($logs.Count -eq 1) ('expected exactly one Antigravity process log for conversation '+$conversation) 2
  $model=P-AgyLogModel ([Text.Encoding]::UTF8.GetString($logs[0].bytes).Replace("`r",'')) $conversation
  $proof=[ordered]@{kind='antigravity-log';conversation_id=$conversation}
  $t=P-Frozen $out $found[0].bytes;$proof['path']=$t.path;$proof['sha256']=$t.sha256;$proof['log']=P-Frozen $logOut $logs[0].bytes
  [Console]::WriteLine('VALID');[Console]::WriteLine((V-Json @{model_evidence=$proof;model=$model;source=$logs[0].path}));exit 0
}

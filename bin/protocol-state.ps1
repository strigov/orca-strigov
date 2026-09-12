#Requires -Version 5.1
# C6 native validator. All subprocesses are bounded read-only Git helpers.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'lib/verification.ps1')
$PCaps=@{plan_review=4;fused_review=4;final_review=2;gate_fix=2}
$PReview=@('plan-reviewer','review-primary','review-control','review-final')
$PWrite=@('plan-writer','plan-reviser','implementer','frontend-implementer','quickfix','synthesizer')
$PTokens=@{
  'plan-writer'=@('PLAN_WRITTEN','REVISED','NEEDS_AUTHORIZATION','BLOCKED');'plan-reviser'=@('REVISED','NEEDS_AUTHORIZATION','BLOCKED')
  'plan-reviewer'=@('APPROVED','CHANGES_REQUESTED','BLOCKED');'implementer'=@('DONE','DONE_WITH_CONCERNS','NEEDS_CONTEXT','NEEDS_AUTHORIZATION','BLOCKED')
  'frontend-implementer'=@('DONE','DONE_WITH_CONCERNS','NEEDS_CONTEXT','NEEDS_AUTHORIZATION','BLOCKED');'quickfix'=@('DONE','DONE_WITH_CONCERNS','NEEDS_CONTEXT','BLOCKED')
  'gate'=@('GATE_OK','GATE_FAIL','NO_COMMANDS','NEEDS_JUDGMENT','BLOCKED');'review-primary'=@('REVIEW_OK','REVIEW_BLOCKING','BLOCKED')
  'review-control'=@('REVIEW_OK','REVIEW_BLOCKING','BLOCKED');'review-final'=@('REVIEW_OK','REVIEW_BLOCKING','BLOCKED')
  'synthesizer'=@('SYNTHESIS_DONE','BLOCKED');'diagnosis'=@('NEEDS_MORE_CONTEXT','NEEDS_MORE_REASONING','PHASE_TOO_LARGE','PLAN_WRONG','IMPASSE_SUMMARY','BLOCKED')
}
function P-Require($ok,[string]$why,[int]$code=1) {
  if (-not $ok) { $e=New-Object InvalidOperationException($why);$e.Data['code']=$code;throw $e }
}
function P-Need($obj,[string[]]$keys) { P-Require ($obj -is [Collections.IDictionary] -and @($keys | Where-Object { -not $obj.Contains($_) }).Count -eq 0) ('missing facts: '+($keys -join ', ')) 2 }
function P-Eq($a,$b) { return (V-Json $a) -ceq (V-Json $b) }
function P-Subset($a,$b) { return @(@($a) | Where-Object { $_ -cnotin @($b) }).Count -eq 0 }
function P-Ref($r) {
  P-Need $r @('path','sha256');P-Require ([IO.Path]::IsPathRooted($r.path)) 'artifact path must be absolute'
  V-Safe $r.path;P-Require ([IO.File]::Exists($r.path)) ('missing artifact: '+$r.path) 2
  $bytes=[IO.File]::ReadAllBytes($r.path);P-Require ((V-Hash $bytes) -ceq $r.sha256) ('artifact hash mismatch: '+$r.path)
  return $VUtf8.GetString($bytes).TrimStart([char]0xfeff)
}
function P-Decode([string]$text) { return ,(V-Normal ((ConvertFrom-Json -InputObject ('{"data":'+$text+'}')).data)) }
function P-Record($r) { return ,(P-Decode (P-Ref $r)) }
function P-Line([string]$text,[string]$label,$default=$null) {
  $rows=[regex]::Matches($text,'(?m)^'+[regex]::Escape($label)+': (.+)\r?$')
  if (-not $rows.Count -and $null -ne $default) { return ,$default }
  P-Require ($rows.Count -eq 1) ('format: expected one '+$label)
  return ,(P-Decode $rows[0].Groups[1].Value)
}
function P-Plan($s) {
  if ($null -eq $s.plan) { P-Require ($s.mode -ceq 'quickfix') 'plan-less mode must be quickfix';return ,@() }
  $text=P-Ref $s.plan;$m=[regex]::Match($text,'^---\r?\n(.*?)\r?\n---(?:\r?\n|$)','Singleline')
  P-Require $m.Success 'missing plan frontmatter' 2;$front=$m.Groups[1].Value
  $meta=@{}
  foreach ($name in 'protocol_version','orca_run','plan_base','contracts') {
    $rows=[regex]::Matches($front,'(?m)^'+$name+':\s*(.*?)\s*$');P-Require ($rows.Count -eq 1) ('missing plan metadata: '+$name) 2
    $meta[$name]=V-Unquote $rows[0].Groups[1].Value
  }
  P-Require ($meta.protocol_version -ceq '2') 'legacy metadata is not certified' 2
  P-Require ($meta.orca_run -ceq $s.orca_run -and $meta.plan_base -ceq $s.plan_base) 'plan/run/base mismatch'
  $contracts=P-Decode $meta.contracts
  P-Require ($contracts -is [Array] -and @($contracts | Select-Object -Unique).Count -eq $contracts.Count) 'invalid contract ids'
  foreach ($c in $contracts) { P-Require ($c -is [string] -and $c -cmatch '^[A-Za-z][A-Za-z0-9_-]*$') 'invalid contract id' }
  $phases=@();$items=[regex]::Split($front,'(?m)^  - id:\s*')
  foreach ($item in @($items | Select-Object -Skip 1)) {
    $rows=$item -split '\r?\n';$p=@{id=(V-Unquote $rows[0].Trim())}
    foreach ($row in @($rows | Select-Object -Skip 1)) { $f=[regex]::Match($row,'^    (risk|base|consumes|produces):\s*(.*?)\s*$');if ($f.Success) { $p[$f.Groups[1].Value]=$f.Groups[2].Value } }
    P-Require ($p.risk -cin @('none','SECURITY','DATA_LOSS','REGRESSION')) 'format: missing/invalid phase risk'
    P-Need $p @('consumes','produces');foreach ($key in 'consumes','produces') { $p[$key]=P-Decode $p[$key];P-Require ($p[$key] -is [Array]) 'contract references must be arrays' }
    $phases+=,$p
  }
  P-Require ($phases.Count -gt 0 -and @($phases.id | Select-Object -Unique).Count -eq $phases.Count) 'invalid phases'
  $produced=@();foreach ($p in $phases) { P-Require (P-Subset $p.produces $contracts) 'undeclared produced contract';P-Require (P-Subset $p.consumes $produced) 'consume without an earlier producer';$produced+=@($p.produces) }
  if ($null -ne $s.phase) { $p=@($phases | Where-Object { $_.id -ceq $s.phase });P-Require ($p.Count -eq 1 -and $p[0].base -ceq $s.base) 'phase/base mismatch' }
  return ,$phases
}
function P-Model($o,$start=$null) {
  $model=$o.projection.provider.model
  if ($null -ne $start) {
    $raw=P-Record $start;P-Require ($raw.ok -eq $true) 'unsuccessful worker-start receipt' 2;$launched=$raw.result;$d=$o.dispatch
    P-Need $launched @('runId','taskId','dispatchId','launch')
    P-Require ($launched.runId -ceq $d.runId -and $launched.taskId -ceq $d.taskId -and $launched.dispatchId -ceq $d.id) 'worker-start identity mismatch'
    $effective=$launched.launch.effective.model;P-Require ($effective -is [string] -and $effective) 'missing effective launch model' 2
    P-Require ($null -eq $model -or $model -ceq $effective) 'conflicting actual model facts'
    if ($null -eq $model) { $model=$effective }
  };P-Require ($null -ne $model) 'unknown actual model family' 2;return $model
}
function P-Family($o,$start=$null) {
  $mapping=P-Line ([IO.File]::ReadAllText((Join-Path $PSScriptRoot '../skills/orca-dev/roles.md'),$VUtf8)) 'FAMILY_MODELS'
  $model=P-Model $o $start;P-Require ($model -and $mapping.Contains($model)) 'unknown actual model family' 2;return $mapping[$model]
}
function P-Observation($r,$active) {
  $raw=P-Record $r;P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2;$o=$raw.result
  P-Need $o @('dispatch','projection');$d=$o.dispatch;P-Need $d @('id','taskId','runId','status','assigneeHandle')
  P-Require ($d.taskId -ceq $active.task_id -and $d.runId -ceq $active.run_id) 'Task/Run observation mismatch'
  P-Require ($d.id -ceq $active.dispatch_id) 'Dispatch observation mismatch'
  P-Require ($o.projection.workspace.id -ceq $active.worktree_id) 'observation worktree mismatch' 2
  $o.projection.provider.model=P-Model $o $r.start;return $o
}
function P-Fleet($data,$s) {
  P-Require (-not @($s.write_ownership | Where-Object { $_.StartsWith('pending:') }).Count) 'unbound writer intent' 2
  P-Need $data @('fleet');P-Require ($data.fleet -is [Array] -and $data.fleet.Count) 'missing fresh fleet' 2
  $workers=@();$cursor=$null;$total=$null;$ids=@()
  foreach ($page in $data.fleet) {
    P-Require (P-Eq $page.cursor $cursor) 'fleet cursor mismatch' 2;$raw=P-Record $page;P-Require ($raw.ok -eq $true) 'fleet unavailable' 2
    P-Require ($raw.id -and $raw.id -cnotin @($s.used_fleet_ids)) 'fleet observation already used' 2;$ids+=$raw.id
    $r=$raw.result;P-Need $r @('workers','page','scope');P-Require ($r.scope.source -ceq 'all') 'fleet must cover all local runs' 2
    P-Require ($null -eq $total -or $total -eq $r.page.total) 'inconsistent fleet' 2;$total=$r.page.total;$workers+=@($r.workers)
    $cursor=if ($r.page.hasMore) { $r.page.nextCursor } else { $null }
  }
  P-Require ($null -eq $cursor -and $workers.Count -eq $total -and @($workers.dispatchId | Select-Object -Unique).Count -eq $total) 'incomplete fleet' 2
  $ownership=@()
  foreach ($w in $workers) {
    $p=$w.projection;$uncertain=$w.terminalState -cin @('release_pending','release_unknown') -or $w.resource.ownershipState -cin @('user_owned','external','pre_existing')
    if (-not $uncertain -and $w.dispatchStatus -cin @('completed','failed') -and $p.evidence.durable -eq $true) { continue }
    P-Require ($p.workspace.id) 'unknown fleet workspace' 2;if ($p.workspace.id -cne $s.worktree_id) { continue }
    P-Require (-not $uncertain) 'unresolved release/external ownership' 2
    if ($w.terminalState -ceq 'released' -and $p.liveness.verdict -ceq 'exited') { continue };$ownership+=$w.dispatchId
  }
  $s.write_ownership=$ownership;P-Require (-not $ownership.Count) 'live or unverifiable prior writer' 2
  $s['used_fleet_ids']=@($s.used_fleet_ids)+$ids
}
function P-Artifact($r,$s,[bool]$current=$true) {
  $text=P-Ref $r
  if ($r.kind -ceq 'plan') { return @{id=$r.sha256;snapshot_id=$null;files=@{};manifest=$null} }
  $obj=V-Normal ($text | ConvertFrom-Json);$manifest=$null
  if ($r.kind -ceq 'package') {
    P-Require ($obj.complete -eq $true) 'incomplete package' 2
    if ($current) { P-Require (V-PackageValid $r.path) 'stale or incomplete package' };$snap=$obj.snapshot_after;$id=$obj.package_id;$manifest=$obj
  } else {
    P-Require ($r.kind -ceq 'snapshot' -and $obj.valid -eq $true) 'invalid snapshot' 2;$snap=$obj;$id=$snap.snapshot_id
    if ($current) { $inputs=if ($r.Contains('inputs')) { $r.inputs } else { @() };$now=V-Snapshot $s.worktree $inputs $snap.manifest.exclusions;P-Require ($now.valid -and $now.snapshot_id -ceq $snap.snapshot_id) 'stale snapshot' }
  }
  P-Require ([IO.Path]::GetFullPath($snap.manifest.root) -eq [IO.Path]::GetFullPath($s.worktree)) 'artifact worktree mismatch'
  return @{id=$id;snapshot_id=$snap.snapshot_id;files=$snap.manifest.files;head=$snap.manifest.head;manifest=$manifest}
}
function P-Report([string]$text,$a,$art,[string]$outcome,$modified) {
  $rows=@($text -split '\r?\n');$token=$rows[0];$role=$a.role
  P-Require ($PTokens.ContainsKey($role) -and $token -cin $PTokens[$role]) 'format: role verdict'
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
  $findings=P-Line $text 'FINDINGS' @()
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
    P-Require (-not $text.Contains('CANNOT_VERIFY') -or @($findings | Where-Object { $_.kind -ceq 'cannot_verify' }).Count) 'format: unstructured CANNOT_VERIFY'
  }
  if ($role -cin @('implementer','frontend-implementer','quickfix') -and $a.round -gt 1) { $fix=P-Line $text 'FIX_EVIDENCE';P-Require ($fix.tests -and $fix.commands -and $fix.outputs) 'format: fix evidence' }
  if ($role -ceq 'quickfix') { P-Require (@($modified).Count -eq 1) 'quickfix must modify exactly one file' }
  if ($role -ceq 'gate') { P-Require ($rows.Count -gt 1 -and ($rows[1].StartsWith('verify: ') -or $rows[1] -match '^lint: .+ \| typecheck: .+ \| tests: .+')) 'format: gate summary' }
  if ($role -ceq 'synthesizer') { P-Require ($rows.Count -gt 1 -and $rows[1].StartsWith('docs/reviews/')) 'format: synthesis path' }
  if ($role -ceq 'diagnosis') {
    $sections=@{NEEDS_MORE_CONTEXT='Context';NEEDS_MORE_REASONING='Context';PHASE_TOO_LARGE='Split';PLAN_WRONG='Plan defect';IMPASSE_SUMMARY='Summary'}
    P-Require ($text.Contains('## '+$sections[$token]) -and $text.Contains('## Evidence')) 'format: diagnosis sections'
  }
  return @{token=$token;findings=$findings;coverage=(P-Line $text 'COVERAGE' @{})}
}
function P-Independent($art,$coverage,$family,$provenance=@()) {
  $m=$art.manifest;P-Require ($null -ne $m) 'review requires a complete package' 2;$writers=@{}
  foreach ($w in $m.provenance.writes) {
    $saved=P-Record @{path=$w.receipt_path;sha256=$w.receipt_sha256};$o=$saved.result;$d=$o.dispatch
    P-Require ($d.id -ceq $w.dispatch_id -and $d.taskId -ceq $w.task_id -and $d.runId -ceq $w.run_id) 'unknown write provenance' 2
    $ref=@($provenance | Where-Object { $_.path -ceq $w.receipt_path -and $_.sha256 -ceq $w.receipt_sha256 } | Select-Object -First 1)
    $start=if ($ref.Count) { $ref[0].start } else { $null }
    $actual=P-Family $o $start;P-Require ($actual -ceq $w.family) 'claimed author family differs from launch'
    foreach ($path in $w.files) { $writers[$path]=@($writers[$path])+$actual }
  }
  P-Require (P-Subset $coverage.files @($m.files | ForEach-Object { $_.path })) 'unknown coverage file'
  foreach ($name in $coverage.files) { P-Require ($writers[$name]) ('unknown actual author: '+$name) 2;P-Require ($family -cnotin $writers[$name]) ('same-family review: '+$name) }
  P-Require (P-Subset $coverage.parts @($m.parts | ForEach-Object { $_.path })) 'unknown coverage part'
  foreach ($c in $coverage.contracts) {
    $matches=@($m.coverage.contracts | Where-Object { $_.id -ceq $c.id });P-Require ($matches.Count -eq 1) 'unknown coverage contract'
    foreach ($side in 'producer','consumer') { P-Require (P-Subset $c[$side] $matches[0][$side]) 'unknown contract side';P-Require (P-Subset $c[$side] $coverage.files) 'contract side lacks file review' }
  }
}
function P-Evidence($text,$art) {
  $records=P-Line $text 'EVIDENCE';P-Require ($records -is [Array] -and $records.Count) 'missing executable evidence' 2;$passed=0
  foreach ($entry in $records) {
    $st=P-Record $entry;P-Require (V-EvidenceValid $st) 'stale or invalid runner evidence';$e=$st.evidence
    P-Require ((P-Eq $e.source_after.manifest.files $art.files) -and $e.source_after.manifest.head -ceq $art.head) 'evidence snapshot mismatch'
    if ($e.key.check.independent_replay) { P-Require (-not $e.origin_run_id) 'required replay reused implementer evidence' }
    if ($st.exit_code -eq 0) { $passed++ } else { $base=P-Record $entry.baseline;P-Require ((V-EvidenceValid $base) -and $base.evidence.key.provenance.kind -ceq 'BASE' -and $base.exit_code -ne 0 -and $base.evidence.failure_signature -ceq $e.failure_signature) 'unproven inherited failure' }
  }
  P-Require ($passed -gt 0) 'zero passing checks';return ,$records
}
function P-Commit($fact,$s) {
  P-Need $fact @('sha','base','artifact');foreach ($key in 'sha','base') { P-Require ($fact[$key] -is [string] -and $fact[$key] -cmatch '^[a-f0-9]{40}$') 'missing full commit identity' 2 }
  $root=$s.worktree;P-Require ((V-GitText $root @('rev-parse',($fact.sha+'^{commit}'))) -ceq $fact.sha) 'commit not found' 2
  P-Require ($fact.sha -cne $fact.base) 'base is not a completion commit'
  [void](V-Git $root @('merge-base','--is-ancestor',$fact.base,$fact.sha));[void](V-Git $root @('merge-base','--is-ancestor',$fact.sha,'HEAD'))
  $art=P-Artifact $fact.artifact $s $false;P-Require ($fact.base -ceq $art.head) 'commit base differs from accepted candidate HEAD';$expected=@{}
  foreach ($label in $art.files.Keys) {
    if (-not $label.StartsWith('repo:')) { continue };$item=$art.files[$label]
    P-Require ($item.Contains('index') -or $item.type -ceq 'missing') 'accepted source was not staged'
    if ($item.type -cne 'missing') { $expected[$label.Substring(5)]=$item.index }
  }
  $tree=@();$entries=@{}
  foreach ($row in (V-Nul (V-Git $root @('ls-tree','-r','-z',$fact.sha)))) { $pair=$row.Split(@([char]9),2);$meta=$pair[0].Split(' ');$entries[$pair[1]]=@($meta[0],$meta[2]) }
  P-Require (P-Eq $entries $expected) 'commit does not contain accepted index/source';return $art
}
function P-Covered($s,$art,$roles) {
  $reports=@($s.accepted | Where-Object { $_.role -cin $roles -and $_.step -ceq $s.step -and ((P-Eq (P-Artifact $_.artifact $s $false).files $art.files) -or ($null -eq $s.phase -and $s.plan -and $_.artifact_id -ceq $s.plan.sha256)) })
  P-Require (P-Subset $roles @($reports | ForEach-Object { $_.role })) 'required report is missing' 2
  foreach ($r in $reports) {
    $a=P-Artifact $r.artifact $s $false;$fields=P-Report (P-Ref $r.report) $r.binding $a $r.outcome $r.modified
    P-Require ($fields.token -ceq $r.token -and (P-Eq $fields.findings $r.findings) -and (P-Eq $fields.coverage $r.coverage)) 'accepted report state mismatch'
    $obs=P-Observation $r.observation $r.binding;P-Require ((P-Family $obs) -ceq $r.family) 'accepted family mismatch'
    P-Require ($obs.dispatch.status -ceq 'completed' -and $obs.projection.evidence.durable -eq $true) 'accepted settlement missing' 2
    if ($r.role -ceq 'gate' -and $fields.token -ceq 'GATE_OK') { P-Require (P-Eq (P-Evidence (P-Ref $r.report) $a) $r.evidence) 'accepted evidence mismatch' }
    if ($r.role -ceq 'plan-reviewer') { P-Require ($s.provenance.Count) 'unknown plan authors' 2;foreach ($author in $s.provenance) { P-Require ((P-Family (P-Record $author).result $author.start) -cne $r.family) 'same-family plan review' } }
    if ($r.role -cin $PReview -and $r.role -cne 'plan-reviewer') { P-Independent $a $r.coverage $r.family $s.provenance }
    P-Require (-not @($r.findings | Where-Object { $_.id -cnotin @($s.closed_ledger_ids) }).Count -and $r.token -cin @('REVIEW_OK','GATE_OK','APPROVED','DONE','DONE_WITH_CONCERNS')) 'unresolved findings or verification'
  }
  $reviews=@($reports | Where-Object { $_.role -cin $PReview -and $_.role -cne 'plan-reviewer' })
  if ($reviews.Count -and $null -eq $art.manifest) { $art=P-Artifact $reviews[0].artifact $s $false };$m=$art.manifest
  if ($reviews.Count -and $null -ne $m) {
    $files=@();$parts=@();foreach ($r in $reviews) { $files+=@($r.coverage.files);$parts+=@($r.coverage.parts) }
    P-Require (P-Subset @($m.files | ForEach-Object { $_.path }) $files) 'incomplete file coverage' 2
    P-Require (P-Subset @($m.parts | ForEach-Object { $_.path }) $parts) 'incomplete part coverage' 2
    foreach ($c in $m.coverage.contracts) { foreach ($side in 'producer','consumer') {
      $union=@();foreach ($r in $reviews) { foreach ($part in $r.coverage.contracts) { if ($part.id -ceq $c.id) { $union+=@($part[$side]) } } }
      P-Require (P-Subset $c[$side] $union) ('incomplete contract '+$c.id+':'+$side) 2
    } }
  }
}
function P-Barrier($s,$phases) {
  if ($s.write_ownership.Count) { return 'awaiting_writer' }
  if ($s.open_ledger_ids.Count -or @($s.accepted | ForEach-Object { $_.findings } | Where-Object { $_.id -cnotin @($s.closed_ledger_ids) }).Count) { return 'awaiting_resolution' }
  if ($s.commit_barrier.confirmed_sha) {
    if ($s.mode -ceq 'quickfix') { return 'complete' }
    if ($s.step -ceq 'completion') { return 'complete' }
    $last=if ($phases.Count) { $phases[-1].id } else { $null };if ($s.phase -cne $last) { return 'ready_next_phase' };return 'awaiting_final_review'
  }
  $roles=@($s.accepted | Where-Object { $_.step -ceq $s.step } | ForEach-Object { $_.role })
  if ($s.step -ceq 'final-review') { return 'awaiting_final_review' };if ($s.step -ceq 'delivery') { return 'awaiting_delivery' };if ($s.step -ceq 'completion') { return 'awaiting_completion_commit' }
  if ($s.mode -ceq 'quickfix') { if ('quickfix' -cin $roles) { return 'awaiting_commit' };return 'awaiting_implementation' }
  if ($null -eq $s.phase) { if ('plan-reviewer' -cin $roles) { return 'awaiting_commit' };return 'awaiting_plan_review' }
  if ('gate' -cnotin $roles) { return 'awaiting_gate' };if (-not (P-Subset @('review-primary','review-control') $roles)) { return 'awaiting_review' };return 'awaiting_commit'
}
function P-Final($s,$phases,$committed) {
  P-Require (P-Subset @($phases | ForEach-Object { $_.id }) @($s.phase_commits | ForEach-Object { $_.phase })) 'uncommitted phases' 2
  P-Need $s.final @('review','delivery')
  P-Require ($s.step -ceq 'completion' -and $s.plan -and (P-Ref $s.plan) -match '(?m)^status: done\r?$') 'final bookkeeping is incomplete' 2
  $planName=$s.plan.path.Substring($s.worktree.TrimEnd('\','/').Length+1).Replace('\','/')
  foreach ($stage in 'review','delivery') {
    $role=if ($stage -ceq 'review') { 'review-final' } else { 'gate' };$reports=$s.final[$stage]
    P-Require ($reports.Count -gt 0 -and -not @($reports | Where-Object { $_.role -cne $role }).Count) ('unfinished final '+$stage) 2
    $previous=P-Decode (V-Json $s);$previous.accepted=$reports;$previous.step=if ($stage -ceq 'review') { 'final-review' } else { 'delivery' }
    $before=P-Artifact $reports[0].artifact $s $false;P-Covered $previous $before @($role)
    $left=@{};$right=@{};foreach ($k in $before.files.Keys) { if ($k -cne ('repo:'+$planName)) { $left[$k]=$before.files[$k] } };foreach ($k in $committed.files.Keys) { if ($k -cne ('repo:'+$planName)) { $right[$k]=$committed.files[$k] } }
    P-Require (P-Eq $left $right) 'final proof covers different implementation'
  }
}
function P-Validate($data) {
  P-Need $data @('schema_version','action','state');P-Require ($data.schema_version -eq 1) 'unsupported input schema' 2
  $s=P-Decode (V-Json $data.state)
  P-Need $s @('schema_version','mode','plan','ledger','orca_run','plan_base','phase','base','step','worktree','worktree_id','workspace','active','rounds','format_corrections','accepted','processed','open_ledger_ids','write_ownership','phase_commits','commit_barrier','final','provenance')
  P-Require ($s.schema_version -eq 1) 'legacy resume is unverifiable' 2
  P-Require ($s.mode -cin @('plan','quickfix') -and $s.step -cin @('plan','phase','quickfix','final-review','delivery','completion')) 'invalid protocol mode/step'
  P-Require ([IO.Path]::IsPathRooted($s.worktree) -and [IO.Path]::IsPathRooted($s.workspace)) 'absolute workspace required'
  if ($data.plan -and -not (P-Eq $data.plan $s.plan)) {
    $authorResult=$data.action -ceq 'accept-report' -and $s.active.role -cin @('plan-writer','plan-reviser')
    P-Require ($data.plan.path -ceq $s.plan.path -and ($authorResult -or ($null -eq $s.active -and (-not $s.accepted.Count -or $s.step -ceq 'completion')))) 'plan change after frozen assignment';$s.plan=$data.plan
  }
  $phases=P-Plan $s
  P-Require ([regex]::Matches((V-GitText $s.worktree @('worktree','list','--porcelain')),'(?m)^worktree ').Count -le 2) 'more than two worktrees'
  foreach ($sha in $s.plan_base,$s.base) { P-Require ($sha -is [string] -and $sha -cmatch '^[a-f0-9]{40}$') 'missing recorded base' 2;[void](V-Git $s.worktree @('cat-file','-e',($sha+'^{commit}'))) }
  foreach ($key in $PCaps.Keys) { $n=$s.rounds[$key];P-Require (($n -is [int] -or $n -is [long]) -and $n -ge 0 -and $n -le $PCaps[$key]) ('round cap: '+$key) }
  foreach ($n in $s.format_corrections.Values) { P-Require (($n -is [int] -or $n -is [long]) -and $n -ge 0 -and $n -le 1) 'format-correction cap' }
  $ledger=if ($null -eq $s.ledger) { ,@() } else { ,(P-Record $s.ledger) };P-Require ($ledger -is [Array]) 'invalid ledger'
  $s.open_ledger_ids=@($ledger | Where-Object { $_.status -ceq 'open' -and $_.decision -cin @('ACCEPTED','PARTIALLY_ACCEPTED','ESCALATED_TO_HUMAN') } | ForEach-Object { $_.id })
  $s['closed_ledger_ids']=@($ledger | Where-Object { $_.status -cin @('fixed','closed','resolved') } | ForEach-Object { $_.id })
  foreach ($fact in $s.phase_commits) { [void](P-Commit $fact $s) }
  if ($s.commit_barrier.confirmed_sha) {
    $facts=@($s.phase_commits);if ($s.final.Contains('completion')) { $facts+=,$s.final.completion }
    P-Require (@($facts | Where-Object { $_.sha -ceq $s.commit_barrier.confirmed_sha }).Count) 'unverified commit barrier' 2
    if ($s.step -ceq 'completion') { P-Final $s $phases (P-Commit $s.final.completion $s) }
  }
  $action=$data.action;$decision='accepted'
  switch -CaseSensitive ($action) {
    'accept-report' {
      $a=$s.active;P-Require ($null -ne $a) 'no current Dispatch' 2
      $raw=P-Record $data.event;P-Require ($raw.ok -eq $true) 'Orca did not accept event' 2;$r=$raw.result
      if ($r.Contains('message')) { $messages=@($r.message);$delivery=$null } else { $messages=@($r.messages);$delivery=$r.deliveryId }
      if (-not $messages.Count -and $r.timedOut -eq $true) { return @{state=$s;decision='not-completion'} }
      $selected=@($messages | Where-Object { $_.id -ceq $data.message_id });P-Require ($selected.Count -eq 1) 'missing exact delivery message' 2
      $msg=$selected[0];$payload=$msg.payload;if ($payload -is [string]) { $payload=P-Decode $payload };if ($null -eq $payload) { $payload=@{} }
      if ($msg.id -cin $s.processed.messages) {
        if ($delivery -and $delivery -cnotin $s.processed.deliveries -and (P-Subset @($r.messages | ForEach-Object { $_.id }) $s.processed.messages)) { $s.processed.deliveries+=,$delivery }
        return @{state=$s;decision='duplicate'}
      }
      P-Require ($null -eq $delivery -or $delivery -cnotin $s.processed.deliveries) 'unprocessed message in an acknowledged delivery'
      $ignored=if ($msg.type -cne 'worker_done') { 'not-completion' } elseif ($msg.run_id -cne $s.orca_run -or $payload.taskId -cne $a.task_id -or $payload.dispatchId -cne $a.dispatch_id) { 'stale' } else { $null }
      if ($ignored) {
        $s.processed.messages+=,$msg.id
        if ($delivery -and (P-Subset @($messages | ForEach-Object { $_.id }) $s.processed.messages)) { $s.processed.deliveries+=,$delivery }
        return @{state=$s;decision=$ignored}
      }
      $o=P-Observation $data.observation $a
      P-Require ($o.dispatch.status -ceq 'completed' -and $o.projection.evidence.durable -eq $true) 'missing durable settlement' 2
      P-Require ($msg.from_handle -ceq $o.dispatch.assigneeHandle) 'wrong report sender'
      $text=P-Ref $data.report;P-Require ($payload.reportPath -ceq $data.report.path -and $msg.subject -ceq ($text -split '\r?\n')[0]) 'report path/subject mismatch'
      $art=P-Artifact $data.artifact $s
      if ($a.role -cnotin $PWrite) { P-Require ($a.artifact_id -ceq $art.id -and (P-Eq $a.snapshot_id $art.snapshot_id)) 'assigned artifact changed' }
      $fields=P-Report $text $a $art $payload.outcome @($payload.filesModified)
      if ($s.format_lock) { $lock=$s.format_lock;P-Require ($art.id -ceq $lock.artifact_id -and (P-Eq $art.snapshot_id $lock.snapshot_id) -and $a.role -ceq $lock.role -and $a.round -eq $lock.round) 'format correction changed substantive artifact' }
      $family=P-Family $o
      if ($a.role -cin $PReview -and $a.role -cne 'plan-reviewer') { P-Independent $art $fields.coverage $family $s.provenance }
      $proofs=if ($a.role -ceq 'gate' -and $fields.token -ceq 'GATE_OK') { ,(P-Evidence $text $art) } else { ,@() }
      $accepted=@{role=$a.role;token=$fields.token;family=$family;step=$s.step;artifact_id=$art.id;snapshot_id=$art.snapshot_id;binding=$a;outcome=$payload.outcome;modified=@($payload.filesModified)
        report=$data.report;artifact=$data.artifact;observation=$data.observation;findings=$fields.findings;coverage=$fields.coverage;evidence=$proofs}
      if ($a.role -ceq 'plan-reviewer') { P-Require ($s.provenance.Count) 'unknown plan authors' 2;foreach ($author in $s.provenance) { P-Require ((P-Family (P-Record $author).result $author.start) -cne $family) 'same-family plan review' } }
      if ($a.role -cin $PWrite) { $s.provenance+=,$data.observation }
      $s.accepted=@($s.accepted | Where-Object { -not ($_.role -ceq $a.role -and $_.binding.round -lt $a.round) })
      $s.accepted+=,$accepted;$s.processed.messages+=,$msg.id
      if ($delivery -and (P-Subset @($r.messages | ForEach-Object { $_.id }) $s.processed.messages)) { $s.processed.deliveries+=,$delivery }
      $s.write_ownership=@($s.write_ownership | Where-Object { $_ -cne $a.dispatch_id })
      if (@($fields.findings | Where-Object { $_.risk -cin @('SECURITY','DATA_LOSS') }).Count) { $decision='risk-escalation' }
    }
    'bind-dispatch' {
      $a=$s.active;P-Require ($a -and $null -eq $a.dispatch_id) 'no pending dispatch intent'
      $raw=P-Record $data.observation;P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2;$o=$raw.result;$d=$o.dispatch
      P-Require ($d.taskId -ceq $a.task_id -and $d.runId -ceq $s.orca_run -and $null -eq $d.retryOfDispatchId) 'dispatch does not bind pending fresh Task'
      P-Require ($d.id -and (P-Model $o $data.observation.start) -ceq $a.model) 'actual launch differs from proposal';$a.dispatch_id=$d.id
      [void](P-Observation $data.observation $a)
      if ($a.format_corrected) { $s.format_corrections[$d.id]=1 }
      if ($a.role -cin $PWrite) { $s.write_ownership=@($d.id) }
    }
    { $_ -cin @('dispatch','format-correction') } {
      P-Fleet $data $s;$p=$data.proposed;P-Need $p @('run_id','task_id','dispatch_id','role','phase','round','worktree_id')
      P-Require ($PTokens.ContainsKey($p.role) -and $p.run_id -ceq $s.orca_run -and (P-Eq $p.phase $s.phase) -and $p.worktree_id -ceq $s.worktree_id) 'proposed binding mismatch'
      P-Require (($p.round -is [int] -or $p.round -is [long]) -and $p.round -ge 1) 'invalid proposed round'
      P-Require ($p.task_id -and $null -eq $p.dispatch_id) 'dispatch proposal needs a fresh Task and null not-yet-created Dispatch';P-Need $p @('model')
      $art=P-Artifact $data.artifact $s
      if ($action -ceq 'format-correction') {
        $old=$s.active;P-Require ($null -ne $old) 'missing defective assignment' 2;$key=$old.dispatch_id
        P-Require (-not $s.format_corrections[$key]) 'format-correction exhausted'
        $o=P-Observation $data.observation $old;P-Require ($o.dispatch.status -ceq 'completed') 'format correction before settlement' 2
        P-Require ($old.artifact_id -ceq $art.id -and (P-Eq $old.snapshot_id $art.snapshot_id)) 'format correction changed original artifact'
        $bad=P-Ref $data.report;$defective=$false
        try { [void](P-Report $bad $old $art $data.outcome $data.files_modified) }
        catch { P-Require ($_.Exception.Message.StartsWith('format:')) 'not a format-only defect';$defective=$true }
        P-Require $defective 'report has no format defect'
        P-Require ($p.role -ceq $old.role -and $p.round -eq $old.round -and $p.dispatch_id -cne $old.dispatch_id) 'format correction requires one new same-role Dispatch'
        $s.format_corrections[$key]=1;$p['format_corrected']=$true;$s['format_lock']=@{artifact_id=$art.id;snapshot_id=$art.snapshot_id;role=$old.role;round=$old.round}
      } else {
        $s.Remove('format_lock')
        $groups=@{'plan-reviewer'='plan_review';'review-primary'='fused_review';'review-control'='fused_review';'review-final'='final_review'};$group=$groups[$p.role];if ($p.gate_fix) { $group='gate_fix' }
        if ($group) { $count=$s.rounds[$group];P-Require ($p.round -in @($count,($count+1)) -and $p.round -le $PCaps[$group]) ('round cap/sequence: '+$group);$s.rounds[$group]=$p.round }
        if ($group) { $family=P-Family @{projection=@{provider=@{model=$p.model}}};P-Require (-not @($s.accepted | Where-Object { $_.role -ceq $p.role -and $_.binding.round -eq $p.round -and $_.family -ceq $family }).Count) 'substantive review needs a new round' }
        if ($p.role -cin $PReview -and $p.role -cne 'plan-reviewer') { P-Independent $art $p.coverage (P-Family @{projection=@{provider=@{model=$p.model}}}) $s.provenance }
      }
      $p['artifact_id']=$art.id;$p['snapshot_id']=$art.snapshot_id;$s.active=$p
      if ($p.role -cin $PWrite) { $s.write_ownership=@('pending:'+$p.task_id) }
    }
    'finish-checkpoint' {
      P-Fleet $data $s;P-Require (-not $s.open_ledger_ids.Count) 'open accepted findings';$art=P-Artifact $data.artifact $s
      P-Require ($s.step -cin @('final-review','delivery')) 'not a final checkpoint'
      P-Require (P-Subset @($phases | ForEach-Object { $_.id }) @($s.phase_commits | ForEach-Object { $_.phase })) 'uncommitted phases' 2
      $role=if ($s.step -ceq 'final-review') { 'review-final' } else { 'gate' };P-Covered $s $art @($role)
      $key=if ($role -ceq 'review-final') { 'review' } else { 'delivery' }
      $s.final[$key]=@($s.accepted | Where-Object { $_.step -ceq $s.step -and $_.role -ceq $role })
      $s.step=if ($key -ceq 'review') { 'delivery' } else { 'completion' };$s.active=$null;$s.commit_barrier=@{}
    }
    { $_ -cin @('prepare-commit','confirm-commit','advance','complete') } {
      P-Fleet $data $s;P-Require (-not $s.open_ledger_ids.Count) 'open accepted ledger findings'
      $art=P-Artifact $data.artifact $s ($action -ceq 'prepare-commit')
      P-Require (-not (V-GitText $s.worktree @('diff','--no-ext-diff','--name-only','--'))) 'hook/working-tree or unstaged source after acceptance'
      $roles=if ($s.mode -ceq 'quickfix') { @('quickfix') } elseif ($null -eq $s.phase) { @('plan-reviewer') } else { @('gate','review-primary','review-control') }
      if ($s.step -cin @('final-review','delivery','completion')) { $roles=if ($s.step -ceq 'final-review') { @('review-final') } else { @('gate') } }
      P-Covered $s $art $roles
      foreach ($accepted in $s.accepted) { foreach ($proof in $accepted.evidence) { P-Require (V-EvidenceValid (P-Record $proof)) 'accepted evidence no longer valid' } }
      if ($action -ceq 'prepare-commit') { $s.commit_barrier=@{expected_snapshot=$art.snapshot_id;expected_sha=$null;confirmed_sha=$null} }
      else {
        $fact=$data.commit;$committed=P-Commit $fact $s;P-Require ($committed.snapshot_id -ceq $art.snapshot_id) 'commit artifact differs from accepted candidate'
        $obj=P-Record $fact.artifact;$snap=if ($fact.artifact.kind -ceq 'snapshot') { $obj } else { $obj.snapshot_after }
        $inputs=if ($data.artifact.Contains('inputs')) { $data.artifact.inputs } else { @() };$current=V-Snapshot $s.worktree $inputs $snap.manifest.exclusions
        P-Require ($current.valid -and (P-Eq $current.manifest.files $committed.files)) 'hook/working-tree change after acceptance'
        $s.commit_barrier=@{expected_snapshot=$art.snapshot_id;expected_sha=$fact.sha;confirmed_sha=$fact.sha}
        if ($s.step -cin @('phase','plan','quickfix') -and -not @($s.phase_commits | Where-Object { $_.sha -ceq $fact.sha }).Count) { $entry=P-Decode (V-Json $fact);$entry['phase']=$s.phase;$s.phase_commits+=,$entry }
        if ($action -ceq 'advance') {
          $ids=@($phases | ForEach-Object { $_.id });$index=[Array]::IndexOf($ids,$s.phase)
          if ($index+1 -lt $ids.Count) { $s.phase=$ids[$index+1];$s.step='phase';$s.base=$fact.sha } else { $s.step='final-review' }
          $s.accepted=@();$s.commit_barrier=@{};$s.active=$null
          $s.rounds.fused_review=0;$s.rounds.gate_fix=0
        }
        if ($action -ceq 'complete') {
          P-Require ($fact.sha -cnotin @($s.phase_commits | ForEach-Object { $_.sha })) 'completion requires a separate commit'
          P-Final $s $phases $committed;$s.final['completion']=$fact
        }
      }
    }
    'resume' { if (-not $s.commit_barrier.confirmed_sha) { foreach ($accepted in $s.accepted) { if ($accepted.step -ceq $s.step) { [void](P-Artifact $accepted.artifact $s) } } } }
    default { P-Require $false 'unknown action' }
  }
  $s['barrier']=P-Barrier $s $phases;return @{state=$s;decision=$decision}
}

try {
  P-Require ($args.Count -in @(2,3) -and $args[0] -ceq 'validate') 'usage: protocol-state validate INPUT_JSON [RESUME_OUT]'
  $data=P-Decode ([IO.File]::ReadAllText($args[1],$VUtf8).TrimStart([char]0xfeff));$result=P-Validate $data
  if ($args.Count -eq 3) {
    $target=[IO.Path]::GetFullPath($args[2]);$workspace=[IO.Path]::GetFullPath($result.state.workspace).TrimEnd('\','/')
    P-Require ($target.StartsWith($workspace+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -and [IO.Directory]::Exists([IO.Path]::GetDirectoryName($target))) 'resume output outside existing workspace'
    V-Safe $target;$protected=New-Object 'Collections.Generic.List[string]';$protected.Add([IO.Path]::GetFullPath($args[1]))
    function P-Protect($obj) { if ($obj -is [Collections.IDictionary]) { if ($obj.Contains('path')) { $protected.Add([IO.Path]::GetFullPath($obj.path)) };foreach ($v in $obj.Values) { P-Protect $v } } elseif ($obj -is [Array]) { foreach ($v in $obj) { P-Protect $v } } }
    P-Protect $data;P-Require ($target -notin $protected) 'resume must not replace an input artifact';V-Save $target $result.state
  }
  [Console]::WriteLine('VALID');[Console]::WriteLine((V-Json $result));exit 0
} catch {
  $code=2;$next='supply-bound-facts';$reason=$_.Exception.Message
  if ($_.Exception.Data.Contains('code')) { $code=[int]$_.Exception.Data['code'];$next='resolve-protocol-blocker' }
  if ($reason.StartsWith('format:')) {
    $corrected=$false;$active=$data.state.active;$corrections=$data.state.format_corrections
    if ($null -ne $active -and $null -ne $active.dispatch_id -and $corrections -is [Collections.IDictionary] -and $corrections.Contains($active.dispatch_id)) { $corrected=[bool]$corrections[$active.dispatch_id] }
    $next=if ($corrected) { 'protocol-blocker' } else { 'format-correction' }
  }
  [Console]::WriteLine($(if ($code -eq 1) { 'INVALID' } else { 'UNVERIFIABLE' }));[Console]::WriteLine((V-Json @{reason=$reason;next_action=$next}));exit $code
}

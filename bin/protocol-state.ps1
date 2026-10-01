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
function P-Cap($s,[string]$group) {
  # Protocol cap plus the user's recorded one-round extensions for this phase.
  $extra=0
  foreach ($x in @($s['cap_extensions'])) {
    if ($null -eq $x -or $x.group -cne $group -or $x.phase -cne $s.phase) { continue }
    $auth=P-Record $x.authorization
    P-Require ($auth.schema_version -eq 1 -and $auth.run_id -ceq $s.orca_run -and $auth.phase -ceq $x.phase -and $auth.group -ceq $group -and $auth.extra_rounds -eq 1 -and $auth.user_decision -is [string] -and $auth.user_decision.Trim()) 'invalid cap extension authorization'
    $extra++
  };return $PCaps[$group]+$extra
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
  return $VUtf8.GetString($bytes).TrimStart([char]0xfeff).Replace("`r`n","`n")
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
  if ($null -eq $s.plan) {
    if ($s.step -ceq 'bootstrap') { [void](P-Bootstrap $s) } else { P-Require ($s.mode -ceq 'quickfix') 'plan-less mode must be quickfix or authorized bootstrap' };return ,@()
  }
  $text=P-Ref $s.plan;$m=[regex]::Match($text,'^---\r?\n(.*?)\r?\n---(?:\r?\n|$)','Singleline')
  P-Require $m.Success 'missing plan frontmatter' 2;$front=$m.Groups[1].Value
  $meta=@{}
  foreach ($name in 'protocol_version','orca_run','plan_base','contracts') {
    $rows=[regex]::Matches($front,'(?m)^'+$name+':\s*(.*?)\s*$');P-Require ($rows.Count -eq 1) ('missing plan metadata: '+$name) 2
    $meta[$name]=V-Unquote $rows[0].Groups[1].Value
  }
  P-Require ($meta.protocol_version -ceq '2') 'legacy metadata is not certified' 2
  P-Require ($meta.orca_run -ceq $s.orca_run -and $meta.plan_base -ceq $s.plan_base) 'plan/run/base mismatch'
  if ($s.authorization) {
    [void](P-Ref $s.authorization)
    $requestHash=[regex]::Matches($front,'(?m)^request_sha256:\s*(.*?)\s*$')
    P-Require ($requestHash.Count -eq 1) 'missing plan metadata: request_sha256' 2
    P-Require ((V-Unquote $requestHash[0].Groups[1].Value) -ceq $s.authorization.sha256) 'plan/request mismatch'
  }
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
  if ($null -ne $s.phase) { $p=@($phases | Where-Object { $_.id -ceq $s.phase });P-Require ($p.Count -eq 1 -and ($s.track_group -or $p[0].base -ceq $s.base)) 'phase/base mismatch' }
  return ,$phases
}
function P-Bootstrap($s) {
  P-Require ($s.mode -ceq 'plan' -and $s.step -ceq 'bootstrap' -and $null -eq $s.phase -and -not $s.phase_commits.Count -and -not $s.track_group) 'invalid bootstrap state'
  P-Require ($null -eq $s.active -or ($s.active.role -ceq 'plan-writer' -and $s.active.round -eq 1)) 'bootstrap permits only first plan-writer'
  $r=P-Record $s.authorization;P-Need $r @('schema_version','run_id','worktree_id','plan_base','plan_path','request')
  P-Require ($r.schema_version -eq 1 -and $r.run_id -ceq $s.orca_run -and $r.worktree_id -ceq $s.worktree_id -and $r.plan_base -ceq $s.plan_base -and $s.base -ceq $s.plan_base) 'bootstrap request binding mismatch'
  P-Require ([IO.Path]::IsPathRooted($r.plan_path) -and [IO.Path]::GetFullPath($r.plan_path).StartsWith([IO.Path]::GetFullPath($s.worktree).TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -and $r.request -is [string] -and $r.request.Trim()) 'invalid bootstrap request/plan path'
  P-Require ($null -eq $s.plan -or $s.plan.path -ceq $r.plan_path) 'bootstrap draft path mismatch'
  $history=@($s.accepted);if ($s.Contains('report_history')) { $history=@($s.report_history) }
  $authors=@($history | ForEach-Object { $_.observation })
  P-Require ((P-Eq $history $s.accepted) -and (P-Eq $authors $s.provenance)) 'unverifiable bootstrap history' 2
  foreach ($previous in $history) {
    P-Require ($previous.role -ceq 'plan-writer' -and $previous.binding.round -eq 1 -and $previous.step -ceq 'bootstrap' -and $previous.binding.run_id -ceq $s.orca_run -and $null -eq $previous.binding.phase -and $previous.token -cin @('BLOCKED','NEEDS_AUTHORIZATION')) 'invalid bootstrap history'
    [void](P-AcceptedReport $s $previous.report)
    $a=$previous.artifact;$source=if ($a.source_path) { $a.source_path } else { $a.path }
    P-Require (($a.kind -ceq 'request' -and $a.path -ceq $s.authorization.path -and $a.sha256 -ceq $s.authorization.sha256) -or ($a.kind -ceq 'plan' -and $source -ceq $r.plan_path)) 'bootstrap history artifact mismatch'
  }
  return $r
}
function P-Tracks($s,$phases) {
  $records=@{}
  $raw=$VUtf8.GetString((V-Git $s.worktree @('worktree','list','--porcelain','-z')))
  foreach ($block in $raw.Split(@("`0`0"),[StringSplitOptions]::RemoveEmptyEntries)) {
    $fields=@{}
    foreach ($row in $block.Split([char]0)) { if ($row) { $pair=$row -split ' ',2;$fields[$pair[0]]=if ($pair.Count -eq 2) { $pair[1] } else { '' } } }
    if ($fields.worktree) { $records[[IO.Path]::GetFullPath($fields.worktree)]=$fields }
  }
  $target=[IO.Path]::GetFullPath($s.worktree);P-Require ($records.ContainsKey($target)) 'TARGET is not a Git worktree' 2
  if (-not $s.track_group) { return }
  $g=P-Record $s.track_group;P-Need $g @('schema_version','run_id','parent_worktree','parent_head','plan','tracks')
  P-Require ($g.schema_version -eq 1 -and $g.run_id -ceq $s.orca_run -and (P-Eq $g.plan $s.plan)) 'track group run/immutable-plan mismatch'
  P-Require ([IO.Path]::IsPathRooted($g.parent_worktree) -and $g.parent_head -is [string] -and $g.parent_head -cmatch '^[a-f0-9]{40}$') 'invalid track parent BASE/path'
  $parent=[IO.Path]::GetFullPath($g.parent_worktree);P-Require ($records.ContainsKey($parent)) 'missing track parent worktree' 2
  $planPath=[IO.Path]::GetFullPath($g.plan.path);$parentPrefix=$parent.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
  P-Require ($planPath.StartsWith($parentPrefix,[StringComparison]::OrdinalIgnoreCase)) 'track plan outside parent'
  $planName=$planPath.Substring($parentPrefix.Length).Replace('\','/')
  $committedPlan=$VUtf8.GetString((V-Git $parent @('show',($g.parent_head+':'+$planName)))).TrimStart([char]0xfeff).Replace("`r`n","`n")
  P-Require ($committedPlan -ceq (P-Ref $g.plan)) 'track plan differs from parent history'
  [void](V-Git $s.worktree @('merge-base','--is-ancestor',$s.plan_base,$g.parent_head))
  [void](V-Git $s.worktree @('merge-base','--is-ancestor',$g.parent_head,$records[$parent].HEAD))
  $tracks=$g.tracks;P-Require ($tracks -is [Array] -and $tracks.Count) 'missing tracks' 2
  $paths=@($tracks | ForEach-Object { [IO.Path]::GetFullPath($_.worktree) })
  P-Require (@($tracks.id | Select-Object -Unique).Count -eq $tracks.Count -and @($paths | Select-Object -Unique).Count -eq $tracks.Count -and @($tracks.worktree_id | Select-Object -Unique).Count -eq $tracks.Count -and @($tracks.phase | Select-Object -Unique).Count -eq $tracks.Count) 'duplicate track binding'
  $active=@();$selected=$null;$completed=@($s.track_commits | Where-Object { $null -ne $_ })
  $completedIds=@($completed | ForEach-Object { $_.track_id })
  P-Require (@($completedIds | Select-Object -Unique).Count -eq $completed.Count -and (P-Subset $completedIds $tracks.id)) 'invalid completed tracks'
  foreach ($t in $tracks) {
    P-Need $t @('id','worktree','worktree_id','phase','base');$path=[IO.Path]::GetFullPath($t.worktree)
    P-Require ([IO.Path]::IsPathRooted($t.worktree)) 'absolute child worktree required'
    P-Require ($path -ne $parent -and $records.ContainsKey($path) -and $t.base -ceq $g.parent_head) 'track BASE/worktree mismatch'
    $childPlan=Join-Path $path $planName;V-Safe $childPlan
    P-Require ([IO.File]::ReadAllText($childPlan,$VUtf8).Replace("`r`n","`n") -ceq (P-Ref $g.plan)) 'child changed immutable plan'
    $p=@($phases | Where-Object { $_.id -ceq $t.phase });P-Require ($p.Count -eq 1) 'unknown track phase'
    [void](V-Git $s.worktree @('merge-base','--is-ancestor',$p[0].base,$t.base))
    [void](V-Git $path @('merge-base','--is-ancestor',$t.base,$records[$path].HEAD))
    $done=@($completed | Where-Object { $_.track_id -ceq $t.id })
    if ($done.Count) {
      P-Require ($done[0].base -ceq $t.base) 'completed track BASE mismatch'
      $child=P-Decode (V-Json $s);$child.worktree=$path;[void](P-Commit $done[0] $child)
      [void](V-Git $s.worktree @('merge-base','--is-ancestor',$done[0].sha,$records[$parent].HEAD))
    } else { $active+=,$t }
    if ($path -eq $target) { $selected=$t }
  }
  P-Require ($active.Count -le 2) 'more than two active child tracks in this Run'
  if ($target -ne $parent) { P-Require ($selected -and $selected.worktree_id -ceq $s.worktree_id -and $selected.phase -ceq $s.phase -and $selected.base -ceq $s.base) 'TARGET track binding mismatch' 2 }
  foreach ($t in $active) {
    $p=@($phases | Where-Object { $_.id -ceq $t.phase })[0]
    foreach ($other in $active) { if ($t.id -cne $other.id) {
      $q=@($phases | Where-Object { $_.id -ceq $other.phase })[0]
      P-Require (-not @($p.produces | Where-Object { $_ -cin (@($q.consumes)+@($q.produces)) }).Count) 'parallel producer/consumer conflict'
    } }
  }
}
$POrcaPreamble='You are working inside Orca, a multi-agent IDE. You are a dispatched worker.'
function P-RolesFact([string]$label) { return ,(P-Line ([IO.File]::ReadAllText((Join-Path $PSScriptRoot '../skills/orca-dev/roles.md'),$VUtf8).TrimStart([char]0xfeff)) $label) }
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
  $s['used_fleet_ids']=@($s.used_fleet_ids | Where-Object { $null -ne $_ })+$ids
}
function P-Artifact($r,$s,[bool]$current=$true) {
  $text=P-Ref $r
  if ($r.kind -cin @('plan','request')) {
    if ($current) {
      $target=if ($r.kind -ceq 'request') { $s.authorization } else { $s.plan }
      $sourcePath=if ($r.Contains('source_path')) { $r.source_path } else { $r.path }
      P-Require ($target -and $sourcePath -ceq $target.path -and $r.sha256 -ceq $target.sha256) 'assigned plan/request mismatch'
      if ($r.kind -ceq 'request') { [void](P-Bootstrap $s) }
    };return @{id=$r.sha256;snapshot_id=$null;files=@{};manifest=$null}
  }
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
  $text=$text.Replace("`r`n","`n")
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
    # An explicitly empty section ("CANNOT_VERIFY: []" or a bare header) states none.
    $stated=[regex]::Replace($text,'(?m)^CANNOT_VERIFY:[ \t]*(\[\])?[ \t]*$','')
    P-Require (-not $stated.Contains('CANNOT_VERIFY') -or @($findings | Where-Object { $_.kind -ceq 'cannot_verify' }).Count) 'format: unstructured CANNOT_VERIFY'
  }
  if ($role -cin @('implementer','frontend-implementer','quickfix') -and ($a.round -gt 1 -or $a.fix)) { $fix=P-Line $text 'FIX_EVIDENCE';P-Require ($fix.tests -and $fix.commands -and $fix.outputs) 'format: fix evidence' }
  if ($role -ceq 'quickfix') { P-Require (@($modified).Count -eq 1) 'quickfix must modify exactly one file' }
  if ($role -ceq 'gate') { P-Require ($rows.Count -gt 1 -and ($rows[1].StartsWith('verify: ') -or $rows[1] -match '^lint: .+ \| typecheck: .+ \| tests: .+')) 'format: gate summary' }
  if ($role -ceq 'synthesizer') { P-Require ($rows.Count -gt 1 -and $rows[1].StartsWith('docs/reviews/')) 'format: synthesis path' }
  if ($role -ceq 'diagnosis') {
    $sections=@{NEEDS_MORE_CONTEXT='Context';NEEDS_MORE_REASONING='Context';PHASE_TOO_LARGE='Split';PLAN_WRONG='Plan defect';IMPASSE_SUMMARY='Summary'}
    P-Require ($text.Contains('## '+$sections[$token]) -and $text.Contains('## Evidence')) 'format: diagnosis sections'
  }
  return @{token=$token;findings=$findings;coverage=(P-Line $text 'COVERAGE' @{})}
}
function P-KnownFamilies() { return @(@(V-Values (P-RolesFact 'FAMILY_MODELS'))+@(V-Values (P-RolesFact 'FAMILY_PREFIXES')) | Select-Object -Unique) }
function P-Waived($s) {
  # Units the user released from the family rule for this step: "path|reviewer family" entries.
  $out=@()
  foreach ($w in @($s['independence_waivers'])) {
    if ($null -eq $w -or $w.step -cne $s.step -or -not (P-Eq $w.phase $s.phase)) { continue }
    $auth=P-Record $w.authorization
    P-Require ($auth.schema_version -eq 1 -and $auth.run_id -ceq $s.orca_run -and $auth.step -ceq $w.step -and (P-Eq $auth.phase $w.phase) -and (P-Eq $auth.files $w.files) -and $auth.reviewer_family -ceq $w.reviewer_family -and $auth.user_decision -is [string] -and $auth.user_decision.Trim()) 'invalid independence waiver authorization'
    foreach ($path in $w.files) { $out+=,($path+'|'+$w.reviewer_family) }
  };return ,$out
}
function P-Authors($art,$provenance=@()) {
  # Actual author families per file of a complete package, from its write receipts.
  $m=$art.manifest;P-Require ($null -ne $m) 'review requires a complete package' 2;$writers=@{}
  foreach ($w in $m.provenance.writes) {
    $saved=P-Record @{path=$w.receipt_path;sha256=$w.receipt_sha256};$o=$saved.result;$d=$o.dispatch
    P-Require ($d.id -ceq $w.dispatch_id -and $d.taskId -ceq $w.task_id -and $d.runId -ceq $w.run_id) 'unknown write provenance' 2
    $ref=@($provenance | Where-Object { $_.path -ceq $w.receipt_path -and $_.sha256 -ceq $w.receipt_sha256 } | Select-Object -First 1)
    $source=if ($ref.Count) { $ref[0] } else { $null }
    $actual=P-Family $o $source;P-Require ($actual -ceq $w.family) 'claimed author family differs from launch'
    foreach ($path in $w.files) { $writers[$path]=@($writers[$path])+$actual }
  };return $writers
}
function P-Independent($art,$coverage,$family,$provenance=@(),$waived=@()) {
  $m=$art.manifest;$writers=P-Authors $art $provenance
  P-Require (P-Subset $coverage.files @($m.files | ForEach-Object { $_.path })) 'unknown coverage file'
  foreach ($name in $coverage.files) { P-Require ($writers[$name]) ('unknown actual author: '+$name) 2;P-Require ($family -cnotin $writers[$name] -or (($name+'|'+$family) -cin @($waived))) ('same-family review: '+$name) }
  P-Require (P-Subset $coverage.parts @($m.parts | ForEach-Object { $_.path })) 'unknown coverage part'
  foreach ($c in $coverage.contracts) {
    $matches=@($m.coverage.contracts | Where-Object { $_.id -ceq $c.id });P-Require ($matches.Count -eq 1) 'unknown coverage contract'
    foreach ($side in 'producer','consumer') { P-Require (P-Subset $c[$side] $matches[0][$side]) 'unknown contract side';P-Require (P-Subset $c[$side] $coverage.files) 'contract side lacks file review' }
  }
}
function P-SourceFiles($files) {
  # A candidate's identity is its repository entries; declared inputs are checked separately.
  $out=[ordered]@{};foreach ($k in @($files.Keys)) { if ($k.StartsWith('repo:',[StringComparison]::Ordinal)) { $out[$k]=$files[$k] } };return $out
}
function P-InputFiles($files) {
  $out=[ordered]@{};foreach ($k in @($files.Keys)) { if (-not $k.StartsWith('repo:',[StringComparison]::Ordinal)) { $out[$k]=$files[$k] } };return $out
}
function P-Evidence($text,$art) { return ,(P-EvidenceRecords (P-Line $text 'EVIDENCE') $art) }
function P-EvidenceRecords($records,$art) {
  P-Require ($records -is [Array] -and $records.Count) 'missing executable evidence' 2;$passed=0
  foreach ($entry in $records) {
    $st=P-Record $entry;P-Require (V-EvidenceValid $st) 'stale or invalid runner evidence';$e=$st.evidence
    $m=$e.source_after.manifest
    P-Require ((P-Eq (P-SourceFiles $m.files) (P-SourceFiles $art.files)) -and $m.head -ceq $art.head) 'evidence snapshot mismatch'
    if (-not (P-Eq (P-InputFiles $m.files) (P-InputFiles $art.files))) {
      # A C5 package carries no declared inputs: they must still be what the check ran on.
      $declared=if ($e.key.check.Contains('inputs') -and $null -ne $e.key.check.inputs) { @($e.key.check.inputs) } else { @() }
      $now=V-Snapshot $m.root $declared $m.exclusions
      P-Require ($now.valid -and (P-Eq (P-InputFiles $now.manifest.files) (P-InputFiles $m.files))) 'stale check inputs'
    }
    if ($e.key.check.independent_replay) { P-Require (-not $e.origin_run_id) 'required replay reused implementer evidence' }
    if ($st.exit_code -eq 0) { $passed++ } else { $base=P-Record $entry.baseline;P-Require ((V-EvidenceValid $base) -and $base.evidence.key.provenance.kind -ceq 'BASE' -and $base.exit_code -ne 0 -and $base.evidence.failure_signature -ceq $e.failure_signature) 'unproven inherited failure' }
  }
  P-Require ($passed -gt 0) 'zero passing checks';return ,$records
}
function P-ScriptGate($s,$art) {
  # A green verify-gate recorded by record-gate proves the same source as a gate worker's EVIDENCE.
  foreach ($g in @($s['script_gates'])) {
    if ($null -eq $g -or $g.step -cne $s.step) { continue }
    $gated=P-Artifact $g.artifact $s $false
    if ((P-Eq (P-SourceFiles $gated.files) (P-SourceFiles $art.files)) -and $gated.head -ceq $art.head) { [void](P-EvidenceRecords $g.evidence $gated);return $true }
  };return $false
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
  $present=@($reports | ForEach-Object { $_.role });if ('gate' -cin $roles -and (P-ScriptGate $s $art)) { $present+='gate' }
  P-Require (P-Subset $roles $present) 'required report is missing' 2
  foreach ($r in $reports) {
    $a=P-Artifact $r.artifact $s $false;$fields=P-Report (P-Ref $r.report) $r.binding $a $r.outcome $r.modified
    P-Require ($fields.token -ceq $r.token -and (P-Eq $fields.findings $r.findings) -and (P-Eq $fields.coverage $r.coverage)) 'accepted report state mismatch'
    $obs=P-Observation $r.observation $r.binding;P-Require ((P-Family $obs) -ceq $r.family) 'accepted family mismatch'
    P-Require ($obs.dispatch.status -ceq 'completed' -and $obs.projection.evidence.durable -eq $true) 'accepted settlement missing' 2
    if ($r.role -ceq 'gate' -and $fields.token -ceq 'GATE_OK') { P-Require (P-Eq (P-Evidence (P-Ref $r.report) $a) $r.evidence) 'accepted evidence mismatch' }
    if ($r.role -ceq 'plan-reviewer') { P-Require ($s.provenance.Count) 'unknown plan authors' 2;foreach ($author in $s.provenance) { P-Require ((P-Family (P-Record $author).result $author) -cne $r.family) 'same-family plan review' } }
    if ($r.role -cin $PReview -and $r.role -cne 'plan-reviewer') { P-Independent $a $r.coverage $r.family $s.provenance (P-Waived $s) }
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
function P-AcceptedReport($s,$reference) {
  $history=if ($s.Contains('report_history')) { $s.report_history } else { $s.accepted }
  $matches=@($history | Where-Object { P-Eq $_.report $reference });P-Require ($matches.Count -eq 1) 'closure report is not accepted' 2
  $r=$matches[0];$art=P-Artifact $r.artifact $s $false;$fields=P-Report (P-Ref $r.report) $r.binding $art $r.outcome $r.modified
  P-Require ($fields.token -ceq $r.token -and (P-Eq $fields.findings $r.findings) -and (P-Eq $fields.coverage $r.coverage)) 'closure report state mismatch'
  $o=P-Observation $r.observation $r.binding
  P-Require ($o.dispatch.status -ceq 'completed' -and $o.projection.evidence.durable -eq $true -and (P-Family $o) -ceq $r.family) 'closure report settlement mismatch' 2
  return @{report=$r;artifact=$art}
}
function P-ReviewClosure($s,$proof,$finding,$origin,$pending=$null) {
  P-Need $proof @('fix_report','review_report')
  $origin=(P-AcceptedReport $s $proof.report).report
  $a=P-AcceptedReport $s $proof.fix_report;$b=P-AcceptedReport $s $proof.review_report
  $fix=$a.report;$written=$a.artifact;$review=$b.report;$reviewed=$b.artifact
  foreach ($r in $fix,$review) { P-Require ((P-Eq $r.binding.phase $origin.binding.phase) -and $r.binding.run_id -ceq $s.orca_run -and $r.step -ceq $origin.step) 'closure phase/round mismatch' }
  P-Require ($review.binding.round -gt $origin.binding.round) 'closure phase/round mismatch'
  P-Require ($fix.role -cin $PWrite -and $fix.token -cin @('DONE','DONE_WITH_CONCERNS','REVISED')) 'closure missing successful fix'
  $history=if ($s.Contains('report_history')) { $s.report_history } else { $s.accepted };$positions=@()
  foreach ($item in $origin,$fix,$review) {
    for ($i=0;$i -lt $history.Count;$i++) { if (P-Eq $history[$i].report $item.report) { $positions+=,$i;break } }
  }
  P-Require ($positions.Count -eq 3 -and $positions[0] -lt $positions[1] -and $positions[1] -lt $positions[2]) 'closure report order must be finding, fix, re-review'
  foreach ($key in 'task_id','dispatch_id') { P-Require (@($origin.binding[$key],$fix.binding[$key],$review.binding[$key] | Select-Object -Unique).Count -eq 3) 'closure requires distinct accepted attempts' 2 }
  P-Require ($fix.role -ceq 'plan-reviser' -or $fix.binding.fix -eq $true -or $fix.binding.round -gt 1) 'closure requires an accepted fix response' 2
  $fixed=P-Line (P-Ref $fix.report) 'FIX_EVIDENCE' @{};$addressed=$fixed.findings
  P-Require ($addressed -is [Array] -and @($addressed | Where-Object { $_.id -ceq $finding.id -and (P-Eq $_.report $origin.report) }).Count -eq 1) 'closure fix finding binding mismatch'
  P-Require ($review.role -cin $PReview -and $review.token -cin @('APPROVED','REVIEW_OK') -and -not @($review.findings | Where-Object { $_.id -ceq $finding.id }).Count) 'closure missing positive re-review'
  P-Require (P-Eq $proof.artifact $review.artifact) 'closure review artifact mismatch'
  $historical=$false
  if ($proof.artifact.kind -ceq 'plan') {
    P-Require ($written.id -ceq $reviewed.id) 'closure fix/review snapshot mismatch'
    P-Require ($s.provenance.Count) 'unknown plan authors' 2
    foreach ($author in $s.provenance) { P-Require ((P-Family (P-Record $author).result $author) -cne $review.family) 'same-family plan review' }
    $source=if ($proof.artifact.Contains('source_path')) { $proof.artifact.source_path } else { $proof.artifact.path }
    $name='repo:'+$source.Substring($s.worktree.TrimEnd('\','/').Length+1).Replace('\','/')
    foreach ($fact in @(@($s.phase_commits)+@($pending) | Where-Object { $null -ne $_ })) { if ((P-Commit $fact $s).files[$name].sha256 -ceq $reviewed.id) { $historical=$true } }
    P-Require ((V-Hash ([IO.File]::ReadAllBytes($source))) -ceq $reviewed.id -or $historical) 'stale closure source'
  } else {
    # A C4 snapshot and a C5 package list different capture exclusions; compare reviewed bytes, index and HEAD.
    # The positive re-review after the fix may cover a later round's cumulative source; it must share
    # the phase HEAD, cover the fix's files and (below) still be the current or committed source.
    P-Require ($written.head -ceq $reviewed.head) 'closure fix/review snapshot mismatch'
    P-Independent $reviewed $review.coverage $review.family $s.provenance (P-Waived $s)
    P-Require ($review.coverage.files.Count -gt 0 -and (P-Subset $fix.modified $review.coverage.files)) 'closure fix lacks review coverage' 2
    $raw=P-Record $proof.artifact;$m=if ($proof.artifact.kind -ceq 'package') { $raw.snapshot_after.manifest } else { $raw.manifest }
    $inputs=if ($proof.artifact.Contains('inputs')) { $proof.artifact.inputs } else { @() }
    $current=V-Snapshot $s.worktree $inputs $m.exclusions
    foreach ($fact in @(@($s.phase_commits)+@($pending) | Where-Object { $null -ne $_ })) { if (P-Eq (P-SourceFiles (P-Commit $fact $s).files) (P-SourceFiles $reviewed.files)) { $historical=$true } }
    P-Require ($current.valid -and (((P-Eq $current.manifest.files $reviewed.files) -and $current.manifest.head -ceq $reviewed.head) -or $historical)) 'stale closure source'
  }
}
function P-Ledger($s,$pending=$null) {
  # pending: the commit a confirm/advance/complete is registering; it proves closed source like a recorded one.
  $ledger=if ($null -eq $s.ledger) { ,@() } else { ,(P-Record $s.ledger) }
  P-Require ($ledger -is [Array] -and @($ledger.id | Select-Object -Unique).Count -eq $ledger.Count) 'invalid ledger'
  $closed=@();$opened=@()
  foreach ($item in $ledger) {
    if ($item.status -cnotin @('fixed','resolved','closed','verified-by-controller')) {
      if ($item.status -ceq 'open' -and $item.decision -cin @('ACCEPTED','PARTIALLY_ACCEPTED','ESCALATED_TO_HUMAN')) { $opened+=,$item.id };continue
    }
    P-Require ($null -ne $item.closure) 'missing closure evidence' 2
    $proof=P-Record $item.closure;P-Need $proof @('schema_version','finding_id','report','artifact')
    P-Require ($proof.schema_version -eq 1 -and $proof.finding_id -ceq $item.id) 'closure finding binding mismatch'
    $reports=if ($s.Contains('report_history')) { $s.report_history } else { $s.accepted }
    $origin=@($reports | Where-Object { P-Eq $_.report $proof.report })
    P-Require ($origin.Count -eq 1) 'closure report is not accepted' 2;$origin=$origin[0]
    $originalArt=@{id=$origin.artifact_id;snapshot_id=$origin.snapshot_id}
    $fields=P-Report (P-Ref $origin.report) $origin.binding $originalArt $origin.outcome $origin.modified
    $finding=@($fields.findings | Where-Object { $_.id -ceq $item.id });P-Require ($finding.Count -eq 1) 'closure wrong finding';$finding=$finding[0]
    if ($finding.kind -ceq 'blocking') { P-ReviewClosure $s $proof $finding $origin $pending;$closed+=,$item.id;continue }
    P-Need $proof @('result','command','expect')
    if ($finding.kind -ceq 'cannot_verify') {
      P-Require ($proof.command -ceq $finding.check -and $proof.expect -ceq $finding.expect) 'closure CHECK binding mismatch'
      if ($proof.Contains('review_report') -and $null -ne $proof.review_report) {
        # Fixes of the same round move the candidate off the finding's bytes. The unchanged
        # CHECK may then prove the candidate of a later positive re-review without the finding.
        $review=(P-AcceptedReport $s $proof.review_report).report
        P-Require ((P-Eq $review.binding.phase $origin.binding.phase) -and $review.binding.run_id -ceq $s.orca_run -and $review.step -ceq $origin.step -and $review.binding.round -gt $origin.binding.round) 'closure phase/round mismatch'
        $positions=@()
        foreach ($item in $origin,$review) {
          for ($i=0;$i -lt $reports.Count;$i++) { if (P-Eq $reports[$i].report $item.report) { $positions+=,$i;break } }
        }
        P-Require ($positions.Count -eq 2 -and $positions[0] -lt $positions[1]) 'closure report order must be finding, re-review'
        P-Require ($review.role -cin $PReview -and $review.token -cin @('APPROVED','REVIEW_OK') -and -not @($review.findings | Where-Object { $_.id -ceq $finding.id }).Count) 'closure missing positive re-review'
        P-Require (P-Eq $proof.artifact $review.artifact) 'closure review artifact mismatch'
      } else { P-Require (P-Eq $proof.artifact $origin.artifact) 'closure CHECK binding mismatch' }
    }
    $art=P-Artifact $proof.artifact $s $false;$st=P-Record $proof.result
    P-Require (V-EvidenceValid $st) 'stale or invalid closure CHECK evidence'
    P-Require ($st.exit_code -eq 0) 'negative closure CHECK; finding remains blocking'
    $e=$st.evidence;P-Require ($proof.command -and $proof.expect -and $e.key.check.command -ceq $proof.command) 'closure command mismatch'
    $m=$e.source_after.manifest;P-Require ([IO.Path]::GetFullPath($m.root) -eq [IO.Path]::GetFullPath($s.worktree)) 'closure worktree mismatch'
    if ($proof.artifact.kind -ceq 'plan') {
      $sourcePath=if ($proof.artifact.Contains('source_path')) { $proof.artifact.source_path } else { $proof.artifact.path }
      $name='repo:'+$sourcePath.Substring($s.worktree.TrimEnd('\','/').Length+1).Replace('\','/')
      P-Require ($m.files[$name].sha256 -ceq $proof.artifact.sha256) 'closure plan snapshot mismatch'
    } else { P-Require ((P-Eq (P-SourceFiles $m.files) (P-SourceFiles $art.files)) -and $m.head -ceq $art.head) 'closure snapshot mismatch' }
    # The CHECK's own declared inputs must still be what it ran on; a C5 package carries none.
    $inputs=if ($proof.artifact.Contains('inputs') -and @($proof.artifact.inputs).Count) { $proof.artifact.inputs } elseif ($e.key.check.Contains('inputs') -and $null -ne $e.key.check.inputs) { @($e.key.check.inputs) } else { @() }
    $current=V-Snapshot $s.worktree $inputs $m.exclusions
    $historical=$false
    foreach ($fact in @(@($s.phase_commits)+@($pending) | Where-Object { $null -ne $_ })) { if ($fact.base -ceq $m.head -and (P-Eq (P-SourceFiles (P-Commit $fact $s).files) (P-SourceFiles $m.files))) { $historical=$true } }
    P-Require ($current.valid -and ((P-Eq $current.manifest.files $m.files) -or $historical)) 'stale closure source'
    P-Require ($current.manifest.head -ceq $m.head -or $historical) 'stale closure HEAD'
    $closed+=,$item.id
  }
  $reports=if ($s.Contains('report_history')) { $s.report_history } else { $s.accepted }
  foreach ($r in $reports) { foreach ($f in $r.findings) {
    $disposition=@($ledger | Where-Object { $_.id -ceq $f.id })
    $scopedOut=$f.kind -ceq 'blocking' -and $disposition.Count -eq 1 -and $disposition[0].decision -cin @('REJECTED_BY_SCOPE','DEFER','NIT')
    if ($f.id -cnotin $closed -and -not $scopedOut -and $f.id -cnotin $opened) { $opened+=,$f.id }
  } }
  $s.open_ledger_ids=$opened;$s['closed_ledger_ids']=$closed
}
function P-Barrier($s,$phases) {
  if ($s.step -ceq 'bootstrap' -and -not $s.write_ownership.Count) { return 'awaiting_plan_writer' }
  if ($s.write_ownership.Count) { return 'awaiting_writer' }
  if ($s.open_ledger_ids.Count -or @($s.accepted | ForEach-Object { $_.findings } | Where-Object { $_.id -cnotin @($s.closed_ledger_ids) }).Count) { return 'awaiting_resolution' }
  if ($s.commit_barrier.confirmed_sha) {
    if ($s.mode -ceq 'quickfix') { return 'complete' }
    if ($s.step -ceq 'completion') { return 'complete' }
    $last=if ($phases.Count) { $phases[-1].id } else { $null };if ($s.phase -cne $last) { return 'ready_next_phase' };return 'awaiting_final_review'
  }
  $roles=@($s.accepted | Where-Object { $_.step -ceq $s.step } | ForEach-Object { $_.role })
  if (@(@($s['script_gates']) | Where-Object { $null -ne $_ -and $_.step -ceq $s.step }).Count) { $roles+='gate' }
  if ($s.step -ceq 'final-review') { return 'awaiting_final_review' };if ($s.step -ceq 'delivery') { return 'awaiting_delivery' };if ($s.step -ceq 'completion') { return 'awaiting_completion_commit' }
  if ($s.mode -ceq 'quickfix') { if ('quickfix' -cin $roles) { return 'awaiting_commit' };return 'awaiting_implementation' }
  if ($null -eq $s.phase) { if ('plan-reviewer' -cin $roles) { return 'awaiting_commit' };return 'awaiting_plan_review' }
  if (-not @($roles | Where-Object { $_ -cin @('implementer','frontend-implementer','gate','review-primary','review-control') }).Count) { return 'awaiting_implementation' }
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
  P-Require ($s.mode -cin @('plan','quickfix') -and $s.step -cin @('bootstrap','plan','phase','quickfix','final-review','delivery','completion')) 'invalid protocol mode/step'
  P-Require ([IO.Path]::IsPathRooted($s.worktree) -and [IO.Path]::IsPathRooted($s.workspace)) 'absolute workspace required'
  $starting=$s.step -ceq 'bootstrap'
  if ($starting) {
    $request=P-Bootstrap $s
    P-Require ($data.action -cin @('resume','dispatch','bind-dispatch','accept-report','format-correction')) 'bootstrap action is not authorized'
    if ($data.action -cin @('dispatch','format-correction')) {
      P-Require ($data.proposed.role -ceq 'plan-writer' -and $data.proposed.round -eq 1 -and (-not [IO.File]::Exists($request.plan_path) -or $s.plan -or ($data.action -ceq 'format-correction' -and $data.plan))) 'bootstrap permits only first plan-writer before plan exists'
    }
  }
  if ($data.plan -and -not (P-Eq $data.plan $s.plan)) {
    $authorResult=$data.action -cin @('accept-report','format-correction') -and $s.active.role -cin @('plan-writer','plan-reviser')
    $expectedPath=if ($starting) { $request.plan_path } else { $s.plan.path }
    P-Require ($data.plan.path -ceq $expectedPath -and ($authorResult -or (-not $starting -and $null -eq $s.active -and (-not $s.accepted.Count -or $s.step -ceq 'completion')))) 'plan change after frozen assignment';$s.plan=$data.plan
  }
  $phases=P-Plan $s
  P-Tracks $s $phases
  foreach ($sha in $s.plan_base,$s.base) { P-Require ($sha -is [string] -and $sha -cmatch '^[a-f0-9]{40}$') 'missing recorded base' 2;[void](V-Git $s.worktree @('cat-file','-e',($sha+'^{commit}'))) }
  foreach ($key in $PCaps.Keys) { $n=$s.rounds[$key];P-Require (($n -is [int] -or $n -is [long]) -and $n -ge 0 -and $n -le (P-Cap $s $key)) ('round cap: '+$key) }
  foreach ($n in $s.format_corrections.Values) { P-Require (($n -is [int] -or $n -is [long]) -and $n -ge 0 -and $n -le 1) 'format-correction cap' }
  $history=if ($s.Contains('report_history')) { $s.report_history } else { $s.accepted }
  foreach ($previous in $history) { [void](P-Ref $previous.report) }
  foreach ($previous in $s.protected_reports) { [void](P-Ref $previous) }
  $confirming=$data.action -cin @('confirm-commit','advance','complete') -and $data.commit -is [Collections.IDictionary]
  $pendingCommit=if ($confirming) { $data.commit } else { $null };P-Ledger $s $pendingCommit
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
      P-Require (-not @($history | Where-Object { $_.report.path -ceq $data.report.path }).Count -and -not @($s.protected_reports | Where-Object { $_.path -ceq $data.report.path }).Count) 'report path already bound to a prior attempt'
      $text=P-Ref $data.report;$subjectToken=([string]$msg.subject -split '[\s:]',2)[0]
      P-Require ($payload.reportPath -ceq $data.report.path -and $subjectToken -ne '' -and $subjectToken -ceq ($text -split '\r?\n')[0]) 'report path/subject mismatch'
      $art=P-Artifact $data.artifact $s
      if ($a.role -cnotin $PWrite) { P-Require ($a.artifact_id -ceq $art.id -and (P-Eq $a.snapshot_id $art.snapshot_id)) 'assigned artifact changed' }
      $fields=P-Report $text $a $art $payload.outcome @($payload.filesModified)
      if ($starting -and $fields.token -cnotin @('BLOCKED','NEEDS_AUTHORIZATION')) {
        P-Require ($fields.token -ceq 'PLAN_WRITTEN' -and $null -ne $s.plan -and $data.artifact.kind -ceq 'plan') 'bootstrap writer must deliver the real plan'
        $s.step='plan'
      }
      if ($s.format_lock) { $lock=$s.format_lock;P-Require ($art.id -ceq $lock.artifact_id -and (P-Eq $art.snapshot_id $lock.snapshot_id) -and $a.role -ceq $lock.role -and $a.round -eq $lock.round) 'format correction changed substantive artifact' }
      $family=P-Family $o
      if ($a.role -cin $PReview -and $a.role -cne 'plan-reviewer') { P-Independent $art $fields.coverage $family $s.provenance (P-Waived $s) }
      $proofs=if ($a.role -ceq 'gate' -and $fields.token -ceq 'GATE_OK') { ,(P-Evidence $text $art) } else { ,@() }
      $accepted=@{role=$a.role;token=$fields.token;family=$family;step=$s.step;artifact_id=$art.id;snapshot_id=$art.snapshot_id;binding=$a;outcome=$payload.outcome;modified=@($payload.filesModified)
        report=$data.report;artifact=$data.artifact;observation=$data.observation;findings=$fields.findings;coverage=$fields.coverage;evidence=$proofs}
      if ($a.role -ceq 'plan-reviewer') { P-Require ($s.provenance.Count) 'unknown plan authors' 2;foreach ($author in $s.provenance) { P-Require ((P-Family (P-Record $author).result $author) -cne $family) 'same-family plan review' } }
      if ($a.role -cin $PWrite) { $s.provenance+=,$data.observation }
      $sameRoundFix=-not $starting -and $a.role -cin $PWrite -and $a.fix -eq $true -and $fields.token -cin @('DONE','DONE_WITH_CONCERNS','REVISED')
      $s.accepted=@($s.accepted | Where-Object { -not ($_.role -ceq $a.role -and ($_.binding.round -lt $a.round -or ($sameRoundFix -and $_.step -ceq $s.step -and (P-Eq $_.binding.phase $a.phase) -and $_.binding.round -eq $a.round))) })
      $s.accepted+=,$accepted;$s.processed.messages+=,$msg.id
      $s['report_history']=@($history)+@($accepted)
      if ($delivery -and (P-Subset @($r.messages | ForEach-Object { $_.id }) $s.processed.messages)) { $s.processed.deliveries+=,$delivery }
      $s.write_ownership=@($s.write_ownership | Where-Object { $_ -cne $a.dispatch_id })
      if (@($fields.findings | Where-Object { $_.risk -cin @('SECURITY','DATA_LOSS') }).Count) { $decision='risk-escalation' }
    }
    'bind-dispatch' {
      $a=$s.active;P-Require ($a -and $null -eq $a.dispatch_id) 'no pending dispatch intent'
      $raw=P-Record $data.observation;P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2;$o=$raw.result;$d=$o.dispatch
      P-Require ($d.taskId -ceq $a.task_id -and $d.runId -ceq $s.orca_run -and $null -eq $d.retryOfDispatchId) 'dispatch does not bind pending fresh Task'
      P-Require ($d.id -and (P-ModelMatches $a.model (P-Model $o $data.observation))) 'actual launch differs from proposal';$a.dispatch_id=$d.id
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
        if ($old.role -cin $PWrite) { $old.artifact_id=$art.id;$old.snapshot_id=$art.snapshot_id }
        P-Require ($old.artifact_id -ceq $art.id -and (P-Eq $old.snapshot_id $art.snapshot_id)) 'format correction changed original artifact'
        $bad=P-Ref $data.report;$defective=$false
        try { [void](P-Report $bad $old $art $data.outcome $data.files_modified) }
        catch { P-Require ($_.Exception.Message.StartsWith('format:')) 'not a format-only defect';$defective=$true }
        P-Require $defective 'report has no format defect'
        P-Require ($p.role -ceq $old.role -and $p.round -eq $old.round -and $p.dispatch_id -cne $old.dispatch_id) 'format correction requires one new same-role Dispatch'
        $s.format_corrections[$key]=1;$p['format_corrected']=$true;$s['format_lock']=@{artifact_id=$art.id;snapshot_id=$art.snapshot_id;role=$old.role;round=$old.round}
        $s['protected_reports']=@($s.protected_reports | Where-Object { $null -ne $_ })+@($data.report)
      } else {
        $s.Remove('format_lock')
        $groups=@{'plan-reviewer'='plan_review';'review-primary'='fused_review';'review-control'='fused_review';'review-final'='final_review'};$group=$groups[$p.role];if ($p.gate_fix) { $group='gate_fix' }
        if ($group) { $count=$s.rounds[$group];P-Require ($p.round -in @($count,($count+1)) -and $p.round -le (P-Cap $s $group)) ('round cap/sequence: '+$group);$s.rounds[$group]=$p.round }
        if ($group) { $family=P-Family @{projection=@{provider=@{model=$p.model}}};P-Require (-not @($s.accepted | Where-Object { $_.role -ceq $p.role -and $_.binding.round -eq $p.round -and $_.family -ceq $family }).Count) 'substantive review needs a new round' }
        if ($p.role -cin $PReview -and $p.role -cne 'plan-reviewer') { P-Independent $art $p.coverage (P-Family @{projection=@{provider=@{model=$p.model}}}) $s.provenance (P-Waived $s) }
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
      foreach ($accepted in @(@($s.accepted)+@($s['script_gates']) | Where-Object { $null -ne $_ })) { foreach ($proof in $accepted.evidence) { P-Require (V-EvidenceValid (P-Record $proof)) 'accepted evidence no longer valid' } }
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
          $s.accepted=@();$s['script_gates']=@();$s.commit_barrier=@{};$s.active=$null
          $s.rounds.fused_review=0;$s.rounds.gate_fix=0
        }
        if ($action -ceq 'complete') {
          P-Require ($fact.sha -cnotin @($s.phase_commits | ForEach-Object { $_.sha })) 'completion requires a separate commit'
          P-Final $s $phases $committed;$s.final['completion']=$fact
        }
      }
    }
    'extend-cap' {
      # Only the user lifts a cap; the coordinator records that decision verbatim, one round per record.
      $auth=P-Record $data.authorization;P-Need $auth @('schema_version','run_id','phase','group','extra_rounds','findings','user_decision')
      P-Require ($auth.schema_version -eq 1 -and $PCaps.ContainsKey([string]$auth.group) -and $auth.run_id -ceq $s.orca_run -and $auth.phase -ceq $s.phase -and $auth.extra_rounds -eq 1) 'cap extension binding mismatch'
      P-Require ($s.rounds[$auth.group] -ge (P-Cap $s $auth.group)) 'cap extension before the cap is reached'
      P-Require ($auth.findings -is [Array] -and $auth.findings.Count -and (P-Subset $auth.findings @($s.open_ledger_ids))) 'cap extension must name open findings'
      P-Require ($auth.user_decision -is [string] -and $auth.user_decision.Trim()) "cap extension without the user's decision"
      $s['cap_extensions']=@(@(@($s['cap_extensions']) | Where-Object { $null -ne $_ })+,@{group=$auth.group;phase=$auth.phase;authorization=$data.authorization})
    }
    'waive-independence' {
      # Only the user releases a unit from the family rule, and only where no independent family
      # exists: every known family already authored it. The coordinator records that decision verbatim.
      $auth=P-Record $data.authorization;P-Need $auth @('schema_version','run_id','step','phase','files','reviewer_family','user_decision')
      P-Require ($auth.schema_version -eq 1 -and $auth.run_id -ceq $s.orca_run -and $auth.step -ceq $s.step -and (P-Eq $auth.phase $s.phase)) 'independence waiver binding mismatch'
      P-Require ($auth.files -is [Array] -and $auth.files.Count -and -not @($auth.files | Where-Object { -not ($_ -is [string] -and $_) }).Count -and $auth.reviewer_family -cin (P-KnownFamilies)) 'independence waiver must name files and a known reviewer family'
      P-Require ($auth.user_decision -is [string] -and $auth.user_decision.Trim()) "independence waiver without the user's decision"
      $writers=P-Authors (P-Artifact $data.artifact $s) $s.provenance
      foreach ($name in $auth.files) { P-Require ((P-Subset (P-KnownFamilies) @($writers[$name]))) ('independence waiver needs every family as author: '+$name) }
      $s['independence_waivers']=@(@(@($s['independence_waivers']) | Where-Object { $null -ne $_ })+,@{step=$auth.step;phase=$auth.phase;files=$auth.files;reviewer_family=$auth.reviewer_family;authorization=$data.authorization})
    }
    'record-gate' {
      # verify-gate GATE_OK needs no worker; its sealed C4 results are the gate evidence.
      P-Require ($s.step -ceq 'phase' -and -not $s.write_ownership.Count) 'script gate outside an unowned phase candidate'
      $art=P-Artifact $data.artifact $s;$proofs=P-EvidenceRecords $data.evidence $art
      $kept=@(@($s['script_gates']) | Where-Object { $null -ne $_ -and $_.step -cne $s.step })
      $s['script_gates']=@($kept+,@{step=$s.step;artifact=$data.artifact;evidence=$proofs})
    }
    'resume' {
      if (-not $s.commit_barrier.confirmed_sha) {
        foreach ($accepted in $s.accepted) {
          if ($accepted.step -ceq $s.step) {
            # A diagnosis or a verdict with unclosed findings approves nothing: its candidate is
            # expected to be repaired, so it is history. Approvals must still match the tree.
            $history=($accepted.role -ceq 'diagnosis') -or [bool]@($accepted.findings | Where-Object { $_.id -cnotin @($s.closed_ledger_ids) }).Count
            [void](P-Artifact $accepted.artifact $s (-not $history))
          }
        }
      }
    }
    default { P-Require $false 'unknown action' }
  }
  $s['barrier']=P-Barrier $s $phases;return @{state=$s;decision=$decision}
}

if ($MyInvocation.InvocationName -eq '.') { return }

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
  V-Safe $out
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
  V-Safe $out
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

try {
  if ($args.Count -and $args[0] -ceq 'claude-model-evidence') { P-ClaudeEvidence $args }
  if ($args.Count -and $args[0] -ceq 'antigravity-model-evidence') { P-AgyEvidence $args }
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

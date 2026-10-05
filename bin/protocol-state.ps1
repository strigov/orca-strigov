#Requires -Version 5.1
# C6 v2 native validator: one coordinator transition against the current candidate. History is not
# re-proven; invariants: (a) P-Fleet, (b) P-CommitCheck, (c) P-Independent / P-PlanIndependent.
# All subprocesses are bounded read-only Git helpers.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'lib/verification.ps1')
. (Join-Path $PSScriptRoot 'lib/protocol-facts.ps1')
$PCaps=[ordered]@{plan_review=4;fused_review=4;final_review=2;gate_fix=2}
$PGood=@{'plan-reviewer'=@('APPROVED');gate=@('GATE_OK');'review-primary'=@('REVIEW_OK');'review-control'=@('REVIEW_OK');'review-final'=@('REVIEW_OK');quickfix=@('DONE','DONE_WITH_CONCERNS')}
$PWritten=@('DONE','DONE_WITH_CONCERNS','PLAN_WRITTEN','REVISED','SYNTHESIS_DONE')
$PReady=@{plan=@('plan-reviewer');quickfix=@('quickfix');phase=@('gate','review-primary','review-control');'final-review'=@('review-final');delivery=@('gate');completion=@()}
$PDecisions=@('DEFER','NIT','REJECTED_BY_SCOPE')  # ESCALATED_TO_HUMAN keeps a finding open until the user decides
$PKeys=@('schema_version','mode','plan','ledger_path','orca_run','plan_base','phase','base','step','worktree','worktree_id','workspace','active','rounds',
  'cap_extensions','independence_waivers','provenance','accepted','write_ownership','phase_commits','final_source','processed_messages','used_fleet_ids')

function P-Cap($s,[string]$group) {
  # Protocol cap plus the user's one-round extensions for this phase (each checked by extend-cap).
  return $PCaps[$group]+@(@($s.cap_extensions) | Where-Object { $null -ne $_ -and $_.group -ceq $group -and (P-Eq $_.phase $s.phase) }).Count
}
function P-Plan($s) {
  if ($null -eq $s.plan -or $null -eq $s.plan.sha256) { return ,@() }
  $facts=P-PlanRead (P-Ref $s.plan)
  P-Require ($facts.shape -ceq $s.plan.structure) 'plan structure differs from state'
  P-Require ($facts.orca_run -ceq $s.orca_run -and $facts.plan_base -ceq $s.plan_base) 'plan/run/base mismatch'
  if ($null -ne $s.phase) { $p=@($facts.phases | Where-Object { $_.id -ceq $s.phase });P-Require ($p.Count -eq 1 -and $p[0].base -ceq $s.base) 'phase/base mismatch' }
  return ,$facts.phases
}
function P-UpdatePlan($data,$s) {
  # A fresh plan reference: any bytes in a plan author's report, otherwise only bookkeeping lines may move.
  $new=V-Get $data 'plan';$old=$s.plan
  if ($null -eq $new -or ($null -ne $old -and $new.path -ceq $old.path -and $new.sha256 -ceq $old.sha256)) { return }
  P-Require ($null -ne $old -and $new.path -ceq $old.path) 'plan path differs from state'
  $shape=(P-PlanRead (P-Ref $new)).shape
  $author=$data.action -ceq 'accept-report' -and (V-Get $s.active 'role') -cin @('plan-writer','plan-reviser')
  P-Require ($author -or $shape -ceq $old.structure) 'plan change outside the plan author/review path'
  $s.plan=[ordered]@{path=$new.path;sha256=$new.sha256;structure=$shape}
}
function P-Ledger($data,$s) {
  # Coordinator bookkeeping, read only for the four decisions and check results, by finding id.
  $ref=V-Get $data 'ledger';$out=New-Object 'Collections.Generic.Dictionary[string,object]' ([StringComparer]::Ordinal);if ($null -eq $ref) { return ,$out }
  P-Require ($null -eq $s.ledger_path -or $s.ledger_path -ceq $ref.path) 'ledger path differs from state';$s.ledger_path=$ref.path
  $items=P-Record $ref
  P-Require ($items -is [Array] -and -not @($items | Where-Object { -not ($_ -is [Collections.IDictionary] -and $_.id -is [string]) }).Count -and @($items | ForEach-Object { $_.id } | Select-Object -Unique).Count -eq $items.Count) 'invalid ledger'
  foreach ($x in $items) { $out[$x.id]=$x };return ,$out
}
function P-Fleet($data,$s) {
  # Invariant (a): a fresh complete fleet shows no live or unverifiable writer in this worktree.
  P-Require (-not @(@($s.write_ownership) | Where-Object { ([string]$_).StartsWith('pending:') }).Count) 'unbound writer intent' 2
  $fleet=P-FleetWorkers $data @($s.used_fleet_ids);$ownership=@()
  foreach ($w in $fleet.workers) {
    $p=V-Get $w 'projection' @{};if ($null -eq $p) { $p=@{} };$workspace=V-Get $p 'workspace' @{};if ($null -eq $workspace) { $workspace=@{} }
    $uncertain=$w.terminalState -cin @('release_pending','release_unknown') -or (V-Get (V-Get $w 'resource' @{}) 'ownershipState') -cin @('user_owned','external','pre_existing')
    if (-not $uncertain -and $w.dispatchStatus -cin @('completed','failed') -and (V-Get (V-Get $p 'evidence' @{}) 'durable') -eq $true) { continue }
    P-Require ($null -ne (V-Get $workspace 'id')) 'unknown fleet workspace' 2;if ($workspace.id -cne $s.worktree_id) { continue }
    P-Require (-not $uncertain) 'unresolved release/external ownership' 2
    if ($w.terminalState -ceq 'released' -and (V-Get (V-Get $p 'liveness' @{}) 'verdict') -ceq 'exited') { continue };$ownership+=$w.dispatchId
  }
  $s.write_ownership=@($ownership);P-Require (-not $ownership.Count) 'live or unverifiable prior writer' 2
  $s.used_fleet_ids=@(@($s.used_fleet_ids)+@($fleet.ids) | Where-Object { $null -ne $_ })
}
function P-Independent($art,$coverage,$family,$s) {
  # Invariant (c): the reviewer family authored no covered file, unless the user waived it for this step.
  $m=$art.manifest;$writers=P-Authors $art @($s.provenance);if ($null -eq $coverage) { $coverage=@{} }
  $waived=@(foreach ($w in @($s.independence_waivers)) { if ($null -ne $w -and $w.step -ceq $s.step -and (P-Eq $w.phase $s.phase)) { foreach ($path in $w.files) { $path+'|'+$w.reviewer_family } } })
  $files=P-List $coverage 'files';$parts=P-List $coverage 'parts'
  $changed=@($m.files | ForEach-Object { $_.path })
  P-Require (P-Subset $files $changed) 'unknown coverage file'
  foreach ($name in $files) { P-Require ($writers[$name]) ('unknown actual author: '+$name) 2;P-Require ($family -cnotin @($writers[$name]) -or (($name+'|'+$family) -cin $waived)) ('same-family review: '+$name) }
  P-Require (P-Subset $parts @($m.parts | ForEach-Object { $_.path })) 'unknown coverage part'
  foreach ($c in (P-List $coverage 'contracts')) {
    $match=@($m.coverage.contracts | Where-Object { $_.id -ceq (V-Get $c 'id') });P-Require ($match.Count -eq 1) 'unknown coverage contract'
    foreach ($side in 'producer','consumer') { $list=P-List $c $side;P-Require (P-Subset $list $match[0][$side]) 'unknown contract side';P-Require (P-Subset @($list | Where-Object { $_ -cin $changed }) $files) 'contract side lacks file review' }
  }
}
function P-PlanIndependent($s,$family) {
  P-Require (@($s.provenance).Count) 'unknown plan authors' 2
  foreach ($author in @($s.provenance)) { P-Require ((P-Family (P-Record $author).result $author) -cne $family) 'same-family plan review' }
}
function P-Latest($s,[string]$role,$cand) {
  $found=-1;$list=@($s.accepted);for ($i=0;$i -lt $list.Count;$i++) { if ($list[$i].role -ceq $role -and (P-Eq $list[$i].candidate $cand)) { $found=$i } };return $found
}
function P-Checked($item) {
  $path=V-Get $item 'check'
  try { if (-not ($path -is [string] -and [IO.Path]::IsPathRooted($path))) { return $false };$result=P-Decode ([IO.File]::ReadAllText($path,$VUtf8).TrimStart([char]0xfeff)) } catch { return $false }
  # A sealed run-check result (seal intact) that exited 0; bytes are not compared.
  return ($result -is [Collections.IDictionary] -and ($result['exit_code'] -is [int] -or $result['exit_code'] -is [long]) -and $result['exit_code'] -eq 0 -and (V-EvidenceValid $result))
}
function P-Unresolved($s,$cand,$decisions) {
  # Resolved: a ledger decision; a cannot_verify check with exit 0; a later round of the role on cand omitting it.
  $out=@();$list=@($s.accepted)
  for ($i=0;$i -lt $list.Count;$i++) {
    $r=$list[$i];$last=P-Latest $s $r.role $cand;$later=if ($last -gt $i) { $list[$last] } else { $null }
    foreach ($f in @($r.findings)) {
      $item=if ($decisions.ContainsKey($f.id)) { $decisions[$f.id] } else { @{} }
      if ((V-Get $item 'decision') -cin $PDecisions -or ($f.kind -ceq 'cannot_verify' -and (P-Checked $item))) { continue }
      if ($f.kind -ceq 'blocking' -and $null -ne $later -and $later.round -gt $r.round -and $f.id -cnotin @(@($later.findings) | ForEach-Object { $_.id })) { continue }
      $out+=$f.id
    }
  };return ,$out
}
function P-Ready($s,$cand,$decisions) {
  # The step's required roles have positive latest reports on cand, nothing is unresolved, reviews cover the package.
  $rows=@()
  foreach ($role in $PReady[$s.step]) {
    $i=P-Latest $s $role $cand;P-Require ($i -ge 0) ('required report is missing: '+$role) 2
    P-Require (@($s.accepted)[$i].token -cin $PGood[$role]) ('required report is not positive: '+$role);$rows+=,@($s.accepted)[$i]
  }
  $still=P-Unresolved $s $cand $decisions;P-Require (-not $still.Count) ('unresolved findings: '+($still -join ', '))
  $reviews=@($rows | Where-Object { $_.role -cin $PReview -and $_.role -cne 'plan-reviewer' })
  if (-not $reviews.Count) { return }
  $m=P-Record $reviews[0].artifact;$skip=P-PlanName $s
  $union={ param($key) @(foreach ($r in $reviews) { foreach ($p in (P-List $r.coverage $key)) { $p } }) }
  P-Require (P-Subset @($m.files | ForEach-Object { $_.path } | Where-Object { $_ -cne $skip }) (& $union 'files')) 'incomplete file coverage' 2
  P-Require (P-Subset @($m.parts | ForEach-Object { $_.path }) (& $union 'parts')) 'incomplete part coverage' 2
  foreach ($c in @($m.coverage.contracts)) { foreach ($side in 'producer','consumer') {
    $sides=@(foreach ($r in $reviews) { foreach ($x in (P-List $r.coverage 'contracts')) { if ($x.id -ceq $c.id) { foreach ($p in (P-List $x $side)) { $p } } } })
    P-Require (P-Subset @($c[$side] | Where-Object { $_ -cne $skip }) $sides) ('incomplete contract '+$c.id+':'+$side) 2
  } }
}
function P-Current($s) {
  if ($s.step -ceq 'plan') { return $s.plan.sha256 }
  $rows=@(@($s.accepted) | Where-Object { $_.role -cnotin @('diagnosis','synthesizer') })
  if (-not $rows.Count) { return $null };$last=$rows[$rows.Count-1]
  if ($last.role -cin $PWrite -and $last.token -cnotin $PWritten) { return $null };return $last.candidate
}
function P-Committed($s) { return ,@(@($s.phase_commits) | Where-Object { $null -ne $_ -and $_.step -ceq $s.step -and (P-Eq $_.phase $s.phase) }) }
function P-Barrier($s,$phases,$decisions=@{}) {
  $step=$s.step
  if (@($s.write_ownership).Count) { return 'awaiting_writer' }
  if ((P-Committed $s).Count) {
    if ($step -cin @('quickfix','completion')) { return 'complete' }
    $last=if (@($phases).Count) { @($phases)[@($phases).Count-1].id } else { $null }
    if ($s.phase -cne $last) { return 'ready_next_phase' };return 'awaiting_final_review'
  }
  if ($step -ceq 'final-review') { return 'awaiting_final_review' };if ($step -ceq 'delivery') { return 'awaiting_delivery' };if ($step -ceq 'completion') { return 'awaiting_completion_commit' }
  $cand=P-Current $s
  if ($null -eq $cand) { if ($step -ceq 'plan') { return 'awaiting_plan_writer' };return 'awaiting_implementation' }
  try { P-Ready $s $cand $decisions;return 'awaiting_commit' } catch { if (-not $_.Exception.Data.Contains('code')) { throw } }
  $rows=@(foreach ($role in $PReady[$step]) { P-Latest $s $role $cand })
  if ($rows[0] -lt 0) { if ($step -ceq 'plan') { return 'awaiting_plan_review' };if ($step -ceq 'phase') { return 'awaiting_gate' };return 'awaiting_implementation' }
  foreach ($i in $rows) { if ($i -ge 0 -and @($s.accepted)[$i].token -cnotin $PGood[@($s.accepted)[$i].role]) { return 'awaiting_resolution' } }
  if ($rows -contains -1 -or -not (P-Unresolved $s $cand $decisions).Count) { return 'awaiting_review' };return 'awaiting_resolution'
}
function P-IsAncestor([string]$root,[string]$a,[string]$b) { try { [void](V-Git $root @('merge-base','--is-ancestor',$a,$b));return $true } catch { return $false } }
function P-CommitCheck($s,$fact,$cand,$art) {
  # Invariant (b): the commit tree is the accepted candidate; the plan file may differ in bookkeeping lines only.
  P-Need $fact @('sha','base');$root=$s.worktree;$sha=$fact.sha;$base=$fact.base
  foreach ($x in $sha,$base) { P-Require ($x -is [string] -and $x -cmatch '^[a-f0-9]{40}$') 'missing full commit identity' 2 }
  P-Require (P-IsAncestor $root $sha $sha) 'commit not found' 2;P-Require ($sha -cne $base) 'base is not a completion commit'
  P-Require ((P-IsAncestor $root $base $sha) -and (P-IsAncestor $root $sha 'HEAD')) 'commit is not above its base on HEAD'
  $name=P-PlanName $s
  if ($art.kind -ceq 'plan') {
    P-Require ($base -ceq $s.plan_base) 'plan commit base differs from plan_base'
    $changed=@((V-GitText $root @('diff-tree','--no-commit-id','-r','--name-only',$base,$sha)).Split("`n") | Where-Object { $_ })
    P-Require ($changed.Count -eq 1 -and $changed[0] -ceq $name) 'plan commit must change only the plan file'
    P-Require ((V-Hash (V-Git $root @('show',($sha+':'+$name)))) -ceq $cand) 'plan commit blob differs from accepted plan';return $null
  }
  P-Require ($base -ceq $art.head) 'commit base differs from accepted candidate HEAD'
  $now=P-Fresh $s $art
  P-Require (-not (V-GitText $root @('diff','--no-ext-diff','--name-only','--'))) 'hook/working-tree or unstaged source after acceptance'
  $expected=@{}
  foreach ($label in @($now.manifest.files.Keys)) {
    if (-not $label.StartsWith('repo:',[StringComparison]::Ordinal) -or $label.Substring(5) -ceq $name) { continue };$item=$now.manifest.files[$label]
    P-Require ($item.Contains('index')) 'accepted source was not staged';if ($item.type -cne 'missing') { $expected[$label.Substring(5)]=$item.index }
  }
  $tree=@{};foreach ($row in (V-Nul (V-Git $root @('ls-tree','-r','-z',$sha)))) { $pair=$row.Split(@([char]9),2);$meta=$pair[0].Split(' ');$tree[$pair[1]]=@($meta[0],$meta[2]) }
  $hasPlan=$null -ne $name -and $tree.ContainsKey($name);if ($hasPlan) { $tree.Remove($name) }
  P-Require (P-Eq $tree $expected) 'commit does not contain accepted index/source'
  if (-not $hasPlan) { return $null }
  $facts=P-PlanRead ($VUtf8.GetString((V-Git $root @('show',($sha+':'+$name)))).TrimStart([char]0xfeff).Replace("`r`n","`n"))
  P-Require ($facts.shape -ceq $s.plan.structure) 'commit changes the plan beyond bookkeeping';return $facts
}
function P-AcceptReport($data,$s) {
  $raw=P-Record (V-Get $data 'event');P-Require ($raw.ok -eq $true) 'Orca did not accept event' 2;$r=V-Get $raw 'result' @{}
  if ($r.Contains('message')) { $messages=@($r.message) } else { $messages=P-List $r 'messages' }
  if (-not $messages.Count -and (V-Get $r 'timedOut') -eq $true) { return 'not-completion' }
  $selected=@($messages | Where-Object { $_.id -ceq (V-Get $data 'message_id') });P-Require ($selected.Count -eq 1) 'missing exact delivery message' 2
  $msg=$selected[0];$payload=V-Get $msg 'payload';if ($payload -is [string]) { $payload=P-Decode $payload };if ($null -eq $payload) { $payload=@{} }
  if ($msg.id -cin @($s.processed_messages)) { return 'duplicate' }
  $a=$s.active;P-Require ($null -ne $a) 'no current Dispatch' 2
  $ignored=if ($msg.type -cne 'worker_done') { 'not-completion' } elseif ($msg.run_id -cne $s.orca_run -or $payload.taskId -cne $a.task_id -or $payload.dispatchId -cne $a.dispatch_id) { 'stale' } else { $null }
  if ($ignored) { $s.processed_messages=@(@($s.processed_messages)+@($msg.id));return $ignored }
  $o=P-Observation $data.observation $a
  P-Require ($o.dispatch.status -ceq 'completed' -and $o.projection.evidence.durable -eq $true) 'missing durable settlement' 2
  P-Require ($msg.from_handle -ceq $o.dispatch.assigneeHandle) 'wrong report sender'
  $report=V-Get $data 'report';$text=P-Ref $report
  P-Require (-not @(@($s.accepted) | Where-Object { $null -ne $_.report -and $_.report.path -ceq $report.path }).Count) 'report path already bound to an accepted attempt'
  # The verdict is report line 1; the subject must lead with that exact token (a worker may append ": <why>").
  $subjectToken=([string]$msg.subject -split '[\s:]',2)[0]
  P-Require ($payload.reportPath -ceq $report.path -and $subjectToken -ne '' -and $subjectToken -ceq ($text -split '\n')[0]) 'report path/subject mismatch'
  $current=if ($null -eq (V-Get $data 'artifact') -and $null -eq $a.artifact_id) { $null } else { $true }
  $art=P-Artifact (V-Get $data 'artifact') $s $current;$role=$a.role
  if ($role -cnotin $PWrite) { P-Require ($a.artifact_id -ceq $art.id -and (P-Eq $a.snapshot_id $art.snapshot_id)) 'assigned artifact changed' }
  $fields=P-Report $text $a $art (V-Get $payload 'outcome') (P-List $payload 'filesModified')
  if ($role -cin @('plan-writer','plan-reviser') -and $fields.token -cin $PWritten) { P-Require ($art.kind -ceq 'plan' -and $art.id -ceq $s.plan.sha256) 'plan author must deliver the current plan' }
  $family=P-Family $o
  if ($role -cin $PReview -and $role -cne 'plan-reviewer') { P-Independent $art $fields.coverage $family $s }
  if ($role -ceq 'plan-reviewer') { P-PlanIndependent $s $family }
  $proofs=if ($role -ceq 'gate' -and $fields.token -ceq 'GATE_OK') { ,(P-EvidenceRecords (P-Line $text 'EVIDENCE') $art $s) } else { ,@() }
  if ($role -cin $PWrite) { $s.provenance=@(@($s.provenance)+,$data.observation) }
  $entry=[ordered]@{role=$role;token=$fields.token;round=$a.round;phase=$a.phase;step=$s.step;candidate=$art.candidate;artifact=(V-Get $data 'artifact');findings=@($fields.findings)
    coverage=$fields.coverage;family=$family;report=$report;dispatch_id=$a.dispatch_id;evidence=@($proofs)}
  $s.accepted=@(@($s.accepted)+,$entry);$s.processed_messages=@(@($s.processed_messages)+@($msg.id))
  $s.write_ownership=@(@($s.write_ownership) | Where-Object { $_ -cne $a.dispatch_id });$s.active=$null
  if (@($fields.findings | Where-Object { $_.risk -cin @('SECURITY','DATA_LOSS') }).Count) { return 'risk-escalation' };return 'accepted'
}
function P-Dispatch($data,$s) {
  P-Fleet $data $s;$p=V-Get $data 'proposed';P-Need $p @('run_id','task_id','dispatch_id','role','phase','round','worktree_id','model')
  P-Require ($p.role -is [string] -and $PTokens.ContainsKey($p.role) -and $p.run_id -ceq $s.orca_run -and (P-Eq $p.phase $s.phase) -and $p.worktree_id -ceq $s.worktree_id) 'proposed binding mismatch'
  P-Require (($p.round -is [int] -or $p.round -is [long]) -and $p.round -ge 1) 'invalid proposed round'
  P-Require ($p.task_id -and $null -eq $p.dispatch_id) 'dispatch proposal needs a fresh Task and null not-yet-created Dispatch'
  $unplanned=$null -ne $s.plan -and $null -eq $s.plan.sha256
  P-Require (-not $unplanned -or $p.role -ceq 'plan-writer') 'only a plan-writer may start before the plan exists'
  $current=if ($unplanned -and $null -eq (V-Get $data 'artifact')) { $null } else { $true }
  $art=P-Artifact (V-Get $data 'artifact') $s $current;$family=P-Family @{projection=@{provider=@{model=$p.model}}}
  $groups=@{'plan-reviewer'='plan_review';'review-primary'='fused_review';'review-control'='fused_review';'review-final'='final_review'};$group=$groups[$p.role];if ($p.gate_fix) { $group='gate_fix' }
  if ($group) {
    $count=$s.rounds[$group];P-Require ($p.round -in @($count,($count+1)) -and $p.round -le (P-Cap $s $group)) ('round cap/sequence: '+$group);$s.rounds[$group]=$p.round
    P-Require (-not @(@($s.accepted) | Where-Object { $_.role -ceq $p.role -and $_.round -eq $p.round -and $_.family -ceq $family }).Count) 'substantive review needs a new round'
  }
  if ($p.role -cin $PReview -and $p.role -cne 'plan-reviewer') { P-Independent $art (V-Get $p 'coverage' @{}) $family $s }
  $p['artifact_id']=$art.id;$p['snapshot_id']=$art.snapshot_id;$s.active=$p
  if ($p.role -cin $PWrite) { $s.write_ownership=@('pending:'+$p.task_id) }
}
function P-UserRecord($data,$s,[string[]]$keys,[string[]]$where,[string]$label) {
  # A user's decision saved verbatim by the coordinator, bound to this Run and step/phase.
  $auth=P-Record (V-Get $data 'authorization');P-Need $auth (@('schema_version','run_id','user_decision')+$keys)
  P-Require ($auth.schema_version -eq 1 -and $auth.run_id -ceq $s.orca_run -and -not @($where | Where-Object { -not (P-Eq $auth[$_] $s[$_]) }).Count) ($label+' binding mismatch')
  P-Require ($auth.user_decision -is [string] -and $auth.user_decision.Trim()) ($label+" without the user's decision");return $auth
}
function P-Validate($data) {
  P-Need $data @('schema_version','action','state');P-Require ($data.schema_version -eq 1) 'unsupported input schema' 2
  $s=P-Decode (V-Json $data.state)
  P-Require ($s -is [Collections.IDictionary] -and $s.schema_version -eq 2) 'schema 1 state: run protocol-state migrate' 2;P-Need $s $PKeys
  P-Require ($s.mode -cin @('plan','quickfix') -and $s.step -cin @('plan','phase','quickfix','final-review','delivery','completion') -and ($s.mode -ceq 'quickfix') -eq ($s.step -ceq 'quickfix') -and ($s.step -ceq 'quickfix') -eq ($null -eq $s.plan)) 'invalid protocol mode/step'
  P-Require ([IO.Path]::IsPathRooted($s.worktree) -and [IO.Path]::IsPathRooted($s.workspace)) 'absolute workspace required'
  P-Require ([IO.Path]::GetFullPath((V-GitText $s.worktree @('rev-parse','--show-toplevel'))).TrimEnd('\','/') -eq [IO.Path]::GetFullPath($s.worktree).TrimEnd('\','/')) 'TARGET is not a Git worktree' 2
  foreach ($sha in $s.plan_base,$s.base) { P-Require ($sha -is [string] -and $sha -cmatch '^[a-f0-9]{40}$' -and (P-IsAncestor $s.worktree $sha $sha)) 'missing recorded base' 2 }
  P-UpdatePlan $data $s
  P-Require ($null -eq $s.plan -or $null -ne $s.plan.sha256 -or $s.step -ceq 'plan') 'missing plan outside the plan step' 2
  $decisions=P-Ledger $data $s;$phases=P-Plan $s
  foreach ($key in $PCaps.Keys) { $n=$s.rounds[$key];P-Require (($n -is [int] -or $n -is [long]) -and $n -ge 0 -and $n -le (P-Cap $s $key)) ('round cap: '+$key) }
  $action=$data.action;$decision='accepted'
  switch -CaseSensitive ($action) {
    'accept-report' { $decision=P-AcceptReport $data $s }
    'dispatch' { P-Dispatch $data $s }
    'bind-dispatch' {
      $a=$s.active;P-Require ($a -and $null -eq $a.dispatch_id) 'no pending dispatch intent'
      $raw=P-Record $data.observation;P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2;$o=$raw.result;$d=$o.dispatch
      P-Require ($d.taskId -ceq $a.task_id -and $d.runId -ceq $s.orca_run -and $null -eq $d.retryOfDispatchId) 'dispatch does not bind pending fresh Task'
      P-Require ($d.id -and (P-ModelMatches $a.model (P-Model $o $data.observation))) 'actual launch differs from proposal';$a.dispatch_id=$d.id
      [void](P-Observation $data.observation $a);if ($a.role -cin $PWrite) { $s.write_ownership=@($d.id) }
    }
    { $_ -cin @('prepare-commit','confirm-commit') } {
      P-Fleet $data $s;P-Require ($s.step -cin @('plan','phase','quickfix','final-review')) 'not a commit step'
      $art=P-Artifact (V-Get $data 'artifact') $s ($action -ceq 'prepare-commit');P-Ready $s $art.candidate $decisions
      if ($action -ceq 'prepare-commit') { P-Require (-not (V-GitText $s.worktree @('diff','--no-ext-diff','--name-only','--'))) 'hook/working-tree or unstaged source after acceptance' }
      else {
        $fact=V-Get $data 'commit';[void](P-CommitCheck $s $fact $art.candidate $art)
        if (-not @((P-Committed $s) | Where-Object { $_.sha -ceq $fact.sha }).Count) { $s.phase_commits=@(@($s.phase_commits)+,([ordered]@{phase=$s.phase;step=$s.step;sha=$fact.sha;base=$fact.base;candidate=$art.candidate})) }
      }
    }
    'advance' {
      $done=P-Committed $s;P-Require ($s.step -cin @('plan','phase') -and $done.Count) 'advance before the phase commit is confirmed' 2
      $ids=@($phases | ForEach-Object { $_.id });$index=[Array]::IndexOf($ids,$s.phase)
      if ($index+1 -lt $ids.Count) { $s.phase=$ids[$index+1];$s.base=$done[$done.Count-1].sha;$s.step='phase' } else { $s.step='final-review' }
      $s.accepted=@();$s.active=$null;$s.rounds.fused_review=0;$s.rounds.gate_fix=0
    }
    'finish-checkpoint' {
      P-Fleet $data $s;P-Require ($s.step -cin @('final-review','delivery')) 'not a final checkpoint'
      P-Require (P-Subset @($phases | ForEach-Object { $_.id }) @(@($s.phase_commits) | Where-Object { $_.step -ceq 'phase' } | ForEach-Object { $_.phase })) 'uncommitted phases' 2
      $art=P-Artifact (V-Get $data 'artifact') $s $true
      if ($s.step -ceq 'delivery') { P-Require ($art.candidate -ceq $s.final_source) 'delivery covers a different source than the final review' }
      P-Ready $s $art.candidate $decisions
      $s.final_source=$art.candidate;$s.step=if ($s.step -ceq 'final-review') { 'delivery' } else { 'completion' };$s.accepted=@();$s.active=$null
    }
    'complete' {
      P-Fleet $data $s;P-Require ($s.step -ceq 'completion' -and $s.final_source) 'not a final checkpoint'
      $art=P-Artifact (V-Get $data 'artifact') $s
      P-Require ($art.kind -cne 'plan' -and $art.candidate -ceq $s.final_source) 'completion candidate differs from the final-reviewed source'
      $fact=V-Get $data 'commit';P-Require ((V-Get $fact 'sha') -cnotin @(@($s.phase_commits) | ForEach-Object { $_.sha })) 'completion requires a separate commit'
      $plan=P-CommitCheck $s $fact $s.final_source $art;P-Require ($null -ne $plan -and $plan.done) 'final bookkeeping is incomplete' 2
      $s.phase_commits=@(@($s.phase_commits)+,([ordered]@{phase=$s.phase;step='completion';sha=$fact.sha;base=$fact.base;candidate=$art.candidate}))
    }
    'extend-cap' {
      # Only the user lifts a reached cap, one round per verbatim record.
      $auth=P-UserRecord $data $s @('phase','group','extra_rounds','findings') @('phase') 'cap extension'
      P-Require ($PCaps.Contains([string]$auth.group) -and $auth.extra_rounds -eq 1) 'cap extension binding mismatch'
      P-Require ($s.rounds[$auth.group] -ge (P-Cap $s $auth.group)) 'cap extension before the cap is reached'
      $known=@(foreach ($r in @($s.accepted)) { foreach ($f in @($r.findings)) { $f.id } })
      P-Require ($auth.findings -is [Array] -and $auth.findings.Count -and (P-Subset $auth.findings $known)) 'cap extension must name accepted findings'
      $s.cap_extensions=@(@($s.cap_extensions)+,([ordered]@{group=$auth.group;phase=$auth.phase;authorization=$data.authorization}))
    }
    'waive-independence' {
      # Only the user releases a unit from the family rule, and only where every known family already authored it.
      $auth=P-UserRecord $data $s @('step','phase','files','reviewer_family') @('step','phase') 'independence waiver'
      P-Require ($auth.files -is [Array] -and $auth.files.Count -and -not @($auth.files | Where-Object { -not ($_ -is [string] -and $_) }).Count -and $auth.reviewer_family -cin (P-KnownFamilies)) 'independence waiver must name files and a known reviewer family'
      $writers=P-Authors (P-Artifact (V-Get $data 'artifact') $s $true) @($s.provenance)
      foreach ($name in $auth.files) { P-Require (P-Subset (P-KnownFamilies) @($writers[$name])) ('independence waiver needs every family as author: '+$name) }
      $s.independence_waivers=@(@($s.independence_waivers)+,([ordered]@{step=$auth.step;phase=$auth.phase;files=$auth.files;reviewer_family=$auth.reviewer_family;authorization=$data.authorization}))
    }
    'record-author' {
      # A settled writer whose report was rejected still authored bytes: register its observation (with its model
      # proof) so C5 provenance resolves. More author families only make reviews stricter, never weaker.
      $raw=P-Record $data.observation;P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2
      $result=$raw.result;P-Need $result @('dispatch','projection');$d=$result.dispatch
      $ws=V-Get $result.projection 'workspace'
      P-Require ($d.runId -ceq $s.orca_run -and $ws -is [Collections.IDictionary] -and (V-Get $ws 'id') -ceq $s.worktree_id) 'author observation outside this Run and worktree'
      P-Require ($d.status -cin @('completed','failed') -and (V-Get (V-Get $result.projection 'evidence') 'durable') -eq $true) 'author Dispatch is not durably settled' 2
      [void](P-Model $result $data.observation)
      P-Require (-not @($s.provenance | Where-Object { $_.path -ceq $data.observation.path }).Count) 'author already recorded'
      $s.provenance=@(@($s.provenance)+,$data.observation)
    }
    'record-gate' {
      # A green verify-gate needs no worker; its sealed C4 results are the gate evidence.
      P-Require ($s.step -cin @('phase','delivery') -and -not @($s.write_ownership).Count) 'script gate outside an unowned phase or delivery candidate'
      $art=P-Artifact (V-Get $data 'artifact') $s $true;$proofs=P-EvidenceRecords (V-Get $data 'evidence') $art $s
      $s.accepted=@(@($s.accepted)+,([ordered]@{role='gate';token='GATE_OK';round=$s.rounds.gate_fix;phase=$s.phase;step=$s.step;candidate=$art.candidate;artifact=$data.artifact
        findings=@();coverage=@{};family=$null;report=$null;dispatch_id=$null;evidence=@($proofs)}))
    }
    default { P-Require ($action -ceq 'resume') 'unknown action' }
  }
  $s['barrier']=P-Barrier $s $phases $decisions;return @{state=$s;decision=$decision}
}

if ($MyInvocation.InvocationName -eq '.') { return }

try {
  if ($args.Count -and $args[0] -cin @('summary','migrate')) { . (Join-Path $PSScriptRoot 'lib/protocol-tools.ps1');if ($args[0] -ceq 'summary') { P-Summary $args } else { P-Migrate $args } }
  if ($args.Count -and $args[0] -ceq 'claude-model-evidence') { P-ClaudeEvidence $args }
  if ($args.Count -and $args[0] -ceq 'antigravity-model-evidence') { P-AgyEvidence $args }
  P-Require ($args.Count -in @(2,3) -and $args[0] -ceq 'validate') 'usage: protocol-state validate INPUT_JSON [RESUME_OUT]'
  $data=P-Decode ([IO.File]::ReadAllText($args[1],$VUtf8).TrimStart([char]0xfeff));$result=P-Validate $data
  if ($args.Count -eq 3) {
    $target=[IO.Path]::GetFullPath($args[2]);$workspace=[IO.Path]::GetFullPath($result.state.workspace).TrimEnd('\','/')
    P-Require ($target.StartsWith($workspace+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -and [IO.Directory]::Exists([IO.Path]::GetDirectoryName($target))) 'resume output outside existing workspace'
    try { V-Safe $target } catch { P-Require $false 'linked resume output' }
    $protected=New-Object 'Collections.Generic.List[string]';$protected.Add([IO.Path]::GetFullPath($args[1]))
    function P-Protect($obj) { if ($obj -is [Collections.IDictionary]) { if ($obj.Contains('path') -and $obj.path -is [string]) { $protected.Add([IO.Path]::GetFullPath($obj.path)) };foreach ($v in $obj.Values) { P-Protect $v } } elseif ($obj -is [Array]) { foreach ($v in $obj) { P-Protect $v } } }
    P-Protect $data;P-Require ($target -notin $protected) 'resume must not replace an input artifact';V-Save $target $result.state
  }
  [Console]::WriteLine('VALID');[Console]::WriteLine((V-Json @{decision=$result.decision;state=$result.state}));exit 0
} catch {
  $code=2;$next='supply-bound-facts';$reason=$_.Exception.Message
  if ($_.Exception.Data.Contains('code')) { $code=[int]$_.Exception.Data['code'];$next='resolve-protocol-blocker' }
  [Console]::WriteLine($(if ($code -eq 1) { 'INVALID' } else { 'UNVERIFIABLE' }));[Console]::WriteLine((V-Json @{reason=$reason;next_action=$next}));exit $code
}

#Requires -Version 5.1
# C6 v2 native validator: one coordinator transition against the current candidate. History is not
# re-proven; invariants: (a) P-Fleet, (b) P-CommitCheck, (c) P-Independent / P-PlanIndependent.
# All subprocesses are bounded read-only Git helpers.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'lib/verification.ps1')
. (Join-Path $PSScriptRoot 'lib/protocol-facts.ps1')
# Ordinal maps throughout: a group, role or step differing only in case is unknown, as in Python.
$PCaps=V-Map;$PCaps['plan_review']=4;$PCaps['fused_review']=4;$PCaps['final_review']=2;$PCaps['gate_fix']=2
$PGood=V-Map;$PGood['plan-reviewer']=@('APPROVED');$PGood['gate']=@('GATE_OK');$PGood['review-primary']=@('REVIEW_OK');$PGood['review-control']=@('REVIEW_OK');$PGood['review-final']=@('REVIEW_OK');$PGood['quickfix']=@('DONE','DONE_WITH_CONCERNS')
$PWritten=@('DONE','DONE_WITH_CONCERNS','PLAN_WRITTEN','REVISED','SYNTHESIS_DONE')
$PReady=V-Map;$PReady['plan']=@('plan-reviewer');$PReady['quickfix']=@('quickfix');$PReady['phase']=@('gate','review-primary','review-control');$PReady['final-review']=@('review-final');$PReady['delivery']=@('gate');$PReady['completion']=@()
# A final-fix commit also needs a gate on the fixed bytes; the final checkpoint itself needs only the final review.
$PCommitReady=V-Map;foreach ($k in @($PReady.Keys)) { $PCommitReady[$k]=$PReady[$k] };$PCommitReady['final-review']=@('gate','review-final')
$PPlanAuthors=@('plan-writer','plan-reviser')
$PPlanRoles=@('plan-writer','plan-reviser','plan-reviewer','diagnosis')  # may run while a plan revision awaits its review
$PDecisions=@('DEFER','NIT','REJECTED_BY_SCOPE')  # ESCALATED_TO_HUMAN keeps a finding open until the user decides
$PKeys=@('schema_version','mode','plan','ledger_path','orca_run','plan_base','phase','base','step','worktree','worktree_id','workspace','active','rounds',
  'cap_extensions','independence_waivers','provenance','accepted','write_ownership','phase_commits','final_source','processed_messages','used_fleet_ids')

function P-Cap($s,[string]$group) {
  # Protocol cap plus the user's one-round extensions (each checked by extend-cap). Plan review is one budget per
  # plan, so its extensions count in every phase; the other groups are per phase.
  return $PCaps[$group]+@(@($s.cap_extensions) | Where-Object { $null -ne $_ -and $_.group -ceq $group -and ($group -ceq 'plan_review' -or (P-Eq $_.phase $s.phase)) }).Count
}
function P-Plan($s) {
  if ($null -eq $s.plan -or $null -eq $s.plan.sha256) { return ,@() }
  $facts=P-PlanRead (P-Ref $s.plan)
  P-Require ($facts.shape -ceq $s.plan.structure) 'plan structure differs from state'
  P-Require ($facts.orca_run -ceq $s.orca_run -and $facts.plan_base -ceq $s.plan_base) 'plan/run/base mismatch'
  if ($null -ne $s.phase) { $p=@($facts.phases | Where-Object { $_.id -ceq $s.phase });P-Require ($p.Count -eq 1 -and $p[0].base -ceq $s.base) 'phase/base mismatch' }
  return ,$facts.phases
}
function P-LegacySuperset($s) {
  # Every model family an older state can name as a writer of this Run: its writer observations in provenance and the
  # write rows of every package it still references. An observation whose family cannot be read counts as every family.
  $families=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
  foreach ($ref in @($s.provenance)) {
    try { [void]$families.Add((P-Family (P-Record $ref).result $ref)) } catch { foreach ($f in (P-KnownFamilies)) { [void]$families.Add($f) } }
  }
  foreach ($r in @($s.accepted)) {
    if ((V-Get (V-Get $r 'artifact' @{}) 'kind') -cne 'package') { continue }
    try { $writers=P-Authors @{manifest=(P-Record $r.artifact)} @($s.provenance);foreach ($k in @($writers.Keys)) { foreach ($f in @($writers[$k])) { [void]$families.Add($f) } } } catch { continue }
  }
  return ,@($families)
}
function P-ApprovedStructure($s) {
  # The plan structure an older state can prove approved: its latest accepted plan-reviewer APPROVED (unless a plan
  # author's entry came later), else the plan-only commit's plan when no plan author's entry remains. Otherwise none.
  if ($null -eq $s.plan -or $s.step -ceq 'plan') { return $null }
  $list=@($s.accepted);$approval=-1;$revision=-1
  for ($i=0;$i -lt $list.Count;$i++) {
    if ($list[$i].role -cin $PPlanAuthors) { $revision=$i } elseif ($list[$i].role -ceq 'plan-reviewer' -and $list[$i].token -ceq 'APPROVED') { $approval=$i }
  }
  try {
    if ($approval -ge 0 -and $approval -gt $revision) { return (P-PlanRead (P-Ref $list[$approval].artifact)).shape }
    $commit=@(@($s.phase_commits) | Where-Object { $_.step -ceq 'plan' } | Select-Object -First 1)
    if ($commit.Count -and $revision -lt 0) {
      return (P-PlanRead ($VUtf8.GetString((V-Git $s.worktree @('show',($commit[0].sha+':'+(P-PlanName $s))))).TrimStart([char]0xfeff).Replace("`r`n","`n"))).shape
    }
  } catch { }
  return $null
}
function P-SourceCapture($s) {
  # The repository entries of the worktree right now (plan file and synthesis excluded) and their candidate digest.
  $now=V-Snapshot $s.worktree @() @($s.workspace);P-Require $now.valid ('unverifiable source capture: '+$now.reason) 2
  $skip=@(P-PlanName $s)+@((P-Synthesis $s).Keys);$entries=V-Map
  foreach ($k in @($now.manifest.files.Keys)) {
    $x=$now.manifest.files[$k];if ($k.StartsWith('repo:',[StringComparison]::Ordinal) -and $x.type -cne 'missing' -and $k.Substring(5) -cnotin $skip) { $entries[$k.Substring(5)]=P-Entry $x }
  }
  return @{candidate=(P-Candidate $now.manifest.files $s);entries=$entries}
}
function P-SourceCandidate($s) { return (P-SourceCapture $s).candidate }
function P-PlanLane($s,$assignment) {
  # A plan author edits the plan file only: the source candidate is still the one captured at its dispatch.
  $source=V-Get $assignment 'source'
  if ($null -ne $source) { P-Require ((P-SourceCandidate $s) -ceq $source) 'plan author changed source outside the plan: revert it or attribute it with record-author (route further source work to an implementer)' }
}
function P-Upgrade($s) {
  # A state written before authors/plan_authors existed rebuilds them once from what it holds: the validated write receipts
  # of the C5 packages its accepted reviews used (a write touching the plan file is plan authorship) and its accepted plan
  # writer/reviser entries. Nothing rebuilt stays unknown: an unknown author never makes a reviewer independent.
  # Legacy rule: a file committed in an earlier phase (plan_base..the current phase's base; every phase in the final steps)
  # gets the superset of every writer family the state can name (P-LegacySuperset): it only makes independence stricter.
  # Consumed final-review rounds and the approved plan structure are rebuilt only from evidence the state holds.
  if (-not $s.Contains('authors') -or $null -eq (V-Get $s 'plan_authors')) {
    $name=P-PlanName $s;$rebuilt=V-Map;$planRefs=New-Object Collections.ArrayList;$observed=V-Map
    foreach ($ref in @($s.provenance)) { try { $observed[(P-Record $ref).result.dispatch.id]=$ref } catch { } }
    $addPlan={ param($ref) if ($ref.path -cnotin @($planRefs | ForEach-Object { $_.path })) { [void]$planRefs.Add($ref) } }
    foreach ($r in @($s.accepted)) {
      $id=V-Get $r 'dispatch_id';if ($r.role -cin $PPlanAuthors -and $null -ne $id -and $observed.Contains($id)) { & $addPlan $observed[$id] }
      if ((V-Get (V-Get $r 'artifact' @{}) 'kind') -cne 'package') { continue }
      try { $m=P-Record $r.artifact;$writers=P-Authors @{manifest=$m} @($s.provenance) } catch { continue }
      foreach ($path in @($writers.Keys)) { if ($path -cne $name) { $rebuilt[$path]=@(@(@($rebuilt[$path] | Where-Object { $null -ne $_ })+@($writers[$path])) | Sort-Object -Unique -CaseSensitive) } }
      foreach ($w in (P-List $m.provenance 'writes')) {
        if ($name -cin @($w.files)) {
          $known=@(@($s.provenance) | Where-Object { $_.path -ceq $w.receipt_path -and $_.sha256 -ceq $w.receipt_sha256 })
          & $addPlan $(if ($known.Count) { $known[0] } else { [ordered]@{path=$w.receipt_path;sha256=$w.receipt_sha256} })
        }
      }
    }
    if (-not $s.Contains('authors')) {
      $end=if ($s.step -cin @('plan','phase','quickfix')) { $s.base } else { 'HEAD' }
      # Every path any recorded commit range changed, not only the endpoint diff: a file changed in one phase and
      # restored in a later one still had that phase's writers.
      $ranges=@(,@($s.plan_base,$end));foreach ($c in @($s.phase_commits)) { if ($null -ne $c) { $ranges+=,@($c.base,$c.sha) } }
      $earlier=@(@(foreach ($r in $ranges) { V-Nul (V-Git $s.worktree @('diff','--no-ext-diff','--name-only','-z',$r[0],$r[1],'--')) }) | Where-Object { $_ -cne $name } | Sort-Object -Unique -CaseSensitive)
      if ($earlier.Count) {
        $superset=P-LegacySuperset $s
        foreach ($x in $earlier) { $rebuilt[$x]=@(@(@($rebuilt[$x] | Where-Object { $null -ne $_ })+@($superset)) | Sort-Object -Unique -CaseSensitive) }
      }
      $sorted=V-Map;foreach ($k in @($rebuilt.Keys | Sort-Object -CaseSensitive)) { $sorted[$k]=$rebuilt[$k] };$s['authors']=$sorted
    }
    if ($null -eq (V-Get $s 'plan_authors')) { $s['plan_authors']=@($planRefs) }
  }
  if ($s.Contains('authors_incomplete')) { $s.Remove('authors_incomplete') }  # a round-4/5 development field; no installed version wrote it
  if (-not $s.Contains('attempts')) {
    # The final-review rounds counted so far are consumed: after a checkpoint, and conservatively in final-review too (an
    # older runtime may have reopened it). There the rebuilt R<round>-REOPEN identity lets the user extend the cap.
    $n=$s.rounds.final_review;$reopened=$s.step -ceq 'final-review' -and $n -gt 0
    $s['attempts']=@(if ($reopened -or $s.step -cin @('delivery','completion')) { for ($k=1;$k -le $n;$k++) { [ordered]@{role='review-final';round=$k;family=$null} } })
    if ($reopened) {
      $item=[ordered]@{id=('R'+$n+'-REOPEN');kind='blocking';location='final-review';issue='consumed final-review rounds rebuilt for an older state'}
      $s.accepted=@(@($s.accepted)+,([ordered]@{role='reopen';token='REOPENED';round=$n;phase=$s.phase;step='final-review';candidate=$null;artifact=$null
        findings=@($item);coverage=@{};family=$null;report=$null;dispatch_id=$null;evidence=@()}))
    }
  }
  if (-not $s.Contains('plan_approved')) { $s['plan_approved']=P-ApprovedStructure $s }
}
function P-ImportPlanApproval($data,$s) {
  # resume with prior_plan_approval_state: an earlier saved state of this Run whose accepted, independent plan approval
  # is of the current plan structure restores plan_approved (and its evidence reference) only.
  $refspec=V-Get $data 'prior_plan_approval_state';if ($null -eq $refspec) { return }
  $check={ param($ok,$why) if (-not $ok) { P-Require $false ('prior plan approval does not apply: '+$why) } }
  & $check ($data.action -ceq 'resume' -and $null -ne $s.plan) 'only resume of a plan Run imports a prior approval'
  $obj=P-Record $refspec;$prior=if ($obj -is [Collections.IDictionary] -and $obj.Contains('action')) { $obj.state } else { $obj }
  & $check ($prior -is [Collections.IDictionary] -and (V-Get $prior 'schema_version') -eq 2 -and (V-Get $prior 'accepted') -is [Array]) 'not a schema 2 state'
  & $check ((V-Get $prior 'orca_run') -ceq $s.orca_run -and (V-Get $prior 'worktree') -ceq $s.worktree -and (V-Get $prior 'plan_base') -ceq $s.plan_base -and
    (V-Get (V-Get $prior 'plan' @{}) 'path') -ceq $s.plan.path) 'another Run, worktree, plan path or plan_base'
  & $check (P-Subset @(V-Get $prior 'processed_messages' @()) @($s.processed_messages)) 'not an earlier state of this Run'
  $rows=@($prior.accepted);$last=-1;for ($i=0;$i -lt $rows.Count;$i++) { if ($rows[$i].role -ceq 'plan-reviewer' -and $rows[$i].token -ceq 'APPROVED') { $last=$i } }
  & $check ($last -ge 0) 'it holds no accepted plan-reviewer APPROVED'
  $e=$rows[$last];& $check (-not @($rows | Select-Object -Skip ($last+1) | Where-Object { $_.role -cin $PPlanAuthors }).Count) "a plan author's entry follows the approval"
  $art=V-Get $e 'artifact' @{};& $check ((V-Get $art 'kind') -ceq 'plan' -and $e.candidate -ceq (V-Get $art 'sha256')) 'the approval is not of a plan artifact'
  $text=P-Ref $e.report;$b=P-Line $text 'BINDING'
  & $check (($text -split '\n')[0] -ceq 'APPROVED' -and $b.run_id -ceq $s.orca_run -and $b.role -ceq 'plan-reviewer' -and $b.dispatch_id -ceq $e.dispatch_id -and
    $b.round -eq $e.round -and $b.artifact_id -ceq $art.sha256) 'its report binding differs from the entry'
  & $check ((P-PlanRead (P-Ref $art)).shape -ceq $s.plan.structure) 'the approved structure is not the current plan'
  try { P-PlanIndependent $s $e.family } catch { if (-not $_.Exception.Data.Contains('code')) { throw };$x=New-Object InvalidOperationException(('prior plan approval does not apply: '+$_.Exception.Message));$x.Data['code']=$_.Exception.Data['code'];throw $x }
  $s['plan_approved']=$s.plan.structure;$s['plan_approval_evidence']=$refspec
}
function P-PlanReviewed($s) {
  # No substantive plan revision awaits its independent plan review (the plan step has its own approval barrier).
  return ($null -eq $s.plan -or $s.step -ceq 'plan' -or $s.plan.structure -ceq $s.plan_approved)
}
function P-Drafted($s) {
  # The live plan file no longer holds the accepted bytes (a plan author's working draft).
  if ($null -eq $s.plan -or $null -eq $s.plan.sha256) { return $false }
  try { return (V-FileHash $s.plan.path) -cne $s.plan.sha256 } catch { return $true }
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
function P-Settled($w) {
  # A fleet row that positively ended: durably completed/failed, or released with an exited process.
  $p=V-Get $w 'projection' @{};if ($null -eq $p) { $p=@{} }
  if ($w.terminalState -cin @('release_pending','release_unknown') -or (V-Get (V-Get $w 'resource' @{}) 'ownershipState') -cin @('user_owned','external','pre_existing')) { return $false }
  return (($w.dispatchStatus -cin @('completed','failed') -and (V-Get (V-Get $p 'evidence' @{}) 'durable') -eq $true) -or
          ($w.terminalState -ceq 'released' -and (V-Get (V-Get $p 'liveness' @{}) 'verdict') -ceq 'exited'))
}
function P-Fleet($data,$s) {
  # Invariant (a): a fresh complete fleet shows no live or unverifiable writer in this worktree. A recorded writer
  # must be in it: absence from an inventory taken before that writer started proves nothing.
  P-Require (-not @(@($s.write_ownership) | Where-Object { ([string]$_).StartsWith('pending:') }).Count) 'unbound writer intent' 2
  $fleet=P-FleetWorkers $data @($s.used_fleet_ids);$ownership=@()
  $rows=V-Map;foreach ($w in @($fleet.workers)) { $rows[[string](V-Get $w 'dispatchId')]=$w }
  foreach ($owner in @($s.write_ownership)) {
    P-Require ($rows.Contains([string]$owner)) ('recorded writer missing from fleet: '+$owner) 2
    # A bound writer that settled without an accepted report still wrote bytes: its family must be recorded first.
    P-Require (-not (P-Settled $rows[[string]$owner])) ('writer '+$owner+' settled without an accepted report: record-author it first') 2
  }
  foreach ($w in $fleet.workers) {
    $p=V-Get $w 'projection' @{};if ($null -eq $p) { $p=@{} };$workspace=V-Get $p 'workspace' @{};if ($null -eq $workspace) { $workspace=@{} }
    $uncertain=$w.terminalState -cin @('release_pending','release_unknown') -or (V-Get (V-Get $w 'resource' @{}) 'ownershipState') -cin @('user_owned','external','pre_existing')
    if (-not $uncertain -and $w.dispatchStatus -cin @('completed','failed') -and (V-Get (V-Get $p 'evidence' @{}) 'durable') -eq $true) { continue }
    P-Require ($null -ne (V-Get $workspace 'id')) 'unknown fleet workspace' 2;if ($workspace.id -cne $s.worktree_id) { continue }
    P-Require (-not $uncertain) 'unresolved release/external ownership' 2
    if ($w.terminalState -ceq 'released' -and (V-Get (V-Get $p 'liveness' @{}) 'verdict') -ceq 'exited') { continue };$ownership+=$w.dispatchId
  }
  $s.write_ownership=@($ownership);P-Require (-not $ownership.Count) 'live or unverifiable prior writer' 2
  $s.used_fleet_ids=@(@($s.used_fleet_ids)+@($fleet.ids) | Where-Object { $null -ne $_ });return ,@($fleet.workers)
}
function P-FileAuthors($art,$s) {
  # Actual author families per file: the package's write receipts plus the cumulative authorship C6 recorded from
  # every accepted or registered writer of this Run (earlier phases, fixes and fallbacks included).
  $writers=P-Authors $art @($s.provenance)
  foreach ($path in @($s.authors.Keys)) { $writers[$path]=@(@($writers[$path] | Where-Object { $null -ne $_ })+@($s.authors[$path])) }
  return ,$writers
}
function P-Independent($art,$coverage,$family,$s) {
  # Invariant (c): the reviewer family authored no covered file or contract side, unless the user waived it for this step.
  $m=$art.manifest;$writers=P-FileAuthors $art $s;if ($null -eq $coverage) { $coverage=@{} }
  $waived=@(foreach ($w in @($s.independence_waivers)) { if ($null -ne $w -and $w.step -ceq $s.step -and (P-Eq $w.phase $s.phase)) { foreach ($path in $w.files) { $path+'|'+$w.reviewer_family } } })
  $files=P-List $coverage 'files';$parts=P-List $coverage 'parts'
  $changed=@($m.files | ForEach-Object { $_.path })
  P-Require (P-Subset $files $changed) 'unknown coverage file'
  foreach ($name in $files) { P-Require ($writers[$name]) ('unknown actual author: '+$name) 2;P-Require ($family -cnotin @($writers[$name]) -or (($name+'|'+$family) -cin $waived)) ('same-family review: '+$name) }
  P-Require (P-Subset $parts @($m.parts | ForEach-Object { $_.path })) 'unknown coverage part'
  $plan=P-PlanName $s
  $sides=@(foreach ($c in (P-List $coverage 'contracts')) { foreach ($side in 'producer','consumer') { foreach ($p in (P-List $c $side)) { if ($p -cnotin $changed -and $p -cne $plan) { $p } } } })
  $sides=@($sides | Select-Object -Unique)
  $earlier=if ($sides.Count) { @(V-Nul (V-Git $s.worktree (@('diff','--no-ext-diff','--name-only','-z',$s.plan_base,'--')+$sides))) } else { @() }
  foreach ($c in (P-List $coverage 'contracts')) {
    $match=@($m.coverage.contracts | Where-Object { $_.id -ceq (V-Get $c 'id') });P-Require ($match.Count -eq 1) 'unknown coverage contract'
    foreach ($side in 'producer','consumer') {
      $list=P-List $c $side;P-Require (P-Subset $list $match[0][$side]) 'unknown contract side';P-Require (P-Subset @($list | Where-Object { $_ -cin $changed }) $files) 'contract side lacks file review'
      # An unchanged side file needs no file review, but its recorded authors still exclude their family from covering it.
      foreach ($name in @($list | Where-Object { $_ -cnotin $changed })) {
        # Written earlier in this Run but with no recorded author: unknown, never independent.
        P-Require ($writers[$name] -or $name -cnotin $earlier) ('unknown actual author: '+$name) 2
        P-Require ($family -cnotin @($writers[$name]) -or (($name+'|'+$family) -cin $waived)) ('same-family review: '+$name)
      }
    }
  }
}
function P-PlanIndependent($s,$family) {
  # Plan authors are the accepted or registered plan writers and revisers only (rebuilt once for an older state).
  $authors=@($s.plan_authors);P-Require ($authors.Count) 'unknown plan authors' 2
  foreach ($author in $authors) { P-Require ((P-Family (P-Record $author).result $author) -cne $family) 'same-family plan review' }
}
function P-Written($s,$before,$art) {
  # Paths a settled writer changed: its own window (dispatch-time vs delivered capture) when the dispatch-time capture
  # is known, otherwise everything changed since the step base. More authors only make reviews stricter.
  if ($null -eq $art.files) { return ,@() }
  $repo={ param($files) $out=V-Map;foreach ($k in @($files.Keys)) { $x=$files[$k];if ($k.StartsWith('repo:',[StringComparison]::Ordinal) -and $x.type -cne 'missing') { $out[$k.Substring(5)]=P-Entry $x } };,$out }
  $now=& $repo $art.files
  if ($null -ne $before) {
    $old=& $repo $before;$paths=@(@(@($old.Keys)+@($now.Keys)) | Select-Object -Unique | Where-Object { -not ($old.Contains($_) -and $now.Contains($_) -and $old[$_] -ceq $now[$_]) })
  } else {
    $paths=@(V-Nul (V-Git $s.worktree @('diff','--no-ext-diff','--name-only','-z',(P-StepBase $s),'--')))
    foreach ($k in @($art.files.Keys)) { $x=$art.files[$k];if ($k.StartsWith('repo:',[StringComparison]::Ordinal) -and $x.type -cne 'missing' -and -not $x.Contains('index')) { $paths+=$k.Substring(5) } }
  }
  $plan=P-PlanName $s;return ,@($paths | Where-Object { $_ -cne $plan })
}
function P-Attribute($s,$paths,[string]$family) {
  foreach ($path in @($paths | Sort-Object -Unique -CaseSensitive)) { $s.authors[$path]=@(@(@($s.authors[$path] | Where-Object { $null -ne $_ })+$family) | Sort-Object -Unique -CaseSensitive) }
}
function P-Latest($s,[string]$role,$cand) {
  $found=-1;$list=@($s.accepted);for ($i=0;$i -lt $list.Count;$i++) { if ($list[$i].role -ceq $role -and (P-Eq $list[$i].candidate $cand)) { $found=$i } };return $found
}
function P-Covered($review) {
  # Every file a review covered: its file coverage and the files named in its contract sides.
  # P-List hands back one array object: flatten with foreach, never @(P-List ...).
  $files=@(foreach ($p in (P-List $review.coverage 'files')) { $p });foreach ($x in (P-List $review.coverage 'contracts')) { foreach ($side in 'producer','consumer') { foreach ($p in (P-List $x $side)) { $files+=$p } } }
  return ,@($files | Select-Object -Unique)
}
function P-Units($finding,$review) {
  # The reviewed unit a finding is about: its location's file when that review covered it (as a file or a contract side),
  # else the review's whole coverage.
  $files=P-Covered $review;$path=([string](V-Get $finding 'location' '')).Split(':')[0].Trim()
  if ($path -cin $files) { return ,@($path) };return ,$files
}
function P-Omitted($s,$review,$finding,$cand) {
  # A later round of the same role on cand covers the finding's unit and none of its reports lists it.
  $later=@{}
  foreach ($r in @($s.accepted)) { if ($r.role -ceq $review.role -and (P-Eq $r.candidate $cand) -and $r.round -gt $review.round -and $r.token -cne 'BLOCKED') { $later[[string]$r.round]=@($later[[string]$r.round] | Where-Object { $null -ne $_ })+,$r } }
  $units=P-Units $finding $review
  foreach ($rows in $later.Values) {
    $listed=@(foreach ($r in $rows) { foreach ($f in @($r.findings)) { $f.id } })
    $covered=@(foreach ($r in $rows) { foreach ($p in (P-Covered $r)) { $p } })
    if ($finding.id -cnotin $listed -and (P-Subset $units $covered)) { return $true }
  };return $false
}
function P-Unresolved($s,$cand,$decisions) {
  # Resolved: a ledger decision; a cannot_verify item checked by its literal CHECK; a later round on cand covering the
  # finding's unit and omitting it. A gate failure is identity only: a positive gate on cand supersedes it.
  # Plan-review findings belong to the plan: outside the plan step they resolve against the latest approved plan.
  $approved=@(@($s.accepted) | Where-Object { $_.role -ceq 'plan-reviewer' -and $_.token -ceq 'APPROVED' } | ForEach-Object { $_.candidate })
  $planCand=if ($approved.Count -and $s.step -cne 'plan') { $approved[$approved.Count-1] } else { $cand }
  $out=@()
  foreach ($r in @($s.accepted)) {
    if ($r.role -cin @('gate','reopen')) { continue }
    foreach ($f in @($r.findings)) {
      $item=if ($decisions.ContainsKey($f.id)) { $decisions[$f.id] } else { @{} }
      if ((V-Get $item 'decision') -cin $PDecisions -or ($f.kind -ceq 'cannot_verify' -and (P-Checked $item $f))) { continue }
      # A cannot_verify item whose literal CHECK actually ran (sealed result in the ledger's execution_evidence) and that
      # the ledger accepted as a defect to fix becomes a fix item: like a blocking finding it closes when a later round
      # covers its unit without it, on a candidate other than the one it was raised on. Whether the run showed the defect
      # is the coordinator's and the later independent reviewer's judgement, not parsed from EXPECT prose.
      $target=if ($r.role -ceq 'plan-reviewer') { $planCand } else { $cand }
      $confirmed=($f.kind -ceq 'cannot_verify') -and ((V-Get $item 'decision') -cin @('ACCEPTED','PARTIALLY_ACCEPTED')) -and (P-Ran $item $f) -and ($target -cne $r.candidate)
      if ((($f.kind -ceq 'blocking') -or $confirmed) -and (P-Omitted $s $r $f $target)) { continue }
      $out+=$f.id
    }
  };return ,$out
}
function P-Approvals($s,[string]$role,$cand) {
  # The current reports of a role on cand: for reviews, the latest attempt of each family in the latest round
  # (complementary assignments share one round; a BLOCKED attempt is superseded by its retry); else the latest report.
  $rows=@(@($s.accepted) | Where-Object { $_.role -ceq $role -and (P-Eq $_.candidate $cand) })
  if (-not $rows.Count) { return ,@() };if ($role -cnotin $PReview -or $role -ceq 'plan-reviewer') { return ,@($rows[$rows.Count-1]) }
  $top=($rows | ForEach-Object { $_.round } | Measure-Object -Maximum).Maximum;$byFamily=V-Map
  foreach ($r in $rows) { if ($r.round -eq $top) { $byFamily[[string]$r.family]=$r } }
  $current=@(@($byFamily.Values) | Where-Object { $_.token -cne 'BLOCKED' });if ($current.Count) { return ,$current };return ,@($rows[$rows.Count-1])
}
function P-Ready($s,$cand,$decisions,$roles=$null) {
  # The step's required roles have positive current reports on cand, nothing is unresolved, the reviews are still
  # independent of every recorded author, and together they cover the package.
  if ($null -eq $roles) { $roles=$PReady[$s.step] };$rows=@()
  foreach ($role in $roles) {
    $current=P-Approvals $s $role $cand;P-Require ($current.Count) ('required report is missing: '+$role) 2
    foreach ($r in $current) { P-Require ($r.token -cin $PGood[$role]) ('required report is not positive: '+$role) };$rows+=$current
  }
  $still=P-Unresolved $s $cand $decisions;P-Require (-not $still.Count) ('unresolved findings: '+($still -join ', '))
  foreach ($r in $rows) { if ($r.role -ceq 'plan-reviewer') { P-PlanIndependent $s $r.family } }
  $reviews=@($rows | Where-Object { $_.role -cin $PReview -and $_.role -cne 'plan-reviewer' })
  if (-not $reviews.Count) { return }
  $packages=V-Map
  foreach ($r in $reviews) { if (-not $packages.Contains($r.artifact.path)) { $packages[$r.artifact.path]=P-Record $r.artifact };P-Independent @{manifest=$packages[$r.artifact.path]} $r.coverage $r.family $s }
  $m=$packages[$reviews[0].artifact.path];$skip=P-PlanName $s
  $union={ param($key) @(foreach ($r in $reviews) { foreach ($p in (P-List $r.coverage $key)) { $p } }) }
  P-Require (P-Subset @($m.files | ForEach-Object { $_.path } | Where-Object { $_ -cne $skip }) (& $union 'files')) 'incomplete file coverage' 2
  P-Require (P-Subset @($m.parts | ForEach-Object { $_.path }) (& $union 'parts')) 'incomplete part coverage' 2
  foreach ($c in @($m.coverage.contracts)) { foreach ($side in 'producer','consumer') {
    $sides=@(foreach ($r in $reviews) { foreach ($x in (P-List $r.coverage 'contracts')) { if ($x.id -ceq $c.id) { foreach ($p in (P-List $x $side)) { $p } } } })
    P-Require (P-Subset @($c[$side] | Where-Object { $_ -cne $skip }) $sides) ('incomplete contract '+$c.id+':'+$side) 2
  } }
}
function P-GateFinding($s) {
  # A failed gate's identity G<r>-B1 (r = the gate-fix round it opens), so the user's cap extension can name it.
  return [ordered]@{id=('G'+($s.rounds.gate_fix+1)+'-B1');kind='blocking';issue='verification gate failed';location='verify-gate'}
}
function P-Current($s) {
  if ($s.step -ceq 'plan') { return $s.plan.sha256 }
  # A mid-phase plan revision and its review are not the source candidate.
  $rows=@(@($s.accepted) | Where-Object { $_.role -cnotin (@('synthesizer')+$PPlanRoles) })
  if (-not $rows.Count) { return $null };$last=$rows[$rows.Count-1]
  if ($last.role -cin $PWrite -and $last.token -cnotin $PWritten) { return $null };return $last.candidate
}
function P-Committed($s) { return ,@(@($s.phase_commits) | Where-Object { $null -ne $_ -and $_.step -ceq $s.step -and (P-Eq $_.phase $s.phase) }) }
function P-Barrier($s,$phases,$decisions=@{}) {
  $step=$s.step
  if (@($s.write_ownership).Count) { return 'awaiting_writer' }
  if (-not (P-PlanReviewed $s)) { return 'awaiting_plan_review' }
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
  $expected=V-Map
  foreach ($label in @($now.manifest.files.Keys)) {
    if (-not $label.StartsWith('repo:',[StringComparison]::Ordinal) -or $label.Substring(5) -ceq $name) { continue };$item=$now.manifest.files[$label]
    P-Require ($item.Contains('index')) 'accepted source was not staged';if ($item.type -cne 'missing') { $expected[$label.Substring(5)]=$item.index }
  }
  $tree=V-Map;foreach ($row in (V-Nul (V-Git $root @('ls-tree','-r','-z',$sha)))) { $pair=$row.Split(@([char]9),2);$meta=$pair[0].Split(' ');$tree[$pair[1]]=@($meta[0],$meta[2]) }
  $hasPlan=$null -ne $name -and $tree.Contains($name);if ($hasPlan) { $tree.Remove($name) }
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
  if ($role -cin $PPlanAuthors) { P-PlanLane $s $a }
  if ($role -cin $PPlanAuthors -and $fields.token -cin $PWritten) { P-Require ($art.kind -ceq 'plan' -and $art.id -ceq $s.plan.sha256) 'plan author must deliver the current plan' }
  $family=P-Family $o
  if ($role -cin $PReview -and $role -cne 'plan-reviewer') { P-Independent $art $fields.coverage $family $s }
  if ($role -ceq 'plan-reviewer') { P-PlanIndependent $s $family }
  $proofs=if ($role -ceq 'gate' -and $fields.token -ceq 'GATE_OK') { ,(P-EvidenceRecords (P-Line $text 'EVIDENCE') $art $s) } else { ,@() }
  $findings=@(if ($role -ceq 'gate' -and $fields.token -ceq 'GATE_FAIL') { P-GateFinding $s } else { $fields.findings })
  $synthesis=$null
  if ($role -ceq 'synthesizer' -and $fields.token -ceq 'SYNTHESIS_DONE') {
    # The synthesis summarises the acceptance; its bytes are frozen here and leave the candidate identity.
    $path=($text -split '\n')[1].Trim();$item=if ($null -ne $art.files) { V-Get $art.files ('repo:'+$path) } else { $null }
    P-Require ($null -ne $item -and $item.type -ceq 'file') 'synthesis path is not in the delivered artifact'
    # Only when it is the synthesizer's only change, one Markdown document under docs/reviews/, does it leave the candidate.
    $wrote=P-Written $s (P-ManifestFiles (V-Get $a 'artifact')) $art
    if ($path -cmatch '\Adocs/reviews/[^/]+\.md\z' -and $wrote.Count -eq 1 -and $wrote[0] -ceq $path) { $synthesis=[ordered]@{path=$path;entry=(P-Entry $item)} }
  }
  if ($role -ceq 'plan-reviewer' -and $fields.token -ceq 'APPROVED') { $s['plan_approved']=$s.plan.structure }
  if ($role -cin $PWrite) {
    $s.provenance=@(@($s.provenance)+,$data.observation)
    if ($role -cin $PPlanAuthors) { if ($null -ne $s.plan_authors) { $s.plan_authors=@(@($s.plan_authors)+,$data.observation) } }
    else { P-Attribute $s (P-Written $s (P-ManifestFiles (V-Get $a 'artifact')) $art) $family }
  }
  $entry=[ordered]@{role=$role;token=$fields.token;round=$a.round;phase=$a.phase;step=$s.step;candidate=$art.candidate;artifact=(V-Get $data 'artifact');findings=$findings
    coverage=$fields.coverage;family=$family;report=$report;dispatch_id=$a.dispatch_id;evidence=@($proofs)}
  if ($null -ne $synthesis) { $entry['synthesis']=$synthesis }
  $s.accepted=@(@($s.accepted)+,$entry);$s.processed_messages=@(@($s.processed_messages)+@($msg.id))
  if ($role -ceq 'gate' -and $fields.token -ceq 'GATE_OK') { $s.rounds.gate_fix=0 }  # the gate-fix cap counts consecutive rounds
  $s.write_ownership=@(@($s.write_ownership) | Where-Object { $_ -cne $a.dispatch_id });$s.active=$null
  if (@($fields.findings | Where-Object { $_.risk -cin @('SECURITY','DATA_LOSS') }).Count) { return 'risk-escalation' };return 'accepted'
}
function P-Dispatch($data,$s) {
  [void](P-Fleet $data $s);$p=V-Get $data 'proposed';P-Need $p @('run_id','task_id','dispatch_id','role','phase','round','worktree_id','model')
  P-Require ($p.role -is [string] -and $PTokens.Contains($p.role) -and $p.run_id -ceq $s.orca_run -and (P-Eq $p.phase $s.phase) -and $p.worktree_id -ceq $s.worktree_id) 'proposed binding mismatch'
  P-Require (($p.round -is [int] -or $p.round -is [long]) -and $p.round -ge 1) 'invalid proposed round'
  P-Require ($p.task_id -and $null -eq $p.dispatch_id) 'dispatch proposal needs a fresh Task and null not-yet-created Dispatch'
  $unplanned=$null -ne $s.plan -and $null -eq $s.plan.sha256
  P-Require (-not $unplanned -or $p.role -ceq 'plan-writer') 'only a plan-writer may start before the plan exists'
  P-Require ((P-PlanReviewed $s) -or $p.role -cin $PPlanRoles) 'plan revision awaits an independent plan review'
  $current=if ($unplanned -and $null -eq (V-Get $data 'artifact')) { $null } else { $true }
  # A new synthesizer may replace a synthesis whose frozen bytes changed (its own dispatch does not re-check them).
  $view=$s;if ($p.role -ceq 'synthesizer') { $view=V-Map;foreach ($k in @($s.Keys)) { $view[$k]=$s[$k] };$view['active']=$p }
  $art=P-Artifact (V-Get $data 'artifact') $view $current;$family=P-Family @{projection=@{provider=@{model=$p.model}}}
  $groups=@{'plan-reviewer'='plan_review';'review-primary'='fused_review';'review-control'='fused_review';'review-final'='final_review'};$group=$groups[$p.role];if ($p.gate_fix) { $group='gate_fix' }
  if ($group) {
    $count=$s.rounds[$group];P-Require ($p.round -in @($count,($count+1)) -and $p.round -le (P-Cap $s $group)) ('round cap/sequence: '+$group);$s.rounds[$group]=$p.round
  }
  if ($p.role -cin $PReview) {
    # A BLOCKED attempt reviewed nothing: its fresh retry keeps the round.
    P-Require (-not @(@($s.accepted) | Where-Object { $_.role -ceq $p.role -and $_.round -eq $p.round -and $_.family -ceq $family -and $_.token -cne 'BLOCKED' }).Count) 'substantive review needs a new round'
    # After a final checkpoint the consumed final-review rounds stay consumed (reopen-final starts a new round).
    P-Require (-not @(@($s.attempts) | Where-Object { $_.role -ceq $p.role -and $_.round -ge $p.round }).Count) 'substantive review needs a new round'
  }
  if ($p.role -cin $PReview -and $p.role -cne 'plan-reviewer') { P-Independent $art (V-Get $p 'coverage' @{}) $family $s }
  # The dispatch-time capture bounds what a writer authored and proves an unbound launch wrote nothing.
  $p['artifact_id']=$art.id;$p['snapshot_id']=$art.snapshot_id;$p['artifact']=V-Get $data 'artifact';$p['candidate']=$art.candidate
  if ($p.role -cin $PPlanAuthors) { $capture=P-SourceCapture $s;$p['source']=$capture.candidate;$p['source_files']=$capture.entries }  # its lane is the plan file
  $s.active=$p
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
  # Added after the first schema 2 states: plan_authors null keeps the legacy rule (every recorded writer is a plan author).
  P-Upgrade $s
  P-Require ($s.mode -cin @('plan','quickfix') -and $s.step -cin @('plan','phase','quickfix','final-review','delivery','completion') -and ($s.mode -ceq 'quickfix') -eq ($s.step -ceq 'quickfix') -and ($s.step -ceq 'quickfix') -eq ($null -eq $s.plan)) 'invalid protocol mode/step'
  P-Require ([IO.Path]::IsPathRooted($s.worktree) -and [IO.Path]::IsPathRooted($s.workspace)) 'absolute workspace required'
  P-Require ([IO.Path]::GetFullPath((V-GitText $s.worktree @('rev-parse','--show-toplevel'))).TrimEnd('\','/') -eq [IO.Path]::GetFullPath($s.worktree).TrimEnd('\','/')) 'TARGET is not a Git worktree' 2
  foreach ($sha in $s.plan_base,$s.base) { P-Require ($sha -is [string] -and $sha -cmatch '^[a-f0-9]{40}$' -and (P-IsAncestor $s.worktree $sha $sha)) 'missing recorded base' 2 }
  $action=$data.action;$decision='accepted'
  # While a plan author's attempt is current (pending, bound, or settled with a rejected report) the live plan is its
  # working draft: transitions of that attempt and a fresh author attempt read the accepted reference, not the file.
  $draft=(V-Get $s.active 'role') -cin $PPlanAuthors -and ($action -cin @('bind-dispatch','accept-report','record-author','reconcile-intent','resume') -or
    ($action -ceq 'dispatch' -and (V-Get (V-Get $data 'proposed') 'role') -cin $PPlanAuthors))
  P-UpdatePlan $data $s
  P-Require ($null -eq $s.plan -or $null -ne $s.plan.sha256 -or $s.step -ceq 'plan') 'missing plan outside the plan step' 2
  $decisions=P-Ledger $data $s
  # Only the live file may be a draft: an accepted plan reference that fails its own checks is never tolerated.
  $phases=if ($draft -and (P-Drafted $s)) { @() } else { P-Plan $s }
  foreach ($key in $PCaps.Keys) { $n=$s.rounds[$key];P-Require (($n -is [int] -or $n -is [long]) -and $n -ge 0 -and $n -le (P-Cap $s $key)) ('round cap: '+$key) }
  P-ImportPlanApproval $data $s
  if ($action -cin @('prepare-commit','confirm-commit','advance','finish-checkpoint','complete')) { P-Require (P-PlanReviewed $s) 'plan revision awaits an independent plan review' }
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
      [void](P-Fleet $data $s);P-Require ($s.step -cin @('plan','phase','quickfix','final-review')) 'not a commit step'
      $art=P-Artifact (V-Get $data 'artifact') $s ($action -ceq 'prepare-commit');P-Ready $s $art.candidate $decisions $PCommitReady[$s.step]
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
      [void](P-Fleet $data $s);P-Require ($s.step -cin @('final-review','delivery')) 'not a final checkpoint'
      P-Require (P-Subset @($phases | ForEach-Object { $_.id }) @(@($s.phase_commits) | Where-Object { $_.step -ceq 'phase' } | ForEach-Object { $_.phase })) 'uncommitted phases' 2
      $art=P-Artifact (V-Get $data 'artifact') $s $true
      if ($s.step -ceq 'delivery') { P-Require ($art.candidate -ceq $s.final_source) 'delivery covers a different source than the final review' }
      P-Ready $s $art.candidate $decisions
      if ($s.step -ceq 'final-review') {  # the consumed final-review attempts outlive the cleared entries
        $s.attempts=@(@($s.attempts)+@(@($s.accepted) | Where-Object { $_.role -ceq 'review-final' -and $_.token -cne 'BLOCKED' } | ForEach-Object { [ordered]@{role=$_.role;round=$_.round;family=$_.family} }))
      }
      $s.final_source=$art.candidate;$s.step=if ($s.step -ceq 'final-review') { 'delivery' } else { 'completion' };$s.accepted=@();$s.active=$null
    }
    'complete' {
      [void](P-Fleet $data $s);P-Require ($s.step -ceq 'completion' -and $s.final_source) 'not a final checkpoint'
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
      $writers=P-FileAuthors (P-Artifact (V-Get $data 'artifact') $s $true) $s
      foreach ($name in $auth.files) { P-Require (P-Subset (P-KnownFamilies) @($writers[$name])) ('independence waiver needs every family as author: '+$name) }
      $s.independence_waivers=@(@($s.independence_waivers)+,([ordered]@{step=$auth.step;phase=$auth.phase;files=$auth.files;reviewer_family=$auth.reviewer_family;authorization=$data.authorization}))
    }
    'record-author' {
      # A settled writer whose report was rejected still authored bytes: register its observation (with its model
      # proof) and the files it changed. More author families only make reviews stricter, never weaker.
      $raw=P-Record $data.observation;P-Require ($raw.ok -eq $true) 'unsuccessful Orca observation' 2
      $result=$raw.result;P-Need $result @('dispatch','projection');$d=$result.dispatch
      $ws=V-Get $result.projection 'workspace'
      P-Require ($d.runId -ceq $s.orca_run -and $ws -is [Collections.IDictionary] -and (V-Get $ws 'id') -ceq $s.worktree_id) 'author observation outside this Run and worktree'
      P-Require ($d.status -cin @('completed','failed') -and (V-Get (V-Get $result.projection 'evidence') 'durable') -eq $true) 'author Dispatch is not durably settled' 2
      $authorFamily=P-Family $result $data.observation
      P-Require (-not @($s.provenance | Where-Object { $_.path -ceq $data.observation.path }).Count) 'author already recorded'
      # The active assignment's own Dispatch, or the Dispatch of its still unbound Task (a launch that started with another
      # model and wrote): its dispatch-time capture bounds the attribution, and the intent is resolved by it.
      $a=$s.active;$own=@{}
      if ($null -ne $a -and ((V-Get $a 'dispatch_id') -ceq $d.id -or ($null -eq (V-Get $a 'dispatch_id') -and (V-Get $a 'task_id') -ceq $d.taskId))) { $own=$a }
      $planned=(V-Get $own 'role') -cin $PPlanAuthors -or (V-Get (V-Get $data 'artifact' @{}) 'kind') -ceq 'plan'
      $art=P-Artifact (V-Get $data 'artifact') $s $(if ($planned -and $null -eq (V-Get $data 'artifact')) { $null } else { $true })
      $s.provenance=@(@($s.provenance)+,$data.observation)
      if ($planned) {
        $s.plan_authors=@(@($s.plan_authors)+,$data.observation)  # a plan author wrote the plan file
        $source=V-Get $own 'source'
        if ((V-Get $own 'role') -cin $PPlanAuthors -and $null -ne $source -and (P-SourceCandidate $s) -cne $source) {
          # Out of its lane it also wrote source: its family authors exactly the delta against the source captured at its
          # dispatch, reversions and deletions included (an assignment without that capture: everything since the base).
          $before=V-Get $own 'source_files'
          if ($null -ne $before) {
            $now=(P-SourceCapture $s).entries
            $delta=@(@(@($before.Keys)+@($now.Keys)) | Select-Object -Unique | Where-Object { -not ($before.Contains($_) -and $now.Contains($_) -and $before[$_] -ceq $now[$_]) })
            P-Attribute $s $delta $authorFamily
          } else {
            P-Require ($null -ne $art.files) 'plan author changed source outside the plan: record-author it with a current snapshot artifact' 2
            P-Attribute $s (P-Written $s $null $art) $authorFamily
          }
        }
      }
      else { P-Attribute $s (P-Written $s (P-ManifestFiles (V-Get $own 'artifact')) $art) $authorFamily }
      $s.write_ownership=@(@($s.write_ownership) | Where-Object { $_ -cne $d.id -and $_ -cne ('pending:'+$d.taskId) })
      if ($own.Count -and $null -eq (V-Get $own 'dispatch_id')) { $s.active=$null }
    }
    'record-gate' {
      # A verify-gate run needs no worker: its sealed C4 results are the gate evidence. A failing run is recorded too,
      # so its identity G<r>-B1 exists for the user's gate-fix cap extension.
      P-Require ($s.step -cin @('phase','final-review','delivery') -and -not @($s.write_ownership).Count) 'script gate outside an unowned phase, final-review or delivery candidate'
      $verdict=V-Get $data 'verdict' 'GATE_OK';P-Require ($verdict -cin @('GATE_OK','GATE_FAIL')) 'unknown gate verdict'
      $art=P-Artifact (V-Get $data 'artifact') $s $true
      $proofs=if ($verdict -ceq 'GATE_OK') { P-EvidenceRecords (V-Get $data 'evidence') $art $s } else { P-FailureRecords (V-Get $data 'evidence') $art $s }
      $findings=@(if ($verdict -ceq 'GATE_FAIL') { P-GateFinding $s })
      $s.accepted=@(@($s.accepted)+,([ordered]@{role='gate';token=$verdict;round=$s.rounds.gate_fix;phase=$s.phase;step=$s.step;candidate=$art.candidate;artifact=$data.artifact
        findings=$findings;coverage=@{};family=$null;report=$null;dispatch_id=$null;evidence=@($proofs)}))
      if ($verdict -ceq 'GATE_OK') { $s.rounds.gate_fix=0 }
    }
    'reconcile-intent' {
      # A writer intent whose launch failed: positive termination of this Task's Dispatches in a fresh fleet, or the
      # saved failed launch receipt when no Dispatch was created; the tree must be the dispatch-time candidate.
      $a=$s.active
      P-Require ($null -ne $a -and $null -eq $a.dispatch_id -and @($s.write_ownership).Count -eq 1 -and @($s.write_ownership)[0] -ceq ('pending:'+$a.task_id)) 'no pending dispatch intent'
      if ($a.role -cin $PPlanAuthors) { P-PlanLane $s $a }  # its source edits are reverted or attributed first
      $s.write_ownership=@();$workers=P-Fleet $data $s;$rows=@($workers | Where-Object { (V-Get $_ 'taskId') -ceq $a.task_id })
      P-Require (-not @($rows | Where-Object { -not (P-Settled $_) }).Count) 'live or unverifiable prior writer' 2
      if (-not $rows.Count) {
        $failure=if ($null -ne (V-Get $data 'launch_failure')) { P-Record $data.launch_failure } else { @{} }
        P-Require ((V-Get $failure 'ok') -eq $false -and $a.task_id -cin @(V-Values $failure)) 'missing launch failure evidence' 2
      }
      if ($null -ne (V-Get $a 'candidate') -and $a.role -cnotin $PPlanAuthors) {
        P-Require ((P-Artifact (V-Get $data 'artifact') $s $true).candidate -ceq $a.candidate) 'the failed launch changed the candidate: bind it or record-author its writer'
      }
      $s.active=$null
    }
    'reopen-final' {
      # A defect found in delivery or by the completion hook goes back to the final review: delivery acceptance is
      # dropped; findings, authorship, commits and the final-review round count stay.
      P-Require ($s.step -cin @('delivery','completion') -and -not @(@($s.phase_commits) | Where-Object { $_.step -ceq 'completion' }).Count) 'reopen-final outside delivery or completion'
      [void](P-Fleet $data $s)
      # The reopening is a bound recovery item R<round>-REOPEN, citing the current capture, so that at the final-review cap
      # the user's extend-cap can name it (a completion-hook reformat leaves no failing gate to name).
      $art=P-Artifact (V-Get $data 'artifact') $s $true;$moved=$art.candidate -cne $s.final_source;$n=$s.rounds.final_review
      $item=[ordered]@{id=('R'+$n+'-REOPEN');kind='blocking';location='final-review';issue=('final review reopened'+$(if ($moved) { '; the source changed after the final checkpoint' } else { '' }))}
      $s.accepted=@(@($s.accepted)+,([ordered]@{role='reopen';token='REOPENED';round=$n;phase=$s.phase;step='final-review';candidate=$art.candidate;artifact=$data.artifact
        findings=@($item);coverage=@{};family=$null;report=$null;dispatch_id=$null;evidence=@()}))
      $s.step='final-review';$s.final_source=$null;$s.active=$null
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

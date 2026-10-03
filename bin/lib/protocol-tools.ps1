#Requires -Version 5.1
# C6 auxiliary CLI (native): a read-only state summary and the one-shot schema 1 -> 2 migration.
function P-Summary($cli) {
  # Print the compact facts of a saved state or proposal; never the raw JSON. Read-only.
  P-Require ($cli.Count -eq 2) 'usage: protocol-state summary STATE_OR_PROPOSAL_JSON'
  $data=P-Decode ([IO.File]::ReadAllText($cli[1],$VUtf8).TrimStart([char]0xfeff))
  $s=if ($data.Contains('action')) { $data.state } else { $data }
  P-Require ($s -is [Collections.IDictionary] -and $s.Contains('accepted')) 'not a C6 state or proposal' 2
  $name={ param($r) if ($r -is [Collections.IDictionary] -and $r.Contains('path') -and $r.path) { [IO.Path]::GetFileName([string]$r.path) } else { '-' } }
  $short={ param($sha) if ($sha) { ([string]$sha).Substring(0,[Math]::Min(7,([string]$sha).Length)) } else { '-' } }
  $get={ param($o,$k,$d='-') if ($o -is [Collections.IDictionary] -and $o.Contains($k) -and $null -ne $o[$k]) { $o[$k] } else { $d } }
  $rows=New-Object 'Collections.Generic.List[string]'
  if ($data.Contains('action')) { $rows.Add('proposal: action='+$data.action) }
  $rows.Add(('schema={0} mode={1} step={2} phase={3} barrier={4} base={5} run={6}' -f (& $get $s 'schema_version'),(& $get $s 'mode'),(& $get $s 'step'),(& $get $s 'phase'),(& $get $s 'barrier'),(& $short (& $get $s 'base' $null)),(& $get $s 'orca_run')))
  $a=& $get $s 'active' $null
  $rows.Add('active: '+$(if ($a -isnot [Collections.IDictionary]) { 'none' } else { 'role={0} round={1} task={2} dispatch={3} fix={4} model={5}' -f (& $get $a 'role'),(& $get $a 'round'),(& $get $a 'task_id'),(& $get $a 'dispatch_id'),(& $get $a 'fix' $false),(& $get $a 'model') }))
  $rounds=@();$ext=@(& $get $s 'cap_extensions' @())
  foreach ($k in 'plan_review','fused_review','final_review','gate_fix') { $rounds+=,('{0}={1}/{2}' -f $k,(& $get (& $get $s 'rounds' @{}) $k),($PCaps[$k]+@($ext | Where-Object { $_.group -ceq $k -and (P-Eq $_.phase $s.phase) }).Count)) }
  $rows.Add('rounds: '+($rounds -join ' '));$rows.Add('write_ownership: ['+(@(& $get $s 'write_ownership' @()) -join ', ')+']')
  $accepted=@($s.accepted);$rows.Add('accepted ('+$accepted.Count+'):')
  foreach ($r in @($accepted | Select-Object -Last 12)) {
    $round=if ($r.Contains('round')) { $r.round } else { & $get (& $get $r 'binding' @{}) 'round' };$where=if ($r.Contains('candidate')) { & $short $r.candidate } else { & $name (& $get $r 'artifact' $null) }
    $ids=@(@(& $get $r 'findings' @()) | ForEach-Object { $_.id });$rows.Add(('  {0} {1} r{2} {3} {4} findings={5}' -f (& $get $r 'role'),(& $get $r 'token'),$round,(& $get $r 'step'),$where,$(if ($ids.Count) { $ids -join ',' } else { '-' })))
  }
  $commits=@(& $get $s 'phase_commits' @());$rows.Add('phase_commits: '+$(if ($commits.Count) { @($commits | ForEach-Object { [string](& $get $_ 'step' '-')+'/'+[string](& $get $_ 'phase' 'None')+' '+(& $short (& $get $_ 'sha' $null)) }) -join ', ' } else { '-' }))
  $waivers=@(& $get $s 'independence_waivers' @())
  $rows.Add(('final_source: {0}  cap_extensions: {1}  independence_waivers: {2}' -f (& $short (& $get $s 'final_source' $null)),$ext.Count,$(if ($waivers.Count) { @($waivers | ForEach-Object { $_.step+'/'+[string]$_.phase+' '+(@($_.files) -join ',')+' -> '+$_.reviewer_family }) -join '; ' } else { '-' })))
  $rows.Add(('processed_messages={0} used_fleet_ids={1}' -f @(& $get $s 'processed_messages' @()).Count,@(& $get $s 'used_fleet_ids' @()).Count))
  $ledger=& $get $s 'ledger_path' $null;$rows.Add(('plan={0} ledger={1} workspace={2}' -f (& $name (& $get $s 'plan' $null)),$(if ($ledger) { [IO.Path]::GetFileName($ledger) } else { '-' }),(& $get $s 'workspace')))
  [Console]::WriteLine(($rows -join "`n"));exit 0
}
function P-Migrate($cli) {
  # Read a schema 1 state once: keep the current phase's accepted entries, commits, records, rounds and message ids.
  P-Require ($cli.Count -eq 3) 'usage: protocol-state migrate STATE_V1_JSON OUT_JSON'
  $old=P-Decode ([IO.File]::ReadAllText($cli[1],$VUtf8).TrimStart([char]0xfeff));if ($old.Contains('action')) { $old=$old.state }
  P-Require ($old.schema_version -eq 1) 'not a schema 1 state' 2
  $out=$cli[2];P-Require ([IO.Path]::IsPathRooted($out) -and [IO.Directory]::Exists([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($out))) -and -not [IO.File]::Exists($out) -and -not [IO.Directory]::Exists($out)) 'migration output must be a new absolute file' 2
  $step=if ($old.step -ceq 'bootstrap') { 'plan' } else { $old.step }
  # The live plan may have moved by bookkeeping lines since the v1 state was saved: adopt its current bytes.
  $plan=if ($old.plan) { $live=[IO.File]::ReadAllBytes($old.plan.path);[ordered]@{path=$old.plan.path;sha256=(V-Hash $live);structure=(P-PlanRead ($VUtf8.GetString($live).TrimStart([char]0xfeff).Replace("`r`n","`n"))).shape} } elseif ($old.mode -ceq 'plan') { [ordered]@{path=(P-Record $old.authorization).plan_path;sha256=$null;structure=$null} } else { $null }
  $s=[ordered]@{schema_version=2;mode=$old.mode;plan=$plan;ledger_path=(V-Get (V-Get $old 'ledger' @{}) 'path');step=$step;accepted=@();phase_commits=@();final_source=$null
    processed_messages=@($old.processed.messages);used_fleet_ids=(P-List $old 'used_fleet_ids');cap_extensions=(P-List $old 'cap_extensions');independence_waivers=(P-List $old 'independence_waivers');barrier=$null}
  foreach ($k in 'orca_run','plan_base','phase','base','worktree','worktree_id','workspace','active','rounds','provenance','write_ownership') { $s[$k]=$old[$k] }
  if ($s.active -is [Collections.IDictionary]) { $s.active.Remove('format_corrected') }
  $entry={ param($art,$fields) $e=[ordered]@{round=0;findings=@();coverage=@{};family=$null;report=$null;dispatch_id=$null;evidence=@();phase=$old.phase;step=$step;candidate=(P-Artifact $art $s).candidate;artifact=$art}
    foreach ($k in $fields.Keys) { $e[$k]=$fields[$k] };$e }
  foreach ($r in @($old.accepted)) {
    if ($r.step -cne $old.step -or -not (P-Eq $r.binding.phase $old.phase) -or $r.artifact.kind -ceq 'request') { continue }
    $s.accepted+=,(& $entry $r.artifact @{role=$r.role;token=$r.token;findings=@($r.findings);coverage=$r.coverage;family=$r.family;report=$r.report;round=$r.binding.round;dispatch_id=$r.binding.dispatch_id;evidence=(P-List $r 'evidence')})
  }
  foreach ($g in (P-List $old 'script_gates')) { if ($g.step -ceq $old.step) { $s.accepted+=,(& $entry $g.artifact @{role='gate';token='GATE_OK';evidence=@($g.evidence)}) } }
  $commits=@(foreach ($c in @($old.phase_commits)) { ,@($c,$(if ($old.mode -ceq 'quickfix') { 'quickfix' } elseif ($null -eq $c.phase) { 'plan' } else { 'phase' })) })
  $final=V-Get $old 'final' @{};if ($final -is [Collections.IDictionary] -and $final.Contains('completion')) { $commits+=,@($final.completion,'completion') }
  foreach ($pair in $commits) { $c=$pair[0];$s.phase_commits+=,([ordered]@{phase=(V-Get $c 'phase' $old.phase);step=$pair[1];sha=$c.sha;base=$c.base;candidate=(P-Artifact $c.artifact $s).candidate}) }
  if ($old.step -cin @('delivery','completion') -and $final -is [Collections.IDictionary] -and (P-List $final 'review').Count) { $s.final_source=(P-Artifact @($final.review)[0].artifact $s).candidate }
  V-Save $out $s
  [Console]::WriteLine('VALID');[Console]::WriteLine((V-Json @{out=$out;step=$step;accepted=@($s.accepted).Count;phase_commits=@($s.phase_commits).Count}));exit 0
}

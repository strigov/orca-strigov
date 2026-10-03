#Requires -Version 5.1
# C8 native coordinator binding/guard; the same C6 validator and shared fixtures.
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'protocol-state.ps1')
$CPlugin=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
function C-Require($ok,[string]$why) { if (-not $ok) { throw $why } }
function C-Safe([string]$path) {
  C-Require ([IO.Path]::IsPathRooted($path)) 'absolute path required'
  $p=[IO.Path]::GetFullPath($path);V-Safe $p;return $p
}
function C-Within([string]$path,[string]$parent) {
  return $path.StartsWith($parent.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)
}
function C-Root([string]$cwd) {
  $p=C-Safe $cwd;C-Require ([IO.Directory]::Exists($p)) 'missing worktree'
  return C-Safe (V-GitText $p @('rev-parse','--show-toplevel'))
}
function C-Path([string]$root,[string]$sid,[string]$client='codex') {
  C-Require ($sid -cmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$') 'invalid session identity'
  C-Require ($client -cin @('codex','claude')) 'unsupported coordinator host'
  $directory=Join-Path $root '.superpowers/sdd/.sessions'
  if ($client -ceq 'claude') {$directory=Join-Path $directory 'claude'}
  return C-Safe (Join-Path $directory ($sid+'.json'))
}
function C-Load([string]$path,[string]$root,[string]$sid,[string]$client='codex') {
  $b=P-Decode ([IO.File]::ReadAllText($path,$VUtf8))
  C-Require ($b.schema_version -eq 1 -and $b.session_id -ceq $sid -and $b.worktree -eq $root -and $b.role -ceq 'coordinator') 'session binding mismatch'
  C-Require ($b.status -cin @('active','held')) 'invalid session status'
  $savedClient=if ($b.Contains('host')) {$b.host} else {'codex'}
  C-Require ($savedClient -ceq $client) 'coordinator host mismatch';return $b
}
function C-ActivePending($s) {
  # C6 clears `active` when it accepts that Dispatch's report.
  return [bool]$s.active
}
function C-Proposal($b) {
  C-Require ($null -ne $b.proposal) 'no C6 checkpoint: bootstrap or restore the pending stage'
  # C6 recomputes the barrier for every action, including heartbeats and duplicates.
  $proposal=P-Record $b.proposal;$validated=P-Validate $proposal;$s=$validated.state
  C-Require ($s.worktree -eq $b.worktree -and $s.workspace -eq $b.workspace) 'C6 workspace differs from binding'
  C-Require (-not $b.orca_run -or $s.orca_run -ceq $b.orca_run) 'C6 Run differs from binding'
  $complete=($s.barrier -ceq 'complete' -and -not (C-ActivePending $s) -and -not @($s.write_ownership).Count -and
    (($s.mode -ceq 'quickfix' -and $proposal.action -ceq 'confirm-commit') -or ($s.mode -ceq 'plan' -and $proposal.action -ceq 'complete')))
  return @{state=$s;complete=$complete}
}
function C-Progress($s) {
  return @{run=$s.orca_run;phase=$s.phase;step=$s.step;barrier=$s.barrier;active=$s.active;
    commit=$(if (@($s.phase_commits).Count) {@($s.phase_commits)[-1].sha} else {$null});accepted=@(@($s.accepted) | ForEach-Object {,@($_.role,$_.token,$_.round,$_.candidate)})}
}
function C-Operate([string]$action,$request) {
  $root=C-Root $request.worktree;C-Require ($root -eq (C-Safe $request.worktree)) 'bind the actual worktree root'
  $client=if ($request.Contains('host')) {$request.host} else {'codex'}
  C-Require ($client -cin @('codex','claude')) 'unsupported coordinator host'
  $expected=if ($client -ceq 'codex') {$env:CODEX_THREAD_ID} else {$null}
  $sid=if ($request.session_id) {$request.session_id} else {$expected}
  C-Require (-not $expected -or $sid -ceq $expected) 'cannot bind another Codex session'
  C-Require ($env:ORCA_STRIGOV_WORKER -cne '1') 'workers cannot become coordinators'
  $path=C-Path $root $sid $client
  if ($action -ceq 'bind') {
    $workspace=C-Safe $request.workspace
    C-Require ([IO.Directory]::Exists($workspace) -and (C-Within $workspace (Join-Path $root '.superpowers/sdd')) -and $workspace -notmatch '[\\/]\.sessions([\\/]|$)') 'use an existing plan workspace'
    C-Require ($request.objective -is [string] -and $request.objective.Trim()) 'objective required'
    if ([IO.File]::Exists($path)) {
      $b=C-Load $path $root $sid $client
      C-Require ($b.objective -ceq $request.objective -and $b.workspace -eq $workspace) 'session already bound; reconcile it instead of replacing the objective'
      return $b
    }
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
    $b=@{schema_version=1;role='coordinator';session_id=$sid;host=$client;worktree=$root;workspace=$workspace;objective=$request.objective;
      status='active';orca_run=$null;proposal=$null;progress=$null;stop_attempts=0;hold=$null;turn_open=($client -ceq 'claude')}
  } else {
    C-Require ([IO.File]::Exists($path)) 'bind this coordinator before changing its state'
    $b=C-Load $path $root $sid $client
    switch -CaseSensitive ($action) {
      'status' {return $b}
      'checkpoint' {
        C-Require (C-Within (C-Safe $request.proposal.path) (C-Safe $b.workspace)) 'checkpoint proposal must be in this plan workspace'
        $candidate=P-Decode (V-Json $b);$candidate.proposal=$request.proposal;$s=(C-Proposal $candidate).state
        $mark=C-Progress $s;if (-not (P-Eq $mark $b.progress)) {$b.stop_attempts=0}
        $b.proposal=$request.proposal;$b.progress=$mark;$b.orca_run=$s.orca_run
        $b['bookkeeping']=@(foreach ($p in @((V-Get $s.plan 'path'),$s.ledger_path)) {if ($p) {C-Safe $p}})
      }
      'hold' {
        C-Require ($request.kind -cin @('user_pause','needs_authority','product_decision','blocked','status_only') -and $request.reason -is [string] -and $request.reason.Trim()) 'hold needs a typed reason'
        C-Require ($null -ne $request.evidence) 'hold needs a hashed user-request or blocker record'
        [void](P-Ref $request.evidence)
        if ($request.kind -ceq 'status_only' -and $b.status -ceq 'held' -and $b.hold.kind -cne 'status_only') {return $b}
        $b.status='held';$b.hold=@{kind=$request.kind;reason=$request.reason;evidence=$request.evidence}
      }
      'resume' {$b.status='active';$b.hold=$null;$b.stop_attempts=0}
      default {throw 'unknown coordinator-session action'}
    }
  }
  V-Save $path $b;return $b
}
function C-Context([string]$event,[string]$message) {return @{hookSpecificOutput=@{hookEventName=$event;additionalContext=$message}}}
function C-EditAllowed($payload,$b) {
  if ($payload.tool_name -cnotin @('apply_patch','Edit','Write','NotebookEdit')) {return $true}
  $inputValue=$payload.tool_input;$paths=@();$patch=$inputValue
  if ($inputValue -is [Collections.IDictionary]) {
    if ($inputValue.file_path) {$paths+=,$inputValue.file_path} elseif ($inputValue.path) {$paths+=,$inputValue.path}
    $patch=if ($inputValue.Contains('command')) {$inputValue.command} elseif ($inputValue.Contains('patch')) {$inputValue.patch} else {$inputValue.input}
  }
  if ($patch -is [string]) {foreach ($m in [regex]::Matches($patch,'(?m)^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$')) {$paths+=,$m.Groups[1].Value}}
  if (-not $paths.Count) {return $false}
  $allowed=@(foreach ($p in $b.bookkeeping) {C-Safe $p})
  foreach ($name in $paths) {
    $target=if ([IO.Path]::IsPathRooted($name)) {C-Safe $name} else {C-Safe (Join-Path $payload.cwd $name)}
    if (-not (C-Within $target (C-Safe $b.workspace)) -and $target -notin $allowed) {return $false}
  }
  return $true
}
function C-Hook($payload,[string]$client='codex') {
  C-Require ($client -cin @('codex','claude')) 'unsupported coordinator host'
  $event=$payload.hook_event_name
  if ($env:ORCA_STRIGOV_WORKER -ceq '1' -or $payload.agent_id -or $event -cin @('SubagentStart','SubagentStop')) {return @{}}
  $sid=$payload.session_id;if ($sid -isnot [string] -or $sid -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$') {return @{}}
  try {$root=C-Root $payload.cwd} catch {return @{}}
  $path=C-Path $root $sid $client
  if (-not [IO.File]::Exists($path)) {
    if ($event -cin @('SessionStart','UserPromptSubmit') -and $env:ORCA_TERMINAL_HANDLE) {
      return C-Context $event ('Orca Strigov: a live Task/Dispatch preamble means worker, not coordinator. Otherwise implementation requests load '+(Join-Path $CPlugin 'skills/orca-dev/SKILL.md')+' and bind this session before source work. No existing Run is required. Standalone plugin maintenance and reviews remain direct. Host: '+$client+'. Session ID: '+$sid)
    }
    return @{}
  }
  $b=C-Load $path $root $sid $client
  $message='[orca-strigov] This session is the coordinator only; delegate source research, code, tests and reviews. Restore '+$path+'. Read '+(Join-Path $CPlugin 'skills/orca-dev/SKILL.md')+'. Objective: '+$b.objective+'. Continue the pending authorized stage; a status summary is not completion.'
  if ($event -ceq 'Interrupt' -and $client -ceq 'codex') {$b.status='held';$b.hold=@{kind='user_pause';reason='User interrupted this turn'};V-Save $path $b;return @{}}
  if ($event -cin @('SessionStart','UserPromptSubmit')) {
    if ($event -ceq 'UserPromptSubmit') {
      $promptHash=V-Hash $VUtf8.GetBytes([string]$payload.prompt)
      if ($promptHash -cne $b.continuation_sha256) {
        if ($client -ceq 'claude' -and $b.turn_open -and $b.status -ceq 'active') {
          $b.status='held';$b.hold=@{kind='unreconciled_turn';reason="Previous Claude turn has no verified Stop. Reconcile the user's latest intent before explicit resume."}
        }
        $b.stop_attempts=0
        if ($b.hold -and $b.hold.kind -ceq 'status_only') {$b.status='active';$b.hold=$null}
      }
      if ($client -ceq 'claude') {$b['turn_open']=$true}
      V-Save $path $b
    }
    if ($b.hold) {$message+=' Held incomplete: '+$b.hold.reason+'. Resume only when the user resolves it.'}
    return C-Context $event $message
  }
  if ($event -ceq 'PreToolUse') {
    if (-not (C-EditAllowed $payload $b)) {return @{hookSpecificOutput=@{hookEventName=$event;permissionDecision='deny';permissionDecisionReason='Coordinator cannot edit source/tests. Dispatch a worker; only bound plan metadata, ledger and plan-workspace artifacts are allowed.'}}}
    return C-Context $event 'Coordinator-only: no source research, edits or tests; use workers. Bookkeeping follows the bound orca-dev protocol.'
  }
  if ($event -cne 'Stop') {return @{}}
  if ($b.status -ceq 'held') {
    if ($b.hold.evidence) {[void](P-Ref $b.hold.evidence)}
    if ($client -ceq 'claude') {$b['turn_open']=$false;V-Save $path $b}
    return @{systemMessage=('Orca objective remains incomplete: '+$b.hold.reason)}
  }
  try {
    $check=C-Proposal $b;if ($check.complete) {
      if ($client -ceq 'claude') {$b['turn_open']=$false;V-Save $path $b}
      return @{}
    }
    $pending=if (C-ActivePending $check.state) {'reconcile the existing active Dispatch and wait'} else {$check.state.barrier}
    if ($pending -ceq 'complete') {$pending='capture a fresh C6 completion proposal; a resume-only checkpoint does not authorize final Stop'}
  } catch {$pending='restore valid C6 evidence: '+$_.Exception.Message}
  $b.stop_attempts++
  if ($b.stop_attempts -gt 3) {
    $b.status='held';$b.hold=@{kind='no_progress';reason=('Repeated premature stop without protocol progress: '+$pending)}
    $reason='The objective is NOT complete. Repeated continuation attempts made no protocol progress. Report the exact pending barrier and ask for the missing intervention; do not claim success, cancel workers or launch duplicates. '+$pending
  } else {
    $reason=$message+' Pending: '+$pending+'. Execute the next permitted action now. If genuinely blocked or answering a status-only request, record an evidenced hold.'
  }
  $b['continuation_sha256']=V-Hash $VUtf8.GetBytes($reason);V-Save $path $b
  return @{decision='block';reason=$reason}
}

$payload=$null
$isHook=($args.Count -gt 0 -and $args[0] -ceq 'hook')
try {
  if ($isHook) {
    $payload=P-Decode ([Console]::In.ReadToEnd())
    C-Require ($args.Count -eq 1 -or ($args.Count -eq 3 -and $args[1] -ceq '--host' -and $args[2] -cin @('codex','claude'))) 'usage: hook [--host codex|claude]'
    $client=if ($args.Count -eq 3) {$args[2]} else {'codex'}
    $result=C-Hook $payload $client
  }
  else {
    C-Require ($args.Count -eq 2) 'usage: coordinator-session bind|checkpoint|hold|resume|status REQUEST_JSON; or hook'
    $result=C-Operate $args[0] (P-Decode ([IO.File]::ReadAllText($args[1],$VUtf8)))
  }
  [Console]::WriteLine((V-Json $result));exit 0
} catch {
  if ($isHook) {
    $message='Orca coordinator guard could not verify state: '+$_.Exception.Message
    if ($payload.hook_event_name -ceq 'Stop') {$result=@{decision='block';reason=($message+'. Recover the binding or report the blocker; do not claim completion.')}}
    elseif ($payload.hook_event_name -ceq 'PreToolUse') {$result=@{hookSpecificOutput=@{hookEventName='PreToolUse';permissionDecision='deny';permissionDecisionReason=$message}}}
    else {$result=@{systemMessage=$message}}
    [Console]::WriteLine((V-Json $result));exit 0
  }
  [Console]::WriteLine((V-Json @{error=$_.Exception.Message}));exit 2
}

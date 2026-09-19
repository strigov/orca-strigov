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
function C-Path([string]$root,[string]$sid) {
  C-Require ($sid -cmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$') 'invalid session identity'
  return C-Safe (Join-Path $root ('.superpowers/sdd/.sessions/'+$sid+'.json'))
}
function C-Load([string]$path,[string]$root,[string]$sid) {
  $b=P-Decode ([IO.File]::ReadAllText($path,$VUtf8))
  C-Require ($b.schema_version -eq 1 -and $b.session_id -ceq $sid -and $b.worktree -eq $root -and $b.role -ceq 'coordinator') 'session binding mismatch'
  C-Require ($b.status -cin @('active','held')) 'invalid session status';return $b
}
function C-ActivePending($s) {
  if (-not $s.active) {return $false}
  if (-not $s.active.dispatch_id) {return $true}
  $history=if ($s.Contains('report_history')) {$s.report_history} else {$s.accepted}
  return -not @($history | Where-Object {$_.binding.dispatch_id -ceq $s.active.dispatch_id}).Count
}
function C-Proposal($b) {
  C-Require ($null -ne $b.proposal) 'no C6 checkpoint: bootstrap or restore the pending stage'
  $proposal=P-Record $b.proposal;$validated=P-Validate $proposal;$s=$validated.state
  if ($validated.decision -cne 'accepted') {$s.barrier=P-Barrier $s (P-Plan $s)}
  C-Require ($s.worktree -eq $b.worktree -and $s.workspace -eq $b.workspace) 'C6 workspace differs from binding'
  C-Require (-not $b.orca_run -or $s.orca_run -ceq $b.orca_run) 'C6 Run differs from binding'
  $complete=($s.barrier -ceq 'complete' -and -not (C-ActivePending $s) -and -not $s.write_ownership.Count -and -not $s.open_ledger_ids.Count -and
    (($s.mode -ceq 'quickfix' -and $proposal.action -ceq 'confirm-commit') -or ($s.mode -ceq 'plan' -and $proposal.action -ceq 'complete')))
  return @{state=$s;complete=$complete}
}
function C-Progress($s) {
  return @{run=$s.orca_run;phase=$s.phase;step=$s.step;barrier=$s.barrier;active=$s.active;
    commit=$s.commit_barrier.confirmed_sha;accepted=@($s.accepted | ForEach-Object {$_.report.sha256});open_ledger_ids=$s.open_ledger_ids}
}
function C-Operate([string]$action,$request) {
  $root=C-Root $request.worktree;C-Require ($root -eq (C-Safe $request.worktree)) 'bind the actual worktree root'
  $sid=if ($request.session_id) {$request.session_id} else {$env:CODEX_THREAD_ID}
  C-Require (-not $env:CODEX_THREAD_ID -or $sid -ceq $env:CODEX_THREAD_ID) 'cannot bind another Codex session'
  C-Require ($env:ORCA_STRIGOV_WORKER -cne '1') 'workers cannot become coordinators'
  $path=C-Path $root $sid
  if ($action -ceq 'bind') {
    $workspace=C-Safe $request.workspace
    C-Require ([IO.Directory]::Exists($workspace) -and (C-Within $workspace (Join-Path $root '.superpowers/sdd')) -and $workspace -notmatch '[\\/]\.sessions([\\/]|$)') 'use an existing plan workspace'
    C-Require ($request.objective -is [string] -and $request.objective.Trim()) 'objective required'
    if ([IO.File]::Exists($path)) {
      $b=C-Load $path $root $sid
      C-Require ($b.objective -ceq $request.objective -and $b.workspace -eq $workspace) 'session already bound; reconcile it instead of replacing the objective'
      return $b
    }
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
    $b=@{schema_version=1;role='coordinator';session_id=$sid;worktree=$root;workspace=$workspace;objective=$request.objective;
      status='active';orca_run=$null;proposal=$null;progress=$null;stop_attempts=0;hold=$null}
  } else {
    C-Require ([IO.File]::Exists($path)) 'bind this coordinator before changing its state'
    $b=C-Load $path $root $sid
    switch -CaseSensitive ($action) {
      'status' {return $b}
      'checkpoint' {
        C-Require (C-Within (C-Safe $request.proposal.path) (C-Safe $b.workspace)) 'checkpoint proposal must be in this plan workspace'
        $candidate=P-Decode (V-Json $b);$candidate.proposal=$request.proposal;$s=(C-Proposal $candidate).state
        $mark=C-Progress $s;if (-not (P-Eq $mark $b.progress)) {$b.stop_attempts=0}
        $b.proposal=$request.proposal;$b.progress=$mark;$b.orca_run=$s.orca_run
        $b['bookkeeping']=@(foreach ($key in 'plan','ledger') {if ($s[$key]) {C-Safe $s[$key].path}})
      }
      'hold' {
        C-Require ($request.kind -cin @('user_pause','needs_authority','product_decision','blocked','status_only') -and $request.reason -is [string] -and $request.reason.Trim()) 'hold needs a typed reason'
        C-Require ($null -ne $request.evidence) 'hold needs a hashed user-request or blocker record'
        [void](P-Ref $request.evidence);$b.status='held';$b.hold=@{kind=$request.kind;reason=$request.reason;evidence=$request.evidence}
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
function C-Hook($payload) {
  $event=$payload.hook_event_name
  if ($env:ORCA_STRIGOV_WORKER -ceq '1' -or $payload.agent_id -or $event -cin @('SubagentStart','SubagentStop')) {return @{}}
  $sid=$payload.session_id;if ($sid -isnot [string] -or $sid -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$') {return @{}}
  try {$root=C-Root $payload.cwd} catch {return @{}}
  $path=C-Path $root $sid
  if (-not [IO.File]::Exists($path)) {
    if ($event -cin @('SessionStart','UserPromptSubmit') -and $env:ORCA_TERMINAL_HANDLE) {
      return C-Context $event ('Orca Strigov: a live Task/Dispatch preamble means worker, not coordinator. Otherwise implementation requests load '+(Join-Path $CPlugin 'skills/orca-dev/SKILL.md')+' and bind this session before source work. No existing Run is required. Standalone plugin maintenance and reviews remain direct. Session ID: '+$sid)
    }
    return @{}
  }
  $b=C-Load $path $root $sid
  $message='[orca-strigov] This session is the coordinator only; delegate source research, code, tests and reviews. Restore '+$path+'. Read '+(Join-Path $CPlugin 'skills/orca-dev/SKILL.md')+'. Objective: '+$b.objective+'. Continue the pending authorized stage; a status summary is not completion.'
  if ($event -ceq 'Interrupt') {$b.status='held';$b.hold=@{kind='user_pause';reason='User interrupted this turn'};V-Save $path $b;return @{}}
  if ($event -cin @('SessionStart','UserPromptSubmit')) {
    if ($event -ceq 'UserPromptSubmit') {
      $promptHash=V-Hash $VUtf8.GetBytes([string]$payload.prompt)
      if ($promptHash -cne $b.continuation_sha256) {
        $b.stop_attempts=0
        if ($b.hold -and $b.hold.kind -ceq 'status_only') {$b.status='active';$b.hold=$null}
      }
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
    return @{systemMessage=('Orca objective remains incomplete: '+$b.hold.reason)}
  }
  try {
    $check=C-Proposal $b;if ($check.complete) {return @{}}
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
try {
  if ($args.Count -eq 1 -and $args[0] -ceq 'hook') {$payload=P-Decode ([Console]::In.ReadToEnd());$result=C-Hook $payload}
  else {
    C-Require ($args.Count -eq 2) 'usage: coordinator-session bind|checkpoint|hold|resume|status REQUEST_JSON; or hook'
    $result=C-Operate $args[0] (P-Decode ([IO.File]::ReadAllText($args[1],$VUtf8)))
  }
  [Console]::WriteLine((V-Json $result));exit 0
} catch {
  if ($args.Count -eq 1 -and $args[0] -ceq 'hook') {
    $message='Orca coordinator guard could not verify state: '+$_.Exception.Message
    if ($payload.hook_event_name -ceq 'Stop') {$result=@{decision='block';reason=($message+'. Recover the binding or report the blocker; do not claim completion.')}}
    elseif ($payload.hook_event_name -ceq 'PreToolUse') {$result=@{hookSpecificOutput=@{hookEventName='PreToolUse';permissionDecision='deny';permissionDecisionReason=$message}}}
    else {$result=@{systemMessage=$message}}
    [Console]::WriteLine((V-Json $result));exit 0
  }
  [Console]::WriteLine((V-Json @{error=$_.Exception.Message}));exit 2
}

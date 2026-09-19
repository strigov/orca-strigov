"""C8: session-scoped coordinator continuity, backed by C6 rather than prose.

Not a security sandbox: local state is coordinator-owned, as are C6 receipts.
Never dispatches, cancels, commits, consumes messages or changes user settings.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import protocol_state as protocol
import verification as v
from posix_runtime import artifact_path

PLUGIN = Path(__file__).resolve().parents[2]
HOLD_KINDS = {"user_pause", "needs_authority", "product_decision", "blocked", "status_only"}
SID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
MAX_STOPS = 3


def require(ok, message):
    if not ok:
        raise ValueError(message)


def safe(path):
    require(isinstance(path, str) and Path(path).is_absolute(), "absolute path required")
    result = artifact_path(path)
    require(not any(p.is_symlink() for p in (result, *result.parents)), "linked session path")
    return result


def within(path, parent):
    return path != parent and parent in path.parents


def session_path(root, sid, host="codex"):
    require(isinstance(sid, str) and SID.fullmatch(sid), "invalid session identity")
    require(host in ("codex", "claude"), "unsupported coordinator host")
    directory = root / ".superpowers" / "sdd" / ".sessions"
    if host == "claude":
        directory = directory / "claude"
    return safe(str(directory / (sid + ".json")))


def root_for(cwd):
    p = safe(cwd)
    require(p.is_dir(), "missing worktree")
    result = subprocess.run(["git", "-C", str(p), "rev-parse", "--show-toplevel"],
                            capture_output=True, timeout=5, check=False)
    require(result.returncode == 0, "development coordinator requires a Git worktree")
    return safe(os.fsdecode(result.stdout).strip())


def load_session(path, root, sid, host="codex"):
    value = v.load(path)
    require(value.get("schema_version") == 1 and value.get("session_id") == sid
            and value.get("worktree") == str(root) and value.get("role") == "coordinator",
            "session binding mismatch")
    require(value.get("status") in ("active", "held"), "invalid session status")
    require(value.get("host", "codex") == host, "coordinator host mismatch")
    return value


def save(path, value):
    safe(str(path))
    v.save(path, value)


def active_pending(state):
    active = state["active"]
    if not active:
        return False
    dispatch = active.get("dispatch_id")
    return not dispatch or not any(r["binding"].get("dispatch_id") == dispatch
                                  for r in state.get("report_history", state["accepted"]))


def read_proposal(binding):
    ref = binding.get("proposal")
    require(ref is not None, "no C6 checkpoint: bootstrap or restore the pending stage")
    proposal = protocol.record(ref)
    state, decision = protocol.validate(proposal)
    # C6 deliberately returns early for heartbeats/duplicate deliveries. Those
    # receipts are valid checkpoints, but their previous barrier is not current.
    if decision != "accepted":
        state["barrier"] = protocol.barrier(state, protocol.plan_facts(state))
    require(state["worktree"] == binding["worktree"]
            and state["workspace"] == binding["workspace"], "C6 workspace differs from binding")
    require(not binding.get("orca_run") or state["orca_run"] == binding["orca_run"],
            "C6 Run differs from binding")
    complete = (state["barrier"] == "complete" and not active_pending(state)
                and not state["write_ownership"] and not state["open_ledger_ids"]
                and ((state["mode"] == "quickfix" and proposal["action"] == "confirm-commit")
                     or (state["mode"] == "plan" and proposal["action"] == "complete")))
    return state, complete


def progress(state):
    return dict(run=state["orca_run"], phase=state["phase"], step=state["step"],
                barrier=state["barrier"], active=state["active"],
                commit=state["commit_barrier"].get("confirmed_sha"),
                accepted=[r["report"]["sha256"] for r in state["accepted"]],
                open_ledger_ids=state["open_ledger_ids"])


def operate(action, request):
    root = root_for(request["worktree"])
    require(str(root) == str(safe(request["worktree"])), "bind the actual worktree root")
    host = request.get("host", "codex")
    require(host in ("codex", "claude"), "unsupported coordinator host")
    expected = os.environ.get("CODEX_THREAD_ID") if host == "codex" else None
    sid = request.get("session_id") or expected
    require(not expected or sid == expected, "cannot bind another Codex session")
    require(os.environ.get("ORCA_STRIGOV_WORKER") != "1", "workers cannot become coordinators")
    path = session_path(root, sid, host)
    if action == "bind":
        workspace = safe(request["workspace"])
        require(workspace.is_dir() and within(workspace, root / ".superpowers" / "sdd")
                and ".sessions" not in workspace.parts, "use an existing plan workspace")
        objective = request["objective"]
        require(isinstance(objective, str) and objective.strip(), "objective required")
        if path.exists():
            binding = load_session(path, root, sid, host)
            require(binding["objective"] == objective and binding["workspace"] == str(workspace),
                    "session already bound; reconcile it instead of replacing the objective")
            return binding
        path.parent.mkdir(parents=True, exist_ok=True)
        binding = dict(schema_version=1, role="coordinator", session_id=sid, host=host,
                       worktree=str(root), workspace=str(workspace), objective=objective,
                       status="active", orca_run=None, proposal=None, progress=None,
                       stop_attempts=0, hold=None, turn_open=(host == "claude"))
    else:
        require(path.is_file(), "bind this coordinator before changing its state")
        binding = load_session(path, root, sid, host)
        if action == "status":
            return binding
        if action == "checkpoint":
            proposal_ref = request["proposal"]
            require(within(safe(proposal_ref["path"]), safe(binding["workspace"])),
                    "checkpoint proposal must be in this plan workspace")
            candidate = dict(binding, proposal=proposal_ref)
            state, _ = read_proposal(candidate)
            mark = progress(state)
            if mark != binding["progress"]:
                binding["stop_attempts"] = 0
            binding.update(proposal=proposal_ref, progress=mark, orca_run=state["orca_run"],
                           bookkeeping=[str(safe(state[k]["path"])) for k in ("plan", "ledger")
                                        if state.get(k)])
        elif action == "hold":
            require(request.get("kind") in HOLD_KINDS and isinstance(request.get("reason"), str)
                    and request["reason"].strip(), "hold needs a typed reason")
            # Evidence is immutable audit context, not a source of new authority.
            evidence = request.get("evidence")
            require(evidence is not None, "hold needs a hashed user-request or blocker record")
            protocol.ref(evidence)
            if (request["kind"] == "status_only" and binding["status"] == "held"
                    and binding["hold"]["kind"] != "status_only"):
                # A persistent hold already allows an incomplete status answer.
                # Do not turn it into a one-prompt hold that clears implicitly.
                return binding
            binding.update(status="held", hold=dict(kind=request["kind"], reason=request["reason"],
                                                   evidence=evidence))
        elif action == "resume":
            binding.update(status="active", hold=None, stop_attempts=0)
        else:
            raise ValueError("unknown coordinator-session action")
    save(path, binding)
    return binding


def context(event, message):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def editing_allowed(payload, binding):
    tool = payload.get("tool_name", "")
    if tool not in ("apply_patch", "Edit", "Write", "NotebookEdit"):
        return True
    value = payload.get("tool_input", {})
    paths = []
    if isinstance(value, dict):
        direct = value.get("file_path") or value.get("path")
        if direct:
            paths.append(direct)
        patch = value.get("command", value.get("patch", value.get("input", "")))
    else:
        patch = value
    if isinstance(patch, str):
        paths.extend(re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M))
    if not paths:
        return False
    # Retain only paths admitted by a validated checkpoint. A stale plan hash
    # must not forbid the metadata repair needed to make the next checkpoint.
    allowed_files = [safe(p) for p in binding.get("bookkeeping", [])]
    for name in paths:
        target = safe(str(Path(payload["cwd"]) / name)) if not Path(name).is_absolute() else safe(name)
        if not within(target, safe(binding["workspace"])) and target not in allowed_files:
            return False
    return True


def hook(payload, host="codex"):
    require(host in ("codex", "claude"), "unsupported coordinator host")
    event = payload.get("hook_event_name")
    if os.environ.get("ORCA_STRIGOV_WORKER") == "1":
        return {}
    # Native subagent hooks are not coordinator hooks, even with a parent ID.
    if payload.get("agent_id") or event in ("SubagentStart", "SubagentStop"):
        return {}
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not SID.fullmatch(sid):
        return {}
    try:
        root = root_for(payload["cwd"])
    except (ValueError, OSError, subprocess.SubprocessError):
        return {}
    path = session_path(root, sid, host)
    if not path.exists():
        if event in ("SessionStart", "UserPromptSubmit") and os.environ.get("ORCA_TERMINAL_HANDLE"):
            return context(event, "Orca Strigov: a live Task/Dispatch preamble means worker, not coordinator. "
                           "Otherwise implementation requests load " + str(PLUGIN / "skills/orca-dev/SKILL.md")
                           + " and bind this session before source work. No existing Run is required. "
                           "Standalone plugin maintenance and reviews remain direct. Host: " + host
                           + ". Session ID: " + sid)
        return {}
    binding = load_session(path, root, sid, host)
    message = ("[orca-strigov] This session is the coordinator only; delegate source research, code, "
               "tests and reviews. Restore " + str(path) + ". Read "
               + str(PLUGIN / "skills/orca-dev/SKILL.md") + ". Objective: " + binding["objective"]
               + ". Continue the pending authorized stage; a status summary is not completion.")
    if event == "Interrupt" and host == "codex":
        binding.update(status="held", hold=dict(kind="user_pause", reason="User interrupted this turn"))
        save(path, binding)
        return {}
    if event in ("SessionStart", "UserPromptSubmit"):
        if event == "UserPromptSubmit":
            prompt_hash = hashlib.sha256(payload.get("prompt", "").encode("utf-8")).hexdigest()
            if prompt_hash != binding.get("continuation_sha256"):
                if host == "claude" and binding.get("turn_open") and binding["status"] == "active":
                    # Claude does not emit Stop on interruption. Do not invent an
                    # Interrupt receipt or automatically restart a lost turn.
                    binding.update(status="held", hold=dict(kind="unreconciled_turn",
                        reason="Previous Claude turn has no verified Stop. Reconcile the user's latest intent before explicit resume."))
                binding["stop_attempts"] = 0
                if (binding.get("hold") or {}).get("kind") == "status_only":
                    binding.update(status="active", hold=None)
            if host == "claude":
                binding["turn_open"] = True
            save(path, binding)
        if binding["hold"]:
            message += " Held incomplete: " + binding["hold"]["reason"] + ". Resume only when the user resolves it."
        return context(event, message)
    if event == "PreToolUse":
        if not editing_allowed(payload, binding):
            return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny",
                    "permissionDecisionReason": "Coordinator cannot edit source/tests. Dispatch a worker; "
                    "only bound plan metadata, ledger and plan-workspace artifacts are allowed."}}
        return context(event, "Coordinator-only: no source research, edits or tests; use workers. "
                       "Bookkeeping follows the bound orca-dev protocol.")
    if event != "Stop":
        return {}
    if binding["status"] == "held":
        if binding["hold"].get("evidence"):
            protocol.ref(binding["hold"]["evidence"])
        if host == "claude":
            binding["turn_open"] = False
            save(path, binding)
        return {"systemMessage": "Orca objective remains incomplete: " + binding["hold"]["reason"]}
    try:
        state, complete = read_proposal(binding)
        if complete:
            if host == "claude":
                binding["turn_open"] = False
                save(path, binding)
            return {}
        pending = "reconcile the existing active Dispatch and wait" if active_pending(state) else state["barrier"]
        if pending == "complete":
            pending = "capture a fresh C6 completion proposal; a resume-only checkpoint does not authorize final Stop"
    except (ValueError, OSError, KeyError, TypeError, protocol.Rejected, subprocess.SubprocessError) as exc:
        pending = "restore valid C6 evidence: " + str(exc)
    binding["stop_attempts"] += 1
    if binding["stop_attempts"] > MAX_STOPS:
        binding.update(status="held", hold=dict(kind="no_progress",
                       reason="Repeated premature stop without protocol progress: " + pending))
        reason = ("The objective is NOT complete. Repeated continuation attempts made no protocol progress. "
                  "Report the exact pending barrier and ask for the missing intervention; do not claim success, "
                  "cancel workers or launch duplicates. " + pending)
    else:
        reason = message + " Pending: " + pending + ". Execute the next permitted action now. "
        reason += "If genuinely blocked or answering a status-only request, record an evidenced hold."
    binding["continuation_sha256"] = hashlib.sha256(reason.encode("utf-8")).hexdigest()
    save(path, binding)
    return {"decision": "block", "reason": reason}


def main(args):
    payload = None
    is_hook = bool(args and args[0] == "hook")
    try:
        if is_hook:
            payload = json.load(sys.stdin)
            require(args in (["hook"], ["hook", "--host", "codex"], ["hook", "--host", "claude"]),
                    "usage: hook [--host codex|claude]")
            result = hook(payload, args[2] if len(args) == 3 else "codex")
        else:
            require(len(args) == 2, "usage: coordinator-session bind|checkpoint|hold|resume|status REQUEST_JSON; or hook")
            result = operate(args[0], v.load(args[1]))
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, protocol.Rejected, subprocess.SubprocessError) as exc:
        if is_hook:
            event = (payload or {}).get("hook_event_name")
            message = "Orca coordinator guard could not verify state: " + str(exc)
            if event == "Stop":
                print(json.dumps(dict(decision="block", reason=message + ". Recover the binding or report the blocker; do not claim completion.")))
            elif event == "PreToolUse":
                print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                    "permissionDecision": "deny", "permissionDecisionReason": message}}))
            else:
                print(json.dumps(dict(systemMessage=message)))
            return 0
        print(json.dumps(dict(error=str(exc))))
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

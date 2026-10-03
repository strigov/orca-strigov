"""C6 v2: check one coordinator transition against the current candidate.

Never dispatches, commits or changes lifecycle. History is not re-proven: the state is
coordinator-owned and each call checks its own transition plus three invariants:
(a) fleet_clear, (b) commit_check, (c) independent / plan_independent."""
import copy
import json
from pathlib import Path
import re
import sys

import verification as v
from posix_runtime import artifact_path
from protocol_facts import (Rejected, require, need, ref, record, line_json, REVIEW, WRITE, TOKENS, report_fields, plan_read,
                            plan_name, artifact, fresh, fleet_workers, authors, evidence_records, model_matches, actual_model,
                            family, known_families, observation, claude_model_evidence, antigravity_model_evidence)

CAPS = {"plan_review": 4, "fused_review": 4, "final_review": 2, "gate_fix": 2}
GOOD = {"plan-reviewer": ["APPROVED"], "gate": ["GATE_OK"], "review-primary": ["REVIEW_OK"], "review-control": ["REVIEW_OK"],
        "review-final": ["REVIEW_OK"], "quickfix": ["DONE", "DONE_WITH_CONCERNS"]}
WRITTEN = ["DONE", "DONE_WITH_CONCERNS", "PLAN_WRITTEN", "REVISED", "SYNTHESIS_DONE"]
READY = {"plan": ["plan-reviewer"], "quickfix": ["quickfix"], "phase": ["gate", "review-primary", "review-control"],
         "final-review": ["review-final"], "delivery": ["gate"], "completion": []}
DECISIONS = ["DEFER", "NIT", "REJECTED_BY_SCOPE", "ESCALATED_TO_HUMAN"]
KEYS = ("schema_version", "mode", "plan", "ledger_path", "orca_run", "plan_base", "phase", "base", "step", "worktree",
        "worktree_id", "workspace", "active", "rounds", "cap_extensions", "independence_waivers", "provenance", "accepted",
        "write_ownership", "phase_commits", "final_source", "processed_messages", "used_fleet_ids")


def cap(state, group):
    """Protocol cap plus the user's one-round extensions for this phase (each checked by extend-cap)."""
    return CAPS[group] + sum(1 for x in state["cap_extensions"] if x["group"] == group and x["phase"] == state["phase"])


def plan_facts(state):
    plan = state["plan"]
    if plan is None or plan["sha256"] is None: return []
    facts = plan_read(ref(plan))
    require(facts["shape"] == plan["structure"], "plan structure differs from state")
    require(facts["orca_run"] == state["orca_run"] and facts["plan_base"] == state["plan_base"], "plan/run/base mismatch")
    if state["phase"] is not None:
        phase = next((p for p in facts["phases"] if p["id"] == state["phase"]), None)
        require(phase is not None and phase.get("base") == state["base"], "phase/base mismatch")
    return facts["phases"]


def update_plan(data, state):
    """A fresh plan reference: any bytes in a plan author's report, otherwise only bookkeeping lines may move."""
    new, old = data.get("plan"), state["plan"]
    if new is None or (old is not None and (new["path"], new["sha256"]) == (old["path"], old["sha256"])): return
    require(old is not None and new["path"] == old["path"], "plan path differs from state")
    shape = plan_read(ref(new))["shape"]
    author = data["action"] == "accept-report" and (state["active"] or {}).get("role") in ("plan-writer", "plan-reviser")
    require(author or shape == old["structure"], "plan change outside the plan author/review path")
    state["plan"] = dict(path=new["path"], sha256=new["sha256"], structure=shape)


def ledger(data, state):
    """Coordinator bookkeeping, read only for the four decisions and check results, by finding id."""
    refspec = data.get("ledger")
    if refspec is None: return {}
    require(state["ledger_path"] in (None, refspec["path"]), "ledger path differs from state")
    state["ledger_path"] = refspec["path"]
    items = record(refspec)
    require(isinstance(items, list) and all(isinstance(x, dict) and isinstance(x.get("id"), str) for x in items) and
            len({x["id"] for x in items}) == len(items), "invalid ledger")
    return {x["id"]: x for x in items}


def fleet_clear(data, state):
    """Invariant (a): a fresh complete fleet shows no live or unverifiable writer in this worktree."""
    require(not any(x.startswith("pending:") for x in state["write_ownership"]), "unbound writer intent", 2)
    workers, receipt_ids = fleet_workers(data, state["used_fleet_ids"])
    ownership = []
    for worker in workers:
        p = worker.get("projection") or {}; workspace = p.get("workspace") or {}
        uncertain = (worker.get("terminalState") in ("release_pending", "release_unknown") or
                     (worker.get("resource") or {}).get("ownershipState") in ("user_owned", "external", "pre_existing"))
        if not uncertain and worker.get("dispatchStatus") in ("completed", "failed") and p.get("evidence", {}).get("durable") is True:
            continue  # A provably settled retained terminal is not a writer, even without a workspace.
        require(workspace.get("id") is not None, "unknown fleet workspace", 2)
        if workspace["id"] != state["worktree_id"]: continue
        if uncertain: raise Rejected("unresolved release/external ownership", 2)
        if worker.get("terminalState") == "released" and p.get("liveness", {}).get("verdict") == "exited": continue
        ownership.append(worker["dispatchId"])
    state["write_ownership"] = ownership
    require(not ownership, "live or unverifiable prior writer", 2)
    state["used_fleet_ids"] = state["used_fleet_ids"] + receipt_ids


def independent(art, coverage, reviewer, state):
    """Invariant (c): the reviewer family authored no covered file, unless the user waived it for this step."""
    m = art["manifest"]; writers = authors(art, state["provenance"])
    waived = {(p, w["reviewer_family"]) for w in state["independence_waivers"]
              if (w["step"], w["phase"]) == (state["step"], state["phase"]) for p in w["files"]}
    require(set(coverage.get("files", [])) <= {f["path"] for f in m["files"]}, "unknown coverage file")
    for name in coverage.get("files", []):
        require(writers.get(name), "unknown actual author: " + name, 2)
        require(reviewer not in writers[name] or (name, reviewer) in waived, "same-family review: " + name)
    require(set(coverage.get("parts", [])) <= {p["path"] for p in m["parts"]}, "unknown coverage part")
    contracts = {c["id"]: c for c in m["coverage"]["contracts"]}
    for c in coverage.get("contracts", []):
        require(c.get("id") in contracts, "unknown coverage contract")
        for side in ("producer", "consumer"):
            require(set(c.get(side, [])) <= set(contracts[c["id"]][side]), "unknown contract side")
            require(set(c.get(side, [])) <= set(coverage.get("files", [])), "contract side lacks file review")


def plan_independent(state, reviewer):
    require(state["provenance"], "unknown plan authors", 2)
    for author in state["provenance"]:
        require(family(record(author)["result"], author) != reviewer, "same-family plan review")


def latest(state, role, cand):
    rows = [i for i, r in enumerate(state["accepted"]) if r["role"] == role and r["candidate"] == cand]
    return rows[-1] if rows else None


def checked(item):
    """A cannot_verify item is checked by a sealed run-check result (seal intact) that exited 0; bytes are not compared."""
    path = item.get("check")
    try: result = v.load(path) if isinstance(path, str) and Path(path).is_absolute() else None
    except (OSError, ValueError): return False
    return isinstance(result, dict) and result.get("exit_code") == 0 and v.evidence_valid(result)


def unresolved(state, cand, decisions):
    """Resolved: a ledger decision; a cannot_verify check with exit 0; a later round of the role on cand omitting it."""
    out = []
    for i, r in enumerate(state["accepted"]):
        last = latest(state, r["role"], cand); later = state["accepted"][last] if last is not None and last > i else None
        for f in r["findings"]:
            item = decisions.get(f["id"], {})
            if item.get("decision") in DECISIONS or (f["kind"] == "cannot_verify" and checked(item)): continue
            if f["kind"] == "blocking" and later and later["round"] > r["round"] and f["id"] not in [x["id"] for x in later["findings"]]: continue
            out.append(f["id"])
    return out


def ready(state, cand, decisions):
    """The step's required roles have positive latest reports on cand, nothing is unresolved, reviews cover the package."""
    rows = []
    for role in READY[state["step"]]:
        i = latest(state, role, cand)
        require(i is not None, "required report is missing: " + role, 2)
        require(state["accepted"][i]["token"] in GOOD[role], "required report is not positive: " + role)
        rows.append(state["accepted"][i])
    still = unresolved(state, cand, decisions)
    require(not still, "unresolved findings: " + ", ".join(still))
    reviews = [r for r in rows if r["role"] in REVIEW and r["role"] != "plan-reviewer"]
    if reviews:
        m = record(reviews[0]["artifact"]); skip = {plan_name(state)}
        union = lambda key: {p for r in reviews for p in r["coverage"].get(key, [])}
        require({f["path"] for f in m["files"]} - skip <= union("files"), "incomplete file coverage", 2)
        require({p["path"] for p in m["parts"]} <= union("parts"), "incomplete part coverage", 2)
        for c in m["coverage"]["contracts"]:
            for side in ("producer", "consumer"):
                sides = {p for r in reviews for x in r["coverage"].get("contracts", []) if x["id"] == c["id"] for p in x.get(side, [])}
                require(set(c[side]) - skip <= sides, "incomplete contract " + c["id"] + ":" + side, 2)


def current(state):
    if state["step"] == "plan": return state["plan"]["sha256"]
    rows = [r for r in state["accepted"] if r["role"] not in ("diagnosis", "synthesizer")]
    if not rows or (rows[-1]["role"] in WRITE and rows[-1]["token"] not in WRITTEN): return None
    return rows[-1]["candidate"]


def committed(state):
    return [c for c in state["phase_commits"] if (c["step"], c["phase"]) == (state["step"], state["phase"])]


def barrier(state, phases, decisions):
    step = state["step"]
    if state["write_ownership"]: return "awaiting_writer"
    if committed(state):
        if step in ("quickfix", "completion"): return "complete"
        return "ready_next_phase" if state["phase"] != (phases[-1]["id"] if phases else None) else "awaiting_final_review"
    if step in ("final-review", "delivery", "completion"):
        return {"final-review": "awaiting_final_review", "delivery": "awaiting_delivery", "completion": "awaiting_completion_commit"}[step]
    cand = current(state)
    if cand is None: return "awaiting_plan_writer" if step == "plan" else "awaiting_implementation"
    try:
        ready(state, cand, decisions); return "awaiting_commit"
    except Rejected: pass
    rows = [latest(state, role, cand) for role in READY[step]]
    if rows[0] is None: return {"plan": "awaiting_plan_review", "phase": "awaiting_gate"}.get(step, "awaiting_implementation")
    if any(i is not None and state["accepted"][i]["token"] not in GOOD[state["accepted"][i]["role"]] for i in rows): return "awaiting_resolution"
    return "awaiting_review" if None in rows or not unresolved(state, cand, decisions) else "awaiting_resolution"


def is_ancestor(root, a, b):
    try: v.git(root, "merge-base", "--is-ancestor", a, b); return True
    except v.subprocess.CalledProcessError: return False


def commit_check(state, fact, cand, art):
    """Invariant (b): the commit tree is the accepted candidate; the plan file may differ in bookkeeping lines only."""
    need(fact, ("sha", "base"))
    root = state["worktree"]; sha, base = fact["sha"], fact["base"]
    for x in (sha, base): require(isinstance(x, str) and re.fullmatch(r"[a-f0-9]{40}", x), "missing full commit identity", 2)
    require(is_ancestor(root, sha, sha), "commit not found", 2)
    require(sha != base, "base is not a completion commit")
    require(is_ancestor(root, base, sha) and is_ancestor(root, sha, "HEAD"), "commit is not above its base on HEAD")
    name = plan_name(state)
    if art["kind"] == "plan":
        require(base == state["plan_base"], "plan commit base differs from plan_base")
        changed = [x for x in v.text_git(root, "diff-tree", "--no-commit-id", "-r", "--name-only", base, sha).split("\n") if x]
        require(changed == [name], "plan commit must change only the plan file")
        require(v.digest(v.git(root, "show", sha + ":" + name)) == cand, "plan commit blob differs from accepted plan")
        return None
    require(base == art["head"], "commit base differs from accepted candidate HEAD")
    now = fresh(state, art)
    require(not v.text_git(root, "diff", "--no-ext-diff", "--name-only", "--"), "hook/working-tree or unstaged source after acceptance")
    expected = {}
    for label, item in now["manifest"]["files"].items():
        if label.startswith("repo:") and label[5:] != name:
            require("index" in item, "accepted source was not staged")
            if item["type"] != "missing": expected[label[5:]] = item["index"]
    tree = {}
    for row in v.git(root, "ls-tree", "-r", "-z", sha).split(b"\0"):
        if row:
            meta, path = row.split(b"\t", 1); mode, _, oid = meta.decode().split()
            tree[path.decode("utf-8")] = [mode, oid]
    has_plan = tree.pop(name, None) is not None
    require(tree == expected, "commit does not contain accepted index/source")
    if not has_plan: return None
    facts = plan_read(v.git(root, "show", sha + ":" + name).decode("utf-8-sig").replace("\r\n", "\n"))
    require(facts["shape"] == state["plan"]["structure"], "commit changes the plan beyond bookkeeping")
    return facts


def accept_report(data, state):
    raw = record(data.get("event")); require(raw.get("ok") is True, "Orca did not accept event", 2)
    result = raw.get("result", {})
    messages = [result["message"]] if "message" in result else result.get("messages", [])
    if not messages and result.get("timedOut") is True: return "not-completion"
    messages = [m for m in messages if m.get("id") == data.get("message_id")]
    require(len(messages) == 1, "missing exact delivery message", 2)
    msg = messages[0]; payload = msg.get("payload")
    payload = (json.loads(payload) if isinstance(payload, str) else payload) or {}
    if msg["id"] in state["processed_messages"]: return "duplicate"
    active = state["active"]; require(active is not None, "no current Dispatch", 2)
    if msg.get("type") != "worker_done" or (msg.get("run_id"), payload.get("taskId"), payload.get("dispatchId")) != (state["orca_run"], active["task_id"], active["dispatch_id"]):
        state["processed_messages"].append(msg["id"])
        return "not-completion" if msg.get("type") != "worker_done" else "stale"
    observed = observation(data.get("observation"), active)
    require(observed["dispatch"]["status"] == "completed" and observed["projection"].get("evidence", {}).get("durable") is True, "missing durable settlement", 2)
    require(msg.get("from_handle") == observed["dispatch"]["assigneeHandle"], "wrong report sender")
    report = data.get("report"); text = ref(report)
    require(not any((r["report"] or {}).get("path") == report["path"] for r in state["accepted"]), "report path already bound to an accepted attempt")
    # The verdict is report line 1; the subject must lead with that exact token (a worker may append ": <why>").
    token = re.split(r"[\s:]", str(msg.get("subject") or ""), maxsplit=1)[0]
    require(payload.get("reportPath") == report["path"] and token != "" and token == text.splitlines()[0], "report path/subject mismatch")
    art = artifact(data.get("artifact"), state, None if data.get("artifact") is None and active.get("artifact_id") is None else True)
    role = active["role"]
    if role not in WRITE: require(active.get("artifact_id") == art["id"] and active.get("snapshot_id") == art["snapshot_id"], "assigned artifact changed")
    token, findings, coverage = report_fields(text, active, art, payload.get("outcome"), payload.get("filesModified", []))
    if role in ("plan-writer", "plan-reviser") and token in WRITTEN:
        require(art["kind"] == "plan" and art["id"] == state["plan"]["sha256"], "plan author must deliver the current plan")
    actual = family(observed)
    if role in REVIEW and role != "plan-reviewer": independent(art, coverage, actual, state)
    if role == "plan-reviewer": plan_independent(state, actual)
    proofs = evidence_records(line_json(text, "EVIDENCE"), art, state) if role == "gate" and token == "GATE_OK" else []
    if role in WRITE: state["provenance"].append(data["observation"])
    state["accepted"].append(dict(role=role, token=token, round=active["round"], phase=active["phase"], step=state["step"],
                                  candidate=art["candidate"], artifact=data.get("artifact"), findings=findings, coverage=coverage,
                                  family=actual, report=report, dispatch_id=active["dispatch_id"], evidence=proofs))
    state["processed_messages"].append(msg["id"])
    state["write_ownership"] = [x for x in state["write_ownership"] if x != active["dispatch_id"]]
    state["active"] = None
    return "risk-escalation" if any(f.get("risk") in ("SECURITY", "DATA_LOSS") for f in findings) else "accepted"


def dispatch(data, state):
    fleet_clear(data, state)
    proposed = data.get("proposed"); need(proposed, ("run_id", "task_id", "dispatch_id", "role", "phase", "round", "worktree_id", "model"))
    require(proposed["role"] in TOKENS and proposed["run_id"] == state["orca_run"] and proposed["phase"] == state["phase"] and
            proposed["worktree_id"] == state["worktree_id"], "proposed binding mismatch")
    require(type(proposed["round"]) is int and proposed["round"] >= 1, "invalid proposed round")
    require(proposed["task_id"] and proposed["dispatch_id"] is None, "dispatch proposal needs a fresh Task and null not-yet-created Dispatch")
    unplanned = state["plan"] is not None and state["plan"]["sha256"] is None
    require(not unplanned or proposed["role"] == "plan-writer", "only a plan-writer may start before the plan exists")
    art = artifact(data.get("artifact"), state, None if unplanned and data.get("artifact") is None else True)
    reviewer = family({"projection": {"provider": {"model": proposed["model"]}}})
    group = {"plan-reviewer": "plan_review", "review-primary": "fused_review", "review-control": "fused_review", "review-final": "final_review"}.get(proposed["role"])
    if proposed.get("gate_fix"): group = "gate_fix"
    if group:
        count = state["rounds"][group]
        require(proposed["round"] in (count, count + 1) and proposed["round"] <= cap(state, group), "round cap/sequence: " + group)
        state["rounds"][group] = proposed["round"]
        require(not any(r["role"] == proposed["role"] and r["round"] == proposed["round"] and r["family"] == reviewer
                        for r in state["accepted"]), "substantive review needs a new round")
    if proposed["role"] in REVIEW and proposed["role"] != "plan-reviewer": independent(art, proposed.get("coverage", {}), reviewer, state)
    proposed.update(artifact_id=art["id"], snapshot_id=art["snapshot_id"])
    state["active"] = proposed
    if proposed["role"] in WRITE: state["write_ownership"] = ["pending:" + proposed["task_id"]]


def user_record(data, state, keys, where, label):
    """A user's decision saved verbatim by the coordinator, bound to this Run and step/phase."""
    auth = record(data.get("authorization")); need(auth, ("schema_version", "run_id", "user_decision") + keys)
    require(auth["schema_version"] == 1 and auth["run_id"] == state["orca_run"] and all(auth[k] == state[k] for k in where), label + " binding mismatch")
    require(isinstance(auth["user_decision"], str) and auth["user_decision"].strip(), label + " without the user's decision")
    return auth


def validate(data):
    need(data, ("schema_version", "action", "state"))
    require(data["schema_version"] == 1, "unsupported input schema", 2)
    state = copy.deepcopy(data["state"])
    require(isinstance(state, dict) and state.get("schema_version") == 2, "schema 1 state: run protocol-state migrate", 2)
    need(state, KEYS)
    require(state["mode"] in ("plan", "quickfix") and state["step"] in READY and
            (state["mode"] == "quickfix") == (state["step"] == "quickfix") == (state["plan"] is None), "invalid protocol mode/step")
    require(Path(state["worktree"]).is_absolute() and Path(state["workspace"]).is_absolute(), "absolute workspace required")
    require(artifact_path(v.text_git(state["worktree"], "rev-parse", "--show-toplevel")) == artifact_path(state["worktree"]), "TARGET is not a Git worktree", 2)
    for sha in (state["plan_base"], state["base"]):
        require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha) and is_ancestor(state["worktree"], sha, sha), "missing recorded base", 2)
    update_plan(data, state)
    require(state["plan"] is None or state["plan"]["sha256"] is not None or state["step"] == "plan", "missing plan outside the plan step", 2)
    decisions = ledger(data, state); phases = plan_facts(state)
    for key in CAPS:
        require(type(state["rounds"].get(key)) is int and 0 <= state["rounds"][key] <= cap(state, key), "round cap: " + key)
    action = data["action"]; decision = "accepted"
    if action == "accept-report": decision = accept_report(data, state)
    elif action == "dispatch": dispatch(data, state)
    elif action == "bind-dispatch":
        active = state["active"]; require(active and active["dispatch_id"] is None, "no pending dispatch intent")
        raw = record(data.get("observation")); require(raw.get("ok") is True, "unsuccessful Orca observation", 2)
        result = raw["result"]; d = result["dispatch"]
        require(d.get("taskId") == active["task_id"] and d.get("runId") == state["orca_run"] and d.get("retryOfDispatchId") is None, "dispatch does not bind pending fresh Task")
        require(d.get("id") and model_matches(active["model"], actual_model(result, data["observation"])), "actual launch differs from proposal")
        active["dispatch_id"] = d["id"]
        observation(data["observation"], active)
        if active["role"] in WRITE: state["write_ownership"] = [d["id"]]
    elif action in ("prepare-commit", "confirm-commit"):
        fleet_clear(data, state)
        require(state["step"] in ("plan", "phase", "quickfix", "final-review"), "not a commit step")
        art = artifact(data.get("artifact"), state, action == "prepare-commit")
        ready(state, art["candidate"], decisions)
        if action == "prepare-commit":
            require(not v.text_git(state["worktree"], "diff", "--no-ext-diff", "--name-only", "--"), "hook/working-tree or unstaged source after acceptance")
        else:
            commit_check(state, data.get("commit"), art["candidate"], art)
            if not any(c["sha"] == data["commit"]["sha"] for c in committed(state)):
                state["phase_commits"].append(dict(phase=state["phase"], step=state["step"], sha=data["commit"]["sha"], base=data["commit"]["base"], candidate=art["candidate"]))
    elif action == "advance":
        require(state["step"] in ("plan", "phase") and committed(state), "advance before the phase commit is confirmed", 2)
        ids = [p["id"] for p in phases]; index = ids.index(state["phase"]) if state["phase"] in ids else -1
        if index + 1 < len(ids): state.update(phase=ids[index + 1], base=committed(state)[-1]["sha"], step="phase")
        else: state["step"] = "final-review"
        state.update(accepted=[], active=None); state["rounds"].update(fused_review=0, gate_fix=0)
    elif action == "finish-checkpoint":
        fleet_clear(data, state)
        require(state["step"] in ("final-review", "delivery"), "not a final checkpoint")
        require({p["id"] for p in phases} <= {c["phase"] for c in state["phase_commits"] if c["step"] == "phase"}, "uncommitted phases", 2)
        art = artifact(data.get("artifact"), state, True)
        if state["step"] == "delivery": require(art["candidate"] == state["final_source"], "delivery covers a different source than the final review")
        ready(state, art["candidate"], decisions)
        state.update(final_source=art["candidate"], step="delivery" if state["step"] == "final-review" else "completion", accepted=[], active=None)
    elif action == "complete":
        fleet_clear(data, state)
        require(state["step"] == "completion" and state["final_source"], "not a final checkpoint")
        art = artifact(data.get("artifact"), state)
        require(art["kind"] != "plan" and art["candidate"] == state["final_source"], "completion candidate differs from the final-reviewed source")
        require((data.get("commit") or {}).get("sha") not in {c["sha"] for c in state["phase_commits"]}, "completion requires a separate commit")
        plan = commit_check(state, data["commit"], state["final_source"], art)
        require(plan is not None and plan["done"], "final bookkeeping is incomplete", 2)
        state["phase_commits"].append(dict(phase=state["phase"], step="completion", sha=data["commit"]["sha"], base=data["commit"]["base"], candidate=art["candidate"]))
    elif action == "extend-cap":
        # Only the user lifts a reached cap, one round per verbatim record.
        auth = user_record(data, state, ("phase", "group", "extra_rounds", "findings"), ("phase",), "cap extension")
        require(auth["group"] in CAPS and auth["extra_rounds"] == 1, "cap extension binding mismatch")
        require(state["rounds"][auth["group"]] >= cap(state, auth["group"]), "cap extension before the cap is reached")
        known = {f["id"] for r in state["accepted"] for f in r["findings"]}
        require(isinstance(auth["findings"], list) and auth["findings"] and set(auth["findings"]) <= known, "cap extension must name accepted findings")
        state["cap_extensions"].append(dict(group=auth["group"], phase=auth["phase"], authorization=data["authorization"]))
    elif action == "waive-independence":
        # Only the user releases a unit from the family rule, and only where every known family already authored it.
        auth = user_record(data, state, ("step", "phase", "files", "reviewer_family"), ("step", "phase"), "independence waiver")
        require(isinstance(auth["files"], list) and auth["files"] and all(isinstance(f, str) and f for f in auth["files"]) and
                auth["reviewer_family"] in known_families(), "independence waiver must name files and a known reviewer family")
        writers = authors(artifact(data.get("artifact"), state, True), state["provenance"])
        for name in auth["files"]:
            require(writers.get(name, set()) >= known_families(), "independence waiver needs every family as author: " + name)
        state["independence_waivers"].append(dict(step=auth["step"], phase=auth["phase"], files=auth["files"],
                                                  reviewer_family=auth["reviewer_family"], authorization=data["authorization"]))
    elif action == "record-gate":
        # A green verify-gate needs no worker; its sealed C4 results are the gate evidence.
        require(state["step"] in ("phase", "delivery") and not state["write_ownership"], "script gate outside an unowned phase or delivery candidate")
        art = artifact(data.get("artifact"), state, True)
        state["accepted"].append(dict(role="gate", token="GATE_OK", round=state["rounds"]["gate_fix"], phase=state["phase"], step=state["step"],
                                      candidate=art["candidate"], artifact=data["artifact"], findings=[], coverage={}, family=None,
                                      report=None, dispatch_id=None, evidence=evidence_records(data.get("evidence"), art, state)))
    else: require(action == "resume", "unknown action")
    state["barrier"] = barrier(state, phases, decisions)
    return state, decision


def main(args):
    try:
        if args and args[0] in ("summary", "migrate"):
            import protocol_tools
            return getattr(protocol_tools, args[0])(args)
        commands = {"claude-model-evidence": claude_model_evidence, "antigravity-model-evidence": antigravity_model_evidence}
        if args and args[0] in commands: return commands[args[0]](args)
        require(len(args) in (2, 3) and args[0] == "validate", "usage: protocol-state validate INPUT_JSON [RESUME_OUT]")
        data = v.load(args[1]); state, decision = validate(data)
        if len(args) == 3:
            target = artifact_path(args[2]); workspace = artifact_path(state["workspace"])
            require(target.is_relative_to(workspace) and target != workspace and target.parent.is_dir(), "resume output outside existing workspace")
            require(not any(p.is_symlink() for p in (target, *target.parents)), "linked resume output")
            protected = {str(Path(args[1]).absolute())}
            def paths(obj):
                if isinstance(obj, dict):
                    if "path" in obj: protected.add(str(Path(obj["path"]).absolute()))
                    for value in obj.values(): paths(value)
                elif isinstance(obj, list):
                    for value in obj: paths(value)
            paths(data)
            require(str(target) not in protected, "resume must not replace an input artifact")
            v.save(target, state)
        print("VALID"); print(json.dumps(dict(decision=decision, state=state), ensure_ascii=True))
        return 0
    except Rejected as e:
        print("INVALID" if e.code == 1 else "UNVERIFIABLE"); print(json.dumps(dict(reason=str(e), next_action=e.next_action)))
        return e.code
    except (OSError, ValueError, TypeError, KeyError, AttributeError, v.subprocess.SubprocessError) as e:
        print("UNVERIFIABLE"); print(json.dumps(dict(reason=str(e), next_action="supply-bound-facts")))
        return 2


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))

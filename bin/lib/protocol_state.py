"""C6: validate one coordinator proposal; no dispatch, commit or lifecycle effects."""
import copy
import json
import os
from pathlib import Path
import re
import sys

import verification as v
from posix_runtime import artifact_path

CAPS = {"plan_review": 4, "fused_review": 4, "final_review": 2, "gate_fix": 2}
REVIEW = {"plan-reviewer", "review-primary", "review-control", "review-final"}
WRITE = {"plan-writer", "plan-reviser", "implementer", "frontend-implementer", "quickfix", "synthesizer"}
TOKENS = {
    "plan-writer": ["PLAN_WRITTEN", "REVISED", "NEEDS_AUTHORIZATION", "BLOCKED"],
    "plan-reviser": ["REVISED", "NEEDS_AUTHORIZATION", "BLOCKED"],
    "plan-reviewer": ["APPROVED", "CHANGES_REQUESTED", "BLOCKED"],
    "implementer": ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "NEEDS_AUTHORIZATION", "BLOCKED"],
    "frontend-implementer": ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "NEEDS_AUTHORIZATION", "BLOCKED"],
    "quickfix": ["DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"],
    "gate": ["GATE_OK", "GATE_FAIL", "NO_COMMANDS", "NEEDS_JUDGMENT", "BLOCKED"],
    "review-primary": ["REVIEW_OK", "REVIEW_BLOCKING", "BLOCKED"],
    "review-control": ["REVIEW_OK", "REVIEW_BLOCKING", "BLOCKED"],
    "review-final": ["REVIEW_OK", "REVIEW_BLOCKING", "BLOCKED"],
    "synthesizer": ["SYNTHESIS_DONE", "BLOCKED"],
    "diagnosis": ["NEEDS_MORE_CONTEXT", "NEEDS_MORE_REASONING", "PHASE_TOO_LARGE", "PLAN_WRONG", "IMPASSE_SUMMARY", "BLOCKED"],
}


class Rejected(Exception):
    def __init__(self, reason, code=1, next_action="resolve-protocol-blocker"):
        self.code, self.next_action = code, next_action
        super().__init__(reason)


def require(ok, reason, code=1):
    if not ok: raise Rejected(reason, code)


def need(obj, keys):
    require(isinstance(obj, dict) and all(k in obj for k in keys), "missing facts: " + ", ".join(keys), 2)


def ref(refspec):
    need(refspec, ("path", "sha256"))
    p = artifact_path(refspec["path"])
    require(Path(refspec["path"]).is_absolute(), "artifact path must be absolute")
    require(p.is_absolute(), "artifact path must be absolute")
    require(not any(x.is_symlink() for x in (p, *p.parents)), "linked artifact path", 2)
    require(p.is_file(), "missing artifact: " + str(p), 2)
    data = p.read_bytes()
    require(v.digest(data) == refspec["sha256"], "artifact hash mismatch: " + str(p))
    # Hash the original bytes, then parse LF and CRLF identically on both backends.
    return data.decode("utf-8-sig").replace("\r\n", "\n")


def record(refspec):
    return json.loads(ref(refspec))


def line_json(text, label, default=None):
    rows = re.findall(r"^" + re.escape(label) + r": (.+)$", text, re.M)
    if not rows and default is not None: return default
    require(len(rows) == 1, "format: expected one " + label)
    return json.loads(rows[0])


def plan_facts(state):
    if state["plan"] is None:
        if state["step"] == "bootstrap":
            bootstrap(state)
        else:
            require(state["mode"] == "quickfix", "plan-less mode must be quickfix or authorized bootstrap")
        return []
    text = ref(state["plan"])
    match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    require(match is not None, "missing plan frontmatter", 2)
    front = match[1]
    def scalar(name):
        found = re.findall(r"^" + name + r":\s*(.*?)\s*$", front, re.M)
        require(len(found) == 1, "missing plan metadata: " + name, 2)
        return v.unquote(found[0])
    require(scalar("protocol_version") == "2", "legacy metadata is not certified", 2)
    require(scalar("orca_run") == state["orca_run"] and scalar("plan_base") == state["plan_base"], "plan/run/base mismatch")
    if state.get("authorization"):
        ref(state["authorization"])
        require(scalar("request_sha256") == state["authorization"]["sha256"], "plan/request mismatch")
    contracts = json.loads(scalar("contracts"))
    require(isinstance(contracts, list) and len(set(contracts)) == len(contracts), "invalid contract ids")
    require(all(isinstance(x, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", x) for x in contracts), "invalid contract id")
    phases = []
    for item in re.split(r"^  - id:\s*", front, flags=re.M)[1:]:
        rows = item.splitlines(); p = {"id": v.unquote(rows[0].strip())}
        for row in rows[1:]:
            field = re.match(r"^    (risk|base|consumes|produces):\s*(.*?)\s*$", row)
            if field: p[field[1]] = field[2]
        require(p.get("risk") in ("none", "SECURITY", "DATA_LOSS", "REGRESSION"), "format: missing/invalid phase risk")
        need(p, ("consumes", "produces"))
        for key in ("consumes", "produces"):
            p[key] = json.loads(p[key]); require(isinstance(p[key], list), "contract references must be arrays")
        phases.append(p)
    require(bool(phases) and len({p["id"] for p in phases}) == len(phases), "invalid phases")
    produced = set()
    for p in phases:
        require(set(p["produces"]) <= set(contracts), "undeclared produced contract")
        require(set(p["consumes"]) <= produced, "consume without an earlier producer")
        produced.update(p["produces"])
    if state["phase"] is not None:
        phase = next((p for p in phases if p["id"] == state["phase"]), None)
        require(phase is not None, "phase/base mismatch")
        if not state.get("track_group"):
            require(phase.get("base") == state["base"], "phase/base mismatch")
    return phases


def bootstrap(state):
    require(state["mode"] == "plan" and state["step"] == "bootstrap" and state["phase"] is None and
            not state["phase_commits"] and not state.get("track_group"), "invalid bootstrap state")
    active = state["active"]
    require(active is None or (active["role"] == "plan-writer" and active["round"] == 1), "bootstrap permits only first plan-writer")
    request = record(state.get("authorization"))
    need(request, ("schema_version", "run_id", "worktree_id", "plan_base", "plan_path", "request"))
    require(request["schema_version"] == 1 and request["run_id"] == state["orca_run"] and
            request["worktree_id"] == state["worktree_id"] and request["plan_base"] == state["plan_base"] and
            state["base"] == state["plan_base"], "bootstrap request binding mismatch")
    p = Path(request["plan_path"])
    require(p.is_absolute() and p.is_relative_to(Path(state["worktree"])) and
            isinstance(request["request"], str) and request["request"].strip(), "invalid bootstrap request/plan path")
    require(state["plan"] is None or state["plan"]["path"] == request["plan_path"], "bootstrap draft path mismatch")
    # Failed attempts remain evidence, not permission to start plan consumers.
    history = state.get("report_history", state["accepted"])
    require(history == state["accepted"] and state["provenance"] == [r["observation"] for r in history],
            "unverifiable bootstrap history", 2)
    for r in history:
        require(r["role"] == "plan-writer" and r["binding"]["round"] == 1 and r["step"] == "bootstrap" and
                r["binding"]["run_id"] == state["orca_run"] and r["binding"]["phase"] is None and
                r["token"] in ("BLOCKED", "NEEDS_AUTHORIZATION"), "invalid bootstrap history")
        accepted_report(state, r["report"])
        a = r["artifact"]
        require((a["kind"] == "request" and a["path"] == state["authorization"]["path"] and
                 a["sha256"] == state["authorization"]["sha256"]) or
                (a["kind"] == "plan" and a.get("source_path", a["path"]) == request["plan_path"]),
                "bootstrap history artifact mismatch")
    return request


def track_facts(state, phases):
    # NUL records avoid quoted paths and occurrences of 'worktree ' inside paths.
    records = {}
    for block in v.git(state["worktree"], "worktree", "list", "--porcelain", "-z").split(b"\0\0"):
        fields = {}
        for row in block.split(b"\0"):
            if row:
                key, _, value = row.decode("utf-8").partition(" ")
                fields[key] = value
        if "worktree" in fields: records[Path(fields["worktree"]).resolve()] = fields
    require(Path(state["worktree"]).resolve() in records, "TARGET is not a Git worktree", 2)
    if not state.get("track_group"): return
    group = record(state["track_group"])
    need(group, ("schema_version", "run_id", "parent_worktree", "parent_head", "plan", "tracks"))
    require(group["schema_version"] == 1 and group["run_id"] == state["orca_run"] and
            group["plan"] == state["plan"], "track group run/immutable-plan mismatch")
    require(Path(group["parent_worktree"]).is_absolute() and isinstance(group["parent_head"], str) and
            re.fullmatch(r"[a-f0-9]{40}", group["parent_head"]), "invalid track parent BASE/path")
    parent = Path(group["parent_worktree"]).resolve()
    require(parent in records, "missing track parent worktree", 2)
    plan_path = Path(group["plan"]["path"]).resolve()
    require(plan_path.is_relative_to(parent), "track plan outside parent")
    committed_plan = v.git(parent, "show", group["parent_head"] + ":" + plan_path.relative_to(parent).as_posix())
    require(committed_plan.decode("utf-8-sig").replace("\r\n", "\n") == ref(group["plan"]), "track plan differs from parent history")
    v.git(state["worktree"], "merge-base", "--is-ancestor", state["plan_base"], group["parent_head"])
    v.git(state["worktree"], "merge-base", "--is-ancestor", group["parent_head"], records[parent]["HEAD"])
    tracks = group["tracks"]
    require(isinstance(tracks, list) and tracks, "missing tracks", 2)
    require(len({t["id"] for t in tracks}) == len(tracks) and
            len({Path(t["worktree"]).resolve() for t in tracks}) == len(tracks) and
            len({t["worktree_id"] for t in tracks}) == len(tracks) and len({t["phase"] for t in tracks}) == len(tracks), "duplicate track binding")
    active = []; selected = None
    completed = state.get("track_commits", [])
    require(len({c["track_id"] for c in completed}) == len(completed) and
            {c["track_id"] for c in completed} <= {t["id"] for t in tracks}, "invalid completed tracks")
    for track in tracks:
        need(track, ("id", "worktree", "worktree_id", "phase", "base"))
        require(Path(track["worktree"]).is_absolute(), "absolute child worktree required")
        path = Path(track["worktree"]).resolve()
        require(path != parent and path in records and track["base"] == group["parent_head"], "track BASE/worktree mismatch")
        child_plan = path / plan_path.relative_to(parent)
        require(child_plan.read_bytes().decode("utf-8-sig").replace("\r\n", "\n") == ref(group["plan"]), "child changed immutable plan")
        phase = next((p for p in phases if p["id"] == track["phase"]), None)
        require(phase is not None, "unknown track phase")
        # The sealed group overrides phase.base only with a verified descendant of
        # that planned base. Workers never edit the shared plan to guess a SHA.
        v.git(state["worktree"], "merge-base", "--is-ancestor", phase["base"], track["base"])
        v.git(path, "merge-base", "--is-ancestor", track["base"], records[path]["HEAD"])
        done = next((c for c in completed if c["track_id"] == track["id"]), None)
        if done:
            require(done["base"] == track["base"], "completed track BASE mismatch")
            child = dict(state, worktree=str(path))
            commit_fact(done, child)
            v.git(state["worktree"], "merge-base", "--is-ancestor", done["sha"], records[parent]["HEAD"])
        else:
            active.append(track)
        if path == Path(state["worktree"]).resolve(): selected = track
    require(len(active) <= 2, "more than two active child tracks in this Run")
    if Path(state["worktree"]).resolve() != parent:
        require(selected is not None and selected["worktree_id"] == state["worktree_id"] and
                selected["phase"] == state["phase"] and selected["base"] == state["base"], "TARGET track binding mismatch", 2)
    for t in active:
        p = next(p for p in phases if p["id"] == t["phase"])
        for other in active:
            q = next(p for p in phases if p["id"] == other["phase"])
            if t != other:
                require(not (set(p["produces"]) & (set(q["consumes"]) | set(q["produces"]))), "parallel producer/consumer conflict")


def actual_model(observed, start=None):
    model = (observed.get("projection", {}).get("provider") or {}).get("model")
    if start is not None:
        raw = record(start); require(raw.get("ok") is True, "unsuccessful worker-start receipt", 2)
        launched = raw.get("result", {}); d = observed.get("dispatch", {})
        need(launched, ("runId", "taskId", "dispatchId", "launch"))
        require((launched["runId"], launched["taskId"], launched["dispatchId"]) ==
                (d.get("runId"), d.get("taskId"), d.get("id")), "worker-start identity mismatch")
        effective = (launched["launch"].get("effective") or {}).get("model")
        require(isinstance(effective, str) and effective, "missing effective launch model", 2)
        require(model is None or model == effective, "conflicting actual model facts")
        if model is None: model = effective
    require(model is not None, "unknown actual model family", 2)
    return model


def family(observation, start=None):
    model = actual_model(observation, start)
    roles = (Path(__file__).parents[2] / "skills/orca-dev/roles.md").read_text(encoding="utf-8-sig")
    mapping = line_json(roles, "FAMILY_MODELS")
    require(model in mapping, "unknown actual model family", 2)
    return mapping[model]


def observation(refspec, active):
    raw = record(refspec)
    require(raw.get("ok") is True, "unsuccessful Orca observation", 2)
    result = raw.get("result", {}); need(result, ("dispatch", "projection"))
    d = result["dispatch"]; need(d, ("id", "taskId", "runId", "status", "assigneeHandle"))
    require(d["taskId"] == active["task_id"] and d["runId"] == active["run_id"], "Task/Run observation mismatch")
    require(d["id"] == active["dispatch_id"], "Dispatch observation mismatch")
    require(result["projection"].get("workspace", {}).get("id") == active["worktree_id"], "observation worktree mismatch", 2)
    result["projection"]["provider"]["model"] = actual_model(result, refspec.get("start"))
    return result


def fleet_clear(data, state):
    require(not any(x.startswith("pending:") for x in state["write_ownership"]), "unbound writer intent", 2)
    need(data, ("fleet",))
    require(isinstance(data["fleet"], list) and data["fleet"], "missing fresh fleet", 2)
    workers = []; cursor = None; total = None; receipt_ids = []
    for page in data["fleet"]:
        require(page.get("cursor") == cursor, "fleet cursor mismatch", 2)
        raw = record(page); require(raw.get("ok") is True, "fleet unavailable", 2)
        require(raw.get("id") and raw["id"] not in state.get("used_fleet_ids", []), "fleet observation already used", 2)
        receipt_ids.append(raw["id"])
        result = raw["result"]; need(result, ("workers", "page", "scope"))
        require(result["scope"].get("source") == "all", "fleet must cover all local runs", 2)
        paging = result["page"]; require(total is None or total == paging["total"], "inconsistent fleet", 2)
        total = paging["total"]; workers.extend(result["workers"])
        cursor = paging["nextCursor"] if paging["hasMore"] else None
    require(cursor is None and len(workers) == total and len({w["dispatchId"] for w in workers}) == total, "incomplete fleet", 2)
    ownership = []
    for worker in workers:
        p = worker.get("projection") or {}; workspace = p.get("workspace") or {}
        resource = worker.get("resource") or {}
        uncertain = (worker.get("terminalState") in ("release_pending", "release_unknown") or
                     resource.get("ownershipState") in ("user_owned", "external", "pre_existing"))
        if not uncertain and worker.get("dispatchStatus") in ("completed", "failed") and p.get("evidence", {}).get("durable") is True:
            continue  # A provably settled retained terminal is not a writer, even without a workspace.
        require(workspace.get("id") is not None, "unknown fleet workspace", 2)
        if workspace["id"] != state["worktree_id"]: continue
        if uncertain:
            raise Rejected("unresolved release/external ownership", 2)
        if worker.get("terminalState") == "released" and p.get("liveness", {}).get("verdict") == "exited": continue
        ownership.append(worker["dispatchId"])
    state["write_ownership"] = ownership
    require(not ownership, "live or unverifiable prior writer", 2)
    state["used_fleet_ids"] = state.get("used_fleet_ids", []) + receipt_ids


def artifact(refspec, state, current=True):
    kind = refspec.get("kind"); raw = ref(refspec)
    if kind in ("plan", "request"):
        if current:
            target = state.get("authorization") if kind == "request" else state["plan"]
            require(target is not None and refspec["sha256"] == target["sha256"] and
                    (refspec.get("source_path", refspec["path"]) == target["path"]), "assigned plan/request mismatch")
            if kind == "request": bootstrap(state)
        return {"id": refspec["sha256"], "snapshot_id": None, "files": {}, "manifest": None}
    obj = json.loads(raw)
    if kind == "package":
        require(obj.get("complete") is True, "incomplete package", 2)
        if current: require(v.package_valid(refspec["path"]), "stale or incomplete package")
        snap = obj["snapshot_after"]; aid = obj["package_id"]
    else:
        require(kind == "snapshot" and obj.get("valid") is True, "invalid snapshot", 2)
        snap = obj; aid = snap["snapshot_id"]
        if current:
            m = snap["manifest"]
            now = v.snapshot(state["worktree"], refspec.get("inputs", []), m["exclusions"])
            require(now["valid"] and now["snapshot_id"] == snap["snapshot_id"], "stale snapshot")
    require(artifact_path(snap["manifest"]["root"]) == artifact_path(state["worktree"]), "artifact worktree mismatch")
    return dict(id=aid, snapshot_id=snap["snapshot_id"], files=snap["manifest"]["files"], head=snap["manifest"]["head"], manifest=obj if kind == "package" else None)


def report_fields(text, active, art, outcome, modified):
    text = text.replace("\r\n", "\n")
    role = active["role"]; rows = text.splitlines(); token = rows[0] if rows else ""
    require(role in TOKENS and token in TOKENS[role], "format: role verdict")
    failed = token == "BLOCKED" or (role in WRITE and token in ("NEEDS_CONTEXT", "NEEDS_AUTHORIZATION"))
    require(outcome == ("failed" if failed else "succeeded"), "format: subject/outcome conflict")
    b = line_json(text, "BINDING")
    keys = ("schema_version", "run_id", "task_id", "dispatch_id", "role", "phase", "round", "artifact_id", "snapshot_id")
    require(set(b) == set(keys) and b["schema_version"] == 1, "format: binding schema")
    for key in ("run_id", "task_id", "dispatch_id", "role", "phase", "round"):
        require(b[key] == active[key], "conflicting report binding: " + key)
    require(b["artifact_id"] == art["id"] and b["snapshot_id"] == art["snapshot_id"], "conflicting artifact binding")
    if token == "BLOCKED":
        require("## Reason" in text, "format: missing Reason")
        return token, [], {}
    if role == "review-primary":
        require(len(rows) >= 3 and rows[1] in ("SPEC: OK", "SPEC: FAIL") and rows[2] in ("QUALITY: OK", "QUALITY: FAIL"), "format: SPEC/QUALITY")
        require((token == "REVIEW_BLOCKING") == ("FAIL" in rows[1] + rows[2]), "format: SPEC/QUALITY verdict conflict")
    if role == "plan-reviewer":
        simplicity = re.findall(r"^SIMPLICITY: (OK|CHANGES_REQUESTED)$", text, re.M)
        require("## Simplicity" in text and len(simplicity) == 1, "format: SIMPLICITY")
        require(not (token == "APPROVED" and simplicity[0] != "OK"), "format: simplicity verdict conflict")
    findings = line_json(text, "FINDINGS", [])
    if role in REVIEW:
        findings = line_json(text, "FINDINGS")
        require(isinstance(findings, list), "format: findings array")
        for f in findings:
            require(isinstance(f, dict) and all(f.get(k) for k in ("id", "kind", "issue", "location")), "format: finding fields")
            require(f["kind"] in ("blocking", "cannot_verify"), "format: finding kind")
            if f["kind"] == "cannot_verify": required = ("check", "expect")
            elif role == "review-control": required = ("authorization_relation", "why_now", "minimal_fix", "risk")
            else: required = ("class", "change", "risk")
            require(all(f.get(k) for k in required), "format: required finding fields")
            if f["kind"] == "blocking":
                require(f["risk"] in ("none", "SECURITY", "DATA_LOSS", "REGRESSION", "GUARANTEED_FAIL"), "format: finding risk")
                if role != "review-control": require(f["class"] in ("MUST_FIX_NOW", "REGRESSION_FROM_AUTHORIZED_FIX"), "format: finding class")
                if role == "plan-reviewer":
                    require(f.get("criterion"), "format: plan criterion")
                    if active["round"] > 1 and f["class"] == "MUST_FIX_NOW": require(f.get("new_blocker_materiality"), "format: new blocker materiality")
                if f.get("simplicity"): require(all(f.get(k) for k in ("unnecessary_cost_or_risk", "simpler_alternative", "preserved_properties")), "format: simplicity finding")
        blocking = any(f["kind"] == "blocking" for f in findings)
        require((token in ("REVIEW_BLOCKING", "CHANGES_REQUESTED")) == blocking, "format: findings/verdict conflict")
        require("CANNOT_VERIFY" not in text or any(f["kind"] == "cannot_verify" for f in findings), "format: unstructured CANNOT_VERIFY")
    if role in ("implementer", "frontend-implementer", "quickfix") and (active["round"] > 1 or active.get("fix")):
        fix = line_json(text, "FIX_EVIDENCE")
        require(all(fix.get(k) for k in ("tests", "commands", "outputs")), "format: fix evidence")
    if role == "quickfix": require(len(modified) == 1, "quickfix must modify exactly one file")
    if role == "gate":
        require(len(rows) > 1 and (rows[1].startswith("verify: ") or re.match(r"^lint: .+ \| typecheck: .+ \| tests: .+", rows[1])), "format: gate summary")
    if role == "synthesizer": require(len(rows) > 1 and rows[1].startswith("docs/reviews/"), "format: synthesis path")
    if role == "diagnosis":
        sections = {"NEEDS_MORE_CONTEXT": "Context", "NEEDS_MORE_REASONING": "Context", "PHASE_TOO_LARGE": "Split", "PLAN_WRONG": "Plan defect", "IMPASSE_SUMMARY": "Summary"}
        require("## " + sections[token] in text and "## Evidence" in text, "format: diagnosis sections")
    return token, findings, line_json(text, "COVERAGE", {})


def independent(art, coverage, reviewer_family, provenance=()):
    m = art["manifest"]
    require(m is not None, "review requires a complete package", 2)
    writers = {}
    for write in m["provenance"].get("writes", []):
        saved = record({"path": write["receipt_path"], "sha256": write["receipt_sha256"]})
        observed = saved.get("result", {})
        d = observed.get("dispatch", {})
        require((d.get("id"), d.get("taskId"), d.get("runId")) ==
                (write["dispatch_id"], write["task_id"], write["run_id"]), "unknown write provenance", 2)
        start = next((r.get("start") for r in provenance if r["path"] == write["receipt_path"] and r["sha256"] == write["receipt_sha256"]), None)
        actual = family(observed, start)
        require(actual == write["family"], "claimed author family differs from launch")
        for path in write["files"]: writers.setdefault(path, set()).add(actual)
    files = {f["path"] for f in m["files"]}
    require(set(coverage.get("files", [])) <= files, "unknown coverage file")
    for name in coverage.get("files", []):
        require(writers.get(name), "unknown actual author: " + name, 2)
        require(reviewer_family not in writers[name], "same-family review: " + name)
    require(set(coverage.get("parts", [])) <= {p["path"] for p in m["parts"]}, "unknown coverage part")
    contracts = {c["id"]: c for c in m["coverage"]["contracts"]}
    for c in coverage.get("contracts", []):
        require(c.get("id") in contracts, "unknown coverage contract")
        for side in ("producer", "consumer"):
            require(set(c.get(side, [])) <= set(contracts[c["id"]][side]), "unknown contract side")
            require(set(c.get(side, [])) <= set(coverage.get("files", [])), "contract side lacks file review")


def evidence(text, art):
    records = line_json(text, "EVIDENCE")
    require(isinstance(records, list) and records, "missing executable evidence", 2)
    passed = 0
    for entry in records:
        st = record(entry)
        require(v.evidence_valid(st), "stale or invalid runner evidence")
        e = st["evidence"]
        require(e["source_after"]["manifest"]["files"] == art["files"] and e["source_after"]["manifest"]["head"] == art["head"], "evidence snapshot mismatch")
        if e["key"]["check"]["independent_replay"]:
            require(not e.get("origin_run_id"), "required replay reused implementer evidence")
        if st["exit_code"] == 0: passed += 1
        else:
            base = record(entry.get("baseline"))
            require(v.evidence_valid(base) and base["evidence"]["key"]["provenance"]["kind"] == "BASE" and
                    base["exit_code"] != 0 and base["evidence"]["failure_signature"] == e["failure_signature"], "unproven inherited failure")
    require(passed > 0, "zero passing checks")
    return records


def commit_fact(fact, state):
    need(fact, ("sha", "base", "artifact"))
    for key in ("sha", "base"):
        require(isinstance(fact[key], str) and re.fullmatch(r"[a-f0-9]{40}", fact[key]), "missing full commit identity", 2)
    root = state["worktree"]
    require(v.text_git(root, "rev-parse", fact["sha"] + "^{commit}") == fact["sha"], "commit not found", 2)
    require(fact["sha"] != fact["base"], "base is not a completion commit")
    v.git(root, "merge-base", "--is-ancestor", fact["base"], fact["sha"])
    v.git(root, "merge-base", "--is-ancestor", fact["sha"], "HEAD")
    art = artifact(fact["artifact"], state, current=False)
    require(fact["base"] == art.get("head"), "commit base differs from accepted candidate HEAD")
    expected = {}
    for label, item in art["files"].items():
        if not label.startswith("repo:"): continue
        require("index" in item or item["type"] == "missing", "accepted source was not staged")
        if item["type"] != "missing": expected[label[5:]] = item["index"]
    tree = {}
    for row in v.git(root, "ls-tree", "-r", "-z", fact["sha"]).split(b"\0"):
        if row:
            meta, path = row.split(b"\t", 1); mode, _, oid = meta.decode().split()
            tree[path.decode("utf-8")] = [mode, oid]
    require(tree == expected, "commit does not contain accepted index/source")
    return art


def covered(state, art, roles):
    reports = [x for x in state["accepted"] if x["role"] in roles and x["step"] == state["step"] and
               (artifact(x["artifact"], state, current=False)["files"] == art["files"] or
                (state["phase"] is None and state["plan"] and x["artifact_id"] == state["plan"]["sha256"]))]
    require(set(roles) <= {r["role"] for r in reports}, "required report is missing", 2)
    for r in reports:
        text = ref(r["report"])
        saved_art = artifact(r["artifact"], state, current=False)
        token, findings, coverage = report_fields(text, r["binding"], saved_art, r["outcome"], r["modified"])
        require((token, findings, coverage) == (r["token"], r["findings"], r["coverage"]), "accepted report state mismatch")
        obs = observation(r["observation"], r["binding"])
        require(family(obs) == r["family"], "accepted family mismatch")
        require(obs["dispatch"]["status"] == "completed" and obs["projection"].get("evidence", {}).get("durable") is True, "accepted settlement missing", 2)
        if r["role"] == "gate" and token == "GATE_OK":
            require(evidence(ref(r["report"]), saved_art) == r["evidence"], "accepted evidence mismatch")
        if r["role"] == "plan-reviewer":
            require(state["provenance"], "unknown plan authors", 2)
            for author in state["provenance"]: require(family(record(author)["result"], author.get("start")) != r["family"], "same-family plan review")
        if r["role"] in REVIEW and r["role"] != "plan-reviewer": independent(saved_art, coverage, r["family"], state["provenance"])
        require(not [f for f in r["findings"] if f["id"] not in state.get("closed_ledger_ids", [])] and r["token"] in ("REVIEW_OK", "GATE_OK", "APPROVED", "DONE", "DONE_WITH_CONCERNS"), "unresolved findings or verification")
    if reviews := [r for r in reports if r["role"] in REVIEW and r["role"] != "plan-reviewer"]:
        if art["manifest"] is None:
            art = artifact(reviews[0]["artifact"], state, current=False)
    if reviews and art["manifest"] is not None:
        m = art["manifest"]
        require({f["path"] for f in m["files"]} <= {p for r in reviews for p in r["coverage"].get("files", [])}, "incomplete file coverage", 2)
        require({p["path"] for p in m["parts"]} <= {p for r in reviews for p in r["coverage"].get("parts", [])}, "incomplete part coverage", 2)
        for contract in m["coverage"]["contracts"]:
            for side in ("producer", "consumer"):
                union = {p for r in reviews for c in r["coverage"].get("contracts", []) if c["id"] == contract["id"] for p in c.get(side, [])}
                require(set(contract[side]) <= union, "incomplete contract " + contract["id"] + ":" + side, 2)


def accepted_report(state, reference):
    matches = [r for r in state.get("report_history", state["accepted"]) if r["report"] == reference]
    require(len(matches) == 1, "closure report is not accepted", 2)
    r = matches[0]
    art = artifact(r["artifact"], state, current=False)
    token, findings, coverage = report_fields(ref(r["report"]), r["binding"], art, r["outcome"], r["modified"])
    require((token, findings, coverage) == (r["token"], r["findings"], r["coverage"]), "closure report state mismatch")
    obs = observation(r["observation"], r["binding"])
    require(obs["dispatch"]["status"] == "completed" and obs["projection"].get("evidence", {}).get("durable") is True and
            family(obs) == r["family"], "closure report settlement mismatch", 2)
    return r, art


def review_closure(state, proof, finding, origin):
    need(proof, ("fix_report", "review_report"))
    origin, _ = accepted_report(state, proof["report"])
    fix, written = accepted_report(state, proof["fix_report"])
    review, reviewed = accepted_report(state, proof["review_report"])
    require(all(r["binding"]["phase"] == origin["binding"]["phase"] and r["binding"]["run_id"] == state["orca_run"]
                for r in (fix, review)) and fix["step"] == review["step"] == origin["step"] and
            review["binding"]["round"] > origin["binding"]["round"], "closure phase/round mismatch")
    require(fix["role"] in WRITE and fix["token"] in ("DONE", "DONE_WITH_CONCERNS", "REVISED"), "closure missing successful fix")
    history = state.get("report_history", state["accepted"])
    positions = [next(i for i, r in enumerate(history) if r["report"] == item["report"]) for item in (origin, fix, review)]
    require(positions[0] < positions[1] < positions[2], "closure report order must be finding, fix, re-review")
    for key in ("task_id", "dispatch_id"):
        require(len({r["binding"][key] for r in (origin, fix, review)}) == 3, "closure requires distinct accepted attempts", 2)
    require(fix["role"] == "plan-reviser" or fix["binding"].get("fix") is True or fix["binding"]["round"] > 1,
            "closure requires an accepted fix response", 2)
    fixed = line_json(ref(fix["report"]), "FIX_EVIDENCE", {})
    addressed = fixed.get("findings", []) if isinstance(fixed, dict) else []
    require(isinstance(addressed, list) and sum(isinstance(item, dict) and item.get("id") == finding["id"] and
            item.get("report") == origin["report"] for item in addressed) == 1, "closure fix finding binding mismatch")
    require(review["role"] in REVIEW and review["token"] in ("APPROVED", "REVIEW_OK") and
            not any(f["id"] == finding["id"] for f in review["findings"]), "closure missing positive re-review")
    require(proof["artifact"] == review["artifact"], "closure review artifact mismatch")
    if proof["artifact"]["kind"] == "plan":
        require(written["id"] == reviewed["id"], "closure fix/review snapshot mismatch")
        require(state["provenance"], "unknown plan authors", 2)
        for author in state["provenance"]:
            require(family(record(author)["result"], author.get("start")) != review["family"], "same-family plan review")
        source = Path(proof["artifact"].get("source_path", proof["artifact"]["path"]))
        name = "repo:" + source.relative_to(state["worktree"]).as_posix()
        historical = any(commit_fact(c, state)["files"].get(name, {}).get("sha256") == reviewed["id"] for c in state["phase_commits"])
        require(v.digest(source.read_bytes()) == reviewed["id"] or historical, "stale closure source")
    else:
        require(written["snapshot_id"] == reviewed["snapshot_id"] and written["files"] == reviewed["files"] and
                written["head"] == reviewed["head"], "closure fix/review snapshot mismatch")
        independent(reviewed, review["coverage"], review["family"], state["provenance"])
        require(review["coverage"].get("files") and set(fix["modified"]) <= set(review["coverage"]["files"]),
                "closure fix lacks review coverage", 2)
        raw = record(proof["artifact"]); m = raw["snapshot_after"]["manifest"] if proof["artifact"]["kind"] == "package" else raw["manifest"]
        current = v.snapshot(state["worktree"], proof["artifact"].get("inputs", []), m["exclusions"])
        historical = any(commit_fact(c, state)["files"] == reviewed["files"] for c in state["phase_commits"])
        require(current["valid"] and ((current["manifest"]["files"] == reviewed["files"] and current["manifest"]["head"] == reviewed["head"]) or historical), "stale closure source")


def ledger_facts(state):
    ledger = [] if state["ledger"] is None else record(state["ledger"])
    require(isinstance(ledger, list) and len({x["id"] for x in ledger}) == len(ledger), "invalid ledger")
    closed = []; opened = []
    for item in ledger:
        if item.get("status") not in ("fixed", "resolved", "closed", "verified-by-controller"):
            if item.get("status") == "open" and item.get("decision") in ("ACCEPTED", "PARTIALLY_ACCEPTED", "ESCALATED_TO_HUMAN"):
                opened.append(item["id"])
            continue
        require(item.get("closure") is not None, "missing closure evidence", 2)
        proof = record(item["closure"])
        need(proof, ("schema_version", "finding_id", "report", "artifact"))
        require(proof["schema_version"] == 1 and proof["finding_id"] == item["id"], "closure finding binding mismatch")
        reports = state.get("report_history", state["accepted"])
        origin = next((r for r in reports if r["report"] == proof["report"]), None)
        require(origin is not None, "closure report is not accepted", 2)
        original_art = {"id": origin["artifact_id"], "snapshot_id": origin["snapshot_id"]}
        _, findings, _ = report_fields(ref(origin["report"]), origin["binding"], original_art, origin["outcome"], origin["modified"])
        finding = next((f for f in findings if f["id"] == item["id"]), None)
        require(finding is not None, "closure wrong finding")
        if finding["kind"] == "blocking":
            review_closure(state, proof, finding, origin)
            closed.append(item["id"])
            continue
        need(proof, ("result", "command", "expect"))
        if finding["kind"] == "cannot_verify":
            require(proof["artifact"] == origin["artifact"] and proof["command"] == finding["check"] and
                    proof["expect"] == finding["expect"], "closure CHECK binding mismatch")
        # Every closing status for cannot_verify needs the exact executable CHECK.
        art = artifact(proof["artifact"], state, current=False)
        st = record(proof["result"])
        require(v.evidence_valid(st), "stale or invalid closure CHECK evidence")
        require(st["exit_code"] == 0, "negative closure CHECK; finding remains blocking")
        e = st["evidence"]
        require(proof["command"] and proof["expect"] and e["key"]["check"]["command"] == proof["command"], "closure command mismatch")
        m = e["source_after"]["manifest"]
        require(artifact_path(m["root"]) == artifact_path(state["worktree"]), "closure worktree mismatch")
        if proof["artifact"]["kind"] == "plan":
            name = "repo:" + artifact_path(proof["artifact"].get("source_path", proof["artifact"]["path"])).relative_to(artifact_path(state["worktree"])).as_posix()
            require(m["files"].get(name, {}).get("sha256") == proof["artifact"]["sha256"], "closure plan snapshot mismatch")
        else:
            require(m["files"] == art["files"] and m["head"] == art["head"], "closure snapshot mismatch")
        current = v.snapshot(state["worktree"], proof["artifact"].get("inputs", []), m["exclusions"])
        historical = any(c["base"] == m["head"] and commit_fact(c, state)["files"] == m["files"] for c in state["phase_commits"])
        require(current["valid"] and (current["manifest"]["files"] == m["files"] or historical), "stale closure source")
        # A recorded confirmed commit may change HEAD, never source bytes.
        require(current["manifest"]["head"] == m["head"] or historical, "stale closure HEAD")
        closed.append(item["id"])
    # A later REVIEW_OK without the old item cannot erase unresolved history.
    decisions = {x["id"]: x for x in ledger}
    for report in state.get("report_history", state["accepted"]):
        for f in report["findings"]:
            disposition = decisions.get(f["id"], {})
            scoped_out = f["kind"] == "blocking" and disposition.get("decision") in ("REJECTED_BY_SCOPE", "DEFER", "NIT")
            if f["id"] not in closed and not scoped_out and f["id"] not in opened: opened.append(f["id"])
    state["open_ledger_ids"] = opened
    state["closed_ledger_ids"] = closed


def barrier(state, phases):
    if state["step"] == "bootstrap" and not state["write_ownership"]: return "awaiting_plan_writer"
    if state["write_ownership"]: return "awaiting_writer"
    if state["open_ledger_ids"] or any(f["id"] not in state.get("closed_ledger_ids", []) for r in state["accepted"] for f in r["findings"]): return "awaiting_resolution"
    if state["commit_barrier"].get("confirmed_sha"):
        if state["mode"] == "quickfix": return "complete"
        if state["step"] == "completion": return "complete"
        return "ready_next_phase" if state["phase"] != (phases[-1]["id"] if phases else None) else "awaiting_final_review"
    roles = {x["role"] for x in state["accepted"] if x["step"] == state["step"]}
    if state["step"] == "final-review": return "awaiting_final_review"
    if state["step"] == "delivery": return "awaiting_delivery"
    if state["step"] == "completion": return "awaiting_completion_commit"
    if state["mode"] == "quickfix": return "awaiting_commit" if "quickfix" in roles else "awaiting_implementation"
    if state["phase"] is None: return "awaiting_commit" if "plan-reviewer" in roles else "awaiting_plan_review"
    # An untouched phase starts with a writer. A resumed phase with downstream
    # acceptance must not regress to implementation when an older compact
    # checkpoint retained gate/reviews rather than the original writer report.
    if not roles.intersection(("implementer", "frontend-implementer", "gate", "review-primary", "review-control")):
        return "awaiting_implementation"
    if "gate" not in roles: return "awaiting_gate"
    if not {"review-primary", "review-control"} <= roles: return "awaiting_review"
    return "awaiting_commit"


def final_facts(state, phases, committed):
    require({p["id"] for p in phases} <= {f["phase"] for f in state["phase_commits"]}, "uncommitted phases", 2)
    need(state["final"], ("review", "delivery"))
    require(state["step"] == "completion" and state["plan"] and re.search(r"^status: done\r?$", ref(state["plan"]), re.M), "final bookkeeping is incomplete", 2)
    plan_name = str(Path(state["plan"]["path"]).relative_to(state["worktree"])).replace(os.sep, "/")
    without_plan = lambda files: {k: val for k, val in files.items() if k != "repo:" + plan_name}
    for stage, role in (("review", "review-final"), ("delivery", "gate")):
        reports = state["final"][stage]
        require(reports and all(p.get("role") == role for p in reports), "unfinished final " + stage, 2)
        previous = copy.deepcopy(state); previous["accepted"] = reports
        previous["step"] = "final-review" if stage == "review" else "delivery"
        before = artifact(reports[0]["artifact"], state, current=False)
        covered(previous, before, [role])
        require(without_plan(before["files"]) == without_plan(committed["files"]), "final proof covers different implementation")


def validate(data):
    need(data, ("schema_version", "action", "state"))
    require(data["schema_version"] == 1, "unsupported input schema", 2)
    state = copy.deepcopy(data["state"])
    need(state, ("schema_version", "mode", "plan", "ledger", "orca_run", "plan_base", "phase", "base", "step", "worktree", "worktree_id", "workspace", "active", "rounds", "format_corrections", "accepted", "processed", "open_ledger_ids", "write_ownership", "phase_commits", "commit_barrier", "final", "provenance"))
    require(state["schema_version"] == 1, "legacy resume is unverifiable", 2)
    require(state["mode"] in ("plan", "quickfix") and state["step"] in ("bootstrap", "plan", "phase", "quickfix", "final-review", "delivery", "completion"), "invalid protocol mode/step")
    require(Path(state["worktree"]).is_absolute() and Path(state["workspace"]).is_absolute(), "absolute workspace required")
    starting = state["step"] == "bootstrap"
    if starting:
        request = bootstrap(state)
        require(data["action"] in ("resume", "dispatch", "bind-dispatch", "accept-report", "format-correction"), "bootstrap action is not authorized")
        if data["action"] in ("dispatch", "format-correction"):
            require(data.get("proposed", {}).get("role") == "plan-writer" and data["proposed"]["round"] == 1 and
                    (not Path(request["plan_path"]).exists() or state["plan"] or
                     (data["action"] == "format-correction" and data.get("plan"))), "bootstrap permits only first plan-writer before plan exists")
    if data.get("plan") and data["plan"] != state["plan"]:
        author_result = data["action"] in ("accept-report", "format-correction") and (state["active"] or {}).get("role") in ("plan-writer", "plan-reviser")
        expected_path = request["plan_path"] if starting else state["plan"]["path"]
        require(data["plan"]["path"] == expected_path and (author_result or (not starting and state["active"] is None and
                (not state["accepted"] or state["step"] == "completion"))), "plan change after frozen assignment")
        state["plan"] = data["plan"]
    phases = plan_facts(state)
    track_facts(state, phases)
    for sha in (state["plan_base"], state["base"]):
        require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha), "missing recorded base", 2)
        v.git(state["worktree"], "cat-file", "-e", sha + "^{commit}")
    for key, cap in CAPS.items():
        require(type(state["rounds"].get(key)) is int and 0 <= state["rounds"][key] <= cap, "round cap: " + key)
    require(all(type(n) is int and 0 <= n <= 1 for n in state["format_corrections"].values()), "format-correction cap")
    for previous in state.get("report_history", state["accepted"]): ref(previous["report"])
    for previous in state.get("protected_reports", []): ref(previous)
    ledger_facts(state)
    for fact in state["phase_commits"]: commit_fact(fact, state)
    if state["commit_barrier"].get("confirmed_sha"):
        facts = state["phase_commits"] + ([state["final"]["completion"]] if "completion" in state["final"] else [])
        require(any(f["sha"] == state["commit_barrier"]["confirmed_sha"] for f in facts), "unverified commit barrier", 2)
        if state["step"] == "completion": final_facts(state, phases, commit_fact(state["final"]["completion"], state))
    action = data["action"]; decision = "accepted"
    if action == "accept-report":
        active = state["active"]; require(active is not None, "no current Dispatch", 2)
        raw = record(data.get("event")); require(raw.get("ok") is True, "Orca did not accept event", 2)
        result = raw.get("result", {})
        if "message" in result: messages = [result["message"]]; delivery = None
        else: messages = result.get("messages", []); delivery = result.get("deliveryId")
        if not messages and result.get("timedOut") is True: return state, "not-completion"
        all_messages = messages
        messages = [m for m in messages if m.get("id") == data.get("message_id")]
        require(len(messages) == 1, "missing exact delivery message", 2)
        msg = messages[0]; payload = msg.get("payload")
        if isinstance(payload, str): payload = json.loads(payload)
        payload = payload or {}
        if msg["id"] in state["processed"]["messages"]:
            if delivery and delivery not in state["processed"]["deliveries"] and all(m["id"] in state["processed"]["messages"] for m in result.get("messages", [])):
                state["processed"]["deliveries"].append(delivery)
            return state, "duplicate"
        require(delivery not in state["processed"]["deliveries"] or delivery is None, "unprocessed message in an acknowledged delivery")
        def processed():
            state["processed"]["messages"].append(msg["id"])
            if delivery and all(m["id"] in state["processed"]["messages"] for m in all_messages): state["processed"]["deliveries"].append(delivery)
        if msg.get("type") != "worker_done":
            processed(); return state, "not-completion"
        if (msg.get("run_id"), payload.get("taskId"), payload.get("dispatchId")) != (state["orca_run"], active["task_id"], active["dispatch_id"]):
            processed(); return state, "stale"
        observed = observation(data.get("observation"), active)
        require(observed["dispatch"]["status"] == "completed" and observed["projection"].get("evidence", {}).get("durable") is True, "missing durable settlement", 2)
        require(msg.get("from_handle") == observed["dispatch"]["assigneeHandle"], "wrong report sender")
        report = data.get("report"); text = ref(report)
        require(not any(r["report"]["path"] == report["path"] for r in state.get("report_history", state["accepted"])) and
                not any(r["path"] == report["path"] for r in state.get("protected_reports", [])), "report path already bound to a prior attempt")
        require(payload.get("reportPath") == report["path"] and msg.get("subject") == text.splitlines()[0], "report path/subject mismatch")
        art = artifact(data.get("artifact"), state)
        if active["role"] not in WRITE:
            require(active.get("artifact_id") == art["id"] and active.get("snapshot_id") == art["snapshot_id"], "assigned artifact changed")
        token, findings, coverage = report_fields(text, active, art, payload.get("outcome"), payload.get("filesModified", []))
        if starting and token not in ("BLOCKED", "NEEDS_AUTHORIZATION"):
            require(token == "PLAN_WRITTEN" and state["plan"] is not None and data["artifact"]["kind"] == "plan", "bootstrap writer must deliver the real plan")
            state["step"] = "plan"
        lock = state.get("format_lock")
        if lock:
            require((art["id"], art["snapshot_id"], active["role"], active["round"]) == (lock["artifact_id"], lock["snapshot_id"], lock["role"], lock["round"]), "format correction changed substantive artifact")
        actual_family = family(observed)
        if active["role"] in REVIEW and active["role"] != "plan-reviewer": independent(art, coverage, actual_family, state["provenance"])
        proofs = evidence(text, art) if active["role"] == "gate" and token == "GATE_OK" else []
        accepted = dict(role=active["role"], token=token, family=actual_family, step=state["step"], artifact_id=art["id"], snapshot_id=art["snapshot_id"], binding=active, outcome=payload["outcome"], modified=payload.get("filesModified", []),
                        report=report, artifact=data["artifact"], observation=data["observation"], findings=findings, coverage=coverage, evidence=proofs)
        if active["role"] == "plan-reviewer":
            require(state["provenance"], "unknown plan authors", 2)
            for author in state["provenance"]:
                require(family(record(author)["result"], author.get("start")) != actual_family, "same-family plan review")
        if active["role"] in WRITE:
            state["provenance"].append(data["observation"])
        if "report_history" not in state: state["report_history"] = copy.deepcopy(state["accepted"])
        same_round_fix = (not starting and active["role"] in WRITE and active.get("fix") is True and
                          token in ("DONE", "DONE_WITH_CONCERNS", "REVISED"))
        state["accepted"] = [r for r in state["accepted"] if not (r["role"] == active["role"] and
            (r["binding"]["round"] < active["round"] or (same_round_fix and r["step"] == state["step"] and
             r["binding"]["phase"] == active["phase"] and r["binding"]["round"] == active["round"])))]
        state["accepted"].append(accepted)
        state.setdefault("report_history", []).append(copy.deepcopy(accepted))
        state["processed"]["messages"].append(msg["id"])
        # A delivery is ackable only after every message it contains was handled.
        if delivery and all(m["id"] in state["processed"]["messages"] for m in result.get("messages", [])):
            state["processed"]["deliveries"].append(delivery)
        state["write_ownership"] = [x for x in state["write_ownership"] if x != active["dispatch_id"]]
        if any(f.get("risk") in ("SECURITY", "DATA_LOSS") for f in findings): decision = "risk-escalation"
    elif action == "bind-dispatch":
        active = state["active"]; require(active and active["dispatch_id"] is None, "no pending dispatch intent")
        raw = record(data.get("observation")); require(raw.get("ok") is True, "unsuccessful Orca observation", 2)
        result = raw["result"]; d = result["dispatch"]
        require(d.get("taskId") == active["task_id"] and d.get("runId") == state["orca_run"] and d.get("retryOfDispatchId") is None, "dispatch does not bind pending fresh Task")
        require(d.get("id") and actual_model(result, data["observation"].get("start")) == active["model"], "actual launch differs from proposal")
        active["dispatch_id"] = d["id"]
        observation(data["observation"], active)
        if active.get("format_corrected"): state["format_corrections"][d["id"]] = 1
        if active["role"] in WRITE: state["write_ownership"] = [d["id"]]
    elif action in ("dispatch", "format-correction"):
        fleet_clear(data, state)
        proposed = data.get("proposed"); need(proposed, ("run_id", "task_id", "dispatch_id", "role", "phase", "round", "worktree_id"))
        require(proposed["role"] in TOKENS and proposed["run_id"] == state["orca_run"] and proposed["phase"] == state["phase"] and proposed["worktree_id"] == state["worktree_id"], "proposed binding mismatch")
        require(type(proposed["round"]) is int and proposed["round"] >= 1, "invalid proposed round")
        require(proposed["task_id"] and proposed["dispatch_id"] is None, "dispatch proposal needs a fresh Task and null not-yet-created Dispatch")
        need(proposed, ("model",))
        art = artifact(data.get("artifact"), state)
        if action == "format-correction":
            old = state["active"]; require(old is not None, "missing defective assignment", 2)
            key = old["dispatch_id"]; require(state["format_corrections"].get(key, 0) == 0, "format-correction exhausted")
            settled = observation(data.get("observation"), old)
            require(settled["dispatch"]["status"] == "completed", "format correction before settlement", 2)
            if old["role"] in WRITE:
                old.update(artifact_id=art["id"], snapshot_id=art["snapshot_id"])
            require(old.get("artifact_id") == art["id"] and old.get("snapshot_id") == art["snapshot_id"], "format correction changed original artifact")
            bad = ref(data.get("report"))
            try: report_fields(bad, old, art, data.get("outcome"), data.get("files_modified", []))
            except Rejected as e: require(str(e).startswith("format:"), "not a format-only defect")
            else: raise Rejected("report has no format defect")
            require(proposed["role"] == old["role"] and proposed["round"] == old["round"] and proposed["dispatch_id"] != old["dispatch_id"], "format correction requires one new same-role Dispatch")
            state["format_corrections"][key] = 1; proposed["format_corrected"] = True
            state.setdefault("protected_reports", []).append(data["report"])
            state["format_lock"] = dict(artifact_id=art["id"], snapshot_id=art["snapshot_id"], role=old["role"], round=old["round"])
        else:
            state.pop("format_lock", None)
            group = {"plan-reviewer": "plan_review", "review-primary": "fused_review", "review-control": "fused_review", "review-final": "final_review"}.get(proposed["role"])
            if proposed.get("gate_fix"): group = "gate_fix"
            if group:
                count = state["rounds"][group]
                require(proposed["round"] in (count, count + 1) and proposed["round"] <= CAPS[group], "round cap/sequence: " + group)
                state["rounds"][group] = proposed["round"]
                prior = [r for r in state["accepted"] if r["role"] == proposed["role"] and r["binding"]["round"] == proposed["round"]]
                require(not any(r["family"] == family({"projection": {"provider": {"model": proposed["model"]}}}) for r in prior), "substantive review needs a new round")
            if proposed["role"] in REVIEW and proposed["role"] != "plan-reviewer":
                independent(art, proposed.get("coverage", {}), family({"projection": {"provider": {"model": proposed["model"]}}}), state["provenance"])
        proposed.update(artifact_id=art["id"], snapshot_id=art["snapshot_id"])
        state["active"] = proposed
        if proposed["role"] in WRITE: state["write_ownership"] = ["pending:" + proposed["task_id"]]
    elif action == "finish-checkpoint":
        fleet_clear(data, state); require(not state["open_ledger_ids"], "open accepted findings")
        art = artifact(data.get("artifact"), state)
        require(state["step"] in ("final-review", "delivery"), "not a final checkpoint")
        require({p["id"] for p in phases} <= {f["phase"] for f in state["phase_commits"]}, "uncommitted phases", 2)
        role = "review-final" if state["step"] == "final-review" else "gate"
        covered(state, art, [role])
        key = "review" if role == "review-final" else "delivery"
        state["final"][key] = [r for r in state["accepted"] if r["step"] == state["step"] and r["role"] == role]
        state["step"] = "delivery" if key == "review" else "completion"
        state["active"] = None; state["commit_barrier"] = {}
    elif action in ("prepare-commit", "confirm-commit", "advance", "complete"):
        fleet_clear(data, state)
        require(not state["open_ledger_ids"], "open accepted ledger findings")
        art = artifact(data.get("artifact"), state, current=action == "prepare-commit")
        require(not v.text_git(state["worktree"], "diff", "--no-ext-diff", "--name-only", "--"), "hook/working-tree or unstaged source after acceptance")
        roles = ["quickfix"] if state["mode"] == "quickfix" else (["plan-reviewer"] if state["phase"] is None else ["gate", "review-primary", "review-control"])
        if state["step"] in ("final-review", "delivery", "completion"):
            roles = ["review-final"] if state["step"] == "final-review" else ["gate"]
        covered(state, art, roles)
        for accepted in state["accepted"]:
            for proof in accepted.get("evidence", []):
                require(v.evidence_valid(record(proof)), "accepted evidence no longer valid")
        if action == "prepare-commit":
            state["commit_barrier"] = dict(expected_snapshot=art["snapshot_id"], expected_sha=None, confirmed_sha=None)
        else:
            fact = data.get("commit"); committed = commit_fact(fact, state)
            require(committed["snapshot_id"] == art["snapshot_id"], "commit artifact differs from accepted candidate")
            current = v.snapshot(state["worktree"], data["artifact"].get("inputs", []), json.loads(ref(fact["artifact"]))["manifest"]["exclusions"] if fact["artifact"]["kind"] == "snapshot" else json.loads(ref(fact["artifact"]))["snapshot_after"]["manifest"]["exclusions"])
            require(current["valid"] and current["manifest"]["files"] == committed["files"], "hook/working-tree change after acceptance")
            state["commit_barrier"] = dict(expected_snapshot=art["snapshot_id"], expected_sha=fact["sha"], confirmed_sha=fact["sha"])
            if state["step"] in ("phase", "plan", "quickfix") and not any(x["sha"] == fact["sha"] for x in state["phase_commits"]):
                state["phase_commits"].append(dict(fact, phase=state["phase"]))
            if action == "advance":
                ids = [p["id"] for p in phases]; index = ids.index(state["phase"]) if state["phase"] in ids else -1
                state["phase"] = ids[index+1] if index+1 < len(ids) else state["phase"]
                if index+1 < len(ids): state["base"] = fact["sha"]
                state["step"] = "phase" if index+1 < len(ids) else "final-review"
                state["accepted"] = []; state["commit_barrier"] = {}; state["active"] = None
                state["rounds"]["fused_review"] = 0; state["rounds"]["gate_fix"] = 0
            if action == "complete":
                require(fact["sha"] not in {f["sha"] for f in state["phase_commits"]}, "completion requires a separate commit")
                final_facts(state, phases, committed)
                state["final"]["completion"] = fact
    elif action == "resume":
        if not state["commit_barrier"].get("confirmed_sha"):
            for accepted in state["accepted"]:
                if accepted["step"] == state["step"]: artifact(accepted["artifact"], state)
    else: raise Rejected("unknown action")
    state["barrier"] = barrier(state, phases)
    return state, decision


def main(args):
    state = None
    try:
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
        print("INVALID" if e.code == 1 else "UNVERIFIABLE")
        next_action = e.next_action
        if str(e).startswith("format:"):
            old = data.get("state", {}); active = old.get("active") or {}
            next_action = "format-correction" if not old.get("format_corrections", {}).get(active.get("dispatch_id"), 0) else "protocol-blocker"
        print(json.dumps(dict(reason=str(e), next_action=next_action)))
        return e.code
    except (OSError, ValueError, TypeError, KeyError, AttributeError, v.subprocess.SubprocessError) as e:
        print("UNVERIFIABLE"); print(json.dumps(dict(reason=str(e), next_action="supply-bound-facts")))
        return 2


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))

"""C6 facts: read-only parsers of hashed inputs (reports, plan, artifacts, fleet pages, C4 evidence,
Orca observations and actual-model proof). Every protocol decision lives in protocol_state.py."""
import json
import copy
import os
from pathlib import Path
import re

import verification as v
from posix_runtime import artifact_path


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
# Plan bookkeeping lines that may move without the plan author/review path.
META = re.compile(r"^(?:status|plan_base|orca_run|commits|    status|    base|    commits):.*(?:\n|$)", re.M)


def report_fields(text, active, art, outcome, modified):
    """The worker report contract: verdict token, BINDING = live assignment, role sections and findings."""
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
    findings = []
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
        # An explicitly empty section ("CANNOT_VERIFY: []" or a bare header) states none.
        stated = re.sub(r"^CANNOT_VERIFY:[ \t]*(\[\])?[ \t]*$", "", text, flags=re.M)
        require("CANNOT_VERIFY" not in stated or any(f["kind"] == "cannot_verify" for f in findings), "format: unstructured CANNOT_VERIFY")
    if role in ("implementer", "frontend-implementer", "quickfix") and (active["round"] > 1 or active.get("fix")):
        fix = line_json(text, "FIX_EVIDENCE")
        require(isinstance(fix, dict) and all(fix.get(k) for k in ("tests", "commands", "outputs")), "format: fix evidence")
    if role == "quickfix": require(len(modified) == 1, "quickfix must modify exactly one file")
    if role == "gate":
        require(len(rows) > 1 and (rows[1].startswith("verify: ") or re.match(r"^lint: .+ \| typecheck: .+ \| tests: .+", rows[1])), "format: gate summary")
    if role == "synthesizer": require(len(rows) > 1 and rows[1].startswith("docs/reviews/"), "format: synthesis path")
    if role == "diagnosis":
        sections = {"NEEDS_MORE_CONTEXT": "Context", "NEEDS_MORE_REASONING": "Context", "PHASE_TOO_LARGE": "Split", "PLAN_WRONG": "Plan defect", "IMPASSE_SUMMARY": "Summary"}
        require("## " + sections[token] in text and "## Evidence" in text, "format: diagnosis sections")
    return token, findings, line_json(text, "COVERAGE", {})


def plan_read(text):
    """Plan frontmatter: structure digest (bookkeeping lines removed), run/base scalars and phase contracts."""
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", text, re.S)
    require(match is not None, "missing plan frontmatter", 2)
    front = match[1]
    def scalar(name):
        found = re.findall(r"^" + name + r":\s*(.*?)\s*$", front, re.M)
        require(len(found) == 1, "missing plan metadata: " + name, 2)
        return v.unquote(found[0])
    shape = v.digest((META.sub("", front) + "\0" + text[match.end():]).encode("utf-8"))
    require(scalar("protocol_version") == "2", "legacy metadata is not certified", 2)
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
    return dict(shape=shape, orca_run=scalar("orca_run"), plan_base=scalar("plan_base"), phases=phases,
                done=re.search(r"^status: done[ \t]*$", front, re.M) is not None)


def plan_name(state):
    if state["plan"] is None: return None
    path, root = artifact_path(state["plan"]["path"]), artifact_path(state["worktree"])
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else None


def entry(x):
    """A repository entry's identity: its bytes (or type) and the Git executable bit of its index entry."""
    value = x.get("sha256", x["type"])
    return value + "+x" if (x.get("index") or [None])[0] == "100755" else value


def synthesis(state):
    """Accepted synthesis documents of this step: {path: entry}. Each summarises an acceptance and is frozen by it."""
    return {r["synthesis"]["path"]: r["synthesis"]["entry"] for r in state["accepted"] if r.get("synthesis")}


def candidate(files, state):
    """Candidate identity: repository entries (bytes + executable bit); no HEAD, exclusions, staging, declared inputs,
    plan file or accepted synthesis document."""
    skip = {plan_name(state)} | set(synthesis(state))
    entries = {k[5:]: entry(x) for k, x in files.items()
               if k.startswith("repo:") and x["type"] != "missing" and k[5:] not in skip}
    return v.digest(v.encoded(entries))


def fresh(state, art):
    now = v.snapshot(state["worktree"], [], art["exclusions"])
    require(now["valid"] and candidate(now["manifest"]["files"], state) == art["candidate"], "stale artifact: the working tree is no longer this candidate")
    # A synthesizer assignment replaces the frozen synthesis: its own dispatch and acceptance do not re-check the old bytes.
    if (state.get("active") or {}).get("role") == "synthesizer": return now
    for path, value in synthesis(state).items():
        x = now["manifest"]["files"].get("repo:" + path)
        require(x is not None and entry(x) == value, "stale synthesis: " + path)
    return now


def step_base(state):
    return state["plan_base"] if state["step"] in ("final-review", "delivery", "completion") else state["base"]


def package_bound(obj, m, state):
    """A package reviews the step's diff: from the step base, and a range package's candidate is its reviewed tree."""
    require(obj["base"] == step_base(state), "package base differs from the step base")
    if obj["mode"] != "range": return
    root = state["worktree"]; skip = {plan_name(state)} | set(synthesis(state))
    tracked = all("index" in x for k, x in m["files"].items() if k.startswith("repo:") and x["type"] != "missing" and k[5:] not in skip)
    dirty = [p for p in v.git(root, "diff", "--no-ext-diff", "--name-only", "-z", obj["head"], "--").decode("utf-8").split("\0") if p and p not in skip]
    require(tracked and not dirty and obj["head"] == m["head"] == v.text_git(root, "rev-parse", "HEAD"), "range package differs from its reviewed tree")


def artifact(refspec, state, current=False):
    """A plan, C4 snapshot or C5 package reference; current=None admits a missing artifact (first plan writer)."""
    if refspec is None and current is None: return dict(kind=None, id=None, snapshot_id=None, candidate=None, manifest=None, files=None)
    kind = (refspec or {}).get("kind"); raw = ref(refspec)
    if kind == "plan":
        if current: require(state["plan"] is not None and refspec["sha256"] == state["plan"]["sha256"] and
                            refspec.get("source_path", refspec["path"]) == state["plan"]["path"], "assigned plan mismatch")
        return dict(kind=kind, id=refspec["sha256"], snapshot_id=None, candidate=refspec["sha256"], manifest=None, files=None)
    obj = json.loads(raw)
    if kind == "package":
        identity = dict(obj); pid = identity.pop("package_id", None)
        require(obj.get("complete") is True and v.digest(v.encoded(identity)) == pid, "incomplete package", 2)
        snap = obj["snapshot_after"]; aid = pid
    else:
        require(kind == "snapshot" and obj.get("valid") is True, "invalid snapshot", 2)
        snap = obj; aid = obj["snapshot_id"]
    m = snap["manifest"]
    require(artifact_path(m["root"]) == artifact_path(state["worktree"]), "artifact worktree mismatch")
    art = dict(kind=kind, id=aid, snapshot_id=snap["snapshot_id"], candidate=candidate(m["files"], state), head=m["head"],
               exclusions=m["exclusions"], manifest=obj if kind == "package" else None, files=m["files"])
    if current:
        fresh(state, art)
        if kind == "package": package_bound(obj, m, state)
    return art


def manifest_files(refspec):
    """The captured files of a snapshot or package reference; None for a plan or an absent artifact."""
    if not isinstance(refspec, dict) or refspec.get("kind") not in ("snapshot", "package"): return None
    obj = record(refspec)
    return (obj["snapshot_after"] if refspec["kind"] == "package" else obj)["manifest"]["files"]


def fleet_workers(data, used):
    """All worker rows of one complete, unused, all-Run worker-list collection, plus its receipt ids."""
    need(data, ("fleet",))
    require(isinstance(data["fleet"], list) and data["fleet"], "missing fresh fleet", 2)
    workers = []; cursor = None; total = None; receipt_ids = []
    for page in data["fleet"]:
        require(page.get("cursor") == cursor, "fleet cursor mismatch", 2)
        raw = record(page); require(raw.get("ok") is True, "fleet unavailable", 2)
        require(raw.get("id") and raw["id"] not in used, "fleet observation already used", 2)
        receipt_ids.append(raw["id"])
        result = raw["result"]; need(result, ("workers", "page", "scope"))
        require(result["scope"].get("source") == "all", "fleet must cover all local runs", 2)
        paging = result["page"]; require(total is None or total == paging["total"], "inconsistent fleet", 2)
        total = paging["total"]; workers.extend(result["workers"])
        cursor = paging["nextCursor"] if paging["hasMore"] else None
    require(cursor is None and len(workers) == total and len({w["dispatchId"] for w in workers}) == total, "incomplete fleet", 2)
    return workers, receipt_ids


def authors(art, provenance):
    """Actual author families per file of a complete package, from its write receipts."""
    m = art["manifest"]
    require(m is not None, "review requires a complete package", 2)
    writers = {}
    for write in m["provenance"].get("writes", []):
        observed = record({"path": write["receipt_path"], "sha256": write["receipt_sha256"]}).get("result", {})
        d = observed.get("dispatch", {})
        require((d.get("id"), d.get("taskId"), d.get("runId")) == (write["dispatch_id"], write["task_id"], write["run_id"]), "unknown write provenance", 2)
        source = next((r for r in provenance if r["path"] == write["receipt_path"] and r["sha256"] == write["receipt_sha256"]), None)
        actual = family(observed, source)
        require(actual == write["family"], "claimed author family differs from launch")
        for path in write["files"]: writers.setdefault(path, set()).add(actual)
    return writers


def gate_records(records, art, state):
    """Sealed C4 results of the candidate's bytes; returns (passed, failures not proven inherited from BASE)."""
    require(isinstance(records, list) and records, "missing executable evidence", 2)
    passed = failed = 0
    for item in records:
        st = record(item)
        require(v.evidence_valid(st), "stale or invalid runner evidence")
        e = st["evidence"]
        require(candidate(e["source_after"]["manifest"]["files"], state) == art["candidate"], "evidence snapshot mismatch")
        if e["key"]["check"]["independent_replay"]: require(not e.get("origin_run_id"), "required replay reused implementer evidence")
        if st["exit_code"] == 0: passed += 1
        elif item.get("baseline") is None: failed += 1
        else:
            base = record(item["baseline"])
            require(v.evidence_valid(base) and base["evidence"]["key"]["provenance"]["kind"] == "BASE" and
                    base["exit_code"] != 0 and base["evidence"]["failure_signature"] == e["failure_signature"], "unproven inherited failure")
    return passed, failed


def evidence_records(records, art, state):
    """GATE_OK evidence: at least one pass, every failure proven inherited from BASE."""
    passed, failed = gate_records(records, art, state)
    require(not failed, "unproven inherited failure")
    require(passed > 0, "zero passing checks")
    return records


def failure_records(records, art, state):
    """GATE_FAIL evidence: at least one failure of the candidate that BASE does not explain."""
    require(gate_records(records, art, state)[1] > 0, "zero failing checks")
    return records


EXPECT = re.compile(r"exit (\d+)(?!\d)(.*)", re.S)
STDOUT = re.compile(r"; stdout (exactly|contains): (.*)", re.S)


def ran(item, finding, key="execution_evidence"):
    """The finding's literal CHECK actually ran: the ledger field holds an intact sealed run-check result (absolute path,
    or {path, sha256} whose hash must match) of exactly that command. Its outcome is not interpreted here."""
    ref_ = item.get(key); path = ref_.get("path") if isinstance(ref_, dict) else ref_
    try:
        if not (isinstance(path, str) and Path(path).is_absolute()): return False
        if isinstance(ref_, dict) and v.digest(Path(path).read_bytes()) != ref_.get("sha256"): return False
        result = v.load(path)
    except (OSError, ValueError): return False
    return isinstance(result, dict) and v.evidence_valid(result) and result["evidence"]["key"]["check"]["command"] == finding.get("check")


def checked(item, finding, key="check"):
    """A cannot_verify finding is checked by the sealed run-check result of its literal CHECK command that exited with the
    code its EXPECT states (`exit <n>` first). Only the explicit `; stdout exactly|contains: <text>` form is matched against
    the sealed stdout; any other text after the exit code is the human-checked part of the expectation (existing reports
    such as `exit 0; stdout — …`). The original candidate's bytes are not compared. `key` names the ledger field holding
    the result: an absolute path, or a {path, sha256} reference whose hash must match."""
    ref_ = item.get(key); path = ref_.get("path") if isinstance(ref_, dict) else ref_
    try:
        if not (isinstance(path, str) and Path(path).is_absolute()): return False
        if isinstance(ref_, dict) and v.digest(Path(path).read_bytes()) != ref_.get("sha256"): return False
        result = v.load(path)
    except (OSError, ValueError): return False
    if not (isinstance(result, dict) and v.evidence_valid(result)): return False
    want = EXPECT.fullmatch(str(finding.get("expect", "")).strip())
    if want is None or result["evidence"]["key"]["check"]["command"] != finding.get("check") or result["exit_code"] != int(want[1]): return False
    stdout = STDOUT.fullmatch(want[2])
    if stdout is None: return True
    try: out = Path(result["stdout_log"]).read_bytes().decode("utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError): return False
    return out.rstrip("\n") == stdout[2] if stdout[1] == "exactly" else stdout[2] in out


def values(obj):
    if isinstance(obj, dict): return [x for item in obj.values() for x in values(item)]
    if isinstance(obj, list): return [x for item in obj for x in values(item)]
    return [obj]


ORCA_PREAMBLE = "You are working inside Orca, a multi-agent IDE. You are a dispatched worker."


def roles_fact(label):
    return line_json((Path(__file__).parents[2] / "skills/orca-dev/roles.md").read_text(encoding="utf-8-sig"), label)


def model_matches(proposed, actual):
    # A Claude CLI alias names a model tier; the transcript records its full id.
    prefix = roles_fact("MODEL_ALIASES").get(proposed)
    return proposed == actual or (prefix is not None and actual.startswith(prefix))


def launched_receipt(start, d):
    raw = record(start); require(raw.get("ok") is True, "unsuccessful worker-start receipt", 2)
    launched = raw.get("result", {})
    need(launched, ("runId", "taskId", "dispatchId", "launch"))
    require((launched["runId"], launched["taskId"], launched["dispatchId"]) ==
            (d.get("runId"), d.get("taskId"), d.get("id")), "worker-start identity mismatch")
    return launched


def launch_terminal(launched, action):
    rows = [e for e in launched.get("effects") or [] if e.get("kind") == "terminal" and e.get("role") == "agent"]
    require(len(rows) == 1 and rows[0].get("action") == action and rows[0].get("id"), "terminal launch chain mismatch", 2)
    return rows[0]["id"]


def reused_model(observed, launched, origin):
    """B1: a --terminal reuse inherits the model of the start that created that live process."""
    d = observed.get("dispatch", {}); worker = observed.get("worker") or {}; terminal = observed.get("terminal") or {}
    handle = launch_terminal(launched, "reused")
    require(handle == d.get("assigneeHandle") == worker.get("agentTerminalHandle"), "reused terminal handle mismatch")
    raw = record(origin); require(raw.get("ok") is True, "unsuccessful origin worker-start receipt", 2)
    first = raw.get("result", {}); need(first, ("runId", "dispatchId", "launch"))
    require(first["runId"] == d.get("runId") and first["dispatchId"] != d.get("id"), "origin worker-start run mismatch")
    require(launch_terminal(first, "created") == handle, "origin terminal handle mismatch")
    incarnation = (first.get("prompt") or {}).get("processIncarnation")
    require(isinstance(incarnation, str) and incarnation, "missing terminal incarnation", 2)
    require((launched.get("prompt") or {}).get("processIncarnation") == incarnation and
            terminal.get("handle", handle) == handle and terminal.get("incarnationId", incarnation) == incarnation and
            str(d.get("processIncarnation", ":" + incarnation)).endswith(":" + incarnation), "terminal incarnation changed")
    effective = first["launch"].get("effective") or {}
    require(isinstance(effective.get("model"), str) and effective["model"], "missing origin launch model", 2)
    provider = (observed.get("projection", {}).get("provider") or {}).get("id")
    require(effective.get("agent") == provider, "origin launch agent mismatch")
    return effective["model"]


def preamble_text(row):
    if row.get("type") != "user" or row.get("isSidechain"): return None
    content = (row.get("message") or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return content if isinstance(content, str) and ORCA_PREAMBLE in content else None


def preamble_binds(text, d):
    tasks = re.findall(r"^Your task ID is: (\S+)$", text, re.M)
    dispatches = re.findall(r"--dispatch-id (ctx_[A-Za-z0-9_-]+)", text)
    senders = re.findall(r"--from (term_[A-Za-z0-9_-]+)", text)
    return (tasks == [d.get("taskId")] and dispatches and set(dispatches) == {d.get("id")} and
            senders and set(senders) == {d.get("assigneeHandle")})


def transcript_rows(text):
    rows = []
    for line in text.split("\n"):
        if line.strip():
            row = json.loads(line); require(isinstance(row, dict), "invalid session transcript record", 2); rows.append(row)
    return rows


def within(child, root):
    child, root = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(root))
    return child == root or child.startswith(root.rstrip(os.sep) + os.sep)


def transcript_model(observed, rows, completed_at=None):
    """B2: the only model that answered after this Dispatch's Orca preamble in one Claude session."""
    d = observed.get("dispatch", {}); terminal = observed.get("terminal") or {}
    root = terminal.get("worktreePath")
    require(isinstance(root, str) and os.path.isabs(root) and
            terminal.get("worktreeId") == observed.get("projection", {}).get("workspace", {}).get("id"), "missing Dispatch worktree path", 2)
    starts = [i for i, row in enumerate(rows) if preamble_text(row) is not None and preamble_binds(preamble_text(row), d)]
    require(starts, "no Orca preamble for this Dispatch in Claude transcript", 2)
    session = rows[starts[0]].get("sessionId"); models = set(); through_completion = False
    for row in rows[starts[0]:]:
        text = preamble_text(row)
        if text is not None and not preamble_binds(text, d): break  # the next Dispatch owns the rest
        require(row.get("sessionId", session) == session, "Claude transcript session changed")
        if row.get("cwd") is not None: require(within(row["cwd"], root), "Claude transcript cwd outside Dispatch worktree")
        if completed_at is not None and not through_completion and row.get("timestamp") is not None:
            through_completion = utc_seconds(row["timestamp"]) >= utc_seconds(completed_at)
        if row.get("type") == "assistant":
            model = (row.get("message") or {}).get("model")
            if model != "<synthetic>": models.add(model)  # local error/interrupt stubs have no author
    require(len(models) <= 1, "conflicting actual model facts")
    model = next(iter(models), None)
    require(isinstance(model, str) and model, "no model response after Orca preamble", 2)
    require(completed_at is None or through_completion, "model proof does not cover Dispatch completion", 2)
    return model


def agy_preamble_text(row):
    content = row.get("content") if row.get("type") == "USER_INPUT" else None
    return content if isinstance(content, str) and ORCA_PREAMBLE in content else None


def agy_log_model(text, conversation):
    """One Antigravity CLI process log: it created this conversation and resolved exactly one model."""
    require(conversation in re.findall(r"\] Created conversation ([0-9a-f-]+)[ \t]*$", text, re.M),
            "Antigravity log does not own this conversation", 2)
    models = set(re.findall(r"\] Resolving model (\S+)[ \t]*$", text, re.M))
    require(len(models) <= 1, "conflicting actual model facts")
    require(models, "no resolved model in Antigravity log", 2)
    return next(iter(models))


def evidence_model(observed, proof):
    provider = observed.get("projection", {}).get("provider") or {}
    require(provider.get("model") is None, "model evidence only for an unreported model")
    kind = proof.get("kind")
    if kind == "claude-transcript":
        require(provider.get("id") == "claude", "model evidence kind does not match provider")
        return transcript_model(observed, transcript_rows(ref(proof)))
    require(kind == "antigravity-log", "unknown model evidence kind", 2)
    require(provider.get("id") == "antigravity", "model evidence kind does not match provider")
    need(proof, ("log", "conversation_id"))
    rows = transcript_rows(ref(proof))
    require(any(agy_preamble_text(r) is not None and preamble_binds(agy_preamble_text(r), observed.get("dispatch", {})) for r in rows),
            "no Orca preamble for this Dispatch in Antigravity transcript", 2)
    return agy_log_model(ref(proof["log"]).replace("\r", ""), proof["conversation_id"])


def actual_model(observed, source=None):
    source = source or {}
    model = (observed.get("projection", {}).get("provider") or {}).get("model")
    start = source.get("start"); origin = source.get("origin_start"); proof = source.get("model_evidence")
    require(origin is None or start is not None, "origin worker-start without current worker-start")
    require(proof is None or (start is None and origin is None), "model evidence with a launch receipt")
    effective = None
    if start is not None:
        launched = launched_receipt(start, observed.get("dispatch", {}))
        effective = (launched["launch"].get("effective") or {}).get("model")
        if origin is not None:
            require(not any((launched["launch"].get("effective") or {}).values()), "origin chain needs a --terminal reuse")
            effective = reused_model(observed, launched, origin)
        require(isinstance(effective, str) and effective, "missing effective launch model", 2)
    elif proof is not None:
        effective = evidence_model(observed, proof)
    if effective is not None:
        require(model is None or model == effective, "conflicting actual model facts")
        if model is None: model = effective
    require(model is not None, "unknown actual model family", 2)
    return model


def family(observation, source=None):
    model = actual_model(observation, source)
    mapping = roles_fact("FAMILY_MODELS")
    if model not in mapping:
        # Full provider ids from verified transcripts; aliases stay explicit above.
        prefix = [f for p, f in roles_fact("FAMILY_PREFIXES").items() if re.fullmatch(re.escape(p) + r"[a-z0-9][a-z0-9.-]*", model)]
        require(len(prefix) == 1, "unknown actual model family: " + model, 2)
        return prefix[0]
    return mapping[model]


def recovered_observation(current, active, bound, binding=None):
    """An accept-only view. Current settlement/identity are never imported from history."""
    d = current["dispatch"]; projection = current["projection"]
    require(d.get("status") == "completed" and (projection.get("evidence") or {}).get("durable") is True,
            "missing durable settlement", 2)
    require(active.get("dispatch_id"), "recovery requires an already bound Dispatch", 2)
    original = active.get("bound_observation")
    if original is None:
        saved = record(binding); need(saved, ("action", "observation"))
        require(saved["action"] == "bind-dispatch", "recovery requires original bind-dispatch")
        original = saved["observation"]
    elif binding is not None:
        saved = record(binding); need(saved, ("action", "observation"))
        require(saved["action"] == "bind-dispatch" and saved["observation"] == original, "conflicting original bind-dispatch")
    require(original == bound, "bound observation differs from original bind-dispatch")
    old = record(bound); require(old.get("ok") is True, "unsuccessful bound observation", 2)
    prior = old.get("result"); need(prior, ("dispatch", "projection", "terminal"))
    previous = prior["dispatch"]; need(previous, ("id", "taskId", "runId", "assigneeHandle", "processIncarnation"))
    for key in ("id", "taskId", "runId", "assigneeHandle", "processIncarnation"):
        require(isinstance(d.get(key), str) and d[key] and isinstance(previous.get(key), str) and previous[key],
                "missing recovery identity: " + key, 2)
        require(d[key] == previous[key], "bound observation identity mismatch: " + key)
    require(previous.get("status") in ("dispatched", "running", "completed"), "bound observation is not a launched Dispatch")
    for receipt in (current, prior):
        dispatch = receipt["dispatch"]; worker = receipt.get("worker")
        require(worker is None or isinstance(worker, dict), "malformed recovery worker", 2)
        worker = {} if worker is None else worker
        require(not dispatch.get("failureCount") and not dispatch.get("lastFailure") and not dispatch.get("terminationReason") and
                worker.get("state") != "failed" and not worker.get("lastError"), "failed launch cannot use observation recovery")
    terminal = prior["terminal"]; need(terminal, ("handle", "ptyId", "incarnationId", "worktreeId", "worktreePath"))
    provider = prior["projection"].get("provider"); workspace = prior["projection"].get("workspace")
    need(provider, ("id",)); need(workspace, ("id",))
    require(isinstance(workspace["id"], str) and workspace["id"], "incomplete bound workspace facts", 2)
    require(all(isinstance(terminal[k], str) and terminal[k] for k in ("handle", "ptyId", "incarnationId", "worktreeId", "worktreePath")) and
            isinstance(provider["id"], str) and provider["id"], "incomplete bound terminal/provider facts", 2)
    require(terminal["handle"] == d["assigneeHandle"] and terminal["ptyId"] + ":" + terminal["incarnationId"] == d["processIncarnation"],
            "bound terminal incarnation mismatch")
    require(terminal["worktreeId"] == workspace["id"] == active["worktree_id"] and terminal["worktreePath"] == active["worktree"],
            "bound observation worktree mismatch")
    old_model = actual_model(prior, bound)
    require(isinstance(old_model, str) and old_model, "incomplete bound model facts", 2)
    result = copy.deepcopy(current)
    # Fill identity facts only; stage, outcome, worker state and evidence remain current.
    for target, historic, keys, label in ((result["projection"], provider, ("id", "model"), "provider"),
                                         (result["projection"], workspace, ("id",), "workspace"),
                                         (result, terminal, ("handle", "ptyId", "incarnationId", "worktreeId", "worktreePath"), "terminal")):
        facts = target.get(label)
        require(facts is None or isinstance(facts, dict), "malformed current " + label, 2)
        facts = {} if facts is None else facts; target[label] = facts
        for key in keys:
            value = old_model if label == "provider" and key == "model" else historic.get(key)
            agrees = (isinstance(facts[key], str) and model_matches(value, facts[key])) if label == "provider" and key == "model" and facts.get(key) is not None else facts.get(key) == value
            require(facts.get(key) is None or agrees, "conflicting current " + label + ": " + key)
            if facts.get(key) is None: facts[key] = value
    for receipt in (current, prior):
        worker = receipt.get("worker") or {}
        for key, value in (("agentTerminalHandle", d["assigneeHandle"]), ("worktreeId", active["worktree_id"])):
            require(worker.get(key) is None or worker[key] == value, "conflicting worker " + key)
    return result, old_model


def observation(refspec, active, recovery=None, binding=None):
    raw = record(refspec)
    require(raw.get("ok") is True, "unsuccessful Orca observation", 2)
    result = raw.get("result", {}); need(result, ("dispatch", "projection"))
    d = result["dispatch"]; need(d, ("id", "taskId", "runId", "status", "assigneeHandle"))
    require(d["taskId"] == active["task_id"] and d["runId"] == active["run_id"], "Task/Run observation mismatch")
    require(d["id"] == active["dispatch_id"], "Dispatch observation mismatch")
    if recovery is not None:
        result, old_model = recovered_observation(result, active, recovery, binding)
        # A start-time model does not prove absence of later switches. Require a full frozen session.
        proof = (refspec or {}).get("model_evidence"); need(proof, ("kind", "path", "sha256"))
        require(proof["kind"] == "claude-transcript" and result["projection"]["provider"]["id"] == "claude",
                "recovery requires completion-covering Claude transcript", 2)
        require(refspec.get("start") is None and refspec.get("origin_start") is None, "model evidence with a launch receipt")
        completed_at = result["dispatch"].get("completedAt")
        require(isinstance(completed_at, str) and completed_at, "missing Dispatch completion time", 2)
        model = transcript_model(result, transcript_rows(ref(proof)), completed_at)
        require(model_matches(old_model, model) and model_matches(result["projection"]["provider"]["model"], model),
                "conflicting actual model facts")
        require(model_matches(active["model"], model), "actual completion differs from proposal")
        result["projection"]["provider"]["model"] = model  # verified full id; original receipts stay unchanged
        return result
    require((result["projection"].get("workspace") or {}).get("id") == active["worktree_id"], "observation worktree mismatch", 2)
    result["projection"]["provider"]["model"] = actual_model(result, refspec)
    return result

def known_families():
    return set(roles_fact("FAMILY_MODELS").values()) | set(roles_fact("FAMILY_PREFIXES").values())


def utc_seconds(value):
    require(isinstance(value, str) and value, "missing Dispatch creation time", 2)
    text = value.replace(" ", "T").replace("Z", "+00:00")
    if not re.search(r"[+-]\d\d:\d\d$", text): text += "+00:00"  # Orca SQL timestamps are UTC
    from datetime import datetime
    return datetime.fromisoformat(text).timestamp()


def claude_model_evidence(args):
    """Freeze the one Claude session transcript that proves this Dispatch's model."""
    require(len(args) in (3, 4), "usage: protocol-state claude-model-evidence OBSERVATION_JSON SNAPSHOT_OUT [TRANSCRIPT]")
    raw = v.load(args[1]); require(raw.get("ok") is True, "unsuccessful Orca observation", 2)
    observed = raw.get("result", {}); need(observed, ("dispatch", "projection"))
    provider = observed["projection"].get("provider") or {}
    require(provider.get("id") == "claude" and provider.get("model") is None, "model evidence only for unreported Claude model")
    out = artifact_path(args[2])
    require(Path(args[2]).is_absolute() and out.parent.is_dir() and not out.exists(), "snapshot output must be a new absolute file", 2)
    require(not any(x.is_symlink() for x in (out, *out.parents)), "linked snapshot output", 2)
    if len(args) == 4:
        files = [artifact_path(args[3])]
    else:
        root = (observed.get("terminal") or {}).get("worktreePath")
        require(isinstance(root, str) and os.path.isabs(root), "missing Dispatch worktree path", 2)
        base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"
        folder = base / re.sub(r"[^a-zA-Z0-9]", "-", root)
        since = utc_seconds(observed["dispatch"].get("createdAt")) - 300
        files = sorted(p for p in folder.glob("*.jsonl") if p.is_file() and p.stat().st_mtime >= since)
    found = []
    for path in files:
        data = path.read_bytes()
        rows = transcript_rows(data.decode("utf-8-sig").replace("\r\n", "\n"))
        if any(preamble_text(r) is not None and preamble_binds(preamble_text(r), observed["dispatch"]) for r in rows):
            found.append((path, data, rows))
    require(found, "no Claude transcript with this Dispatch preamble", 2)
    require(len(found) == 1, "several Claude transcripts claim this Dispatch: " + ", ".join(str(x[0]) for x in found), 2)
    path, data, rows = found[0]
    model = transcript_model(observed, rows)
    with out.open("xb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    proof = dict(kind="claude-transcript", path=str(out), sha256=v.digest(data))
    print("VALID"); print(json.dumps(dict(model_evidence=proof, model=model, source=str(path)), ensure_ascii=True))
    return 0


def frozen(path, data):
    with path.open("xb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    return dict(path=str(path), sha256=v.digest(data))


def antigravity_model_evidence(args):
    """Freeze the Antigravity conversation transcript bound to this Dispatch and its CLI process log."""
    require(len(args) == 3, "usage: protocol-state antigravity-model-evidence OBSERVATION_JSON SNAPSHOT_OUT")
    raw = v.load(args[1]); require(raw.get("ok") is True, "unsuccessful Orca observation", 2)
    observed = raw.get("result", {}); need(observed, ("dispatch", "projection"))
    provider = observed["projection"].get("provider") or {}
    require(provider.get("id") == "antigravity" and provider.get("model") is None, "model evidence only for an unreported model")
    out = artifact_path(args[2]); log_out = Path(str(out) + ".cli.log")
    require(Path(args[2]).is_absolute() and out.parent.is_dir() and not out.exists() and not log_out.exists(),
            "snapshot output must be a new absolute file", 2)
    require(not any(x.is_symlink() for x in (out, *out.parents)), "linked snapshot output", 2)
    home = Path(os.environ.get("ORCA_AGY_HOME") or Path.home() / ".gemini" / "antigravity-cli")
    since = utc_seconds(observed["dispatch"].get("createdAt")) - 300
    found = []
    for path in sorted((home / "brain").glob("*/.system_generated/logs/transcript.jsonl")):
        if path.stat().st_mtime < since: continue
        data = path.read_bytes(); rows = transcript_rows(data.decode("utf-8-sig").replace("\r\n", "\n"))
        if any(agy_preamble_text(r) is not None and preamble_binds(agy_preamble_text(r), observed["dispatch"]) for r in rows):
            found.append((path.parents[2].name, data))
    require(found, "no Antigravity transcript with this Dispatch preamble", 2)
    require(len(found) == 1, "several Antigravity conversations claim this Dispatch: " + ", ".join(x[0] for x in found), 2)
    conversation, transcript = found[0]
    logs = [(p, p.read_bytes()) for p in sorted((home / "log").glob("*.log")) if not p.is_symlink() and p.stat().st_mtime >= since]
    logs = [(p, b) for p, b in logs if ("] Created conversation " + conversation).encode() in b]
    require(len(logs) == 1, "expected exactly one Antigravity process log for conversation " + conversation, 2)
    model = agy_log_model(logs[0][1].decode("utf-8", "replace").replace("\r", ""), conversation)
    proof = dict(kind="antigravity-log", conversation_id=conversation, **frozen(out, transcript))
    proof["log"] = frozen(log_out, logs[0][1])
    print("VALID"); print(json.dumps(dict(model_evidence=proof, model=model, source=str(logs[0][0])), ensure_ascii=True))
    return 0

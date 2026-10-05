"""C6 auxiliary CLI: a read-only state summary and the one-shot schema 1 -> 2 migration."""
import json
from pathlib import Path

import verification as v
from posix_runtime import artifact_path
from protocol_facts import require, ref, record, plan_read, artifact
from protocol_state import CAPS


def migrate(args):
    """Read a schema 1 state once: keep the current phase's accepted entries, commits, records, rounds and message ids."""
    require(len(args) == 3, "usage: protocol-state migrate STATE_V1_JSON OUT_JSON")
    old = v.load(args[1]); old = old["state"] if "action" in old else old
    require(old.get("schema_version") == 1, "not a schema 1 state", 2)
    out = artifact_path(args[2])
    require(Path(args[2]).is_absolute() and out.parent.is_dir() and not out.exists(), "migration output must be a new absolute file", 2)
    step = "plan" if old["step"] == "bootstrap" else old["step"]
    # The live plan may have moved by bookkeeping lines since the v1 state was saved: adopt its current bytes.
    if old["plan"]:
        live = Path(old["plan"]["path"]).read_bytes()
        plan = dict(path=old["plan"]["path"], sha256=v.digest(live), structure=plan_read(live.decode("utf-8-sig").replace("\r\n", "\n"))["shape"])
    else: plan = None
    if plan is None and old["mode"] == "plan": plan = dict(path=record(old["authorization"])["plan_path"], sha256=None, structure=None)
    s = dict(schema_version=2, mode=old["mode"], plan=plan, ledger_path=(old.get("ledger") or {}).get("path"), step=step, accepted=[],
             phase_commits=[], final_source=None, processed_messages=old["processed"]["messages"], used_fleet_ids=old.get("used_fleet_ids", []),
             cap_extensions=old.get("cap_extensions", []), independence_waivers=old.get("independence_waivers", []), barrier=None,
             authors={},  # schema 1 kept no per-file authorship
             **{k: old[k] for k in ("orca_run", "plan_base", "phase", "base", "worktree", "worktree_id", "workspace", "active", "rounds", "provenance", "write_ownership")})
    if s["active"]: s["active"].pop("format_corrected", None)
    entry = lambda art, **x: dict(dict(round=0, findings=[], coverage={}, family=None, report=None, dispatch_id=None, evidence=[]), phase=old["phase"],
                                     step=step, candidate=artifact(art, s)["candidate"], artifact=art, **x)
    for r in old["accepted"]:
        if r["step"] == old["step"] and r["binding"]["phase"] == old["phase"] and r["artifact"]["kind"] != "request":
            s["accepted"].append(entry(r["artifact"], **{k: r[k] for k in ("role", "token", "findings", "coverage", "family", "report")},
                                       round=r["binding"]["round"], dispatch_id=r["binding"]["dispatch_id"], evidence=r.get("evidence", [])))
    for g in old.get("script_gates", []):
        if g["step"] == old["step"]: s["accepted"].append(entry(g["artifact"], role="gate", token="GATE_OK", evidence=g["evidence"]))
    commits = [(c, "quickfix" if old["mode"] == "quickfix" else ("plan" if c["phase"] is None else "phase")) for c in old["phase_commits"]]
    commits += [(old["final"]["completion"], "completion")] if "completion" in (old.get("final") or {}) else []
    for c, kind in commits:
        s["phase_commits"].append(dict(phase=c.get("phase", old["phase"]), step=kind, sha=c["sha"], base=c["base"], candidate=artifact(c["artifact"], s)["candidate"]))
    if old["step"] in ("delivery", "completion") and (old.get("final") or {}).get("review"):
        s["final_source"] = artifact(old["final"]["review"][0]["artifact"], s)["candidate"]
    v.save(out, s)
    print("VALID"); print(json.dumps(dict(out=str(out), step=step, accepted=len(s["accepted"]), phase_commits=len(s["phase_commits"]))))
    return 0


def summary(args):
    """Print the compact facts of a saved state or proposal; never the raw JSON. Read-only."""
    require(len(args) == 2, "usage: protocol-state summary STATE_OR_PROPOSAL_JSON")
    data = v.load(args[1]); state = data.get("state") if "action" in data else data
    require(isinstance(state, dict) and "accepted" in state, "not a C6 state or proposal", 2)
    name = lambda r: Path(r["path"]).name if isinstance(r, dict) and r.get("path") else "-"
    short = lambda sha: (sha or "-")[:7]
    a = state.get("active"); rounds = state.get("rounds") or {}
    rows = ["proposal: action=%s" % data["action"]] if "action" in data else []
    rows += ["schema=%s mode=%s step=%s phase=%s barrier=%s base=%s run=%s" % (state.get("schema_version"), state.get("mode"), state.get("step"),
             state.get("phase"), state.get("barrier", "-"), short(state.get("base")), state.get("orca_run")),
             "active: " + ("none" if not a else "role=%s round=%s task=%s dispatch=%s fix=%s model=%s" % (
                 a.get("role"), a.get("round"), a.get("task_id"), a.get("dispatch_id"), a.get("fix", False), a.get("model"))),
             "rounds: " + " ".join("%s=%s/%s" % (k, rounds.get(k), CAPS[k] + sum(1 for x in state.get("cap_extensions") or []
                                   if x["group"] == k and x["phase"] == state.get("phase"))) for k in CAPS),
             "write_ownership: %s" % (state.get("write_ownership") or []), "accepted (%d):" % len(state["accepted"])]
    rows += ["  %s %s r%s %s %s findings=%s" % (r.get("role"), r.get("token"), r.get("round", r.get("binding", {}).get("round")), r.get("step"),
             short(r["candidate"]) if "candidate" in r else name(r.get("artifact")), ",".join(f["id"] for f in r.get("findings") or []) or "-")
             for r in state["accepted"][-12:]]
    rows += ["phase_commits: " + (", ".join("%s/%s %s" % (c.get("step", "-"), c.get("phase"), short(c.get("sha"))) for c in state.get("phase_commits") or []) or "-"),
             "final_source: %s  cap_extensions: %d  independence_waivers: %s" % (short(state.get("final_source")), len(state.get("cap_extensions") or []),
             "; ".join("%s/%s %s -> %s" % (w["step"], w.get("phase"), ",".join(w["files"]), w["reviewer_family"]) for w in state.get("independence_waivers") or []) or "-"),
             "processed_messages=%d used_fleet_ids=%d" % (len(state.get("processed_messages") or []), len(state.get("used_fleet_ids") or [])),
             "plan=%s ledger=%s workspace=%s" % (name(state.get("plan")), Path(state.get("ledger_path") or "-").name, state.get("workspace"))]
    print("\n".join(rows))
    return 0

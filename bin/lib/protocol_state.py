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
                            plan_name, artifact, fresh, fleet_workers, authors, evidence_records, failure_records, model_matches,
                            actual_model, family, known_families, observation, claude_model_evidence, antigravity_model_evidence,
                            checked, entry, manifest_files, step_base, values, candidate, synthesis)

CAPS = {"plan_review": 4, "fused_review": 4, "final_review": 2, "gate_fix": 2}
GOOD = {"plan-reviewer": ["APPROVED"], "gate": ["GATE_OK"], "review-primary": ["REVIEW_OK"], "review-control": ["REVIEW_OK"],
        "review-final": ["REVIEW_OK"], "quickfix": ["DONE", "DONE_WITH_CONCERNS"]}
WRITTEN = ["DONE", "DONE_WITH_CONCERNS", "PLAN_WRITTEN", "REVISED", "SYNTHESIS_DONE"]
READY = {"plan": ["plan-reviewer"], "quickfix": ["quickfix"], "phase": ["gate", "review-primary", "review-control"],
         "final-review": ["review-final"], "delivery": ["gate"], "completion": []}
# A final-fix commit also needs a gate on the fixed bytes; the final checkpoint itself needs only the final review.
COMMIT_READY = dict(READY, **{"final-review": ["gate", "review-final"]})
PLAN_AUTHORS = ("plan-writer", "plan-reviser")
DECISIONS = ["DEFER", "NIT", "REJECTED_BY_SCOPE"]  # ESCALATED_TO_HUMAN keeps a finding open until the user decides
KEYS = ("schema_version", "mode", "plan", "ledger_path", "orca_run", "plan_base", "phase", "base", "step", "worktree",
        "worktree_id", "workspace", "active", "rounds", "cap_extensions", "independence_waivers", "provenance", "accepted",
        "write_ownership", "phase_commits", "final_source", "processed_messages", "used_fleet_ids")
# Added after the first schema 2 states; a state without them is upgraded once by upgrade().
DEFAULTS = {"plan_authors": [], "authors": {}, "attempts": [], "plan_approved": None}
PLAN_ROLES = PLAN_AUTHORS + ("plan-reviewer", "diagnosis")  # may run while a plan revision awaits its review


def cap(state, group):
    """Protocol cap plus the user's one-round extensions (each checked by extend-cap). Plan review is one budget per
    plan, so its extensions count in every phase; the other groups are per phase."""
    return CAPS[group] + sum(1 for x in state["cap_extensions"] if x["group"] == group and (group == "plan_review" or x["phase"] == state["phase"]))


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


def legacy_superset(state):
    """Every model family an older state can name as a writer of this Run: its writer observations in provenance and the
    write rows of every package it still references. An observation whose family cannot be read counts as every family."""
    families = set()
    for ref in state["provenance"]:
        try: families.add(family(record(ref)["result"], ref))
        except (Rejected, OSError, ValueError, KeyError, TypeError): families |= known_families()
    for r in state["accepted"]:
        if (r.get("artifact") or {}).get("kind") != "package": continue
        try:
            for fams in authors(dict(manifest=record(r["artifact"])), state["provenance"]).values(): families |= fams
        except (Rejected, OSError, ValueError, KeyError, TypeError): continue
    return families


def upgrade(state):
    """A state written before authors/plan_authors existed rebuilds them once from what it holds: the validated write
    receipts of the C5 packages its accepted reviews used (a write touching the plan file is plan authorship) and its
    accepted plan writer/reviser entries. Nothing rebuilt stays unknown: an unknown author never makes a reviewer
    independent (see independent and plan_independent).
    Legacy rule: a file committed in an earlier phase of the Run (plan_base..the current phase's base; every phase in
    the final steps) gets the conservative superset of every writer family the state can name (legacy_superset). It
    only over-approximates, so independence only gets stricter; a file no family may review goes through
    waive-independence. Files touched only in the current phase follow the package and record-author rules. Consumed
    final-review rounds and the approved plan structure are rebuilt only from evidence the state holds."""
    if "authors" not in state or state.get("plan_authors") is None:
        name = plan_name(state); rebuilt = {}; plan_refs = []; observed = {}
        for ref in state["provenance"]:
            try: observed[record(ref)["result"]["dispatch"]["id"]] = ref
            except (Rejected, OSError, ValueError, KeyError, TypeError): pass
        def plan_author(ref):
            if ref["path"] not in [r["path"] for r in plan_refs]: plan_refs.append(ref)
        for r in state["accepted"]:
            if r["role"] in PLAN_AUTHORS and r.get("dispatch_id") in observed: plan_author(observed[r["dispatch_id"]])
            if (r.get("artifact") or {}).get("kind") != "package": continue
            try:
                m = record(r["artifact"]); writers = authors(dict(manifest=m), state["provenance"])
            except (Rejected, OSError, ValueError, KeyError, TypeError): continue
            for path, families in writers.items():
                if path != name: rebuilt.setdefault(path, set()).update(families)
            for w in m["provenance"].get("writes", []):
                if name in w["files"]:
                    plan_author(next((x for x in state["provenance"] if x["path"] == w["receipt_path"] and x["sha256"] == w["receipt_sha256"]),
                                     dict(path=w["receipt_path"], sha256=w["receipt_sha256"])))
        if "authors" not in state:
            end = state["base"] if state["step"] in ("plan", "phase", "quickfix") else "HEAD"
            earlier = [x for x in v.git(state["worktree"], "diff", "--no-ext-diff", "--name-only", "-z", state["plan_base"], end, "--").decode("utf-8").split("\0")
                       if x and x != name]
            superset = legacy_superset(state) if earlier else set()
            for x in earlier: rebuilt.setdefault(x, set()).update(superset)
            state["authors"] = {path: sorted(f) for path, f in sorted(rebuilt.items())}
        if state.get("plan_authors") is None: state["plan_authors"] = plan_refs
    state.pop("authors_incomplete", None)  # a round-4/5 development field; no installed version wrote it
    if "attempts" not in state:
        # The final-review rounds counted so far are consumed: after a checkpoint, and conservatively in final-review too
        # (an older runtime may have reopened it). There the rebuilt R<round>-REOPEN identity lets the user extend the cap.
        n = state["rounds"]["final_review"]; reopened = state["step"] == "final-review" and n > 0
        consumed = state["step"] in ("delivery", "completion") or reopened
        state["attempts"] = [dict(role="review-final", round=k, family=None) for k in range(1, n + 1)] if consumed else []
        if reopened:
            item = dict(id="R%d-REOPEN" % n, kind="blocking", location="final-review", issue="consumed final-review rounds rebuilt for an older state")
            state["accepted"].append(dict(role="reopen", token="REOPENED", round=n, phase=state["phase"], step="final-review", candidate=None,
                                          artifact=None, findings=[item], coverage={}, family=None, report=None, dispatch_id=None, evidence=[]))
    if "plan_approved" not in state: state["plan_approved"] = approved_structure(state)


def approved_structure(state):
    """The plan structure an older state can prove approved: its latest accepted plan-reviewer APPROVED (unless a plan
    author's entry came later), else the plan-only commit's plan when no plan author's entry remains. Otherwise none:
    the revision awaits its plan review."""
    if state["plan"] is None or state["step"] == "plan": return None
    roles = [r["role"] if r["role"] in PLAN_AUTHORS else "approval" if (r["role"], r["token"]) == ("plan-reviewer", "APPROVED") else None
             for r in state["accepted"]]
    approvals = [i for i, x in enumerate(roles) if x == "approval"]; revisions = [i for i, x in enumerate(roles) if x in PLAN_AUTHORS]
    try:
        if approvals and (not revisions or approvals[-1] > revisions[-1]):
            return plan_read(ref(state["accepted"][approvals[-1]]["artifact"]))["shape"]
        commit = next((c for c in state["phase_commits"] if c["step"] == "plan"), None)
        if commit and not revisions:
            text = v.git(state["worktree"], "show", commit["sha"] + ":" + plan_name(state)).decode("utf-8-sig").replace("\r\n", "\n")
            return plan_read(text)["shape"]
    except (Rejected, OSError, ValueError, KeyError, TypeError, v.subprocess.SubprocessError): pass
    return None


def source_capture(state):
    """The repository entries of the worktree right now (plan file and synthesis excluded) and their candidate digest."""
    now = v.snapshot(state["worktree"], [], [state["workspace"]])
    require(now["valid"], "unverifiable source capture: " + str(now.get("reason")), 2)
    skip = {plan_name(state)} | set(synthesis(state))
    entries = {k[5:]: entry(x) for k, x in now["manifest"]["files"].items() if k.startswith("repo:") and x["type"] != "missing" and k[5:] not in skip}
    return candidate(now["manifest"]["files"], state), entries


def source_candidate(state):
    return source_capture(state)[0]


def plan_lane(state, assignment):
    """A plan author edits the plan file only: the source candidate is still the one captured at its dispatch."""
    if assignment.get("source") is not None:
        require(source_candidate(state) == assignment["source"],
                "plan author changed source outside the plan: revert it or attribute it with record-author (route further source work to an implementer)")


def import_plan_approval(data, state):
    """resume with prior_plan_approval_state: an earlier saved state of this Run whose accepted, independent plan
    approval is of the current plan structure restores plan_approved (and its evidence reference) only."""
    refspec = data.get("prior_plan_approval_state")
    if refspec is None: return
    def check(ok, why):
        if not ok: raise Rejected("prior plan approval does not apply: " + why)
    check(data["action"] == "resume" and state["plan"] is not None, "only resume of a plan Run imports a prior approval")
    obj = record(refspec); prior = obj.get("state") if isinstance(obj, dict) and "action" in obj else obj
    check(isinstance(prior, dict) and prior.get("schema_version") == 2 and isinstance(prior.get("accepted"), list), "not a schema 2 state")
    check(all(prior.get(k) == state[k] for k in ("orca_run", "worktree", "plan_base")) and (prior.get("plan") or {}).get("path") == state["plan"]["path"],
          "another Run, worktree, plan path or plan_base")
    check(set(prior.get("processed_messages") or []) <= set(state["processed_messages"]), "not an earlier state of this Run")
    rows = prior["accepted"]; approvals = [i for i, r in enumerate(rows) if (r.get("role"), r.get("token")) == ("plan-reviewer", "APPROVED")]
    check(approvals, "it holds no accepted plan-reviewer APPROVED")
    e = rows[approvals[-1]]
    check(not any(r.get("role") in PLAN_AUTHORS for r in rows[approvals[-1] + 1:]), "a plan author's entry follows the approval")
    art = e.get("artifact") or {}
    check(art.get("kind") == "plan" and e.get("candidate") == art.get("sha256"), "the approval is not of a plan artifact")
    text = ref(e["report"]); b = line_json(text, "BINDING")
    check(text.splitlines()[0] == "APPROVED" and (b.get("run_id"), b.get("role"), b.get("dispatch_id"), b.get("round"), b.get("artifact_id")) ==
          (state["orca_run"], "plan-reviewer", e.get("dispatch_id"), e.get("round"), art["sha256"]), "its report binding differs from the entry")
    check(plan_read(ref(art))["shape"] == state["plan"]["structure"], "the approved structure is not the current plan")
    try: plan_independent(state, e.get("family"))
    except Rejected as x: raise Rejected("prior plan approval does not apply: " + str(x), x.code)
    state.update(plan_approved=state["plan"]["structure"], plan_approval_evidence=refspec)


def plan_reviewed(state):
    """No substantive plan revision awaits its independent plan review (the plan step has its own approval barrier)."""
    return state["plan"] is None or state["step"] == "plan" or state["plan"]["structure"] == state["plan_approved"]


def drafted(state):
    """The live plan file no longer holds the accepted bytes (a plan author's working draft)."""
    plan = state["plan"]
    if plan is None or plan["sha256"] is None: return False
    try: return v.file_digest(artifact_path(plan["path"])) != plan["sha256"]
    except OSError: return True


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


def settled(worker):
    """A fleet row that positively ended: durably completed/failed, or released with an exited process."""
    p = worker.get("projection") or {}
    if (worker.get("terminalState") in ("release_pending", "release_unknown") or
            (worker.get("resource") or {}).get("ownershipState") in ("user_owned", "external", "pre_existing")): return False
    return ((worker.get("dispatchStatus") in ("completed", "failed") and p.get("evidence", {}).get("durable") is True) or
            (worker.get("terminalState") == "released" and p.get("liveness", {}).get("verdict") == "exited"))


def fleet_clear(data, state):
    """Invariant (a): a fresh complete fleet shows no live or unverifiable writer in this worktree. A recorded writer
    must be in it: absence from an inventory taken before that writer started proves nothing."""
    require(not any(x.startswith("pending:") for x in state["write_ownership"]), "unbound writer intent", 2)
    workers, receipt_ids = fleet_workers(data, state["used_fleet_ids"])
    rows = {w.get("dispatchId"): w for w in workers}
    for owner in state["write_ownership"]:
        require(owner in rows, "recorded writer missing from fleet: " + owner, 2)
        # A bound writer that settled without an accepted report still wrote bytes: its family must be recorded first.
        require(not settled(rows[owner]), "writer " + owner + " settled without an accepted report: record-author it first", 2)
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
    return workers


def file_authors(art, state):
    """Actual author families per file: the package's write receipts plus the cumulative authorship C6 recorded from
    every accepted or registered writer of this Run (earlier phases, fixes and fallbacks included)."""
    writers = authors(art, state["provenance"])
    for path, families in state["authors"].items(): writers.setdefault(path, set()).update(families)
    return writers


def independent(art, coverage, reviewer, state):
    """Invariant (c): the reviewer family authored no covered file or contract side, unless the user waived it for this step."""
    m = art["manifest"]; writers = file_authors(art, state); changed = {f["path"] for f in m["files"]}
    waived = {(p, w["reviewer_family"]) for w in state["independence_waivers"]
              if (w["step"], w["phase"]) == (state["step"], state["phase"]) for p in w["files"]}
    require(set(coverage.get("files", [])) <= changed, "unknown coverage file")
    for name in coverage.get("files", []):
        require(writers.get(name), "unknown actual author: " + name, 2)
        require(reviewer not in writers[name] or (name, reviewer) in waived, "same-family review: " + name)
    require(set(coverage.get("parts", [])) <= {p["path"] for p in m["parts"]}, "unknown coverage part")
    contracts = {c["id"]: c for c in m["coverage"]["contracts"]}
    sides = sorted({p for c in coverage.get("contracts", []) for side in ("producer", "consumer") for p in c.get(side, [])} - changed - {plan_name(state)})
    earlier = set(x for x in v.git(state["worktree"], "diff", "--no-ext-diff", "--name-only", "-z", state["plan_base"], "--", *sides).decode("utf-8").split("\0") if x) if sides else set()
    for c in coverage.get("contracts", []):
        require(c.get("id") in contracts, "unknown coverage contract")
        for side in ("producer", "consumer"):
            require(set(c.get(side, [])) <= set(contracts[c["id"]][side]), "unknown contract side")
            # A side may name a file this package did not change (an earlier phase's producer): it needs no file
            # review, but its recorded authors still exclude their family from covering it.
            require(set(c.get(side, [])) & changed <= set(coverage.get("files", [])), "contract side lacks file review")
            for name in set(c.get(side, [])) - changed:
                # Written earlier in this Run but with no recorded author: unknown, never independent.
                require(writers.get(name) or name not in earlier, "unknown actual author: " + name, 2)
                require(reviewer not in writers.get(name, ()) or (name, reviewer) in waived, "same-family review: " + name)


def plan_independent(state, reviewer):
    """Plan authors are the accepted or registered plan writers and revisers only (rebuilt once for an older state)."""
    require(state["plan_authors"], "unknown plan authors", 2)
    for author in state["plan_authors"]:
        require(family(record(author)["result"], author) != reviewer, "same-family plan review")


def written(state, before, art):
    """Paths a settled writer changed: its own window (dispatch-time vs delivered capture) when the dispatch-time
    capture is known, otherwise everything changed since the step base. More authors only make reviews stricter."""
    if art.get("files") is None: return set()
    repo = lambda files: {k[5:]: entry(x) for k, x in files.items() if k.startswith("repo:") and x["type"] != "missing"}
    now = repo(art["files"])
    if before is not None:
        old = repo(before); paths = {p for p in old.keys() | now.keys() if old.get(p) != now.get(p)}
    else:
        diff = v.git(state["worktree"], "diff", "--no-ext-diff", "--name-only", "-z", step_base(state), "--").decode("utf-8")
        paths = {p for p in diff.split("\0") if p} | {k[5:] for k, x in art["files"].items()
                                                       if k.startswith("repo:") and x["type"] != "missing" and "index" not in x}
    return paths - {plan_name(state)}


def attribute(state, paths, author_family):
    for path in sorted(paths): state["authors"][path] = sorted(set(state["authors"].get(path, [])) | {author_family})


def covered(review):
    """Every file a review covered: its file coverage and the files named in its contract sides."""
    c = review["coverage"]
    return set(c.get("files", [])) | {p for x in c.get("contracts", []) for side in ("producer", "consumer") for p in x.get(side, [])}


def units(finding, review):
    """The reviewed unit a finding is about: its location's file when that review covered it (as a file or a contract
    side), else the review's whole coverage."""
    path = str(finding.get("location", "")).split(":")[0].strip()
    return {path} if path in covered(review) else covered(review)


def omitted(state, review, finding, cand):
    """A later round of the same role on cand covers the finding's unit and none of its reports lists it."""
    later = {}
    for r in state["accepted"]:
        if r["role"] == review["role"] and r["candidate"] == cand and r["round"] > review["round"] and r["token"] != "BLOCKED":
            later.setdefault(r["round"], []).append(r)
    need_units = units(finding, review)
    return any(all(finding["id"] not in [f["id"] for f in r["findings"]] for r in rows) and
               need_units <= {p for r in rows for p in covered(r)} for rows in later.values())


def unresolved(state, cand, decisions):
    """Resolved: a ledger decision; a cannot_verify item checked by its literal CHECK; a later round on cand covering
    the finding's unit and omitting it. A gate failure is identity only: a positive gate on cand supersedes it."""
    # Plan-review findings belong to the plan: outside the plan step they resolve against the latest approved plan.
    approved = [r["candidate"] for r in state["accepted"] if (r["role"], r["token"]) == ("plan-reviewer", "APPROVED")]
    plan_cand = approved[-1] if approved and state["step"] != "plan" else cand
    out = []
    for r in state["accepted"]:
        if r["role"] in ("gate", "reopen"): continue
        for f in r["findings"]:
            item = decisions.get(f["id"], {})
            if item.get("decision") in DECISIONS or (f["kind"] == "cannot_verify" and checked(item, f)): continue
            if f["kind"] == "blocking" and omitted(state, r, f, plan_cand if r["role"] == "plan-reviewer" else cand): continue
            out.append(f["id"])
    return out


def approvals(state, role, cand):
    """The current reports of a role on cand: for reviews, the latest attempt of each family in the latest round
    (complementary assignments share one round; a BLOCKED attempt is superseded by its retry); else the latest report."""
    rows = [r for r in state["accepted"] if r["role"] == role and r["candidate"] == cand]
    if not rows or role not in REVIEW or role == "plan-reviewer": return rows[-1:]
    top = max(r["round"] for r in rows)
    by_family = {r["family"]: r for r in rows if r["round"] == top}
    return [r for r in by_family.values() if r["token"] != "BLOCKED"] or rows[-1:]


def ready(state, cand, decisions, roles=None):
    """The step's required roles have positive current reports on cand, nothing is unresolved, the reviews are still
    independent of every recorded author, and together they cover the package."""
    rows = []
    for role in READY[state["step"]] if roles is None else roles:
        current_rows = approvals(state, role, cand)
        require(current_rows, "required report is missing: " + role, 2)
        for r in current_rows: require(r["token"] in GOOD[role], "required report is not positive: " + role)
        rows += current_rows
    still = unresolved(state, cand, decisions)
    require(not still, "unresolved findings: " + ", ".join(still))
    for r in rows:
        if r["role"] == "plan-reviewer": plan_independent(state, r["family"])
    reviews = [r for r in rows if r["role"] in REVIEW and r["role"] != "plan-reviewer"]
    if reviews:
        packages = {}
        for r in reviews:
            m = packages.setdefault(r["artifact"]["path"], record(r["artifact"]))
            independent(dict(manifest=m), r["coverage"], r["family"], state)
        m = packages[reviews[0]["artifact"]["path"]]; skip = {plan_name(state)}
        union = lambda key: {p for r in reviews for p in r["coverage"].get(key, [])}
        require({f["path"] for f in m["files"]} - skip <= union("files"), "incomplete file coverage", 2)
        require({p["path"] for p in m["parts"]} <= union("parts"), "incomplete part coverage", 2)
        for c in m["coverage"]["contracts"]:
            for side in ("producer", "consumer"):
                sides = {p for r in reviews for x in r["coverage"].get("contracts", []) if x["id"] == c["id"] for p in x.get(side, [])}
                require(set(c[side]) - skip <= sides, "incomplete contract " + c["id"] + ":" + side, 2)


def latest(state, role, cand):
    rows = [i for i, r in enumerate(state["accepted"]) if r["role"] == role and r["candidate"] == cand]
    return rows[-1] if rows else None


def gate_finding(state):
    """A failed gate's identity G<r>-B1 (r = the gate-fix round it opens), so the user's cap extension can name it."""
    return dict(id="G%d-B1" % (state["rounds"]["gate_fix"] + 1), kind="blocking", issue="verification gate failed", location="verify-gate")


def current(state):
    if state["step"] == "plan": return state["plan"]["sha256"]
    # A mid-phase plan revision and its review are not the source candidate.
    rows = [r for r in state["accepted"] if r["role"] not in ("diagnosis", "synthesizer") + PLAN_ROLES]
    if not rows or (rows[-1]["role"] in WRITE and rows[-1]["token"] not in WRITTEN): return None
    return rows[-1]["candidate"]


def committed(state):
    return [c for c in state["phase_commits"] if (c["step"], c["phase"]) == (state["step"], state["phase"])]


def barrier(state, phases, decisions):
    step = state["step"]
    if state["write_ownership"]: return "awaiting_writer"
    if not plan_reviewed(state): return "awaiting_plan_review"
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
    if role in PLAN_AUTHORS: plan_lane(state, active)
    if role in PLAN_AUTHORS and token in WRITTEN:
        require(art["kind"] == "plan" and art["id"] == state["plan"]["sha256"], "plan author must deliver the current plan")
    actual = family(observed)
    if role in REVIEW and role != "plan-reviewer": independent(art, coverage, actual, state)
    if role == "plan-reviewer": plan_independent(state, actual)
    proofs = evidence_records(line_json(text, "EVIDENCE"), art, state) if role == "gate" and token == "GATE_OK" else []
    if role == "gate" and token == "GATE_FAIL": findings = [gate_finding(state)]
    extra = {}
    if role == "synthesizer" and token == "SYNTHESIS_DONE":
        # The synthesis summarises the acceptance: when it is the synthesizer's only change, one Markdown document under
        # docs/reviews/, its bytes are frozen here and leave the candidate identity. Anything else it wrote stays in the
        # candidate and needs the gate and reviews like any change.
        path = text.splitlines()[1].strip(); item = (art["files"] or {}).get("repo:" + path)
        require(item is not None and item["type"] == "file", "synthesis path is not in the delivered artifact")
        if re.fullmatch(r"docs/reviews/[^/]+\.md", path) and written(state, manifest_files(active.get("artifact")), art) == {path}:
            extra["synthesis"] = dict(path=path, entry=entry(item))
    if role == "plan-reviewer" and token == "APPROVED": state["plan_approved"] = state["plan"]["structure"]
    if role in WRITE:
        state["provenance"].append(data["observation"])
        if role in PLAN_AUTHORS:
            if state["plan_authors"] is not None: state["plan_authors"].append(data["observation"])
        else: attribute(state, written(state, manifest_files(active.get("artifact")), art), actual)
    state["accepted"].append(dict(role=role, token=token, round=active["round"], phase=active["phase"], step=state["step"],
                                  candidate=art["candidate"], artifact=data.get("artifact"), findings=findings, coverage=coverage,
                                  family=actual, report=report, dispatch_id=active["dispatch_id"], evidence=proofs, **extra))
    if role == "gate" and token == "GATE_OK": state["rounds"]["gate_fix"] = 0  # the gate-fix cap counts consecutive rounds
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
    require(plan_reviewed(state) or proposed["role"] in PLAN_ROLES, "plan revision awaits an independent plan review")
    # A new synthesizer may replace a synthesis whose frozen bytes changed (its own dispatch does not re-check them).
    view = dict(state, active=proposed) if proposed["role"] == "synthesizer" else state
    art = artifact(data.get("artifact"), view, None if unplanned and data.get("artifact") is None else True)
    reviewer = family({"projection": {"provider": {"model": proposed["model"]}}})
    group = {"plan-reviewer": "plan_review", "review-primary": "fused_review", "review-control": "fused_review", "review-final": "final_review"}.get(proposed["role"])
    if proposed.get("gate_fix"): group = "gate_fix"
    if group:
        count = state["rounds"][group]
        require(proposed["round"] in (count, count + 1) and proposed["round"] <= cap(state, group), "round cap/sequence: " + group)
        state["rounds"][group] = proposed["round"]
    if proposed["role"] in REVIEW:
        # A BLOCKED attempt reviewed nothing: its fresh retry keeps the round.
        require(not any(r["role"] == proposed["role"] and r["round"] == proposed["round"] and r["family"] == reviewer and r["token"] != "BLOCKED"
                        for r in state["accepted"]), "substantive review needs a new round")
        # After a final checkpoint the consumed final-review rounds stay consumed (reopen-final starts a new round).
        require(not any(x["role"] == proposed["role"] and x["round"] >= proposed["round"] for x in state["attempts"]),
                "substantive review needs a new round")
    if proposed["role"] in REVIEW and proposed["role"] != "plan-reviewer": independent(art, proposed.get("coverage", {}), reviewer, state)
    # The dispatch-time capture bounds what a writer authored and proves an unbound launch wrote nothing.
    proposed.update(artifact_id=art["id"], snapshot_id=art["snapshot_id"], artifact=data.get("artifact"), candidate=art["candidate"])
    if proposed["role"] in PLAN_AUTHORS: proposed["source"] = source_candidate(state)  # its lane is the plan file
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
    upgrade(state)
    require(state["mode"] in ("plan", "quickfix") and state["step"] in READY and
            (state["mode"] == "quickfix") == (state["step"] == "quickfix") == (state["plan"] is None), "invalid protocol mode/step")
    require(Path(state["worktree"]).is_absolute() and Path(state["workspace"]).is_absolute(), "absolute workspace required")
    require(artifact_path(v.text_git(state["worktree"], "rev-parse", "--show-toplevel")) == artifact_path(state["worktree"]), "TARGET is not a Git worktree", 2)
    for sha in (state["plan_base"], state["base"]):
        require(isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha) and is_ancestor(state["worktree"], sha, sha), "missing recorded base", 2)
    action = data["action"]; decision = "accepted"
    # While a plan author's attempt is current (pending, bound, or settled with a rejected report) the live plan is its
    # working draft: transitions of that attempt and a fresh author attempt read the accepted reference, not the file.
    draft = (state["active"] or {}).get("role") in PLAN_AUTHORS and (
        action in ("bind-dispatch", "accept-report", "record-author", "reconcile-intent", "resume") or
        (action == "dispatch" and (data.get("proposed") or {}).get("role") in PLAN_AUTHORS))
    update_plan(data, state)
    require(state["plan"] is None or state["plan"]["sha256"] is not None or state["step"] == "plan", "missing plan outside the plan step", 2)
    decisions = ledger(data, state)
    # Only the live file may be a draft: an accepted plan reference that fails its own checks is never tolerated.
    phases = [] if draft and drafted(state) else plan_facts(state)
    for key in CAPS:
        require(type(state["rounds"].get(key)) is int and 0 <= state["rounds"][key] <= cap(state, key), "round cap: " + key)
    import_plan_approval(data, state)
    if action in ("prepare-commit", "confirm-commit", "advance", "finish-checkpoint", "complete"):
        require(plan_reviewed(state), "plan revision awaits an independent plan review")
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
        ready(state, art["candidate"], decisions, COMMIT_READY[state["step"]])
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
        if state["step"] == "final-review":  # the consumed final-review attempts outlive the cleared entries
            state["attempts"] += [dict(role=r["role"], round=r["round"], family=r["family"]) for r in state["accepted"]
                                  if r["role"] == "review-final" and r["token"] != "BLOCKED"]
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
        writers = file_authors(artifact(data.get("artifact"), state, True), state)
        for name in auth["files"]:
            require(writers.get(name, set()) >= known_families(), "independence waiver needs every family as author: " + name)
        state["independence_waivers"].append(dict(step=auth["step"], phase=auth["phase"], files=auth["files"],
                                                  reviewer_family=auth["reviewer_family"], authorization=data["authorization"]))
    elif action == "record-author":
        # A settled writer whose report was rejected still authored bytes: register its observation (with its model
        # proof) and the files it changed. More author families only make reviews stricter, never weaker.
        raw = record(data.get("observation")); require(raw.get("ok") is True, "unsuccessful Orca observation", 2)
        result = raw["result"]; need(result, ("dispatch", "projection")); d = result["dispatch"]
        require(d.get("runId") == state["orca_run"] and (result["projection"].get("workspace") or {}).get("id") == state["worktree_id"], "author observation outside this Run and worktree")
        require(d.get("status") in ("completed", "failed") and result["projection"].get("evidence", {}).get("durable") is True, "author Dispatch is not durably settled", 2)
        author_family = family(result, data["observation"])
        require(not any(r["path"] == data["observation"]["path"] for r in state["provenance"]), "author already recorded")
        active = state["active"] or {}
        # The active assignment's own Dispatch, or the Dispatch of its still unbound Task (a launch that started with
        # another model and wrote): its dispatch-time capture bounds the attribution, and the intent is resolved by it.
        own = active if active.get("dispatch_id") == d.get("id") or (active.get("dispatch_id") is None and active.get("task_id") == d.get("taskId")) else {}
        planned = own.get("role") in PLAN_AUTHORS or (data.get("artifact") or {}).get("kind") == "plan"
        art = artifact(data.get("artifact"), state, None if planned and data.get("artifact") is None else True)
        state["provenance"].append(data["observation"])
        if planned:
            state["plan_authors"].append(data["observation"])  # a plan author wrote the plan file
            if own.get("role") in PLAN_AUTHORS and own.get("source") is not None and source_candidate(state) != own["source"]:
                # Out of its lane it also wrote source: registering it attributes every change since the step base.
                require(art["files"] is not None, "plan author changed source outside the plan: record-author it with a current snapshot artifact", 2)
                attribute(state, written(state, None, art), author_family)
        else: attribute(state, written(state, manifest_files(own.get("artifact")), art), author_family)
        state["write_ownership"] = [x for x in state["write_ownership"] if x not in (d.get("id"), "pending:" + str(d.get("taskId")))]
        if own and own.get("dispatch_id") is None: state["active"] = None
    elif action == "record-gate":
        # A verify-gate run needs no worker: its sealed C4 results are the gate evidence. A failing run is recorded too,
        # so its identity G<r>-B1 exists for the user's gate-fix cap extension.
        require(state["step"] in ("phase", "final-review", "delivery") and not state["write_ownership"],
                "script gate outside an unowned phase, final-review or delivery candidate")
        verdict = data.get("verdict", "GATE_OK"); require(verdict in ("GATE_OK", "GATE_FAIL"), "unknown gate verdict")
        art = artifact(data.get("artifact"), state, True)
        proofs = (evidence_records if verdict == "GATE_OK" else failure_records)(data.get("evidence"), art, state)
        state["accepted"].append(dict(role="gate", token=verdict, round=state["rounds"]["gate_fix"], phase=state["phase"], step=state["step"],
                                      candidate=art["candidate"], artifact=data["artifact"], findings=[] if verdict == "GATE_OK" else [gate_finding(state)],
                                      coverage={}, family=None, report=None, dispatch_id=None, evidence=proofs))
        if verdict == "GATE_OK": state["rounds"]["gate_fix"] = 0
    elif action == "reconcile-intent":
        # A writer intent whose launch failed: positive termination of this Task's Dispatches in a fresh fleet, or the
        # saved failed launch receipt when no Dispatch was created; the tree must be the dispatch-time candidate.
        active = state["active"]
        require(active is not None and active["dispatch_id"] is None and state["write_ownership"] == ["pending:" + active["task_id"]],
                "no pending dispatch intent")
        if active["role"] in PLAN_AUTHORS: plan_lane(state, active)  # its source edits are reverted or attributed first
        state["write_ownership"] = []
        rows = [w for w in fleet_clear(data, state) if w.get("taskId") == active["task_id"]]
        require(all(settled(w) for w in rows), "live or unverifiable prior writer", 2)
        if not rows:
            failure = record(data["launch_failure"]) if data.get("launch_failure") is not None else {}
            require(failure.get("ok") is False and active["task_id"] in values(failure), "missing launch failure evidence", 2)
        if active.get("candidate") is not None and active["role"] not in PLAN_AUTHORS:
            require(artifact(data.get("artifact"), state, True)["candidate"] == active["candidate"],
                    "the failed launch changed the candidate: bind it or record-author its writer")
        state["active"] = None
    elif action == "reopen-final":
        # A defect found in delivery or by the completion hook goes back to the final review: delivery acceptance is
        # dropped; findings, authorship, commits and the final-review round count stay.
        require(state["step"] in ("delivery", "completion") and not any(c["step"] == "completion" for c in state["phase_commits"]),
                "reopen-final outside delivery or completion")
        fleet_clear(data, state)
        # The reopening is a bound recovery item R<round>-REOPEN, citing the current capture, so that at the final-review cap
        # the user's extend-cap can name it (a completion-hook reformat leaves no failing gate to name).
        art = artifact(data.get("artifact"), state, True); moved = art["candidate"] != state["final_source"]
        item = dict(id="R%d-REOPEN" % state["rounds"]["final_review"], kind="blocking", location="final-review",
                    issue="final review reopened" + ("; the source changed after the final checkpoint" if moved else ""))
        state["accepted"].append(dict(role="reopen", token="REOPENED", round=state["rounds"]["final_review"], phase=state["phase"], step="final-review",
                                      candidate=art["candidate"], artifact=data["artifact"], findings=[item], coverage={}, family=None,
                                      report=None, dispatch_id=None, evidence=[]))
        state.update(step="final-review", final_source=None, active=None)
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

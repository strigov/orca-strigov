"""C4/C5 file contracts shared by the POSIX entry points (stdlib only)."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
    return h.hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("xb") as f:
            f.write(encoded(value) + b"\n"); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def git(root, *args, env=None):
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    environment.update(env or {})
    return subprocess.run(["git", "-C", str(root), *args], env=environment,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
                          check=True).stdout


def text_git(root, *args):
    return git(root, *args).decode("utf-8", "strict").strip()


def strip_comment(value):
    quote = None; i = 0
    while i < len(value):
        c = value[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2; continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#" and (i == 0 or value[i-1].isspace()):
            return value[:i].rstrip()
        i += 1
    return value.rstrip()


def unquote(value):
    if len(value) > 1 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    if len(value) > 1 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def split_flow(value):
    out = []; start = 0; quote = None; depth = 0; i = 0
    while i < len(value):
        c = value[i]
        if quote:
            if quote == '"' and c == "\\":
                i += 2; continue
            if c == quote:
                quote = None
        elif c in "\"'": quote = c
        elif c in "[{": depth += 1
        elif c in "]}": depth -= 1
        elif c == "," and depth == 0:
            out.append(value[start:i].strip()); start = i + 1
        if depth < 0: raise ValueError("unbalanced verify list")
        i += 1
    if quote or depth: raise ValueError("unbalanced verify list")
    out.append(value[start:].strip())
    return [v for v in out if v]


def check(value, ordinal=1):
    defaults = dict(id="legacy-%d" % ordinal, checkpoint="directed", timeout_seconds=None,
                    cancel_grace_seconds=2, no_progress_seconds=None, resource_key=None,
                    progress_file=None, inputs=[], environment=[], hermetic=False,
                    independent_replay=False)
    if isinstance(value, str):
        value = {"command": value}
    if not isinstance(value, dict) or set(value) - set(defaults) - {"command"}:
        raise ValueError("unsupported verify object fields")
    result = dict(defaults, **value)
    for name in ("id", "command"):
        if not isinstance(result.get(name), str) or not result[name] or "\0" in result[name]:
            raise ValueError("invalid check " + name)
    if result["checkpoint"] not in ("directed", "integration", "final"):
        raise ValueError("invalid checkpoint")
    for name in ("hermetic", "independent_replay"):
        if type(result[name]) is not bool: raise ValueError("invalid " + name)
    for name in ("timeout_seconds", "no_progress_seconds", "cancel_grace_seconds"):
        v = result[name]
        if v is None and name != "cancel_grace_seconds": continue
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
            raise ValueError("invalid " + name)
    for name in ("resource_key", "progress_file"):
        if result[name] is not None and (not isinstance(result[name], str) or not result[name]):
            raise ValueError("invalid " + name)
    if not isinstance(result["inputs"], list) or any(not isinstance(v, str) or not v for v in result["inputs"]):
        raise ValueError("invalid inputs")
    if not isinstance(result["environment"], list): raise ValueError("invalid environment")
    for v in result["environment"]:
        if isinstance(v, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v): continue
        if (not isinstance(v, dict) or set(v) != {"tool", "version_args"} or
                not isinstance(v["tool"], str) or not v["tool"] or
                not isinstance(v["version_args"], list) or
                any(not isinstance(a, str) for a in v["version_args"])):
            raise ValueError("environment must contain variable names or tool/version_args objects")
    return result


def parse(plan, phase=None, checkpoint=None):
    text = Path(plan).read_text(encoding="utf-8-sig")
    front = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not front: return []
    lines = front[1].splitlines()
    indent = lambda s: len(s) - len(s.lstrip(" \t"))
    if phase:
        p = next((i for i, v in enumerate(lines) if v.startswith("phases:")), None)
        if p is None: raise ValueError("phase not found: " + phase)
        end = next((i for i in range(p+1, len(lines)) if re.match(r"^\w", lines[i])), len(lines))
        entries = [(i, m) for i in range(p+1, end)
                   if (m := re.match(r"^(\s*)-\s+id:\s*(.*?)\s*$", lines[i]))]
        found = [(n, i, m) for n, (i, m) in enumerate(entries) if unquote(strip_comment(m[2])) == phase]
        if len(found) != 1: raise ValueError("missing or duplicate phase: " + phase)
        n, start, m = found[0]; stop = entries[n+1][0] if n+1 < len(entries) else end
        width = len(m[1]) + 2
        lines = [v[width:] if v.strip() else "" for v in lines[start+1:stop]]
    keys = [(i, re.match(r"^verify:\s*(.*?)\s*$", v)) for i, v in enumerate(lines)]
    keys = [(i, m) for i, m in keys if m]
    if not keys: return []
    if len(keys) != 1: raise ValueError("duplicate verify key")
    k, m = keys[0]; tail = strip_comment(m[1]); raw = []
    if tail:
        if not (tail.startswith("[") and tail.endswith("]")):
            raise ValueError("verify must be a list")
        raw = split_flow(tail[1:-1])
    else:
        i = k + 1
        while i < len(lines):
            line = lines[i]
            if not line.strip() or line.lstrip().startswith("#"): i += 1; continue
            item = re.match(r"^(\s*)-(?:\s+(.*))?$", line)
            if not item:
                if indent(line) > 0: raise ValueError("unsupported verify structure")
                break
            width = len(item[1]); v = (item[2] or "").strip(); i += 1
            scalar = re.match(r"^([|>])[-+]?[0-9]*\s*(?:#.*)?$", v)
            if scalar:
                body = []
                while i < len(lines) and (not lines[i].strip() or indent(lines[i]) > width):
                    body.append(lines[i]); i += 1
                while body and not body[-1].strip(): body.pop()
                if not any(b.strip() for b in body): raise ValueError("empty block scalar")
                bi = min(indent(b) for b in body if b.strip())
                v = ("\n".join(b[bi:] for b in body) if scalar[1] == "|"
                     else " ".join(b.strip() for b in body if b.strip()))
                raw.append(json.dumps(v)); continue
            while i < len(lines) and lines[i].strip() and indent(lines[i]) > width:
                if v.startswith("{"): raise ValueError("verify JSON object must occupy one line")
                v += " " + lines[i].strip(); i += 1
            raw.append(strip_comment(v))
    result = []
    for v in raw:
        if not v: raise ValueError("empty check")
        if v.startswith("{"): value = json.loads(v)
        elif v.startswith(("[", "&", "*", "!")) or (v[0] not in "\"'" and re.search(r":\s", v)):
            raise ValueError("unsupported verify structure")
        elif v.startswith('"'):
            try: value = json.loads(v)
            except ValueError: value = unquote(v)
        else: value = unquote(v)
        result.append(check(value, len(result)+1))
    if len({c["id"] for c in result}) != len(result): raise ValueError("duplicate check id")
    levels = {"directed": 0, "integration": 1, "final": 2}
    if checkpoint is not None:
        if checkpoint not in levels: raise ValueError("invalid checkpoint")
        result = [c for c in result if levels[c["checkpoint"]] <= levels[checkpoint]]
    return result


def excluded(path, exclusions):
    return any(path == e or e in path.parents for e in exclusions)


def file_record(path):
    try: before = path.lstat()
    except FileNotFoundError: return {"type": "missing"}, None
    witness = [before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns]
    if stat.S_ISLNK(before.st_mode):
        raise ValueError("unresolved symlink: " + str(path))
    if stat.S_ISDIR(before.st_mode):
        return {"type": "directory"}, witness
    if not stat.S_ISREG(before.st_mode): raise ValueError("unsupported file: " + str(path))
    sha = file_digest(path); after = path.stat()
    if witness != [after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns]:
        raise ValueError("unstable file capture: " + str(path))
    return {"type": "file", "mode": stat.S_IMODE(before.st_mode), "bytes": before.st_size, "sha256": sha}, witness


def capture_once(root, inputs, exclusions):
    from posix_runtime import artifact_path
    root = artifact_path(text_git(root, "rev-parse", "--show-toplevel"))
    records = {}; witness = {}; indexed = {}
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not entry: continue
        meta, name = entry.split(b"\t", 1); mode, oid, stage = meta.decode().split()
        name = name.decode("utf-8", "strict")
        if stage != "0" or mode == "160000": raise ValueError("unmerged index or unresolved submodule: " + name)
        indexed[name] = [mode, oid]
    names = set(indexed) | {p.decode("utf-8", "strict") for p in git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p}
    def add(path, label, index=None):
        # Never follow a link in an input ancestor.
        for parent in path.parents:
            if parent.is_symlink(): raise ValueError("symlink input ancestor: " + str(parent))
        record, change = file_record(path)
        if index is not None: record["index"] = index
        records[label] = record; witness[label] = change
    for name in sorted(names):
        p = root / name
        # Tracked sources cannot be hidden by an output/workspace exclusion.
        if name not in indexed and excluded(p, exclusions): continue
        add(p, "repo:" + name, indexed.get(name))
    for item in inputs:
        path = Path(os.path.abspath(root / item))
        if path.name == ".git" or root / ".git" in path.parents:
            raise ValueError(".git is provenance, not a declared input tree")
        add(path, "input:" + str(path))
        if records["input:" + str(path)]["type"] == "missing": raise ValueError("missing declared input: " + str(path))
        if path.is_dir():
            for directory, dirs, files in os.walk(path, followlinks=False):
                for name in sorted(dirs + files):
                    p = Path(directory) / name
                    add(p, "input:" + str(p))
    # Per-path mode/blob entries above carry index semantics, not its stat cache.
    return dict(root=str(root), head=text_git(root, "rev-parse", "HEAD"), files=records,
                exclusions=[str(p) for p in exclusions]), witness


def snapshot(root, inputs=(), exclusions=()):
    try:
        from posix_runtime import artifact_path
        exclusions = [artifact_path(p) for p in exclusions]
        first, witness = capture_once(root, inputs, exclusions)
        second, later = capture_once(root, inputs, exclusions)
        if first != second or witness != later: raise ValueError("unstable snapshot capture")
        return dict(schema_version=1, valid=True, snapshot_id=digest(encoded(first)), manifest=first,
                    mutation_witness=witness, reason=None)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return dict(schema_version=1, valid=False, snapshot_id=None, reason=str(e))


def environment(spec):
    c = spec["verification"]["check"]; variables = {}; tools = []
    for entry in [dict(tool=spec["shell"], version_args=["--version"])] + c["environment"]:
        if isinstance(entry, str):
            variables[entry] = digest(encoded(os.environ.get(entry))); continue
        path = shutil.which(entry["tool"])
        if path is None: raise ValueError("unknown tool: " + entry["tool"])
        resolved = Path(path).resolve(strict=True)
        record, _ = file_record(resolved)
        version = subprocess.run([str(resolved), *entry["version_args"]], capture_output=True,
                                 stdin=subprocess.DEVNULL, timeout=3, check=True)
        output = version.stdout + version.stderr
        if not output or len(output) > 4096: raise ValueError("unverifiable tool version output")
        tools.append(dict(name=entry["tool"], path=str(resolved), sha256=record["sha256"],
                          version=output.decode("utf-8", "strict").strip(), version_sha256=digest(output)))
    return dict(variables=variables, tools=tools, fingerprint=digest(encoded([variables, tools])))


def context(spec):
    v = spec.get("verification")
    if v is None: return None
    if set(v) - {"check", "provenance", "repeat_reason"} or not isinstance(v.get("provenance"), dict):
        raise ValueError("invalid verification binding")
    c = check(v["check"])
    if v.get("repeat_reason") is not None and (not isinstance(v["repeat_reason"], str) or not v["repeat_reason"]):
        raise ValueError("invalid repeat_reason")
    if c != v["check"] or c["command"] != spec["command"]:
        raise ValueError("verification check differs from executed command")
    for field in ("timeout_seconds", "cancel_grace_seconds", "no_progress_seconds", "resource_key", "progress_file"):
        if c[field] != spec.get(field): raise ValueError("verification policy differs: " + field)
    snap = snapshot(spec["cwd"], c["inputs"], [Path(spec["run_dir"]).parent.parent])
    try:
        env = environment(spec)
        error = None
    except (OSError, KeyError, ValueError, subprocess.SubprocessError) as e:
        env = None; error = str(e)
    p = v["provenance"]
    if (set(p) != {"kind", "base_sha", "preparation", "linked_dependencies"} or
            p.get("kind") not in ("HEAD", "BASE") or not isinstance(p.get("linked_dependencies"), list) or
            not re.fullmatch(r"[a-f0-9]{40}", p.get("base_sha", ""))):
        error = error or "unverifiable-provenance"
    elif p["kind"] == "BASE":
        try:
            if (p["preparation"] != "git-worktree-add-detach" or not snap["valid"] or
                    snap["manifest"]["head"] != p["base_sha"] or
                    git(spec["cwd"], "diff", "--name-only", p["base_sha"])):
                error = error or "unverifiable-base-files"
        except subprocess.SubprocessError:
            error = error or "unverifiable-base-files"
    key = dict(check=c, provenance=v["provenance"], shell=spec["shell"], cwd=spec["cwd"],
               snapshot_id=snap["snapshot_id"], environment=env,
               implementation_sha256=digest(Path(__file__).read_bytes() + Path(__file__).with_name("run_check.py").read_bytes() +
                                            Path(__file__).with_name("posix_runtime.py").read_bytes()))
    return dict(snapshot=snap, environment=env, key=key, reason=error)


def log_records(st):
    return [dict(path=st[n + "_log"], bytes=Path(st[n + "_log"]).stat().st_size,
                 sha256=file_digest(st[n + "_log"])) for n in ("stdout", "stderr")]


def tail(path):
    with Path(path).open("rb") as f:
        end = f.seek(0, 2); f.seek(max(0, end-65536))
        return "\n".join(f.read(65536).decode("utf-8", "replace").splitlines()[-200:])


def signature(root, output):
    rows = []
    for line in output.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line).replace(root, "ROOT")
        line = re.sub(r"[^ ]*verify-gate-base\.[A-Za-z0-9]*", "ROOT", line)
        line = re.sub(r"[0-9]+(\.[0-9]+)?s\b", "Ns", line)
        if not re.search(r"\b(passed|failed|errors?|skipped)\b", line): line = re.sub(r"[0-9]{2,}", "N", line)
        if line.strip(): rows.append(line)
    return "\n".join(rows[-8:])


def evidence_valid(st, request=None):
    try:
        result_path = Path(st["run_dir"]) / "result.json"
        result_bytes = result_path.read_bytes()
        if digest(result_bytes) != load(result_path.with_name("result.sha256")): return False
        # Validate the supplied record against the same bytes whose seal passed.
        # A copy must not borrow an intact run's seal after changing its outcome.
        if st != json.loads(result_bytes): return False
        e = st["evidence"]
        if (e["schema_version"] != 1 or not e["valid"] or st["state"] != "exited" or
                not st["cleanup_verified"] or not st["logs_complete"] or st["exit_code"] is None): return False
        if e["logs"] != log_records(st): return False
        if e["failure_signature"] != signature(st["cwd"], tail(st["stdout_log"]) + "\n" + tail(st["stderr_log"])): return False
        req = request or load(Path(st["run_dir"]) / "request.json")
        if e["request_sha256"] != digest(encoded(req)): return False
        if any(st[k] != req[k] for k in ("run_id", "run_dir", "owner", "command", "cwd", "shell")): return False
        if e["key"]["check"] != req["verification"]["check"] or e["key"]["provenance"] != req["verification"]["provenance"]: return False
        if e["source_before"]["snapshot_id"] != e["source_after"]["snapshot_id"]: return False
        if e["source_before"]["mutation_witness"] != e["source_after"]["mutation_witness"]: return False
        if e.get("origin_run_id"):
            origin_path = Path(e["origin_result"])
            if digest(origin_path.read_bytes()) != e["origin_sha256"]: return False
            original = load(origin_path)
            if original["run_id"] != e["origin_run_id"] or original["evidence"].get("origin_run_id"): return False
            if not evidence_valid(original): return False
        return True
    except (OSError, ValueError, KeyError, TypeError): return False


def find_reuse(spec, before):
    c = spec["verification"]["check"]
    if not c["hermetic"]: return None, "non-hermetic"
    if spec["verification"]["provenance"].get("linked_dependencies"): return None, "linked-dependencies-unverifiable"
    if c["independent_replay"]: return None, "required-independent-replay"
    if spec["verification"].get("repeat_reason"): return None, spec["verification"]["repeat_reason"]
    if not before["snapshot"]["valid"] or before["reason"]: return None, "unknown-input-or-environment"
    for path in sorted(Path(spec["run_dir"]).parent.glob("*/result.json")):
        try:
            if path.is_symlink() or path.parent.is_symlink(): continue
            st = load(path); e = st["evidence"]
            if path.parent != Path(st["run_dir"]): continue
            if (e["reusable"] and not e.get("origin_run_id") and e["key"] == before["key"]
                    and evidence_valid(st)):
                return st, "matching-evidence"
        except (OSError, ValueError, KeyError, TypeError): pass
    return None, "no-matching-valid-evidence"


def finish_evidence(spec, st, before, repeat_reason, origin=None):
    after = context(spec)
    reasons = []
    if before is None: reasons.append("command-not-started")
    elif not before["snapshot"]["valid"] or not after["snapshot"]["valid"]: reasons.append("unknown-snapshot")
    elif before["snapshot"] != after["snapshot"]: reasons.append("input-mutation")
    if before and (before["reason"] or after["reason"]): reasons.append("unknown-environment")
    elif before and before["key"] != after["key"]: reasons.append("environment-mutation")
    if st["state"] != "exited" or not st["cleanup_verified"] or not st["logs_complete"]: reasons.append("incomplete-command")
    try: logs = log_records(st)
    except OSError: logs = []; reasons.append("incomplete-logs")
    e = dict(schema_version=1, key=before["key"] if before else None,
             source_before=before["snapshot"] if before else None, source_after=after["snapshot"],
             environment=after["environment"], valid=not reasons, invalidation_reasons=reasons,
             reusable=not reasons and spec["verification"]["check"]["hermetic"] and not spec["verification"]["provenance"].get("linked_dependencies"),
             request_sha256=digest(encoded(spec)), logs=logs, repeat_reason=repeat_reason,
             failure_signature=signature(st["cwd"], tail(st["stdout_log"]) + "\n" + tail(st["stderr_log"])),
             origin_run_id=None)
    if origin:
        path = Path(origin["run_dir"]) / "result.json"
        e.update(origin_run_id=origin["run_id"], origin_result=str(path), origin_sha256=digest(path.read_bytes()))
    return e


def review_provenance(path, files):
    if not path.exists():
        return {"status": "unknown"}, []
    raw = path.read_bytes(); data = json.loads(raw.decode("utf-8-sig")); bindings = []
    if (data.get("schema_version") != 1 or set(data) - {"schema_version", "writes", "contracts", "inputs"}
            or not {"writes", "contracts"} <= set(data)):
        raise ValueError("invalid review provenance declaration")
    def values(obj):
        if isinstance(obj, dict): return [v for item in obj.values() for v in values(item)]
        if isinstance(obj, list): return [v for item in obj for v in values(item)]
        return [obj]
    for write in data["writes"]:
        required = {"family", "files", "receipt_path", "receipt_sha256", "run_id", "task_id", "dispatch_id"}
        if set(write) != required or not isinstance(write["files"], list) or not write["family"]:
            raise ValueError("invalid write provenance")
        receipt = Path(write["receipt_path"])
        saved = receipt.read_bytes()
        if digest(saved) != write["receipt_sha256"]: raise ValueError("changed write receipt")
        facts = values(json.loads(saved.decode("utf-8-sig")))
        if any(not write[k] or write[k] not in facts for k in ("run_id", "task_id", "dispatch_id")):
            raise ValueError("write receipt binding mismatch")
        bindings.append(write)
        for record in files:
            if record["path"] in write["files"]:
                record["author_families"] = sorted(set(record["author_families"] + [write["family"]]))
                record["authorship"] = "requires-family-validation"
    contracts = []
    for c in data["contracts"]:
        if (set(c) != {"id", "producer", "consumer"} or not c["id"] or
                any(not isinstance(c[k], list) or not c[k] or any(not isinstance(p, str) or not p for p in c[k]) for k in ("producer", "consumer"))):
            raise ValueError("invalid producer/consumer contract")
        contracts.append(dict(c, coverage="uncovered"))
    if raw != path.read_bytes(): raise ValueError("changed review provenance")
    return dict(path=str(path), sha256=digest(raw), writes=bindings, status="requires-family-validation"), contracts


def package(base, head, outfile=None):
    root = Path(text_git(Path.cwd(), "rev-parse", "--show-toplevel"))
    base = text_git(root, "rev-parse", "--verify", base + "^{commit}")
    if head != "WORKTREE": head = text_git(root, "rev-parse", "--verify", head + "^{commit}")
    if not outfile:
        if head == "WORKTREE": raise ValueError("WORKTREE mode requires OUTFILE")
        outfile = root / ".superpowers" / "sdd" / ("review-" + base[:7] + ".." + head[:7] + ".diff")
    out = Path(os.path.abspath(outfile)); manifest_path = Path(str(out) + ".manifest.json")
    parts_dir = Path(str(out) + ".parts")
    for p in (out, manifest_path, parts_dir, *out.parents):
        if p.is_symlink(): raise ValueError("symlink package output")
    out.parent.mkdir(parents=True, exist_ok=True)
    # Only recognized SDD storage plus this exact output family is service data.
    exclusions = [out, manifest_path, parts_dir, Path(str(out) + ".provenance.json")]
    for parent in out.parents:
        if parent == root or root not in parent.parents: break
        if parent.parent.name == "sdd" and parent.parent.parent.name == ".superpowers":
            exclusions.insert(0, parent); break
    provenance_path = Path(str(out) + ".provenance.json")
    declared_inputs = load(provenance_path).get("inputs", []) if provenance_path.exists() else []
    if not isinstance(declared_inputs, list) or any(not isinstance(p, str) or not p for p in declared_inputs):
        raise ValueError("invalid review inputs")
    before = snapshot(root, declared_inputs, exclusions)
    index = Path(text_git(root, "rev-parse", "--git-path", "index"))
    if not index.is_absolute(): index = root / index
    index_bytes = index.read_bytes() if index.exists() else None
    manifest = dict(schema_version=1, package_id=None, base=base, mode="worktree" if head == "WORKTREE" else "range",
                    head=head, snapshot_id=before["snapshot_id"], complete=False, files=[], parts=[],
                    exclusions=[str(p) for p in exclusions], limitations=[], coverage={"parts": [], "files": [], "contracts": []})
    manifest["inputs"] = declared_inputs
    manifest["declared_inputs"] = [dict(path=name[6:], record=record, coverage="uncovered", inspection_required=True)
                                   for name, record in before.get("manifest", {}).get("files", {}).items() if name.startswith("input:")]
    tmp = None
    try:
        env = {}; revision = [base, head] if head != "WORKTREE" else [base]
        # Exclude only nontracked service artifacts; tracked files remain reviewable.
        names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
        tracked = set(git(root, "ls-files", "--cached", "-z").split(b"\0"))
        omit = [p.decode("utf-8") for p in names if p and p not in tracked and excluded(root / p.decode("utf-8"), exclusions)]
        pathspec = ["."] + [":(top,literal,exclude)" + p for p in omit]
        untracked = {p.decode("utf-8") for p in git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p and p.decode("utf-8") not in omit}
        if head == "WORKTREE":
            fd, tmp = tempfile.mkstemp(prefix="orca-review-index-"); os.close(fd)
            if index_bytes is None: Path(tmp).unlink()
            else: Path(tmp).write_bytes(index_bytes)
            env = {"GIT_INDEX_FILE": tmp}
            git(root, "add", "--intent-to-add", "-A", "--", *pathspec, env=env)
        diff = git(root, "diff", "--binary", "--no-ext-diff", "--no-textconv", "-U10", *revision, "--", *pathspec, env=env)
        statuses = git(root, "diff", "--name-status", "--no-renames", "-z", *revision, "--", *pathspec, env=env).split(b"\0")
        for i in range(0, len(statuses)-1, 2):
            name = statuses[i+1].decode("utf-8")
            manifest["files"].append(dict(path=name, status=statuses[i].decode(), untracked=name in untracked,
                                          author_families=[], authorship="unknown", coverage="uncovered"))
        counts = git(root, "diff", "--numstat", "--no-renames", "-z", *revision, "--", *pathspec, env=env)
        binary = {entry.split(b"\t", 2)[2].decode("utf-8") for entry in counts.split(b"\0") if entry.startswith(b"-\t-\t")}
        for record in manifest["files"]:
            source = before.get("manifest", {}).get("files", {}).get("repo:" + record["path"], {})
            record.update(binary=record["path"] in binary, oversize=source.get("bytes", 0) > 65536)
            record["inspection_required"] = record["binary"] or record["oversize"]
        manifest["reviewed_trees"] = dict(base=text_git(root, "rev-parse", base + "^{tree}"),
                                          head=text_git(root, "rev-parse", head + "^{tree}") if head != "WORKTREE" else None)
        range_ = base + ".." + ("HEAD" if head == "WORKTREE" else head)
        commits = int(text_git(root, "rev-list", "--count", range_))
        log = git(root, "log", "--oneline", range_, "--", *pathspec)
        stats = git(root, "diff", "--stat", *revision, "--", *pathspec, env=env)
        data = (f"# Review package: {base}..{head}\n\n## Commits\n".encode() + log +
                (b"plus uncommitted working-tree changes\n" if head == "WORKTREE" else b"") +
                b"\n## Files changed\n" + stats + b"\n## Diff\n" + diff)
        out.write_bytes(data)
        if len(data) > 65536: parts_dir.mkdir(exist_ok=True)
        for start in range(0, len(data), 65536):
            chunk = data[start:start+65536]
            part = out if len(data) <= 65536 else parts_dir / ("%04d.diff" % (start // 65536))
            if part != out:
                if part.is_symlink(): raise ValueError("symlink package part")
                part.write_bytes(chunk)
            manifest["parts"].append(dict(path=str(part), start=start, end=start+len(chunk), sha256=digest(chunk)))
        if b"GIT binary patch" in diff: manifest["limitations"].append("binary source inspection required; uncovered until recorded")
        if any(len(line) > 65536 for line in diff.split(b"\n")): manifest["limitations"].append("oversize line split by byte range; source inspection required")
        provenance = Path(str(out) + ".provenance.json")
        manifest["provenance"], manifest["coverage"]["contracts"] = review_provenance(provenance, manifest["files"])
        after = snapshot(root, declared_inputs, exclusions)
        manifest.update(bytes=len(data), sha256=digest(data), snapshot=before, snapshot_after=after,
                        complete=before["valid"] and before == after)
        if not manifest["complete"]: manifest["limitations"].append("unknown or changed snapshot")
    except Exception as e:
        raise RuntimeError("package generation failed: " + str(e)) from e
    finally:
        if tmp: Path(tmp).unlink(missing_ok=True)
        manifest["index_preserved"] = index_bytes == (index.read_bytes() if index.exists() else None)
        if not manifest["index_preserved"]: manifest["complete"] = False
        identity = dict(manifest); identity.pop("package_id", None)
        manifest["package_id"] = digest(encoded(identity))
        save(manifest_path, manifest)
    if not manifest["complete"]: raise ValueError("incomplete package: " + str(manifest_path))
    empty = not manifest["files"] or (head != "WORKTREE" and commits == 0)
    print(("EMPTY " if empty else "wrote ") + str(out) + ": %d commit(s), %d bytes" % (commits, len(data)))
    return 1 if empty else 0


def package_valid(path):
    try:
        m = load(path)
        identity = dict(m); identifier = identity.pop("package_id")
        if digest(encoded(identity)) != identifier: return False
        if not m["complete"] or not m["index_preserved"]: return False
        data = Path(str(path).removesuffix(".manifest.json")).read_bytes()
        if len(data) != m["bytes"] or digest(data) != m["sha256"]: return False
        offset = 0
        for p in m["parts"]:
            part = Path(p["path"]).read_bytes()
            if p["start"] != offset or p["end"] - offset != len(part) or len(part) > 65536: return False
            if digest(part) != p["sha256"] or part != data[offset:p["end"]]: return False
            offset = p["end"]
        if offset != len(data): return False
        provenance = m["provenance"]
        if provenance.get("path"):
            if file_digest(provenance["path"]) != provenance["sha256"]: return False
            for write in provenance["writes"]:
                if file_digest(write["receipt_path"]) != write["receipt_sha256"]: return False
        current = snapshot(m["snapshot"]["manifest"]["root"], m["inputs"], m["exclusions"])
        # Mutation witnesses guard capture/execution, not later metadata refreshes.
        return current["valid"] and current["snapshot_id"] == m["snapshot_after"]["snapshot_id"]
    except (OSError, ValueError, KeyError, TypeError): return False


def main(args):
    if args[0] == "parse":
        checks = parse(args[1], args[3] or None, args[4] or None)
        Path(args[2]).write_bytes(b"".join(encoded(c) + b"\0" for c in checks)); return 0
    if args[0] == "package":
        try: return package(*args[1:])
        except Exception as e:
            if len(args) == 4:
                target = Path(os.path.abspath(args[3] + ".manifest.json"))
                if target.parent.exists() and not any(p.is_symlink() for p in (target, *target.parents)):
                    save(target, dict(schema_version=1, complete=False, error=str(e)))
            raise
    if args[0] == "snapshot":
        s = load(args[1]); save(args[2], snapshot(s["root"], s.get("inputs", []), s.get("exclusions", []))); return 0
    if args[0] == "canonical":  # the identity bytes of a JSON value (backend parity fixture)
        Path(args[2]).write_bytes(encoded(load(args[1]))); return 0
    if args[0] == "validate-evidence": return 0 if evidence_valid(load(args[1])) else 1
    if args[0] == "validate-package": return 0 if package_valid(args[1]) else 1
    raise ValueError("unknown verification operation")


if __name__ == "__main__":
    try: sys.exit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as e:
        print("verification: " + str(e), file=sys.stderr); sys.exit(1 if isinstance(e, RuntimeError) else 2)

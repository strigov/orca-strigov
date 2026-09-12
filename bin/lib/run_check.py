#!/usr/bin/env python3
"""Local C3 supervisor. No scheduler, cache, or model polling.

See skills/orca-dev/runtime-contracts.md. POSIX only; Windows uses run-check.ps1.
"""
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def safe(path):
    """Reject links in every existing component, including the leaf."""
    p = Path(os.path.abspath(path))
    for part in (*reversed(p.parents), p):
        if part.is_symlink():
            raise ValueError("symlink in owned artifact path: " + str(part))
    return p


def read(path):
    return json.loads(safe(path).read_text(encoding="utf-8-sig"))


def atomic(path, data):
    p = safe(path)
    tmp = p.with_name(p.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def identity(pid):
    # Linux exposes a boot-scoped start tick, not merely a recyclable PID.
    try:
        stat = Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return False  # confirmed exit, even when the parent's wait is delayed
        return {"pid": pid, "start": stat[19],
                "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "host": socket.gethostname()}
    except FileNotFoundError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            pass
        return None
    except (OSError, IndexError):
        return None


def alive(record):
    if not record:
        return None
    current = identity(record["pid"])
    if current is None:
        return None
    if current is False:
        return False
    if current["host"] != record.get("host") or current["boot"] != record.get("boot"):
        return None
    return current == record


def group_alive(pgid):
    """Zombies are exited, but a live grandchild still owns the resource."""
    try:
        rows = subprocess.run(["ps", "-eo", "pgid=,stat="], capture_output=True,
                              text=True, timeout=2, check=True).stdout.splitlines()
        return any(int(v[0]) == pgid and not v[1].startswith("Z")
                   for row in rows if len(v := row.split()) >= 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def tree_clear(status):
    tree = status.get("tree")
    if not tree or tree.get("kind") != "posix-group":
        return None
    # Never signal a stale group. Recovery only observes it. A reused group,
    # unknown host, unreadable identity, or any live member keeps the lock.
    record = tree.get("leader")
    if not record or alive(record) is None:
        return None
    members = group_alive(tree["pgid"])
    return None if members is None else not members


def observe(run_dir):
    try:
        s = read(run_dir / "result.json" if (run_dir / "result.json").exists()
                 else run_dir / "status.json")
    except FileNotFoundError:
        return {"state": "unknown", "reason": "initializing-or-lost-owner", "run_dir": str(run_dir)}
    if s["state"] in ("running", "waiting-resource") and alive(s.get("supervisor")) is not True:
        s = dict(s, state="unknown", reason="owner-unverifiable-or-exited", logs_complete=False,
                 exit_code=None, cleanup_verified=tree_clear(s) is True)
    return s


def owner_valid(owner):
    fields = {"local": {"kind", "id"}, "orca": {"kind", "orca_run_id", "task_id", "dispatch_id", "terminal_handle"}}
    return (isinstance(owner, dict) and set(owner) == fields.get(owner.get("kind"))
            and all(isinstance(v, str) and v for v in owner.values()))


def spec_valid(s):
    required = {"schema_version", "run_id", "owner", "cwd", "command", "shell", "run_dir",
                "timeout_seconds", "cancel_grace_seconds", "no_progress_seconds"}
    if set(s) - required - {"progress_file", "resource_key"} or required - set(s):
        raise ValueError("unexpected or missing spec fields")
    if s["schema_version"] != 1 or not owner_valid(s["owner"]):
        raise ValueError("invalid schema or owner")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", s["run_id"]):
        raise ValueError("invalid run_id")
    for name in ("command", "shell", "cwd", "run_dir"):
        if not isinstance(s[name], str) or not s[name] or "\0" in s[name]:
            raise ValueError("invalid " + name)
    for name in ("timeout_seconds", "cancel_grace_seconds", "no_progress_seconds"):
        value = s[name]
        if value is None and name != "cancel_grace_seconds":
            continue
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid " + name)
    for name in ("cwd", "run_dir", "shell"):
        if not os.path.isabs(s[name]):
            raise ValueError(name + " must be absolute")
    if not Path(s["cwd"]).is_dir() or Path(s["shell"]).name not in ("bash", "sh"):
        raise ValueError("cwd must exist; shell must name bash or sh")
    r = safe(s["run_dir"])
    ws = r.parent.parent
    if (r.name != s["run_id"] or r.parent.name != "checks" or ws.parent.name != "sdd"
            or ws.parent.parent.name != ".superpowers" or not ws.is_dir()):
        raise ValueError("run_dir must be an existing plan workspace / checks / run_id")
    if s.get("resource_key") is not None and (not isinstance(s["resource_key"], str) or not s["resource_key"]):
        raise ValueError("invalid resource_key")
    if s.get("progress_file") is not None:
        if not os.path.isabs(s["progress_file"]):
            raise ValueError("progress_file must be absolute")
        safe(s["progress_file"])
    return r


def resource_path(s):
    if not s.get("resource_key"):
        return None
    common = subprocess.run(["git", "-C", s["cwd"], "rev-parse", "--git-common-dir"],
                            check=True, capture_output=True, text=True, timeout=3).stdout.strip()
    common = str((Path(s["cwd"]) / common).resolve())
    key = hashlib.sha256((common + "\n" + s["resource_key"]).encode()).hexdigest()
    root = safe(Path(tempfile.gettempdir()).resolve() / ("orca-dev-resources-" + str(os.getuid())))
    root.mkdir(mode=0o700, exist_ok=True)
    if root.stat().st_uid != os.getuid():
        raise ValueError("foreign resource directory")
    return root / (key + ".json")


def claim(path, binding):
    if path is None:
        return True
    safe(path)
    try:
        with path.open("x", encoding="utf-8") as f:
            json.dump(binding, f)
            f.flush()
            os.fsync(f.fileno())
        return True
    except FileExistsError:
        try:
            previous = read(path)
            old = read(Path(previous["run_dir"]) / "status.json")
            if old.get("owner") != previous["owner"] or old.get("run_id") != previous["run_id"]:
                return False
            if alive(old.get("supervisor")) is not False:
                return False
            final = Path(previous["run_dir"]) / "result.json"
            if final.exists():
                old = read(final)
            if old.get("cleanup_verified") is not True and tree_clear(old) is not True:
                return False
            # Re-check the immutable lock inode before unlink. All contenders
            # serialize recovery with flock; the lock file itself is never aged.
            import fcntl
            with path.open("r") as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if os.fstat(f.fileno()).st_ino == path.stat().st_ino and read(path) == previous:
                    path.unlink()
        except (OSError, ValueError, KeyError):
            pass
        return False


def run(s):
    r = spec_valid(s)
    r.parent.mkdir(exist_ok=True)
    try:
        r.mkdir()
    except FileExistsError:
        if read(r / "request.json") != s:
            raise ValueError("run_id already bound to a different spec")
        state = observe(r)
        print(json.dumps(state, ensure_ascii=False))
        return code(state)
    atomic(r / "request.json", s)
    for name in ("stdout.log", "stderr.log"):
        (r / name).touch(exist_ok=False)
    started = time.monotonic()
    st = dict(schema_version=1, run_id=s["run_id"], run_dir=str(r), owner=s["owner"],
              supervisor=identity(os.getpid()), command=s["command"], cwd=s["cwd"], shell=s["shell"],
              started_at=now(), finished_at=None, duration_seconds=0, exit_code=None,
              state="waiting-resource", reason=None, tree=None, cleanup_verified=False,
              logs_complete=False, stdout_log=str(r / "stdout.log"), stderr_log=str(r / "stderr.log"),
              timeout_seconds=s["timeout_seconds"], resource_lock=None,
              meaningful_progress="unknown", output_activity=False, stalled=False, diagnostic_events=0)
    atomic(r / "status.json", st)
    lock = None
    claimed = False
    child = None
    reason = None
    cancel_at = None
    forced_at = None
    progress = None
    last_progress = started
    interrupted = []
    old_handlers = {sig: signal.signal(sig, lambda n, f: interrupted.append(n))
                    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    binding = {"run_id": s["run_id"], "run_dir": str(r), "owner": s["owner"]}
    try:
        lock = resource_path(s)
        st["resource_lock"] = str(lock) if lock else None
        while True:
            elapsed = time.monotonic() - started
            if interrupted:
                reason = reason or "signal"
            if (r / "cancel.json").exists():
                if read(r / "cancel.json") == s["owner"]:
                    reason = reason or "cancel"
            if s["timeout_seconds"] is not None and elapsed >= s["timeout_seconds"]:
                reason = reason or "deadline"
            if not claimed and not reason:
                claimed = claim(lock, binding)
            if claimed and child is None and not reason:
                # The fork cannot execute the command before durable group binding.
                ready_r, ready_w = os.pipe()
                go_r, go_w = os.pipe()
                child = os.fork()
                if child == 0:
                    try:
                        os.close(ready_r); os.close(go_w)
                        for sig in old_handlers:
                            signal.signal(sig, signal.SIG_DFL)
                        os.setsid()
                        os.write(ready_w, b"1"); os.close(ready_w)
                        if os.read(go_r, 1) != b"1":
                            os._exit(125)
                        os.close(go_r)
                        os.chdir(s["cwd"])
                        for fd, path, flags in ((0, "/dev/null", os.O_RDONLY),
                                                (1, r / "stdout.log", os.O_WRONLY),
                                                (2, r / "stderr.log", os.O_WRONLY)):
                            f = os.open(path, flags); os.dup2(f, fd); os.close(f)
                        os.execv(s["shell"], [s["shell"], "-c", s["command"]])
                    except BaseException:
                        os._exit(127)
                os.close(ready_w); os.close(go_r)
                if os.read(ready_r, 1) != b"1":
                    raise RuntimeError("child setup failed")
                os.close(ready_r)
                st["tree"] = {"kind": "posix-group", "pgid": child, "leader": identity(child)}
                st["state"] = "running"
                atomic(r / "status.json", st)
                os.write(go_w, b"1"); os.close(go_w)
            if child is not None:
                # WNOWAIT pins the leader PID until the whole group is dealt with.
                end = os.waitid(os.P_PID, child, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                members = group_alive(child)
                if end is not None and members is False:
                    _, raw = os.waitpid(child, 0)
                    st["exit_code"] = os.waitstatus_to_exitcode(raw)
                    st["cleanup_verified"] = True
                    break
                if end is not None:
                    reason = reason or "descendants-after-exit"
                if reason and cancel_at is None:
                    os.killpg(child, signal.SIGTERM)
                    cancel_at = time.monotonic()
                if cancel_at is not None and time.monotonic() - cancel_at >= s["cancel_grace_seconds"] and forced_at is None:
                    os.killpg(child, signal.SIGKILL)
                    forced_at = time.monotonic()
                if forced_at is not None and time.monotonic() - forced_at > 2:
                    st["reason"] = "cleanup-unverifiable"
                    break
            elif reason:
                st["cleanup_verified"] = True  # no fork was attempted
                break
            if s.get("progress_file"):
                try:
                    with safe(s["progress_file"]).open("rb") as f:
                        value = f.read(4097)
                    if len(value) > 4096:
                        raise ValueError("progress_file exceeds 4096 bytes")
                    if value != progress:
                        progress = value
                        last_progress = time.monotonic()
                        st["stalled"] = False
                        st["meaningful_progress"] = value.decode("utf-8", errors="replace")
                except FileNotFoundError:
                    pass
            st["output_activity"] = any((r / n).stat().st_size for n in ("stdout.log", "stderr.log"))
            if s["no_progress_seconds"] is not None and time.monotonic() - last_progress >= s["no_progress_seconds"] and not st["stalled"]:
                st["stalled"] = True
                st["diagnostic_events"] += 1
            st["duration_seconds"] = elapsed
            atomic(r / "status.json", st)
            time.sleep(0.08)
    except BaseException as e:
        reason = "runner-error: " + str(e)
        # Only the still-pinned, durably bound child group is eligible for kill.
        if child and st["tree"]:
            try:
                os.killpg(child, signal.SIGKILL)
                until = time.monotonic() + 2
                while group_alive(child) is True and time.monotonic() < until:
                    time.sleep(0.05)
                st["cleanup_verified"] = group_alive(child) is False
                if st["cleanup_verified"]:
                    _, raw = os.waitpid(child, 0)
                    st["exit_code"] = os.waitstatus_to_exitcode(raw)
            except OSError:
                pass
        elif child is None:
            st["cleanup_verified"] = True
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    st.update(finished_at=now(), duration_seconds=time.monotonic() - started,
              state="exited" if not reason and st["cleanup_verified"] else
                    "interrupted" if st["cleanup_verified"] else "unknown",
              reason=st["reason"] or reason or "exit", logs_complete=st["cleanup_verified"])
    atomic(r / "status.json", st)
    atomic(r / "result.json", st)
    if claimed and lock and st["cleanup_verified"] and read(lock) == binding:
        safe(lock).unlink()
    print(json.dumps(st, ensure_ascii=False))
    return code(st)


def code(st):
    if st.get("state") == "exited" and st.get("cleanup_verified") and st.get("logs_complete"):
        rc = st["exit_code"]
        return min(255, rc if rc >= 0 else 128 - rc)
    return 124 if st.get("state") == "interrupted" else 125


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "run":
        return run(read(args[1]))
    if len(args) in (2, 3) and args[0] == "wait":
        r = safe(args[1])
        seconds = float(args[2]) if len(args) == 3 else 60
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("invalid wait duration")
        end = time.monotonic() + seconds
        initial = observe(r)
        while True:
            st = observe(r)
            if (st["state"] not in ("running", "waiting-resource") or
                    st.get("diagnostic_events") != initial.get("diagnostic_events") or time.monotonic() >= end):
                print(json.dumps(st, ensure_ascii=False))
                return code(st)
            time.sleep(0.1)
    if len(args) == 3 and args[0] == "cancel":
        r = safe(args[1])
        owner = read(args[2])
        if owner != read(r / "request.json")["owner"]:
            raise ValueError("cancel owner does not match run")
        atomic(r / "cancel.json", owner)
        print(json.dumps(observe(r), ensure_ascii=False))
        return 0  # receipt only; wait/result is the completion evidence
    raise ValueError("usage: run-check run SPEC_JSON | wait RUN_DIR [SECONDS] | cancel RUN_DIR OWNER_JSON")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("run-check: " + str(error), file=sys.stderr)
        sys.exit(125)

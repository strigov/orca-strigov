"""Bounded real-process fixtures; never run installers or alter user config."""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def until(probe, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = probe()
            if value:
                return value
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.04)
    raise AssertionError("bounded event wait expired")


def stop_owned(p):
    if p.poll() is not None:
        return
    if WINDOWS:
        # Test-only backstop, bound to the still-open Popen incarnation.
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    else:
        os.killpg(p.pid, signal.SIGKILL)
    p.kill()


class Process:
    """Every test process gets a parent watchdog, including assertion failures."""
    def __init__(self, argv, cwd, seconds=14, log_stem=None):
        self.log_stem = log_stem
        self.p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=0x08000000 if WINDOWS else 0,
                                  start_new_session=not WINDOWS)
        self.timer = threading.Timer(seconds, stop_owned, [self.p])
        self.timer.daemon = True
        self.timer.start()

    def finish(self, timeout=14):
        try:
            out, err = self.p.communicate(timeout=timeout)
            if self.log_stem:
                Path(str(self.log_stem) + '.stdout').write_bytes(out)
                Path(str(self.log_stem) + '.stderr').write_bytes(err)
            return self.p.returncode, out.decode("utf-8-sig", "replace"), err.decode("utf-8-sig", "replace")
        finally:
            if self.p.poll() is None:
                stop_owned(self.p)
                self.p.wait(timeout=3)
            self.timer.cancel()

    def close(self):
        stop_owned(self.p)
        self.finish()


def command(argv, cwd, timeout=14):
    return Process(argv, cwd, timeout).finish(timeout)


class TwoWorktrees:
    """Reusable Git fixture: only these temporary repositories acquire commits."""
    def __init__(self, base):
        self.root = Path(base) / "repository with space"
        self.other = Path(base) / "second worktree"
        self.root.mkdir()
        self.git("init", "-q")
        (self.root / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "-c", "core.hooksPath=", "commit", "-qm", "fixture")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("worktree", "add", "--detach", "-q", str(self.other), self.base)
        self.workspaces = {}
        for root in (self.root, self.other):
            ws = root / ".superpowers" / "sdd" / "runner-fixture"
            ws.mkdir(parents=True)
            (ws.parent / ".gitignore").write_text("*\n", encoding="utf-8")
            self.workspaces[root] = ws

    def git(self, *args):
        rc, out, err = command(["git", "-C", str(self.root), *args], self.root)
        if rc:
            raise AssertionError((args, rc, out, err))
        return out


class RunnerFixture:
    def __init__(self, shell):
        self.shell = shell
        artifact_root = os.environ.get("ORCA_TEST_ARTIFACTS")
        if artifact_root:
            Path(artifact_root).mkdir(parents=True, exist_ok=True)
        self.base = Path(os.path.abspath(tempfile.mkdtemp(prefix="runner-", dir=artifact_root)))
        created = self.base.lstat()
        self.base_identity = (created.st_dev, created.st_ino)
        self.git = TwoWorktrees(self.base)
        self.processes = []

    def argv(self, script, *args):
        if WINDOWS:
            return [self.shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(ROOT / "bin" / (script + ".ps1")), *map(str, args)]
        return [self.shell, str(ROOT / "bin" / script), *map(str, args)]

    def python(self, code):
        value = base64.b64encode(code.encode("utf-8")).decode("ascii")
        snippet = "import base64;exec(base64.b64decode('" + value + "'))"
        if WINDOWS:
            return "& '" + sys.executable.replace("'", "''") + "' -u -c '" + snippet.replace("'", "''") + "'"
        import shlex
        return shlex.join([sys.executable, "-u", "-c", snippet])

    def spec(self, code="print('OK')", root=None, **fields):
        root = root or self.git.root
        rid = "test-" + uuid.uuid4().hex
        s = dict(schema_version=1, run_id=rid, owner=dict(kind="local", id=rid),
                 cwd=str(root), command=self.python(code), shell=self.shell,
                 run_dir=str(self.git.workspaces[root] / "checks" / rid),
                 timeout_seconds=9, cancel_grace_seconds=0.2, no_progress_seconds=None,
                 progress_file=None, resource_key=None)
        s.update(fields)
        path = self.base / (rid + ".json")
        write_json(path, s)
        return path, s

    def start(self, spec):
        p = Process(self.argv("run-check", "run", spec), self.git.root, log_stem=str(spec) + '.wrapper')
        self.processes.append(p)
        return p

    def invoke(self, *args):
        return command(self.argv("run-check", *args), self.git.root)

    def run(self, **kwargs):
        path, s = self.spec(**kwargs)
        rc, out, err = self.start(path).finish()
        result = read_json(Path(s["run_dir"]) / "result.json")
        return rc, result, out, err

    def close(self):
        for p in self.processes:
            p.close()
        if not os.environ.get("ORCA_TEST_ARTIFACTS"):
            def owned_regular_path(path):
                path = Path(path)
                if not path.is_absolute() or not path.is_relative_to(self.base):
                    raise ValueError("cleanup outside owned fixture: " + str(path))
                for ancestor in (path, *path.parents):
                    info = ancestor.lstat()
                    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                        raise ValueError("cleanup through symlink/reparse point: " + str(ancestor))
                return path.lstat()

            def readonly_unlink(function, path, error):
                exc = error[1]
                info = owned_regular_path(path)
                if (not WINDOWS or function is not os.unlink or not isinstance(exc, PermissionError)
                        or exc.winerror != 5 or not stat.S_ISREG(info.st_mode)
                        or not info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY):
                    raise exc
                os.chmod(path, info.st_mode | stat.S_IWRITE)
                function(path)

            info = owned_regular_path(self.base)
            if (info.st_dev, info.st_ino) != self.base_identity:
                raise ValueError("fixture directory identity changed")
            # stdlib rmtree unlinks symlinks/junctions without traversing targets.
            # Retry only access-denied deletion of an owned read-only regular file.
            shutil.rmtree(self.base, onerror=readonly_unlink)


def selected_shell():
    if WINDOWS:
        return os.environ.get("ORCA_TEST_SHELL", os.path.join(os.environ["SystemRoot"], "System32", "WindowsPowerShell", "v1.0", "powershell.exe"))
    return shutil.which("bash")


class VerificationFixture(RunnerFixture):
    """C4/C5 drivers share the existing bounded two-worktree fixture."""
    def __init__(self):
        super().__init__(selected_shell())
        self.workspace = self.git.workspaces[self.git.root]

    def helper(self, operation, *args):
        if WINDOWS:
            argv = [self.shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(ROOT / "bin/lib/verification.ps1"), operation, *map(str, args)]
        else:
            argv = [sys.executable, "-B", str(ROOT / "bin/lib/verification.py"), operation, *map(str, args)]
        return command(argv, self.git.root)

    def snapshot(self, inputs=(), exclusions=None):
        spec = self.base / "snapshot-input.json"; out = self.base / "snapshot-output.json"
        write_json(spec, dict(root=str(self.git.root), inputs=list(inputs), exclusions=exclusions or [str(self.workspace)]))
        result = self.helper("snapshot", spec, out)
        if result[0]: raise AssertionError(result)
        return read_json(out)

    def verified_spec(self, code="print('OK')", declaration=None, provenance=None, repeat_reason=None):
        sys.path.insert(0, str(ROOT / "bin/lib"))
        from verification import check
        path, spec = self.spec(code)
        c = check(dict(command=spec["command"], timeout_seconds=spec["timeout_seconds"],
                       cancel_grace_seconds=spec["cancel_grace_seconds"], **(declaration or {})))
        for name in ("command", "timeout_seconds", "cancel_grace_seconds", "no_progress_seconds", "resource_key", "progress_file"):
            spec[name] = c[name]
        spec["verification"] = dict(check=c, provenance=provenance or dict(kind="HEAD", base_sha=self.git.base,
                                                                         preparation="current-worktree", linked_dependencies=[]))
        if repeat_reason: spec["verification"]["repeat_reason"] = repeat_reason
        write_json(path, spec)
        return path, spec

    def verified_run(self, **kwargs):
        path, spec = self.verified_spec(**kwargs)
        rc, out, err = self.start(path).finish()
        result_path = Path(spec["run_dir"]) / "result.json"
        if not result_path.exists(): raise AssertionError((rc, out, err, spec))
        return rc, read_json(result_path)

    def counter_code(self):
        counter = self.workspace / "physical-executions.txt"
        code = ("from pathlib import Path; p=Path(" + repr(str(counter)) + "); "
                "p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); print('OK')")
        return counter, code

    def gate(self, declarations, *options, base=None):
        plan = self.workspace / "plan.md"
        plan.write_text("---\nslug: runner-fixture\nverify:\n" +
                        "".join("  - " + json.dumps(c, ensure_ascii=False) + "\n" for c in declarations) + "---\n", encoding="utf-8")
        return command(self.argv("verify-gate", plan, base or self.git.base, self.git.root, *options), self.git.root)

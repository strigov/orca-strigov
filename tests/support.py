"""Bounded real-process fixtures; never run installers or alter user config."""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
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
        self.base = Path(tempfile.mkdtemp(prefix="runner-", dir=artifact_root))
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
            # Fixtures create no junctions; symlink tests explicitly remove links.
            shutil.rmtree(self.base)

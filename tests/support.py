"""Bounded real-process fixtures; installers use only an isolated test home."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
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
# Scales only harness watchdogs and waits; deadlines under test are never scaled.
TIME_SCALE = float(os.environ.get("ORCA_TEST_TIME_SCALE") or 1)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def read_json(path):
    if WINDOWS:
        # Observe atomic JSON publication without denying its DELETE access.
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint,
                                       ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        try: fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
            raise
        with os.fdopen(fd, "r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def plan_structure(text):
    """C6 v2 plan structure digest: frontmatter minus bookkeeping lines (top-level status, plan_base,
    orca_run, commits; phase status, base, commits), a NUL, then the body. Independent of the validator."""
    import re
    text = text.replace('\r\n', '\n').removeprefix('\ufeff')
    match = re.match(r'^---\n(.*?)\n---(?:\n|$)', text, re.S)
    front = re.sub(r'^(?:status|plan_base|orca_run|commits|    status|    base|    commits):.*(?:\n|$)', '', match[1], flags=re.M)
    return hashlib.sha256((front + '\0' + text[match.end():]).encode('utf-8')).hexdigest()


def until(probe, timeout=5):
    end = time.monotonic() + timeout * TIME_SCALE
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
        subprocess.run([os.path.join(os.environ['SystemRoot'], 'System32', 'taskkill.exe'), "/PID", str(p.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    else:
        os.killpg(p.pid, signal.SIGKILL)
    p.kill()


class Process:
    """Every test process gets a parent watchdog, including assertion failures."""
    def __init__(self, argv, cwd, seconds=14, log_stem=None, env=None):
        self.log_stem = log_stem
        self.p = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  creationflags=0x08000000 if WINDOWS else 0,
                                  start_new_session=not WINDOWS, env=env)
        self.timer = threading.Timer(seconds * TIME_SCALE, stop_owned, [self.p])
        self.timer.daemon = True
        self.timer.start()

    def finish(self, timeout=14):
        try:
            out, err = self.p.communicate(timeout=timeout * TIME_SCALE)
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


def command(argv, cwd, timeout=14, env=None):
    return Process(argv, cwd, timeout, env=env).finish(timeout)


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
        self.base = Path(tempfile.mkdtemp(prefix="runner-", dir=artifact_root)).resolve()
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

    def start(self, spec, seconds=14):
        p = Process(self.argv("run-check", "run", spec), self.git.root,
                    seconds=seconds, log_stem=str(spec) + '.wrapper')
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
    return os.environ.get('ORCA_TEST_SHELL') or shutil.which("bash")


def installation_state(home=None):
    """Read only digests/link identities; never expose or restore user settings."""
    home = Path(home or Path.home())
    names = ['.claude.json', '.gemini/antigravity-cli/settings.json',
             '.codex/config.toml', '.codex/hooks.json', '.codex/skills/orca-dev',
             '.profile', '.bashrc', '.zshrc']
    state = {}
    for name in names:
        p = home / name
        try:
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                state[name] = ['link', os.readlink(p)]
            elif p.is_file(): state[name] = ['file', hashlib.sha256(p.read_bytes()).hexdigest()]
            else: state[name] = ['directory', info.st_dev, info.st_ino]
        except FileNotFoundError: state[name] = None
    state['process_home'] = os.environ.get('ORCA_DEV_HOME')
    if WINDOWS:
        import winreg
        values = []
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            for i in range(winreg.QueryInfoKey(key)[1]): values.append(winreg.EnumValue(key, i))
        state['user_environment_sha256'] = hashlib.sha256(json.dumps(sorted(values), default=str).encode()).hexdigest()
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment') as key:
            try: value = winreg.QueryValueEx(key, 'ORCA_DEV_HOME')
            except FileNotFoundError: value = None
        state['machine_home'] = value
    return state


def directory_state(root):
    """No traversal into even a dangling directory junction."""
    result = {}
    def visit(p):
        for child in p.iterdir():
            info = child.lstat(); name = str(child.relative_to(root))
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                result[name] = ['link', os.readlink(child)]
            elif child.is_dir(): result[name] = ['dir']; visit(child)
            else: result[name] = ['file', hashlib.sha256(child.read_bytes()).hexdigest()]
    visit(Path(root))
    return result


class InstallFixture(RunnerFixture):
    """Use the production test-home seam, never HOME/USERPROFILE overrides."""
    def __init__(self):
        self.real_before = installation_state()
        super().__init__(selected_shell())
        self.home = self.base / 'isolated home ü [space]'
        self.checkout = self.base / 'checkout ü [source] with space'
        self.home.mkdir(); self.checkout.mkdir()
        for name in ('install.ps1', 'install.sh', 'plugin.json'):
            shutil.copyfile(ROOT / name, self.checkout / name)
        for name in ('skills', 'bin', '.codex-plugin', '.claude-plugin', 'hooks'):
            shutil.copytree(ROOT / name, self.checkout / name, ignore=shutil.ignore_patterns('__pycache__'))
        (self.home / '.codex' / 'skills').mkdir(parents=True)
        (self.home / '.gemini' / 'antigravity-cli').mkdir(parents=True)
        write_json(self.home / '.claude.json', dict(unrelated={'keep': 7}, projects={'/unrelated': {'keep': True}}))
        write_json(self.home / '.gemini/antigravity-cli/settings.json', dict(keep=[1,2], trustedWorkspaces=['/unrelated']))
        (self.home / '.codex/config.toml').write_text('unrelated = true\n')
        self.target = self.home / '.codex/skills/orca-dev'
        self.env_file = self.home / '.orca-dev-user-environment.json'
        write_json(self.env_file, dict(keep=True, ORCA_DEV_HOME=str(self.base / 'old checkout')))
        self.env = dict(os.environ, ORCA_DEV_TEST_HOME=str(self.home), ORCA_DEV_HOME=str(self.checkout))
        # Any accidental live-runtime probe fails and leaves an owned sentinel.
        probes = self.base / 'probes'; probes.mkdir()
        for name in ('orca','codex','claude','agy','brew'):
            if WINDOWS:
                body = '@echo off\r\necho probe>"' + str(self.base / 'unexpected-probe') + '"\r\nexit /b 89\r\n'
                (probes / (name + '.cmd')).write_text(body)
            else:
                import shlex
                p = probes / name
                p.write_text('#!/bin/sh\nprintf probe > ' + shlex.quote(str(self.base / 'unexpected-probe')) + '\nexit 89\n')
                p.chmod(0o700)
        self.env['PATH'] = str(probes) + os.pathsep + os.environ['PATH']
        self.calls = 0

    def link(self, path, target):
        path.parent.mkdir(parents=True, exist_ok=True)
        if WINDOWS:
            q = lambda p: "'" + str(p).replace("'", "''") + "'"
            rc, out, err = command([self.shell, '-NoProfile', '-NonInteractive', '-Command',
                '$junctionTarget=' + q(target) + '; if ($PSVersionTable.PSVersion.Major -le 5) { $junctionTarget=[Management.Automation.WildcardPattern]::Escape($junctionTarget) }; New-Item -ItemType Junction -Path ' + q(path) + ' -Target $junctionTarget -ErrorAction Stop | Out-Null'], self.base)
            if rc: raise AssertionError((rc, out, err))
        else: path.symlink_to(target, target_is_directory=True)

    def install(self, check=False, env=None, legacy=True):
        self.calls += 1
        if WINDOWS:
            argv = [self.shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
                    str(self.checkout / 'install.ps1'), '-Check' if check else '-Repo', str(self.git.root)]
        else:
            argv = [self.shell, str(self.checkout / 'install.sh'), '--check' if check else '--repo', str(self.git.root)]
        if legacy: argv.append('-LegacySkill' if WINDOWS else '--legacy-skill')
        p = Process(argv, self.git.root, env=env or self.env, log_stem=self.base / ('install-' + str(self.calls)))
        self.processes.append(p)
        result = p.finish()
        print('INSTALL invocation ' + str(self.calls) + ' exit=' + str(result[0]) + '\n' + result[1] + result[2])
        if result[0] not in (0,1,2): raise AssertionError(result)
        if installation_state() != self.real_before: raise AssertionError('real user configuration changed')
        if (self.base / 'unexpected-probe').exists(): raise AssertionError('test invoked live CLI probe')
        return result

    def close(self):
        try:
            if installation_state() != self.real_before: raise AssertionError('real user configuration changed')
        finally: super().close()


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

    def helpers(self, steps):
        """Finite C4 CLI batches, including explicit fixture mutations between calls.

        Four calls share one native host/watchdog; each retains its actual CLI
        arguments, stdout, stderr and exit status. No running owner is shared.
        """
        results = []
        for offset in range(0, len(steps), 4):
            group = steps[offset:offset + 4]
            if not WINDOWS:
                for operation, args, before in group:
                    if before:
                        prepared = command([sys.executable, '-B', '-c', before], self.git.root)
                        if prepared[0]: raise AssertionError(prepared)
                    results.append(self.helper(operation, *args))
                continue
            quote = lambda p: "'" + str(p).replace("'", "''") + "'"
            script = self.base / 'verification-batch.ps1'
            lines = ["$ErrorActionPreference='Stop'"]
            for operation, args, before in group:
                if before:
                    lines += [self.python(before), "if ($LASTEXITCODE -ne 0) { throw 'fixture preparation failed' }"]
                lines += [
                    '$out=New-Object IO.StringWriter; $err=New-Object IO.StringWriter',
                    '$savedOut=[Console]::Out; $savedErr=[Console]::Error',
                    'try { [Console]::SetOut($out); [Console]::SetError($err); & ' +
                    quote(ROOT / 'bin/lib/verification.ps1') + ' ' +
                    ' '.join(quote(x) for x in (operation, *args)) +
                    ' } finally { [Console]::SetOut($savedOut); [Console]::SetError($savedErr) }',
                    '[Console]::WriteLine((@{code=$LASTEXITCODE; stdout=$out.ToString(); stderr=$err.ToString()} | ConvertTo-Json -Compress))',
                ]
            script.write_text('\n'.join(lines), encoding='utf-8-sig')
            rc, out, err = command([self.shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                                    '-File', str(script)], self.git.root)
            if rc or len(out.splitlines()) != len(group): raise AssertionError((rc, out, err))
            for line in out.splitlines():
                item = json.loads(line)
                results.append((item['code'], item['stdout'], item['stderr']))
        return results

    def snapshots(self, steps):
        """Capture every requested real mutation state, with unique durable outputs."""
        jobs = []; outputs = []
        for i, (before, inputs) in enumerate(steps):
            spec = self.base / ('snapshot-input-' + str(i) + '.json')
            out = self.base / ('snapshot-output-' + str(i) + '.json')
            write_json(spec, dict(root=str(self.git.root), inputs=list(inputs), exclusions=[str(self.workspace)]))
            jobs.append(('snapshot', (spec, out), before)); outputs.append(out)
        for result in self.helpers(jobs):
            if result[0]: raise AssertionError(result)
        return [read_json(out) for out in outputs]

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
        # The gate can run both HEAD and BASE, including snapshots and worktree
        # setup. Its outer watchdog must cover those sequential native launches;
        # each check still enforces its own declared deadline (including 0.3s).
        return command(self.argv("verify-gate", plan, base or self.git.base, self.git.root, *options),
                       self.git.root, timeout=60)


class ProtocolFixture(VerificationFixture):
    """Synthetic Orca receipts plus real Git/C4 artifacts; no live protocol effects."""
    def __init__(self, quickfix=False):
        super().__init__()
        import re
        self.models = json.loads(re.search(r'^FAMILY_MODELS: (.+)$',
            (ROOT / 'skills/orca-dev/roles.md').read_text(encoding='utf-8-sig'), re.M)[1])
        self.serial = 0
        self.plan = self.git.root / 'plan.md'
        if not quickfix:
            self.plan.write_text('---\nprotocol_version: 2\norca_run: fixture-run\nplan_base: ' + self.git.base +
                '\nstatus: implementing\ncontracts: ["C1"]\nphases:\n  - id: F1\n    risk: none\n    base: ' +
                self.git.base + '\n    consumes: []\n    produces: ["C1"]\n---\nFixture plan.\n', encoding='utf-8')
        (self.git.root / 'tracked.txt').write_text('candidate\n', encoding='utf-8')
        self.git.git('add', '--all')
        self.quickfix = quickfix
        self.state = self.v2_state()

    def v2_state(self):
        """A fresh schema 2 C6 state for this fixture (phase F1, or the plan-less quickfix step)."""
        plan = None if self.quickfix else self.plan_ref()
        # A Run that reached a phase had its plan approved in the plan step: the approved structure is the current one.
        return dict(schema_version=2, mode='quickfix' if self.quickfix else 'plan', plan=plan,
                    plan_approved=plan and plan['structure'], attempts=[],
                    ledger_path=None, orca_run='fixture-run', plan_base=self.git.base, phase=None if self.quickfix else 'F1',
                    base=self.git.base, step='quickfix' if self.quickfix else 'phase', worktree=str(self.git.root),
                    worktree_id='fixture-worktree', workspace=str(self.workspace), active=None,
                    rounds=dict(plan_review=0, fused_review=0, final_review=0, gate_fix=0), cap_extensions=[],
                    independence_waivers=[], provenance=[], plan_authors=[], authors={}, accepted=[], write_ownership=[],
                    phase_commits=[], final_source=None, processed_messages=[], used_fleet_ids=[])

    def plan_ref(self, path=None):
        path = Path(path or self.plan)
        return dict(self.reference(path), structure=plan_structure(path.read_text(encoding='utf-8-sig')))

    def plan_artifact(self):
        """An immutable workspace copy of the live plan, as a kind:plan artifact."""
        self.serial += 1
        copy = self.workspace / ('plan-copy-' + str(self.serial) + '.md'); copy.write_bytes(self.plan.read_bytes())
        return dict(self.reference(copy), kind='plan', source_path=str(self.plan))

    def git_commit(self, message='protocol fixture', *options):
        self.git.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                     '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=', 'commit', '-qm', message, *options)
        return self.git.git('rev-parse', 'HEAD').strip()

    def reference(self, path, **extra):
        return dict(path=str(path), sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(), **extra)

    def save(self, value, suffix='.json'):
        self.serial += 1
        path = self.workspace / ('protocol-' + str(self.serial) + suffix)
        if isinstance(value, str): path.write_text(value, encoding='utf-8')
        else: write_json(path, value)
        return self.reference(path)

    def snapshot_ref(self):
        return dict(self.save(self.snapshot()), kind='snapshot')

    def model(self, family):
        return next(m for m, f in self.models.items() if f == family)

    def assignment(self, role='implementer', family='OpenAI', round=1):
        self.serial += 1
        return dict(run_id='fixture-run', task_id='fixture-task-' + str(self.serial), dispatch_id='fixture-dispatch-' + str(self.serial),
            role=role, phase=self.state['phase'], round=round, model=self.model(family), worktree_id='fixture-worktree')

    def observation(self, assignment, status='completed', model=..., start=None, created=None):
        # Orca records when the Dispatch was created (UTC); C6 maps a write receipt to the phase it was dispatched in.
        created = created or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        ref = self.save(dict(ok=True, result=dict(dispatch=dict(id=assignment['dispatch_id'], taskId=assignment['task_id'],
            runId=assignment['run_id'], status=status, assigneeHandle='fixture-terminal', retryOfDispatchId=None, createdAt=created),
            projection=dict(provider=dict(id='fixture-cli', model=assignment['model'] if model is ... else model),
                workspace=dict(id='fixture-worktree'), evidence=dict(durable=True), liveness=dict(verdict='live')))))
        if start is not None: ref['start'] = start
        return ref

    def start_receipt(self, assignment):
        return self.save(dict(ok=True, result=dict(runId=assignment['run_id'], taskId=assignment['task_id'],
            dispatchId=assignment['dispatch_id'], launch=dict(effective=dict(model=assignment['model'])))))

    CLAUDE_HANDLE = 'term_fixture-agent'
    CLAUDE_INCARNATION = 'fixture-incarnation'

    def claude_observation(self, dispatch_id, task_id, status='running', model=None, incarnation=CLAUDE_INCARNATION):
        """Orca worker-show shape for Claude: provider.model stays null, terminal facts are present."""
        created = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
        return self.save(dict(ok=True, result=dict(
            dispatch=dict(id=dispatch_id, taskId=task_id, runId='fixture-run', status=status, assigneeHandle=self.CLAUDE_HANDLE,
                          retryOfDispatchId=None, processIncarnation='fixture-pty:' + incarnation, createdAt=created),
            worker=dict(agentTerminalHandle=self.CLAUDE_HANDLE),
            terminal=dict(handle=self.CLAUDE_HANDLE, incarnationId=incarnation, worktreeId='fixture-worktree', worktreePath=str(self.git.root)),
            projection=dict(provider=dict(id='claude', model=model), workspace=dict(id='fixture-worktree'),
                            evidence=dict(durable=True), liveness=dict(verdict='live')))))

    def launch_receipt(self, task_id, dispatch_id, action, model=None, run_id='fixture-run', handle=CLAUDE_HANDLE, incarnation=CLAUDE_INCARNATION):
        """worker-start: action 'created' launches a model; 'reused' (--terminal) carries none."""
        agent = 'claude' if model else None
        return self.save(dict(ok=True, result=dict(runId=run_id, taskId=task_id, dispatchId=dispatch_id,
            launch=dict(requested=dict(agent=agent, model=model, effort=None), effective=dict(agent=agent, model=model, effort=None)),
            effects=[dict(kind='terminal', role='agent', action=action, id=handle)], prompt=dict(processIncarnation=incarnation))))

    def agy_observation(self, dispatch_id, task_id, model=None):
        """Orca worker-show for Antigravity Path B: provider.model stays null."""
        ref = self.claude_observation(dispatch_id, task_id, model=model)
        data = read_json(ref['path']); data['result']['projection']['provider']['id'] = 'antigravity'
        return self.save(data)

    def agy_home(self, root, conversation, task_id, dispatch_id, models=('gemini-3.8-flash-high',), created=None, created_at=None, after=()):
        """Antigravity CLI data dir: brain/<conversation>/.../transcript.jsonl plus one process log."""
        logs = Path(root) / 'brain' / conversation / '.system_generated' / 'logs'; logs.mkdir(parents=True, exist_ok=True)
        preamble = ('<USER_REQUEST>\nYou are working inside Orca, a multi-agent IDE. You are a dispatched worker.\n'
                    'Your task ID is: ' + task_id + '\n  orca orchestration send --from ' + self.CLAUDE_HANDLE +
                    ' --type worker_done --task-id ' + task_id + ' --dispatch-id ' + dispatch_id + '\n</USER_REQUEST>')
        rows = [dict(step_index=0, source='USER_EXPLICIT', type='USER_INPUT', status='DONE', content=preamble),
                dict(step_index=1, source='MODEL', type='PLANNER_RESPONSE', status='DONE', content='ok')]
        if created_at is not None:  # real transcripts stamp every step in UTC seconds
            for row in rows: row['created_at'] = created_at
        rows += list(after)
        (logs / 'transcript.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        (Path(root) / 'log').mkdir(exist_ok=True)
        lines = ['I0927 02:04:47.302640       1 model_resolver.go:93] Resolving model ' + m for m in models]
        lines += ['I0927 02:05:17.786272     649 server.go:1239] Created conversation ' + (created or conversation)]
        log = Path(root) / 'log' / ('cli-' + conversation[:8] + '.log')
        log.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return logs / 'transcript.jsonl', log

    def claude_transcript(self, path, task_id, dispatch_id, models=('claude-opus-5-5',), cwd=None, after=()):
        """Claude Code session JSONL: Orca preamble, then assistant records carrying message.model."""
        preamble = ('You are working inside Orca, a multi-agent IDE. You are a dispatched worker.\n'
                    'Your task ID is: ' + task_id + '\n  orca orchestration send --from ' + self.CLAUDE_HANDLE +
                    ' --type worker_done --task-id ' + task_id + ' --dispatch-id ' + dispatch_id + ' --outcome succeeded\n')
        cwd = cwd or str(self.git.root)
        rows = [dict(type='attachment', sessionId='fixture-session'),
                dict(type='user', sessionId='fixture-session', cwd=cwd, message=dict(role='user', content=preamble))]
        rows += [dict(type='assistant', sessionId='fixture-session', cwd=cwd, message=dict(role='assistant', model=m, content=[]))
                 for m in models]
        Path(path).write_text(''.join(json.dumps(r) + '\n' for r in list(rows) + list(after)), encoding='utf-8')
        return Path(path)

    def agy_capture(self, proof, captured_at='2026-10-05T05:20:00.000000Z', **override):
        """The capture record antigravity-model-evidence writes after freezing the transcript and log of `proof`."""
        capture = dict(kind='antigravity-capture', conversation_id=proof['conversation_id'], transcript_sha256=proof['sha256'],
                       log_sha256=proof['log']['sha256'], captured_at=captured_at)
        capture.update(override)
        return self.save(capture)

    def codex_observation(self, dispatch_id, task_id, model='gpt-6-luna'):
        """Orca worker-show for a Codex Path B worker: Orca reports provider.model."""
        ref = self.claude_observation(dispatch_id, task_id, model=model)
        data = read_json(ref['path']); data['result']['projection']['provider']['id'] = 'codex'
        return self.save(data)

    def codex_rollout(self, path, task_id, dispatch_id, models=('gpt-6-luna',), cwd=None, timestamp='2026-10-05T05:01:00.000Z', after=()):
        """Codex rollout JSONL: each turn writes turn_context (model, cwd) just before its user message; the
        first turn delivers the Orca preamble, later turns are follow-ups of the same Dispatch."""
        preamble = ('You are working inside Orca, a multi-agent IDE. You are a dispatched worker.\n'
                    'Your task ID is: ' + task_id + '\n  orca orchestration send --from ' + self.CLAUDE_HANDLE +
                    ' --type worker_done --task-id ' + task_id + ' --dispatch-id ' + dispatch_id + ' --outcome succeeded\n')
        cwd = cwd or str(self.git.root)
        def message(role, text):
            kind = 'output_text' if role == 'assistant' else 'input_text'
            return dict(timestamp=timestamp, type='response_item', payload=dict(type='message', role=role, content=[dict(type=kind, text=text)]))
        rows = [dict(timestamp=timestamp, type='session_meta', payload=dict(id='fixture-codex-session', cwd=cwd, source='cli')),
                message('user', '# AGENTS.md instructions for the fixture')]
        for i, model in enumerate(models):
            rows.append(dict(timestamp=timestamp, type='turn_context', payload=dict(turn_id='fixture-turn-' + str(i), cwd=cwd, model=model)))
            rows += [message('user', preamble if i == 0 else 'continue'), message('assistant', 'ok')]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(''.join(json.dumps(r) + '\n' for r in rows + list(after)), encoding='utf-8')
        return Path(path)

    def fleet(self, workers=(), **paging):
        result = dict(scope=dict(source='all'), workers=list(workers), page=dict(total=len(workers), hasMore=False, nextCursor=None))
        result['page'].update(paging)
        return [dict(self.save(dict(id='fixture-fleet-' + uuid.uuid4().hex, ok=True, result=result)), cursor=None)]

    def report_input(self, role='implementer', family='OpenAI', token=None, artifact=None, coverage=None, findings=None, round=1, extra='', assignment=None,
                     synthesis='docs/reviews/fixture-F1.md'):
        # artifact=False: no artifact (a first plan writer that produced no plan).
        artifact = self.snapshot_ref() if artifact is None else artifact
        obj = read_json(artifact['path']) if artifact and artifact['kind'] != 'plan' else {}
        aid = obj.get('package_id', obj.get('snapshot_id', artifact['sha256'])) if artifact else None
        sid = obj.get('snapshot_after', obj).get('snapshot_id')
        a = dict(assignment) if assignment else self.assignment(role, family, round)
        a.update(artifact_id=aid, snapshot_id=sid)
        self.state['active'] = a
        b = dict(schema_version=1, **{k: a[k] for k in ('run_id','task_id','dispatch_id','role','phase','round','artifact_id','snapshot_id')})
        defaults = {'gate': 'GATE_OK', 'plan-reviewer': 'APPROVED', 'review-primary': 'REVIEW_OK',
                    'review-control': 'REVIEW_OK', 'review-final': 'REVIEW_OK'}
        token = token or defaults.get(role, 'DONE')
        lines = [token]
        if role == 'review-primary': lines += ['SPEC: ' + ('FAIL' if token == 'REVIEW_BLOCKING' else 'OK'), 'QUALITY: OK']
        if role == 'gate': lines += ['verify: fixture=PASS']
        if role == 'synthesizer': lines += [synthesis]
        lines += ['BINDING: ' + json.dumps(b)]
        if token == 'BLOCKED': lines += ['## Reason', 'fixture could not produce the artifact']
        if role == 'plan-reviewer': lines += ['## Simplicity', 'SIMPLICITY: OK']
        if role.startswith('review-') or role == 'plan-reviewer': lines += ['FINDINGS: ' + json.dumps(findings or [])]
        if coverage is not None: lines += ['COVERAGE: ' + json.dumps(coverage)]
        lines += [extra]
        report = self.save('\n'.join(lines) + '\n', '.md')
        observation = self.observation(a)
        failed = token == 'BLOCKED' or (role in ('plan-writer', 'plan-reviser', 'implementer', 'frontend-implementer', 'quickfix', 'synthesizer')
                                        and token in ('NEEDS_CONTEXT', 'NEEDS_AUTHORIZATION'))
        message = dict(id='fixture-message-' + str(self.serial), type='worker_done', run_id='fixture-run', from_handle='fixture-terminal',
            subject=token, payload=json.dumps(dict(taskId=a['task_id'], dispatchId=a['dispatch_id'], outcome='failed' if failed else 'succeeded',
                reportPath=report['path'], filesModified=['tracked.txt'])))
        data = dict(schema_version=1, action='accept-report', state=self.state, artifact=artifact, report=report,
                    observation=observation, event=self.save(dict(ok=True, result=dict(message=message))), message_id=message['id'])
        if not artifact: data.pop('artifact')
        return data

    def validate(self, data=None, action='resume', output=None, **fields):
        data = data or dict(schema_version=1, action=action, state=self.state, **fields)
        path = self.save(data)['path']
        args = ['validate', path] + ([str(output)] if output else [])
        rc, out, err = command(self.argv('protocol-state', *args), self.git.root)
        rows = out.splitlines()
        if len(rows) != 2: raise AssertionError((rc, out, err))
        result = json.loads(rows[1])
        if rc == 0: self.state = result['state']
        return rc, rows[0], result

    def validate_many(self, inputs, previous=False, outputs=None):
        """At most six CLI calls per 14s native host; keep the public CLI unchanged."""
        assert 1 <= len(inputs) <= 6
        outputs = outputs or [None] * len(inputs)
        assert len(outputs) == len(inputs)
        if not WINDOWS:
            results=[];last_state=None
            for data, output in zip(inputs, outputs):
                if previous and last_state is not None: data=dict(data, state=last_state)
                results.append(self.validate(data, output=output))
                if results[-1][0]==0: last_state=self.state
            return results
        jobs=[self.save(data)['path'] for data in inputs]
        bundle=self.save(dict(paths=jobs, previous=previous, outputs=[str(p) if p else None for p in outputs]))['path']
        script=self.workspace/'validate-batch.ps1'
        quote=lambda value: "'"+str(value).replace("'","''")+"'"
        script.write_text("$ErrorActionPreference='Stop'\n$jobs=Get-Content -Raw -LiteralPath "+quote(bundle)+" | ConvertFrom-Json\n"+
            "$lastState=$null;$i=0\nforeach ($path in $jobs.paths) {\n"+
            " if ($jobs.previous -and $null -ne $lastState) {\n"+
            "  $inputRecord=Get-Content -Raw -LiteralPath $path | ConvertFrom-Json\n"+
            "  $inputRecord.state=$lastState\n"+
            "  [IO.File]::WriteAllText($path,($inputRecord | ConvertTo-Json -Depth 100),(New-Object Text.UTF8Encoding($false)))\n }\n"+
            " $capture=New-Object IO.StringWriter;$original=[Console]::Out\n"+
            " $cliArgs=@('validate',$path);if ($jobs.outputs[$i]) { $cliArgs+=,$jobs.outputs[$i] };$i++\n"+
            " try { [Console]::SetOut($capture); & "+quote(ROOT/'bin/protocol-state.ps1')+" @cliArgs } finally { [Console]::SetOut($original) }\n"+
            " $lines=$capture.ToString().TrimEnd() -split '\\r?\\n'\n"+
            " $last=@{code=$LASTEXITCODE;token=$lines[0];result=($lines[1] | ConvertFrom-Json)}\n"+
            " if ($last.code -eq 0) { $lastState=$last.result.state }\n"+
            " [Console]::WriteLine(($last | ConvertTo-Json -Depth 100 -Compress))\n}\n",encoding='utf-8')
        rc,out,err=command([self.shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)],self.git.root)
        if rc or len(out.splitlines())!=len(inputs): raise AssertionError((rc,out,err))
        results=[]
        for line in out.splitlines():
            item=json.loads(line);results.append((item['code'],item['token'],item['result']))
            if item['code']==0: self.state=item['result']['state']
        return results

    def commit(self, artifact):
        obj=read_json(artifact['path']);base=obj.get('snapshot_after',obj)['manifest']['head']
        self.git.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=', 'commit', '-qm', 'protocol fixture')
        return dict(sha=self.git.git('rev-parse', 'HEAD').strip(), base=base, artifact=artifact)

    def package_ref(self, families=None, contracts=None, start_families=(), claims=None, unbound=False, base=None, head='WORKTREE', rows=None):
        """rows: explicit write rows [(family, files, createdAt)], several per family allowed; otherwise one row per family."""
        # C6 binds a package to the step base: the phase base, or plan_base in the final steps.
        base = base or (self.state['plan_base'] if self.state['step'] in ('final-review', 'delivery', 'completion') else self.state['base'])
        files = self.git.git('-c', 'core.quotePath=false', 'diff', '--name-only', base, *([] if head == 'WORKTREE' else [head])).splitlines()
        writes = []
        for family, names, created in rows or [(family, names, None) for family, names in (families or {'OpenAI': files}).items()]:
            a = self.assignment(family=family)
            receipt = (self.observation(a, model=None, start=self.start_receipt(a), created=created) if family in start_families
                       else self.observation(a, created=created))
            if 'start' in receipt: self.state['provenance'].append(receipt)
            if unbound:  # The receipt names the declared Task/Run but another Dispatch.
                raw = read_json(receipt['path']); raw['result']['dispatch']['id'] = 'another-dispatch'
                receipt = self.save(dict(raw, other_dispatch=a['dispatch_id']))
            writes.append(dict(family=(claims or {}).get(family, family), files=names, receipt_path=receipt['path'], receipt_sha256=receipt['sha256'],
                **{k: a[k] for k in ('run_id','task_id','dispatch_id')}))
        self.serial += 1
        path = self.workspace / ('package-' + str(self.serial) + '.diff')
        write_json(str(path) + '.provenance.json', dict(schema_version=1, writes=writes,
            contracts=contracts or [dict(id='C1', producer=['tracked.txt'], consumer=['plan.md'])], inputs=[]))
        result = command(self.argv('review-package', base, head, path), self.git.root)
        if result[0]: raise AssertionError(result)
        ref = self.reference(str(path) + '.manifest.json', kind='package')
        m = read_json(ref['path'])
        coverage = dict(files=[x['path'] for x in m['files']], parts=[x['path'] for x in m['parts']], contracts=m['coverage']['contracts'])
        return ref, coverage

    def gate_evidence(self):
        rc, result = self.verified_run(declaration=dict(hermetic=True))
        if rc: raise AssertionError(result)
        # The real runner captured this unchanged source; reuse that artifact in C6 tests.
        self.gate_snapshot = dict(self.save(result['evidence']['source_after']), kind='snapshot')
        return [self.reference(Path(result['run_dir']) / 'result.json')]

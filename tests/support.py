"""Bounded real-process fixtures; never run installers or alter user config."""
import base64
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
        self.state = dict(schema_version=1, mode='quickfix' if quickfix else 'plan',
            plan=None if quickfix else self.reference(self.plan), ledger=None, orca_run='fixture-run',
            plan_base=self.git.base, phase=None if quickfix else 'F1', base=self.git.base,
            step='quickfix' if quickfix else 'phase', worktree=str(self.git.root), worktree_id='fixture-worktree',
            workspace=str(self.workspace), active=None, rounds=dict(plan_review=0, fused_review=0, final_review=0, gate_fix=0),
            format_corrections={}, accepted=[], processed=dict(messages=[], deliveries=[]), open_ledger_ids=[],
            write_ownership=[], phase_commits=[], commit_barrier={}, final={}, provenance=[])

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

    def observation(self, assignment, status='completed', model=..., start=None):
        ref = self.save(dict(ok=True, result=dict(dispatch=dict(id=assignment['dispatch_id'], taskId=assignment['task_id'],
            runId=assignment['run_id'], status=status, assigneeHandle='fixture-terminal', retryOfDispatchId=None),
            projection=dict(provider=dict(id='fixture-cli', model=assignment['model'] if model is ... else model),
                workspace=dict(id='fixture-worktree'), evidence=dict(durable=True), liveness=dict(verdict='live')))))
        if start is not None: ref['start'] = start
        return ref

    def start_receipt(self, assignment):
        return self.save(dict(ok=True, result=dict(runId=assignment['run_id'], taskId=assignment['task_id'],
            dispatchId=assignment['dispatch_id'], launch=dict(effective=dict(model=assignment['model'])))))

    def fleet(self, workers=(), **paging):
        result = dict(scope=dict(source='all'), workers=list(workers), page=dict(total=len(workers), hasMore=False, nextCursor=None))
        result['page'].update(paging)
        return [dict(self.save(dict(id='fixture-fleet-' + uuid.uuid4().hex, ok=True, result=result)), cursor=None)]

    def report_input(self, role='implementer', family='OpenAI', token=None, artifact=None, coverage=None, findings=None, round=1, extra=''):
        artifact = artifact or self.snapshot_ref()
        obj = read_json(artifact['path']) if artifact['kind'] != 'plan' else {}
        aid = obj.get('package_id', obj.get('snapshot_id', artifact['sha256']))
        sid = obj.get('snapshot_after', obj).get('snapshot_id')
        a = self.assignment(role, family, round)
        a.update(artifact_id=aid, snapshot_id=sid)
        self.state['active'] = a
        b = dict(schema_version=1, **{k: a[k] for k in ('run_id','task_id','dispatch_id','role','phase','round','artifact_id','snapshot_id')})
        defaults = {'gate': 'GATE_OK', 'plan-reviewer': 'APPROVED', 'review-primary': 'REVIEW_OK',
                    'review-control': 'REVIEW_OK', 'review-final': 'REVIEW_OK'}
        token = token or defaults.get(role, 'DONE')
        lines = [token]
        if role == 'review-primary': lines += ['SPEC: ' + ('FAIL' if token == 'REVIEW_BLOCKING' else 'OK'), 'QUALITY: OK']
        if role == 'gate': lines += ['verify: fixture=PASS']
        lines += ['BINDING: ' + json.dumps(b)]
        if role == 'plan-reviewer': lines += ['## Simplicity', 'SIMPLICITY: OK']
        if role.startswith('review-') or role == 'plan-reviewer': lines += ['FINDINGS: ' + json.dumps(findings or [])]
        if coverage is not None: lines += ['COVERAGE: ' + json.dumps(coverage)]
        lines += [extra]
        report = self.save('\n'.join(lines) + '\n', '.md')
        observation = self.observation(a)
        message = dict(id='fixture-message-' + str(self.serial), type='worker_done', run_id='fixture-run', from_handle='fixture-terminal',
            subject=token, payload=json.dumps(dict(taskId=a['task_id'], dispatchId=a['dispatch_id'], outcome='succeeded',
                reportPath=report['path'], filesModified=['tracked.txt'])))
        return dict(schema_version=1, action='accept-report', state=self.state, artifact=artifact, report=report,
                    observation=observation, event=self.save(dict(ok=True, result=dict(message=message))), message_id=message['id'])

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

    def package_ref(self, families=None, contracts=None, start_families=()):
        files = self.git.git('diff', '--name-only', self.git.base).splitlines()
        writes = []
        for family, names in (families or {'OpenAI': files}).items():
            a = self.assignment(family=family)
            receipt = self.observation(a, model=None, start=self.start_receipt(a)) if family in start_families else self.observation(a)
            if 'start' in receipt: self.state['provenance'].append(receipt)
            writes.append(dict(family=family, files=names, receipt_path=receipt['path'], receipt_sha256=receipt['sha256'],
                **{k: a[k] for k in ('run_id','task_id','dispatch_id')}))
        self.serial += 1
        path = self.workspace / ('package-' + str(self.serial) + '.diff')
        write_json(str(path) + '.provenance.json', dict(schema_version=1, writes=writes,
            contracts=contracts or [dict(id='C1', producer=['tracked.txt'], consumer=['plan.md'])], inputs=[]))
        result = command(self.argv('review-package', self.git.base, 'WORKTREE', path), self.git.root)
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

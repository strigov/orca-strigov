"""C3 acceptance on actual short processes. Full contention lives only here."""
import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

from support import ROOT, WINDOWS, RunnerFixture, command, read_json, selected_shell, until, write_json


class FixtureCleanupTests(unittest.TestCase):
    def test_readonly_objects_and_foreign_links(self):
        with tempfile.TemporaryDirectory(prefix="runner-foreign-") as foreign, mock.patch.dict(os.environ):
            os.environ.pop("ORCA_TEST_ARTIFACTS",None)
            fixture=RunnerFixture(selected_shell()); closed=False
            target=Path(foreign); sentinel=target/"keep.txt"; sentinel.write_bytes(b"untouched")
            mode=sentinel.stat().st_mode; link=fixture.base/"foreign-link"
            try:
                objects=list((fixture.git.root/".git/objects").glob("[0-9a-f][0-9a-f]/*"))
                self.assertTrue(objects)
                if WINDOWS:
                    self.assertTrue(any(p.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY for p in objects))
                    import base64
                    script="New-Item -ItemType Junction -Path '"+str(link).replace("'","''")+"' -Target '"+str(target).replace("'","''")+"' | Out-Null"
                    result=command([fixture.shell,"-NoProfile","-NonInteractive","-EncodedCommand",
                                    base64.b64encode(script.encode("utf-16le")).decode()],fixture.base)
                    self.assertEqual(result[0],0,result)
                else:
                    link.symlink_to(target,target_is_directory=True)
                fixture.close(); closed=True
                self.assertFalse(fixture.base.exists())
                self.assertEqual(sentinel.read_bytes(),b"untouched")
                self.assertEqual(sentinel.stat().st_mode,mode)
                self.assertEqual(list(target.iterdir()),[sentinel])
                print("cleanup-proof: owned Git tree removed; foreign link target bytes/mode preserved")
            finally:
                if not closed: fixture.close()
            # Opt-in evidence retention still works; clear it to clean our fixture.
            os.environ["ORCA_TEST_ARTIFACTS"]=foreign
            retained=RunnerFixture(selected_shell())
            try:
                retained.close(); self.assertTrue(retained.base.exists())
            finally:
                os.environ.pop("ORCA_TEST_ARTIFACTS",None)
                retained.close()
            self.assertFalse(retained.base.exists())


class RunnerBehavior:
    @classmethod
    def setUpClass(cls):
        cls.fx = RunnerFixture(cls.shell)

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def status(self, s):
        return read_json(Path(s["run_dir"]) / "status.json")

    def test_success_failure_stdin_and_exact_command(self):
        code = "import sys,os;print('Привет \\\" $ & ' + os.getcwd());print(repr(sys.stdin.read()));sys.exit(7)"
        path, s = self.fx.spec(code)
        # A multiline shell command is preserved byte-for-byte in request.json.
        s["command"] = "\n" + s["command"] + "\n"
        write_json(path, s)
        rc, out, err = self.fx.start(path).finish()
        r = read_json(Path(s["run_dir"]) / "result.json")
        self.assertEqual(rc, 7, (out, err))
        self.assertEqual(r["exit_code"], 7)
        self.assertTrue(r["cleanup_verified"] and r["logs_complete"])
        self.assertEqual(read_json(Path(s["run_dir"]) / "request.json")["command"], s["command"])
        log = Path(r["stdout_log"]).read_text(encoding="utf-8")
        self.assertIn("Привет", log)
        self.assertIn(str(self.fx.git.root), log)
        self.assertIn("''", log)
        self.assertGreater(r["duration_seconds"], 0)
        self.assertIsNotNone(r["finished_at"])

    def test_streaming_both_large_logs(self):
        path, s = self.fx.spec("import os,time,threading;a=threading.Thread(target=lambda:os.write(1,b'A'*180000));b=threading.Thread(target=lambda:os.write(2,b'B'*180000));a.start();b.start();a.join();b.join();time.sleep(1);print('END')")
        p = self.fx.start(path)
        rd = Path(s["run_dir"])
        until(lambda: (rd / "stderr.log").stat().st_size >= 180000)
        self.assertIsNone(p.p.poll(), "logs must exist before runner exit")
        self.assertEqual((rd / "stdout.log").stat().st_size, 180000)
        self.assertEqual(p.finish()[0], 0)
        self.assertTrue((rd / "stdout.log").read_bytes().endswith(b"END\n") or (rd / "stdout.log").read_bytes().endswith(b"END\r\n"))
        # PS5.1 can prefix redirected native stderr with CLIXML. The full
        # payload must survive the actual child-shell stream without truncation.
        self.assertIn(b"B" * 180000, (rd / "stderr.log").read_bytes())

    def test_diagnostic_wait_does_not_kill_or_claim_progress(self):
        path, s = self.fx.spec("import time;print('liveness');time.sleep(2.5);print('done')", no_progress_seconds=0.4)
        p = self.fx.start(path)
        until(lambda: self.status(s)["state"] == "running")
        rc, out, err = self.fx.invoke("wait", s["run_dir"], "4")
        st = json.loads(out)
        self.assertEqual(st["diagnostic_events"], 1, (out, err))
        self.assertEqual(st["meaningful_progress"], "unknown")
        self.assertTrue(st["stalled"])
        self.assertIn(st["state"], ("running", "exited"))
        self.assertEqual(p.finish()[0], 0)
        self.assertTrue(read_json(Path(s["run_dir"]) / "result.json")["output_activity"])

    def test_explicit_progress_file(self):
        progress = self.fx.base / ("stage-" + str(time.time_ns()))
        code = "import pathlib,time;p=pathlib.Path(" + repr(str(progress)) + ");p.write_text('stage-1');time.sleep(.6);p.write_text('stage-2');time.sleep(.2)"
        rc, r, out, err = self.fx.run(code=code, progress_file=str(progress), no_progress_seconds=0.4)
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(r["meaningful_progress"], "stage-2")
        self.assertFalse(r["stalled"])

    def tree_spec(self, **kw):
        marker = self.fx.base / ("tree-" + str(time.time_ns()))
        # child and grandchild use the same payload, each self-bounded to 11s.
        leaf = "import os,time,pathlib,signal;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path(" + repr(str(marker)) + ").write_text(str(os.getpid()));time.sleep(11)"
        code = "import subprocess,sys,time,signal;signal.signal(signal.SIGTERM,signal.SIG_IGN);subprocess.Popen([sys.executable,'-c'," + repr(leaf) + "]);time.sleep(11)"
        path, s = self.fx.spec(code, **kw)
        return path, s, marker

    def assert_process_gone(self, pid):
        observation = None
        if WINDOWS:
            import ctypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.OpenProcess.restype = ctypes.c_void_p
            handle = k.OpenProcess(0x100000, False, pid)
            if handle:
                try:
                    k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                    self.assertEqual(k.WaitForSingleObject(handle, 1500), 0, "owned descendant remains alive")
                    observation = "signaled-process-handle"
                finally:
                    k.CloseHandle.argtypes = [ctypes.c_void_p]
                    k.CloseHandle(handle)
            else:
                self.assertEqual(ctypes.get_last_error(), 87, "an unreadable process is not proven exited")
                observation = "absent-process-error-87"
        else:
            stat = Path("/proc/%d/stat" % pid)
            until(lambda: not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z", 2)
            observation = "absent-or-exited-zombie"
        write_json(self.fx.base / ("cleanup-" + str(pid) + ".json"),
                   {"pid": pid, "observation": observation, "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})

    def test_deadline_cleans_descendants(self):
        path, s, marker = self.tree_spec(timeout_seconds=2.5)
        p = self.fx.start(path)
        pid = int(until(lambda: marker.read_text()))
        self.assertEqual(p.finish()[0], 124)
        r = read_json(Path(s["run_dir"]) / "result.json")
        self.assertEqual(r["reason"], "deadline")
        self.assertEqual(r["exit_code"], 124 if WINDOWS else -9)
        self.assertTrue(r["cleanup_verified"] and r["logs_complete"])
        self.assert_process_gone(pid)

    def test_owner_bound_cancel_cleans_descendants(self):
        path, s, marker = self.tree_spec()
        p = self.fx.start(path)
        pid = int(until(lambda: marker.read_text()))
        owner = self.fx.base / (s["run_id"] + "-owner.json")
        write_json(owner, dict(kind="local", id="wrong-owner"))
        self.assertNotEqual(self.fx.invoke("cancel", s["run_dir"], owner)[0], 0)
        self.assertIsNone(p.p.poll())
        write_json(owner, s["owner"])
        self.assertEqual(self.fx.invoke("cancel", s["run_dir"], owner)[0], 0)
        self.assertEqual(p.finish()[0], 124)
        r = read_json(Path(s["run_dir"]) / "result.json")
        self.assertEqual(r["reason"], "cancel")
        self.assertTrue(r["cleanup_verified"])
        self.assert_process_gone(pid)

    def test_duplicate_run_id_and_spec_binding(self):
        marker = self.fx.base / ("count-" + str(time.time_ns()))
        path, s = self.fx.spec("import pathlib,time;p=pathlib.Path(" + repr(str(marker)) + ");p.open('a').write('run\\n');time.sleep(1.3)")
        p = self.fx.start(path)
        until(lambda: marker.exists())
        rc, out, err = self.fx.invoke("run", path)
        self.assertIn(rc, (0, 125), (out, err))
        self.assertEqual(p.finish()[0], 0)
        self.assertEqual(self.fx.invoke("run", path)[0], 0)
        s["command"] = self.fx.python("print('different')"); write_json(path, s)
        self.assertEqual(self.fx.invoke("run", path)[0], 125)
        self.assertEqual(marker.read_text(), "run\n")

    def test_shared_resource_two_worktrees(self):
        key = "shared-" + str(time.time_ns())
        marker = self.fx.base / (key + "-started")
        a, sa = self.fx.spec("import pathlib,time;pathlib.Path(" + repr(str(marker)) + ").touch();time.sleep(2)", resource_key=key)
        pa = self.fx.start(a)
        until(lambda: marker.exists())
        b, sb = self.fx.spec(root=self.fx.git.other, resource_key=key)
        pb = self.fx.start(b)
        state = until(lambda: self.status(sb))
        self.assertEqual(state["state"], "waiting-resource")
        self.assertEqual(pa.finish()[0], 0)
        self.assertEqual(pb.finish()[0], 0)
        ra = read_json(Path(sa["run_dir"]) / "result.json")
        rb = read_json(Path(sb["run_dir"]) / "result.json")
        self.assertEqual(ra["resource_lock"], rb["resource_lock"])
        self.assertGreater(rb["duration_seconds"], 0.5)
        self.assertFalse(Path(ra["resource_lock"]).exists())
        self.assertTrue(ra["cleanup_verified"] and rb["cleanup_verified"])

    def test_unknown_owner_never_ages_out_and_wait_deadline(self):
        # Obtain the real resource path, then simulate a durable unprovable owner.
        key = "unknown-" + str(time.time_ns())
        _, r, _, _ = self.fx.run(resource_key=key)
        rd = Path(r["run_dir"])
        status = read_json(rd / "status.json")
        status.update(supervisor=None, tree=None, cleanup_verified=False, state="unknown", started_at="1900-01-01T00:00:00Z")
        write_json(rd / "status.json", status); (rd / "result.json").unlink()
        lock = Path(r["resource_lock"])
        write_json(lock, {k: r[k] for k in ("run_id", "run_dir", "owner")})
        try:
            rc, result, out, err = self.fx.run(root=self.fx.git.other, resource_key=key, timeout_seconds=0.5)
            self.assertEqual(rc, 124, (out, err))
            self.assertEqual(result["reason"], "deadline")
            self.assertIsNone(result["exit_code"])
            self.assertIsNone(result["tree"])
            self.assertTrue(lock.exists())
        finally:
            lock.unlink()

    def test_stale_owner_process_incarnation(self):
        key = "incarnation-" + str(time.time_ns())
        _, r, _, _ = self.fx.run(resource_key=key)
        rd = Path(r["run_dir"])
        # The same PID with another start identity is not the dead owner.
        r["supervisor"]["pid"] = os.getpid()
        r["supervisor"]["start"] = "different-incarnation"
        write_json(rd / "status.json", r)
        lock = Path(r["resource_lock"])
        write_json(lock, {k: r[k] for k in ("run_id", "run_dir", "owner")})
        try:
            rc, result, out, err = self.fx.run(root=self.fx.git.other, resource_key=key)
            self.assertEqual(rc, 0, (out, err))
            self.assertTrue(result["cleanup_verified"])
            self.assertFalse(lock.exists())
        finally:
            if lock.exists(): lock.unlink()

    def test_unrelated_run_is_not_serialized(self):
        path, s = self.fx.spec("import time;print('holding');time.sleep(3)", resource_key="independent-" + str(time.time_ns()))
        p = self.fx.start(path)
        until(lambda: self.status(s)["state"] == "running")
        rc, result, out, err = self.fx.run(root=self.fx.git.other)
        self.assertEqual(rc, 0, (out, err))
        self.assertIsNone(result["resource_lock"])
        self.assertIsNone(p.p.poll(), "an unrelated run must not wait for the held key")
        self.assertEqual(p.finish()[0], 0)

    def test_symlink_or_junction_artifact_rejected(self):
        target = self.fx.base / ("foreign-" + str(time.time_ns()))
        target.mkdir(); sentinel = target / "keep.txt"; sentinel.write_text("untouched")
        path, s = self.fx.spec()
        rd = Path(s["run_dir"]); rd.parent.mkdir(exist_ok=True)
        if WINDOWS:
            # Creating a directory junction requires no Developer Mode privilege.
            text = "New-Item -ItemType Junction -Path '" + str(rd).replace("'", "''") + "' -Target '" + str(target).replace("'", "''") + "' | Out-Null"
            import base64
            rc, out, err = command([self.shell, "-NoProfile", "-EncodedCommand", base64.b64encode(text.encode("utf-16le")).decode()], self.fx.git.root)
            self.assertEqual(rc, 0, (out, err))
        else:
            rd.symlink_to(target, target_is_directory=True)
        try:
            self.assertEqual(self.fx.invoke("run", path)[0], 125)
            self.assertEqual(sentinel.read_text(), "untouched")
            self.assertEqual(list(target.iterdir()), [sentinel])
        finally:
            if WINDOWS: os.rmdir(rd)
            else: rd.unlink()

    def test_owner_death_keeps_live_posix_group_locked(self):
        key = "death-" + str(time.time_ns())
        path, s, marker = self.tree_spec(resource_key=key)
        p = self.fx.start(path)
        pid = int(until(lambda: marker.read_text()))
        st = self.status(s)
        p.p.kill()  # kill only supervisor; OS tree contract must do the rest
        if WINDOWS:
            p.finish()
        else:
            # Keep the dead supervisor unreaped: zombie exit is known, while its
            # live process group must still prevent resource reclamation.
            until(lambda: Path("/proc/%d/stat" % p.p.pid).read_text().rsplit(")", 1)[1].split()[0] == "Z")
        rc, out, err = self.fx.invoke("wait", s["run_dir"], "0")
        self.assertEqual(json.loads(out)["state"], "unknown", (out, err))
        try:
            if WINDOWS:
                self.assert_process_gone(pid)
                rc, r, out, err = self.fx.run(root=self.fx.git.other, resource_key=key, timeout_seconds=3)
                self.assertEqual(rc, 0, (out, err))
            else:
                rc, r, out, err = self.fx.run(root=self.fx.git.other, resource_key=key, timeout_seconds=0.5)
                self.assertEqual(rc, 124, (out, err))
                self.assertIsNone(r["tree"])
                self.assertTrue(Path(st["resource_lock"]).exists())
                # Test fixture still owns this distinct process group and pins its
                # observed identity; cleanup the live orphan after asserting lock.
                os.killpg(st["tree"]["pgid"], signal.SIGKILL)
                self.assert_process_gone(pid)
                rc, r, out, err = self.fx.run(root=self.fx.git.other, resource_key=key, timeout_seconds=3)
                self.assertEqual(rc, 0, (out, err))
        finally:
            if not WINDOWS:
                try: os.killpg(st["tree"]["pgid"], signal.SIGKILL)
                except ProcessLookupError: pass
                p.finish()

    def test_gate_integration_verdicts_and_logs(self):
        root = self.fx.git.root
        plan = root / "gate-plan.md"
        success = "[Console]::WriteLine('PASS')" if WINDOWS else "printf 'PASS\\n'"
        failure = ("[Console]::WriteLine('tail-marker'); if ([IO.File]::Exists('new-source.txt')) { exit 7 }; exit 0" if WINDOWS
                   else "printf 'tail-marker\\n'; if [ -f new-source.txt ]; then exit 7; fi; exit 0")
        (root / "new-source.txt").write_text("changed")
        plan.write_text("---\nverify:\n- |\n    " + success + "\n- |\n    " + failure + "\n---\n", encoding="utf-8")
        # Three sequential checks share one aggregate parent watchdog; individual
        # short checks retain the <=15s bound (coordinator's Phase3 clarification).
        rc, out, err = command(self.fx.argv("verify-gate", plan, self.fx.git.base, root), root, timeout=45)
        self.assertEqual(rc, 1, (out, err))
        self.assertEqual(out.splitlines()[:2], ["GATE_FAIL", "verify: 2 cmd(s) | passed: 1 | failed: 1 | inherited: 0 | judgment: 0"])
        self.assertIn("tail-marker", out)
        self.assertIn("BASE logs:", out)
        runs = list((root / ".superpowers" / "sdd" / "gate-plan" / "checks").glob("*/result.json"))
        self.assertEqual(len(runs), 3)
        results = [read_json(p) for p in runs]
        self.assertTrue(all(r["cleanup_verified"] and r["logs_complete"] for r in results))
        self.assertTrue(all(r["duration_seconds"] <= 15 for r in results))
        self.assertEqual(sum(r["cwd"] != str(root) for r in results), 1)
        self.assertTrue(all(Path(r["stdout_log"]).exists() for r in results))
        self.assertTrue(all(r["evidence"]["valid"] and not r["evidence"]["reusable"] for r in results))
        self.assertTrue(all((Path(r["run_dir"]) / "result.sha256").exists() for r in results))
        base_result = next(r for r in results if r["cwd"] != str(root))
        self.assertEqual(base_result["evidence"]["key"]["provenance"]["kind"], "BASE")
        self.assertEqual(base_result["evidence"]["key"]["provenance"]["base_sha"], self.fx.git.base)
        self.assertEqual(len(self.fx.git.git("worktree", "list", "--porcelain").split("worktree ")) - 1, 2)
        plan.write_text("---\nverify: []\n---\n", encoding="utf-8")
        rc, out, err = command(self.fx.argv("verify-gate", plan, self.fx.git.base, root), root)
        self.assertEqual(rc, 2, (out, err))
        self.assertEqual(out.splitlines()[0], "NO_COMMANDS")

    def test_powershell_error_or_shell_failure(self):
        bad = "Write-Error 'expected-powershell-error'" if WINDOWS else "exit 6"
        rc, r, out, err = self.fx.run(command=bad)
        self.assertEqual(rc, 1 if WINDOWS else 6, (out, err))
        self.assertEqual(r["state"], "exited")

    def test_gate_legacy_pass_inherited_and_missing_tool(self):
        root = self.fx.git.other
        plan = self.fx.git.workspaces[root] / "legacy-gate.md"
        clean = command(["git", "-C", str(root), "status", "--porcelain"], root)
        self.assertEqual(clean, (0, "", ""), clean)
        success = "[Console]::WriteLine('legacy pass')" if WINDOWS else "printf 'legacy pass\\n'"
        failure = "[Console]::WriteLine('legacy failure'); exit 3" if WINDOWS else "printf 'legacy failure\\n'; exit 3"
        plan.write_text("---\nverify:\n- |\n    " + success + "\n- |\n    " + failure + "\n---\n", encoding="utf-8")
        rc, out, err = command(self.fx.argv("verify-gate", plan, self.fx.git.base, root), root, timeout=45)
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(out.splitlines()[:2], ["GATE_OK", "verify: 2 cmd(s) | passed: 1 | failed: 0 | inherited: 1 | judgment: 0"])
        plan.write_text("---\nverify:\n- orca_test_missing_tool_529917\n---\n", encoding="utf-8")
        rc, out, err = command(self.fx.argv("verify-gate", plan, self.fx.git.base, root), root)
        self.assertEqual(rc, 4, (out, err))
        self.assertEqual(out.splitlines()[:2], ["NEEDS_JUDGMENT", "verify: 1 cmd(s) | passed: 0 | failed: 0 | inherited: 0 | judgment: 1"])

    def test_high_exit_status_is_not_wrapper_success(self):
        rc, r, out, err = self.fx.run(command="exit -1")
        self.assertEqual(rc, 4294967295 if WINDOWS else 255, (out, err))
        self.assertEqual(r["exit_code"], rc)
        self.assertEqual(r["state"], "exited")

    def test_gate_zero_pass_signatures_shared_dependencies_and_bad_base(self):
        root = self.fx.git.root
        plan = self.fx.git.workspaces[root] / "guards.md"
        good = "[Console]::WriteLine('pass')" if WINDOWS else "printf 'pass\\n'"
        bad = "[Console]::WriteLine('stable-failure'); exit 3" if WINDOWS else "printf 'stable-failure\\n'; exit 3"
        def gate(commands, base=None):
            plan.write_text("---\nverify:\n" + "".join("- |\n    " + c + "\n" for c in commands) + "---\n", encoding="utf-8")
            return command(self.fx.argv("verify-gate", plan, base or self.fx.git.base, root), root,
                           timeout=45 if len(commands) > 1 else 14)
        rc, out, err = gate([bad])
        self.assertEqual(rc, 4, (out, err)); self.assertIn("0 commands passed", out)
        (root / "source.py").write_text("source change")
        (root / "node_modules").mkdir()
        try:
            rc, out, err = gate([good, bad])
            self.assertEqual(rc, 4, (out, err)); self.assertIn("shared .venv/node_modules", out)
        finally:
            (root / "node_modules").rmdir()
            (root / "source.py").unlink()
        # Differing failure signatures cannot inherit even when no changed path is named.
        different = ("if ([Environment]::CurrentDirectory.EndsWith('repository with space')) { [Console]::WriteLine('head-error') } else { [Console]::WriteLine('base-error') }; exit 4" if WINDOWS
                     else "case \"$PWD\" in *'repository with space') printf 'head-error\\n';; *) printf 'base-error\\n';; esac; exit 4")
        rc, out, err = gate([good, different])
        self.assertEqual(rc, 4, (out, err)); self.assertIn("different failure", out)
        rc, out, err = gate([bad], "not-a-base")
        self.assertIn(rc, (1, 4), (out, err)); self.assertNotEqual(out.splitlines()[0], "GATE_OK")


if WINDOWS:
    selected = os.environ.get("ORCA_TEST_SHELL")
    # Keep each module inside its per-platform budget. PS7 is a separate required
    # invocation with process-only ORCA_TEST_SHELL, not a second implicit suite.
    shells = [selected or shutil.which("powershell.exe")]
else:
    shells = [shutil.which("bash")]
for index, shell in enumerate(shells):
    if not shell:
        raise RuntimeError("required test shell unavailable")
    globals()["TestRunner" + str(index)] = type("TestRunner" + str(index), (RunnerBehavior, unittest.TestCase), {"shell": shell})

if __name__ == "__main__":
    unittest.main()

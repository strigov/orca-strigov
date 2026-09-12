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

from support import ROOT, WINDOWS, Process, RunnerFixture, command, read_json, selected_shell, until, write_json


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

    def native_reader(self, path, share):
        """Pin one real Windows file incarnation until this binary reader closes."""
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint,
                                       ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        handle = kernel.CreateFileW(str(path), 0x80000000, share, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        try: fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
            raise
        return os.fdopen(fd, "rb")

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
        if WINDOWS:
            status_path = Path(s["run_dir"]) / "status.json"
            # Deny DELETE briefly, then leave a compatible reader open across
            # publication. A pending complete temp proves the owner has a write.
            with until(lambda: self.native_reader(status_path, 3)) as blocker:
                old_bytes = blocker.read()
                pending = until(lambda: next(status_path.parent.glob("status.json.*.tmp"), None))
                pending_value = until(lambda: read_json(pending))
                held_at = time.monotonic()
                until(lambda: time.monotonic() - held_at >= 0.08, timeout=0.2)
                self.assertEqual(read_json(status_path), json.loads(old_bytes))
                self.assertEqual(read_json(pending), pending_value)
                self.assertIsNone(p.p.poll(), "temporary contention must not stop the owner")
                reader = self.native_reader(status_path, 7)
                self.addCleanup(reader.close)
        args = ("wait", s["run_dir"], "4")
        before = self.status(s)
        rc, out, err = self.fx.invoke(*args)
        facts = dict(argv=self.fx.argv("run-check", *args), exit_code=rc,
                     stdout=out, stderr=err, status_before=before)
        try: facts["status_after"] = self.status(s)
        except (OSError, ValueError) as error: facts["status_after"] = dict(unreadable=repr(error))
        # Keep the actual failed reply in the outer runner log before teardown.
        print("diagnostic-wait: " + json.dumps(facts, ensure_ascii=False), flush=True)
        owner_rc, owner_out, owner_err = p.finish()
        owner = dict(exit_code=owner_rc, stdout=owner_out, stderr=owner_err)
        print("diagnostic-wait-owner: " + json.dumps(owner, ensure_ascii=False), flush=True)
        try: st = json.loads(out)
        except ValueError: self.fail("invalid wait JSON: " + json.dumps(facts, ensure_ascii=False))
        self.assertIsInstance(st, dict, facts)
        self.assertEqual(st["diagnostic_events"], 1, facts)
        self.assertEqual(st["meaningful_progress"], "unknown", facts)
        self.assertTrue(st["stalled"], facts)
        self.assertIn(st["state"], ("running", "exited"), facts)
        self.assertEqual(rc, 0 if st["state"] == "exited" else 125, facts)
        self.assertEqual(owner_rc, 0, owner)
        result = read_json(Path(s["run_dir"]) / "result.json")
        self.assertTrue(result["output_activity"])
        self.assertTrue(result["cleanup_verified"] and result["logs_complete"], result)
        if WINDOWS:
            self.assertFalse(pending.exists(), "successful publication consumes its temp")
            self.assertEqual(reader.read(), old_bytes, "the existing handle retains the complete old record")
            with self.native_reader(status_path, 7) as current:
                new_bytes = current.read()
            self.assertNotEqual(new_bytes, old_bytes)
            self.assertEqual(json.loads(new_bytes), result)
            reader.close()
            print("atomic-writer: temporary contention cleared; old handle kept complete JSON; new handle saw final JSON", flush=True)
            # Keep the DELETE-access window of atomic replacement open without
            # deleting anything. ReadAllText's default sharing fails here.
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint,
                                           ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
            kernel.CreateFileW.restype = ctypes.c_void_p
            handle = kernel.CreateFileW(str(Path(s["run_dir"]) / "result.json"), 0x10000, 7, None, 3, 0, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value, ctypes.get_last_error())
            try:
                self.assertEqual(read_json(Path(s["run_dir"]) / "result.json"), result)
                args = ("wait", s["run_dir"], "0")
                rc, out, err = self.fx.invoke(*args)
                facts = dict(argv=self.fx.argv("run-check", *args), exit_code=rc, stdout=out, stderr=err)
                print("diagnostic-wait-delete-sharing: " + json.dumps(facts), flush=True)
                self.assertEqual(rc, 0, facts)
                final = json.loads(out)
                self.assertEqual(final["run_id"], result["run_id"])
                self.assertEqual(final["state"], "exited")
                self.assertTrue(final["cleanup_verified"] and final["logs_complete"])
            finally:
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                self.assertTrue(kernel.CloseHandle(handle))
            # Release actual read contention only after the CLI reports its
            # first failed open. No guessed sleep tied to shell startup speed.
            result_path = Path(s["run_dir"]) / "result.json"
            args = ("-Verbose", "wait", s["run_dir"], "4")
            prefix = []
            with self.native_reader(result_path, 0):
                waiter = Process(self.fx.argv("run-check", *args), self.fx.git.root)
                self.fx.processes.append(waiter)  # includes the normal 14s parent watchdog
                while True:
                    line = waiter.p.stdout.readline()
                    self.assertTrue(line, b"".join(prefix))
                    prefix.append(line)
                    if b"JSON open sharing retry (Win32 32)" in line:
                        break
            rc, out, err = waiter.finish()
            facts = dict(argv=self.fx.argv("run-check", *args), exit_code=rc,
                         stdout=b"".join(prefix).decode("utf-8-sig", "replace") + out, stderr=err)
            print("atomic-reader-temporary: " + json.dumps(facts), flush=True)
            self.assertEqual(rc, 0, facts)
            self.assertEqual(json.loads(out), result, facts)
            original_bytes = result_path.read_bytes()
            with self.native_reader(result_path, 0):
                # A read deadline shorter than the 250ms retry ceiling must
                # still return an error while this exclusive handle stays open.
                args = ("wait", s["run_dir"], "0.05")
                rc, out, err = self.fx.invoke(*args)
                facts = dict(argv=self.fx.argv("run-check", *args), exit_code=rc, stdout=out, stderr=err)
                print("atomic-reader-permanent: " + json.dumps(facts), flush=True)
                self.assertEqual(rc, 125, facts)
                self.assertEqual(out, "", facts)
                self.assertTrue(err, facts)
            self.assertEqual(result_path.read_bytes(), original_bytes)
            try:
                result_path.write_bytes(b'{"broken":')
                rc, out, err = self.fx.invoke("wait", s["run_dir"], "0")
                print("atomic-reader-parse: " + json.dumps(dict(exit_code=rc, stdout=out, stderr=err)), flush=True)
                self.assertEqual(rc, 125, (out, err))
                self.assertEqual(out, "")
                self.assertTrue(err)
                self.assertEqual(result_path.read_bytes(), b'{"broken":')
            finally:
                result_path.write_bytes(original_bytes)
            # An incompatible handle held until owner exit must remain a failure.
            path, blocked = self.fx.spec("import time;print('blocked');time.sleep(2.5)")
            owner = self.fx.start(path)
            until(lambda: self.status(blocked)["state"] == "running")
            rd = Path(blocked["run_dir"])
            with until(lambda: self.native_reader(rd / "status.json", 3)) as blocker:
                old_bytes = blocker.read()
                started = time.monotonic()
                rc, out, err = owner.finish()
                temps = {f.name: read_json(f) for f in rd.glob("status.json.*.tmp")}
                facts = dict(exit_code=rc, stdout=out, stderr=err, retained_temps=temps,
                             contention_seconds=time.monotonic() - started)
                print("atomic-writer-permanent: " + json.dumps(facts), flush=True)
                self.assertEqual(rc, 125, facts)
                self.assertIn("atomic replacement failed (Win32 32)", err, facts)
                self.assertEqual(read_json(rd / "status.json"), json.loads(old_bytes))
                self.assertFalse((rd / "result.json").exists())
                self.assertTrue(temps, facts)
                final = next(v for v in temps.values() if v["state"] == "interrupted")
                self.assertTrue(final["cleanup_verified"] and final["logs_complete"], final)
                self.assertLess(final["duration_seconds"], blocked["timeout_seconds"], final)
            rc, out, err = self.fx.invoke("wait", rd, "0")
            unknown = json.loads(out)
            self.assertEqual(rc, 125, (out, err))
            self.assertEqual(unknown["state"], "unknown")
            self.assertTrue(unknown["cleanup_verified"])
            self.assertFalse(unknown["logs_complete"])
            self.assert_process_gone(json.loads(old_bytes)["tree"]["leader"]["pid"])

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
        args = ("cancel", s["run_dir"], owner)
        rc, out, err = self.fx.invoke(*args)
        facts = dict(argv=self.fx.argv("run-check", *args), exit_code=rc, stdout=out, stderr=err)
        print("owner-bound-cancel: " + json.dumps(facts), flush=True)
        owner_rc, owner_out, owner_err = p.finish()
        owner_facts = dict(exit_code=owner_rc, stdout=owner_out, stderr=owner_err)
        print("owner-bound-cancel-owner: " + json.dumps(owner_facts), flush=True)
        self.assertEqual(rc, 0, facts)
        self.assertEqual(owner_rc, 124, owner_facts)
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

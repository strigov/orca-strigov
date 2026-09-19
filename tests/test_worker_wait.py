"""Shared POSIX/native Windows waiter fixtures. Never contacts real Orca."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def envelope(result):
    return dict(id="synthetic-receipt", ok=True, result=result)


def check(messages=(), **fields):
    result = dict(runId="run-fixture", messages=list(messages), count=len(messages),
                  timedOut=not messages, cancelled=False, connectionLost=False)
    if messages:
        result["deliveryId"] = "delivery-fixture"
    result.update(fields)
    return dict(command="check", stdin_closed=True, response=envelope(result))


def worker(dispatch="dispatch-fixture", verdict="live", required=False, kind="none", **extra):
    return dict(dispatchId=dispatch, projection=dict(
        liveness=dict(verdict=verdict, **extra), attention=dict(requiresAction=required),
        nextAction=dict(kind=kind, argv=[])))


def fleet(workers=None, **paging):
    rows = [worker()] if workers is None else workers
    page = dict(total=len(rows), hasMore=False, nextCursor=None)
    page.update(paging)
    return dict(command="worker-list", stdin_closed=True, response=envelope(dict(
        scope=dict(source="flag", run="run-fixture"), workers=rows, page=page)))


MESSAGE = dict(id="message-fixture", type="worker_done", subject="DONE",
               payload=dict(outcome="succeeded", reportPath="Отчёт.md"))


class WorkerWaitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orca-wait-кириллица space-")
        self.root = Path(self.temp.name).resolve()
        self.request = self.root / "request.json"
        self.scenario = self.root / "scenario.json"
        self.journal = self.root / "calls.jsonl"
        self.output = self.root / "receipts"
        self.spec = dict(schema_version=1,
                         orca_argv=[sys.executable, str(ROOT / "tests/fixtures/orca_wait_cli.py"),
                                    str(self.scenario), str(self.journal)],
                         run_id="run-fixture", dispatch_ids=["dispatch-fixture"],
                         output_dir=str(self.output), terminal="terminal-fixture")
        if os.name == "nt":
            shell = os.environ.get("ORCA_TEST_SHELL", "powershell.exe")
            self.argv = [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                         str(ROOT / "bin/wait-worker-event.ps1"), str(self.request)]
        else:
            self.argv = [os.environ.get("ORCA_TEST_SHELL", "/bin/bash"),
                         str(ROOT / "bin/wait-worker-event"), str(self.request)]

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, steps):
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False), encoding="utf-8")
        self.scenario.write_text(json.dumps(steps, ensure_ascii=False), encoding="utf-8")

    def invoke(self, steps, code=0, event="delivery"):
        self.prepare(steps)
        result = subprocess.run(self.argv, cwd=self.root, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, code, (result.stdout, result.stderr))
        self.assertEqual(len(result.stdout.decode("utf-8-sig").splitlines()), 1, result.stdout)
        response = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(response["event"], event, response)
        return response, self.calls()

    def calls(self):
        return [json.loads(line) for line in self.journal.read_text(encoding="utf-8").splitlines()] if self.journal.exists() else []

    def test_whole_fifo_receipt_is_immutable_and_no_automatic_ack(self):
        messages = [dict(id="old", type="heartbeat"), dict(id="ask", type="question"),
                    dict(id="blocked", type="escalation"), MESSAGE]
        response, calls = self.invoke([check(messages)])
        raw = Path(response["receipt"]).read_bytes()
        self.assertEqual(raw, (self.root / "emitted-000001.bin").read_bytes())
        self.assertEqual(json.loads(raw)["result"]["messages"], messages)
        self.assertEqual((self.output / "request.json").read_bytes(), self.request.read_bytes())
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--ack", calls[0])
        self.assertIn("worker_done,escalation,question", calls[0])
        self.assertIn("540000", calls[0])
        self.assertIn("terminal-fixture", calls[0])

    def test_empty_stdin_and_caller_encoding_survive_success_and_cli_error(self):
        probe = self.root / "input-encoding.json"
        if os.name == "nt":
            self.argv = self.argv[:5] + [str(ROOT / "tests/fixtures/orca_helper_encoding.ps1"),
                                        self.argv[5], str(self.request), str(probe)]
        for code in (0, 7):
            with self.subTest(cli_exit=code):
                self.spec["output_dir"] = str(self.root / ("encoding-%s" % code))
                self.journal.write_text("", encoding="utf-8")
                step = dict(check([MESSAGE]), exit=code)
                response, calls = self.invoke([step], 1 if code else 0, "error" if code else "delivery")
                self.assertEqual(len(calls), 1)
                self.assertEqual((self.root / "stdin-000001.bin").read_bytes(), b"")
                self.assertEqual(Path(response["receipt"]).read_bytes(), (self.root / "emitted-000001.bin").read_bytes())
                if code:
                    self.assertIn("Orca CLI exit 7", response["reason"])
                if os.name == "nt":
                    self.assertEqual(json.loads(probe.read_bytes()), dict(code_page=65001, preamble="EF-BB-BF"))

    def test_each_actionable_message_wakes_without_fleet_poll(self):
        # Subcases use separate output dirs; one shared cross-platform CLI fixture.
        for index, message in enumerate([dict(type="question"), dict(type="escalation"),
                                        dict(type="worker_done", payload=dict(outcome="failed")),
                                        dict(type="heartbeat")]):
            with self.subTest(message=message):
                self.spec["output_dir"] = str(self.root / ("case-%s" % index))
                self.journal.write_text("", encoding="utf-8")
                _, calls = self.invoke([check([message])])
                self.assertEqual([call[1] for call in calls], ["check"])

    def test_empty_windows_and_stale_status_stay_inside_waiter(self):
        stale = worker(verdict="unverifiable", reason="stale_status")
        steps = [check(), check(), check(), fleet(), check(), check(), check(), fleet([stale]), check([MESSAGE])]
        _, calls = self.invoke(steps)
        self.assertEqual([c[1] for c in calls], [s["command"] for s in steps])
        for call in calls:
            self.assertEqual(call[call.index("--run") + 1], "run-fixture")
            self.assertNotIn("--ack", call)
            if call[1] == "worker-list":
                self.assertIn("--include-remote", call)

    def test_coordinator_ack_is_sent_once_then_removed(self):
        self.spec["ack_delivery_id"] = "previous-processed-delivery"
        _, calls = self.invoke([check(), check(), check([MESSAGE])])
        self.assertIn("previous-processed-delivery", calls[0])
        self.assertTrue(all("--ack" not in call for call in calls[1:]))

    def test_attention_never_executes_recovery_or_settles_a_task(self):
        cases = [worker(verdict="exited"), worker(required=True),
                 worker(verdict="unverifiable", required=True, reason="host_unavailable"),
                 worker(kind="recover")]
        for index, row in enumerate(cases):
            with self.subTest(row=row):
                self.spec["output_dir"] = str(self.root / ("case-%s" % index))
                self.journal.write_text("", encoding="utf-8")
                response, calls = self.invoke([check(), check(), check(), fleet([row])], 2, "attention")
                self.assertEqual(response["dispatch_ids"], ["dispatch-fixture"])
                self.assertEqual([call[1] for call in calls], ["check"] * 3 + ["worker-list"])

    def test_fleet_pages_and_unrelated_dispatch_do_not_cause_false_alarm(self):
        steps = [check(), check(), check(),
                 fleet([worker("old-dispatch", verdict="exited")], total=2, hasMore=True, nextCursor="opaque+/="),
                 fleet([worker()], total=2), check([MESSAGE])]
        _, calls = self.invoke(steps)
        self.assertEqual(calls[4][-2:], ["--cursor", "opaque+/="])

    def test_invalid_fleet_stops_with_evidence(self):
        wrong_scope = fleet(); wrong_scope["response"]["result"]["scope"]["run"] = "another-run"
        bad_cursor = fleet(hasMore=True, nextCursor=None, total=2)
        projection = fleet([dict(dispatchId="dispatch-fixture", projection={})])
        malformed = fleet(); malformed["response"]["result"]["scope"] = "invalid"
        cases = [[fleet([])], [wrong_scope], [bad_cursor], [projection], [fleet(total=2)],
                 [malformed],
                 [fleet(total=2, hasMore=True, nextCursor="same"), fleet(total=2)]]
        for index, pages in enumerate(cases):
            with self.subTest(pages=pages):
                self.spec["output_dir"] = str(self.root / ("case-%s" % index))
                self.journal.write_text("", encoding="utf-8")
                response, calls = self.invoke([check(), check(), check()] + pages, 1, "error")
                self.assertTrue(response["reason"])
                self.assertTrue(Path(response["receipt"]).exists())
                self.assertEqual(calls[-1][1], "worker-list")

    def test_errors_disconnects_and_malformed_receipts_do_not_retry(self):
        cases = [check(runId="wrong"), check(count=1), check(count=False), check(connectionLost=True),
                 check(cancelled=True), check(timedOut=False), check([MESSAGE], deliveryId=None),
                 check(timedOut="true"),
                 dict(check(), raw="not JSON"), dict(check(), exit=7)]
        negative = check(); negative["response"]["ok"] = False; cases.append(negative)
        wrong_type = check(); wrong_type["response"]["ok"] = "true"; cases.append(wrong_type)
        for index, step in enumerate(cases):
            with self.subTest(step=step):
                self.spec["output_dir"] = str(self.root / ("case-%s" % index))
                self.journal.write_text("", encoding="utf-8")
                response, calls = self.invoke([step], 1, "error")
                self.assertEqual(len(calls), 1)
                self.assertTrue(response["reason"])
                self.assertEqual(Path(response["receipt"]).read_bytes(), (self.root / "emitted-000001.bin").read_bytes())

    def test_prior_receipts_are_not_overwritten(self):
        response, _ = self.invoke([check([MESSAGE])])
        original = Path(response["receipt"]).read_bytes()
        self.invoke([check()], 1, "error")
        self.assertEqual(Path(response["receipt"]).read_bytes(), original)
        self.assertEqual(len(self.calls()), 1)

    def test_keepalive_is_logged_without_parent_stdout_or_stderr(self):
        self.prepare([dict(check([MESSAGE]), delay=0.6)])
        stdout, stderr = self.root / "parent.out", self.root / "parent.err"
        with stdout.open("wb") as out, stderr.open("wb") as err:
            process = subprocess.Popen(self.argv, cwd=self.root, stdout=out, stderr=err)
            try:
                deadline = time.monotonic() + 10
                while not self.journal.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(self.journal.exists())
                self.assertIsNone(process.poll())
                self.assertEqual(stdout.read_bytes(), b"")
                self.assertEqual(stderr.read_bytes(), b"")
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=5)
        response = json.loads(stdout.read_bytes())
        log = Path(response["receipt"]).with_suffix(".stderr.log")
        self.assertIn(b"_keepalive", log.read_bytes())

    def test_bad_requests_never_call_orca(self):
        original = copy.deepcopy(self.spec)
        for fields in [dict(dispatch_ids=[]), dict(dispatch_ids=["x", "x"]),
                       dict(orca_argv=[]), dict(output_dir="relative"), dict(run_id=""),
                       dict(output_dir=str(self.root / "missing-parent" / "leaf")),
                       dict(schema_version=True)]:
            with self.subTest(fields=fields):
                self.spec = dict(original, **fields)
                _, calls = self.invoke([], 1, "error")
                self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

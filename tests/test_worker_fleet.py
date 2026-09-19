"""Shared POSIX/native Windows collector fixtures; never connects to live Orca."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from support import ProtocolFixture

ROOT = Path(__file__).resolve().parents[1]


def page(ids=(), identity="page-1", **paging):
    meta = dict(limit=100, total=len(ids), hasMore=False, nextCursor=None)
    meta.update(paging)
    return dict(command="worker-list", stdin_closed=True, response=dict(
        id=identity, ok=True, _meta=dict(runtimeId="fixture-runtime"), result=dict(
            scope=dict(source="all"), page=meta,
            workers=[dict(dispatchId=i) for i in ids])))


class WorkerFleetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orca-fleet-кириллица space-")
        self.root = Path(self.temp.name).resolve()
        self.request = self.root / "request.json"
        self.scenario = self.root / "scenario.json"
        self.journal = self.root / "calls.jsonl"
        self.output = self.root / "receipts"
        self.spec = dict(schema_version=1, output_dir=str(self.output), orca_argv=[
            sys.executable, str(ROOT / "tests/fixtures/orca_wait_cli.py"),
            str(self.scenario), str(self.journal)])
        if os.name == "nt":
            self.argv = [os.environ.get("ORCA_TEST_SHELL", "powershell.exe"),
                         "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                         str(ROOT / "bin/collect-worker-fleet.ps1"), str(self.request)]
        else:
            self.argv = [os.environ.get("ORCA_TEST_SHELL", "/bin/bash"),
                         str(ROOT / "bin/collect-worker-fleet"), str(self.request)]

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, steps, code=0, env=None):
        self.request.write_text(json.dumps(self.spec, ensure_ascii=False), encoding="utf-8")
        self.scenario.write_text(json.dumps(steps, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(self.argv, cwd=self.root, capture_output=True, timeout=30, env=env)
        self.assertEqual(result.returncode, code, (result.stdout, result.stderr))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(len(result.stdout.decode("utf-8-sig").splitlines()), 1)
        response = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(response["event"], "error" if code else "collected", response)
        calls = [json.loads(line) for line in self.journal.read_text(encoding="utf-8").splitlines()] if self.journal.exists() else []
        return response, calls

    def test_headless_child_preserves_connection_context_and_raw_receipts(self):
        environment = dict(ORCA_TERMINAL_HANDLE="coordinator-fixture", ORCA_PANE_KEY="pane-fixture",
                           ORCA_STRUCTURED_SESSION="parent-marker", ORCA_ENVIRONMENT="target-fixture",
                           ORCA_PAIRING_CODE="synthetic-not-a-credential", ORCA_CLI_CWD="original-cwd",
                           ORCA_WORKSPACE_ID="workspace-fixture")
        expected = dict(environment, ORCA_TERMINAL_HANDLE=None, ORCA_PANE_KEY=None,
                        ORCA_STRUCTURED_SESSION="1")
        step = page(["one"])
        step["environment"] = expected
        step["raw"] = "\ufeff" + json.dumps(step["response"], ensure_ascii=False, indent=2) + "\r\n"
        response, calls = self.invoke([step], env=dict(os.environ, **environment))
        self.assertEqual(calls, [["orchestration", "worker-list", "--limit", "100", "--json"]])
        manifest = json.loads(Path(response["fleet_file"]).read_bytes())
        self.assertEqual(manifest["worker_count"], 1)
        self.assertEqual(manifest["page_count"], 1)
        ref = manifest["fleet"][0]
        raw = Path(ref["path"]).read_bytes()
        self.assertEqual(raw, (self.root / "emitted-000001.bin").read_bytes())
        self.assertEqual(ref["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIsNone(ref["cursor"])
        self.assertEqual((self.output / "request.json").read_bytes(), self.request.read_bytes())
        self.assertIn(b"_keepalive", Path(ref["path"]).with_suffix(".stderr.log").read_bytes())
        self.assertNotIn("workers", response)
        self.assertNotIn("fleet", response)

    def test_all_pages_use_100_and_exact_opaque_cursor_without_terminal_calls(self):
        cursor = 'opaque+/= "quoted" ' + chr(92)
        steps = [page(["dispatch-%s" % i for i in range(100)], total=101, hasMore=True, nextCursor=cursor),
                 page(["last"], identity="page-2", total=101)]
        response, calls = self.invoke(steps)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], calls[0] + ["--cursor", cursor])
        manifest = json.loads(Path(response["fleet_file"]).read_bytes())
        self.assertEqual([ref["cursor"] for ref in manifest["fleet"]], [None, cursor])
        for i, ref in enumerate(manifest["fleet"], 1):
            self.assertEqual(Path(ref["path"]).read_bytes(), (self.root / ("emitted-%06d.bin" % i)).read_bytes())
        self.assertEqual(response["worker_count"], 101)

    def test_empty_inventory_is_one_real_page(self):
        response, calls = self.invoke([page()])
        self.assertEqual(response["worker_count"], 0)
        self.assertEqual(response["page_count"], 1)
        self.assertEqual(len(calls), 1)

    def test_empty_stdin_and_caller_encoding_survive_success_and_cli_error(self):
        probe = self.root / "input-encoding.json"
        if os.name == "nt":
            self.argv = self.argv[:5] + [str(ROOT / "tests/fixtures/orca_helper_encoding.ps1"),
                                        self.argv[5], str(self.request), str(probe)]
        for code in (0, 7):
            with self.subTest(cli_exit=code):
                self.spec["output_dir"] = str(self.root / ("encoding-%s" % code))
                self.journal.write_text("", encoding="utf-8")
                response, calls = self.invoke([dict(page(), exit=code)], 1 if code else 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual((self.root / "stdin-000001.bin").read_bytes(), b"")
                if code:
                    self.assertIn("Orca CLI exit 7", response["reason"])
                    self.assertFalse((Path(self.spec["output_dir"]) / "fleet.json").exists())
                if os.name == "nt":
                    self.assertEqual(json.loads(probe.read_bytes()), dict(code_page=65001, preamble="EF-BB-BF"))

    def test_partial_wrong_scoped_or_corrupt_inventory_never_publishes_manifest(self):
        cases = []
        for scope in [dict(source="bound", run="run-fixture"), dict(source="flag", run="run-fixture"),
                      dict(source="all", run="unexpected"), None, "invalid"]:
            bad = page(); bad["response"]["result"]["scope"] = scope; cases.append([bad])
        for change in [dict(total=True), dict(total=-1), dict(total=2), dict(limit=10),
                       dict(hasMore="false"), dict(nextCursor="unexpected"),
                       dict(hasMore=True, total=2, nextCursor=None)]:
            cases.append([page(["first"], **change)])
        first = page(["first"], total=3, hasMore=True, nextCursor="next")
        cases += [[first, page(["second"], identity="p2", total=4)],
                  [first, page(["first", "last"], identity="p2", total=3)],
                  [first, page(["second"], identity="p2", total=3, hasMore=True, nextCursor="next")],
                  [first, page(["second", "last"], total=3)],
                  [page([], hasMore=True, total=1, nextCursor="next")]]
        bad = page(); bad["response"]["result"]["partialHostErrors"] = [dict(code="unavailable")]; cases.append([bad])
        for field, value in [("workers", {}), ("workers", [None]), ("workers", [{}]), ("page", None)]:
            bad = page(); bad["response"]["result"][field] = value; cases.append([bad])
        for field, value in [("ok", False), ("ok", "true"), ("id", None), ("_meta", None)]:
            bad = page(); bad["response"][field] = value; cases.append([bad])
        bad = page(["second", "last"], identity="p2", total=3)
        bad["response"]["_meta"]["runtimeId"] = "restarted"
        cases.append([first, bad])
        cases += [[dict(page(), raw="truncated JSON")], [dict(page(), exit=7)]]
        for index, steps in enumerate(cases):
            with self.subTest(index=index):
                self.output = self.root / ("case-%s" % index)
                self.spec["output_dir"] = str(self.output)
                self.journal.write_text("", encoding="utf-8")
                response, calls = self.invoke(steps, code=1)
                self.assertTrue(response["reason"])
                self.assertFalse((self.output / "fleet.json").exists())
                self.assertEqual(len(calls), len(steps))  # No retry or terminal fallback.
                self.assertTrue(Path(response["receipt"]).exists())

    def test_bad_requests_do_not_call_orca(self):
        original = copy.deepcopy(self.spec)
        for fields in [dict(schema_version=True), dict(orca_argv=[]), dict(orca_argv=[""]),
                       dict(output_dir="relative"), dict(output_dir=str(self.root / "missing" / "leaf"))]:
            with self.subTest(fields=fields):
                self.spec = dict(original, **fields)
                _, calls = self.invoke([], code=1)
                self.assertEqual(calls, [])

    def test_existing_receipts_are_not_overwritten(self):
        response, _ = self.invoke([page()])
        manifest = Path(response["fleet_file"]).read_bytes()
        _, calls = self.invoke([], code=1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(Path(response["fleet_file"]).read_bytes(), manifest)

    def test_manifest_feeds_c6_and_cross_run_ownership_still_blocks(self):
        fixture = ProtocolFixture()
        try:
            artifact = fixture.snapshot_ref()
            proposed = fixture.assignment(family="Anthropic")
            proposed["dispatch_id"] = None
            row = dict(dispatchId="other-run-dispatch", runId="other-run", dispatchStatus="running",
                       terminalState="retained", resource=dict(ownershipState="owned"),
                       projection=dict(workspace=dict(id="fixture-worktree"),
                                       evidence=dict(durable=True), liveness=dict(verdict="live")))
            cases = [(row, 2, "prior writer"),
                     (dict(row, dispatchStatus="completed", resource=dict(ownershipState="external")), 2, "external"),
                     (dict(row, dispatchStatus="completed"), 0, None)]
            for index, (worker, code, why) in enumerate(cases):
                with self.subTest(index=index):
                    self.spec["output_dir"] = str(fixture.workspace / ("collected-%s" % index))
                    self.journal.write_text("", encoding="utf-8")
                    step = page(["placeholder"], identity="page-%s" % index)
                    step["response"]["result"]["workers"] = [worker]
                    response, _ = self.invoke([step])
                    fleet = json.loads(Path(response["fleet_file"]).read_bytes())["fleet"]
                    result = fixture.validate(action="dispatch", artifact=artifact, proposed=proposed, fleet=fleet)
                    self.assertEqual(result[0], code, result)
                    if why:
                        self.assertIn(why, result[2]["reason"])
                    else:
                        self.assertIn(step["response"]["id"], result[2]["state"]["used_fleet_ids"])
        finally:
            fixture.close()

    def test_parent_identity_is_unchanged_when_helper_runs_in_same_shell(self):
        probe = self.root / "parent-environment.json"
        names = ["ORCA_TERMINAL_HANDLE", "ORCA_PANE_KEY", "ORCA_STRUCTURED_SESSION"]
        expected = dict(zip(names, ["parent-terminal", "parent-pane", "parent-marker"]))
        if os.name == "nt":
            quote = lambda p: "'" + str(p).replace("'", "''") + "'"
            script = self.root / "parent.ps1"
            script.write_text("& " + quote(ROOT / "bin/collect-worker-fleet.ps1") + " " + quote(self.request) + "\n"
                              "$code=$LASTEXITCODE\n"
                              "$record=@{ORCA_TERMINAL_HANDLE=$env:ORCA_TERMINAL_HANDLE;"
                              "ORCA_PANE_KEY=$env:ORCA_PANE_KEY;ORCA_STRUCTURED_SESSION=$env:ORCA_STRUCTURED_SESSION}\n"
                              "[IO.File]::WriteAllText(" + quote(probe) + ",($record | ConvertTo-Json),"
                              "(New-Object Text.UTF8Encoding($false)))\nexit $code\n", encoding="utf-8-sig")
            self.argv = self.argv[:5] + [str(script)]
        else:
            # Call main in the same Python process, then observe its environment.
            source = ("import json,os,sys; from pathlib import Path; "
                      "sys.path.insert(0,sys.argv.pop(1)); import collect_worker_fleet as c; "
                      "code=c.main(); Path(" + repr(str(probe)) + ").write_text(json.dumps({k:os.environ.get(k) "
                      "for k in " + repr(names) + "})); sys.exit(code)")
            self.argv = [sys.executable, "-B", "-c", source, str(ROOT / "bin/lib"), str(self.request)]
        self.invoke([page()], env=dict(os.environ, **expected))
        self.assertEqual(json.loads(probe.read_bytes()), expected)


if __name__ == "__main__":
    unittest.main()

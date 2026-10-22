"""orca-dev 2.1: unit tests for skills/orca-dev/scripts/{orca_dev,install}.py. No Orca, no network, no real home."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "orca-dev" / "scripts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


orca_dev = load("orca_dev", SCRIPTS / "orca_dev.py")


class FakeOrca:
    """Stands in for run_orca. `script` maps a command prefix (tuple) to a list of responses,
    consumed in order (the last one repeats). A response is (code, data) or (code, data, text)."""

    def __init__(self, script=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.calls = []

    def __call__(self, args, timeout):
        self.calls.append(list(args))
        for size in (3, 2):
            key = tuple(args[:size])
            if key in self.script:
                queue = self.script[key]
                response = queue.pop(0) if len(queue) > 1 else queue[0]
                code, data = response[0], response[1]
                text = response[2] if len(response) > 2 else json.dumps(data or {})
                return code, data, text
        if tuple(args[:2]) == ("terminal", "wait"):
            return 0, {"ok": True, "result": {"wait": {"satisfied": True}}}, ""
        if tuple(args[:2]) == ("terminal", "send"):
            return 0, {"ok": True, "result": {"send": {"accepted": True}}}, ""
        raise AssertionError("unexpected orca call: %r" % (args,))

    def called(self, *prefix):
        return [c for c in self.calls if tuple(c[:len(prefix)]) == prefix]


def screen(*lines, source="screen"):
    return (0, {"ok": True, "result": {"terminal": {"tail": list(lines), "source": source}}})


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def call(fn, argv, **kw):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(argv, **kw)
    return code, out.getvalue(), err.getvalue()


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def template(self, text, name="t.md"):
        path = self.tmp / name
        path.write_bytes(text.encode("utf-8"))
        return str(path)

    def test_lint_and_tokens(self):
        text = "Repo <REPO>, task <TASK>, again <REPO>; bad <absolute path> <slug> <путь> <>"
        self.assertEqual(orca_dev.template_tokens(text), ["REPO", "TASK"])
        self.assertEqual(orca_dev.lint_template(text), ["<>", "<absolute path>", "<slug>", "<путь>"])

    def test_dry_run_fills_literally(self):
        t = self.template("# Brief\nRepo: <REPO>\nTask: <TASK>\n")
        code, out, err = call(orca_dev.cmd_brief, [t, "REPO=/abs/repo", "TASK=<div>text</div> <REPORT>", "--title", "x", "--dry-run"])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "# Brief\nRepo: /abs/repo\nTask: <div>text</div> <REPORT>\n")

    def test_template_lint_exits_1_and_creates_no_task(self):
        for bad in ("<absolute path>", "<slug>", "<путь>"):
            with self.subTest(bad=bad):
                fake = FakeOrca()
                t = self.template("Repo <REPO> at %s\n" % bad)
                code, out, err = call(orca_dev.cmd_brief, [t, "REPO=/r", "--title", "x"], run=fake)
                self.assertEqual(code, 1)
                self.assertIn(bad, err)
                self.assertEqual(fake.calls, [])

    def test_unfilled_token_exits_1_and_lists_it(self):
        fake = FakeOrca()
        t = self.template("<REPO>\n<REPORT>\n")
        code, out, err = call(orca_dev.cmd_brief, [t, "REPO=/r", "--title", "x"], run=fake)
        self.assertEqual(code, 1)
        self.assertIn("<REPORT>", err)
        self.assertEqual(fake.calls, [])

    def test_unknown_or_malformed_key_exits_2(self):
        t = self.template("<REPO>\n")
        for pair in ("OTHER=1", "lower=1", "REPO", "REPO=1"):
            with self.subTest(pair=pair):
                fake = FakeOrca()
                argv = [t, "REPO=/r", pair, "--title", "x"] if pair == "REPO=1" else [t, pair, "--title", "x"]
                code, out, err = call(orca_dev.cmd_brief, argv, run=fake)
                self.assertEqual(code, 2, err)
                self.assertEqual(fake.calls, [])

    def test_missing_template_and_missing_title_exit_2(self):
        self.assertEqual(call(orca_dev.cmd_brief, [str(self.tmp / "nope.md"), "--title", "x"])[0], 2)
        self.assertEqual(call(orca_dev.cmd_brief, ["no-such-brief", "--title", "x"])[0], 2)
        self.assertEqual(call(orca_dev.cmd_brief, [self.template("<REPO>\n"), "REPO=/r"])[0], 2)

    def test_set_file_multiline_utf8_reaches_task_create_unchanged(self):
        value = "Замечание 1: ок\r\n\r\n<b>строка</b> — «кавычки» $(rm) `x`\nконец"
        report = self.tmp / "report.txt"
        report.write_bytes(value.encode("utf-8"))
        t = self.template("Header\n<FINDINGS>\nFooter <REPO>\n")
        fake = FakeOrca({("orchestration", "task-create"): [(0, {"ok": True, "result": {"task": {"id": "task_abc"}}})]})
        code, out, err = call(orca_dev.cmd_brief, [t, "REPO=/r", "--set-file", "FINDINGS=" + str(report),
                                                   "--title", "slug/fix-F1", "--run", "run_1"], run=fake)
        self.assertEqual((code, out.strip(), err), (0, "task_abc", ""))
        [args] = fake.calls
        self.assertEqual(args[:2], ["orchestration", "task-create"])
        self.assertEqual(args[args.index("--spec") + 1], "Header\n" + value + "\nFooter /r\n")
        self.assertEqual(args[args.index("--task-title") + 1], "slug/fix-F1")
        self.assertEqual(args[args.index("--run") + 1], "run_1")
        self.assertEqual(args[-1], "--json")

    def test_set_file_drops_bom_and_rejects_unreadable(self):
        path = self.tmp / "bom.txt"
        path.write_bytes(b"\xef\xbb\xbfhello")
        t = self.template("<X>")
        self.assertEqual(call(orca_dev.cmd_brief, [t, "--set-file", "X=" + str(path), "--title", "x", "--dry-run"])[1], "hello")
        self.assertEqual(call(orca_dev.cmd_brief, [t, "--set-file", "X=" + str(self.tmp / "missing"), "--title", "x"])[0], 2)

    def test_task_create_failure_exits_3(self):
        t = self.template("<REPO>")
        fake = FakeOrca({("orchestration", "task-create"): [(1, {"ok": False, "error": {"message": "runtime down"}})]})
        code, out, err = call(orca_dev.cmd_brief, [t, "REPO=/r", "--title", "x"], run=fake)
        self.assertEqual(code, 3)
        self.assertIn("runtime down", err)

    def test_dry_run_cli_bytes_are_exact(self):
        value = "line1\r\nстрока2\n\n<i>3</i>"
        src = self.tmp / "v.txt"
        src.write_bytes(value.encode("utf-8"))
        t = self.template("A <V> B")
        p = subprocess.run([sys.executable, str(SCRIPTS / "orca_dev.py"), "brief", t, "--set-file", "V=" + str(src),
                            "--title", "x", "--dry-run"], capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout, ("A " + value + " B").encode("utf-8"))


class ClassifyTests(unittest.TestCase):
    def test_codex_busy_then_ready(self):
        self.assertEqual(orca_dev.classify("codex", ["Ask Codex to do anything", "Starting MCP servers (2/9)"], True, 5)["state"], "busy")
        self.assertEqual(orca_dev.classify("codex", ["Ask Codex to do anything"], True, 5)["state"], "ready")

    def test_agy_login_race_is_busy_then_login(self):
        lines = ["Antigravity CLI 1.2", "You are currently not signed in", "Select login method"]
        self.assertEqual(orca_dev.classify("agy", lines, True, 5)["state"], "busy")
        self.assertEqual(orca_dev.classify("agy", lines, True, 25)["state"], "needs_login")
        self.assertEqual(orca_dev.classify("agy", ["Antigravity CLI 1.2", "not signed in"], True, 25)["state"], "busy")
        self.assertEqual(orca_dev.classify("agy", ["Antigravity CLI 1.2", "> "], True, 25)["state"], "ready")

    def test_stream_scrollback_above_last_25_lines_does_not_count(self):
        lines = ["Claude Code v2"] + ["output"] * 30
        self.assertEqual(orca_dev.classify("claude", lines, False, 1)["state"], "waiting")
        self.assertEqual(orca_dev.classify("claude", lines, True, 1)["state"], "ready")

    def test_literal_marker(self):
        self.assertEqual(orca_dev.classify("READY>", ["x", "READY> "], True, 1)["state"], "ready")
        self.assertEqual(orca_dev.classify("READY>", ["ready> "], True, 1)["state"], "waiting")

    def test_known_modals_by_screen_and_by_reason(self):
        v = orca_dev.classify("codex", ["Update available! 0.162.1 -> 0.163.0", "Press enter to continue"], True, 1)
        self.assertEqual(v, {"state": "modal", "modal": "codex-update-prompt"})
        self.assertEqual(orca_dev.classify("codex", [""], True, 1, "agent-update-prompt")["modal"], "codex-update-prompt")
        self.assertEqual(orca_dev.classify("claude", ["Yes, I trust this folder"], True, 1)["modal"], "claude-trust-folder")
        self.assertEqual(orca_dev.classify("agy", ["Do you trust this folder?"], True, 1)["modal"], "agy-trust-folder")
        self.assertEqual(orca_dev.classify("codex", ["Folder access", "Trust this folder?", "› 1. Trust and continue", "  2. Quit"], True, 1)["modal"], "codex-trust-folder")
        self.assertEqual(orca_dev.classify("codex", [""], True, 1, "codex-trust-workspace")["modal"], "codex-trust-folder")
        self.assertEqual(orca_dev.classify("codex", ["Ask Codex to do anything"], True, 1, "agent-trust-workspace")["modal"],
                         "codex-trust-folder")

    def test_login_screens(self):
        self.assertEqual(orca_dev.classify("codex", ["Sign in with ChatGPT"], True, 1)["state"], "needs_login")
        self.assertEqual(orca_dev.classify("claude", ["Claude Code", "Please run /login"], True, 1)["state"], "needs_login")

    def test_unknown_blocked_reason(self):
        self.assertEqual(orca_dev.classify("codex", ["Allow command? y/n"], True, 1, "agent-interactive-prompt")["state"], "blocked")


class ReadyTests(unittest.TestCase):
    def test_windows_claude_trust_selects_yes_before_enter(self):
        clock = Clock()
        fake = FakeOrca({("terminal", "read"): [screen("❯ No, exit", "  Yes, I trust this folder"), screen("Claude Code")]})
        code, out, err = call(orca_dev.cmd_ready, ["term_1", "claude", "30"], run=fake, clock=clock, sleep=clock.sleep)
        self.assertEqual((code, json.loads(out)), (0, {"dismissed": ["claude-trust-folder"]}))
        self.assertEqual(fake.called("terminal", "send"), [
            ["terminal", "send", "--terminal", "term_1", "--text", "\x1b[B", "--json"],
            ["terminal", "send", "--terminal", "term_1", "--enter", "--json"],
        ])

    def test_ready_after_busy_with_final_idle_wait(self):
        clock = Clock()
        fake = FakeOrca({("terminal", "read"): [screen("Ask Codex", "Starting MCP servers (1/9)"), screen("Ask Codex")]})
        code, out, err = call(orca_dev.cmd_ready, ["term_1", "codex", "30"], run=fake, clock=clock, sleep=clock.sleep)
        self.assertEqual((code, json.loads(out)), (0, {"dismissed": []}))
        self.assertIn("60000", fake.called("terminal", "wait")[-1])

    def test_timeout_exit_1_prints_last_lines(self):
        clock = Clock()
        fake = FakeOrca({("terminal", "read"): [screen("$ codex", "loading")]})
        code, out, err = call(orca_dev.cmd_ready, ["term_1", "codex", "10"], run=fake, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 1)
        self.assertIn("loading", err)

    def test_screen_unavailable_falls_back_to_stream_read(self):
        clock = Clock()
        fake = FakeOrca({("terminal", "read"): [(1, {"ok": False, "error": {"message": "incompatible_runtime"}}),
                                                screen("Claude Code", source="stream")]})
        code, out, err = call(orca_dev.cmd_ready, ["term_1", "claude", "10"], run=fake, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 0, err)
        self.assertNotIn("--screen", fake.called("terminal", "read")[1])

    def test_five_failed_reads_exit_3(self):
        clock = Clock()
        fake = FakeOrca({("terminal", "read"): [(1, None, "no such terminal")]})
        code, out, err = call(orca_dev.cmd_ready, ["term_x", "claude", "100"], run=fake, clock=clock, sleep=clock.sleep)
        self.assertEqual(code, 3)
        self.assertEqual(len(fake.called("terminal", "read")), 10)

    def test_usage(self):
        self.assertEqual(call(orca_dev.cmd_ready, ["term_1"])[0], 2)
        self.assertEqual(call(orca_dev.cmd_ready, ["term_1", "codex", "-5"])[0], 2)


SPAWN = ["--agent", "codex", "--model", "gpt-6-astra", "--effort", "high", "--title", "demo/review-quality-F1", "--task", "task_1"]
CREATED = (0, {"ok": True, "result": {"terminal": {"handle": "term_9"}}})
DISPATCHED = (0, {"ok": True, "result": {"dispatch": {"id": "ctx_7", "task_id": "task_1"}}})
RID = "11111111-2222-3333-4444-555555555555"


def spawn(fake, argv=SPAWN, windows=False):
    clock = Clock()
    code, out, err = call(orca_dev.cmd_spawn, argv, run=fake, clock=clock, sleep=clock.sleep,
                          windows=windows, new_request_id=lambda: RID)
    return code, json.loads(out)


class SpawnTests(unittest.TestCase):
    def test_windows_codex_trust_continues_then_dispatches(self):
        fake = FakeOrca({("terminal", "create"): [CREATED],
                         ("terminal", "read"): [screen("Folder access", "Trust this folder?", "› 1. Trust and continue", "  2. Quit"), screen("Ask Codex")],
                         ("orchestration", "dispatch"): [DISPATCHED]})
        code, out = spawn(fake, windows=True)
        self.assertEqual((code, out["stage"], out["dismissed"]), (0, "done", ["codex-trust-folder"]))
        self.assertEqual(fake.called("terminal", "send"), [["terminal", "send", "--terminal", "term_9", "--enter", "--json"]])
        self.assertEqual(len(fake.called("orchestration", "dispatch")), 1)

    def test_argv_matches_launch_md(self):
        self.assertEqual(" ".join(orca_dev.build_argv("agy", "gemini-3.8-flash-high", None)),
                         "agy --model gemini-3.8-flash-high --dangerously-skip-permissions")
        self.assertEqual(" ".join(orca_dev.build_argv("codex", "<model>", "<lvl>")),
                         "codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust -m <model> "
                         "-c model_reasoning_effort=<lvl> -c features.multi_agent=false")
        self.assertEqual(" ".join(orca_dev.build_argv("claude", "<opus|sonnet>", "<lvl>")),
                         "claude --dangerously-skip-permissions --model <opus|sonnet> --effort <lvl>")

    def test_command_line_per_os(self):
        argv = orca_dev.build_argv("codex", "gpt-6-astra", "high")
        self.assertEqual(shlex.split(orca_dev.command_line(argv, windows=False)), argv)
        self.assertEqual(orca_dev.command_line(["a b", "c"], windows=True), '"a b" c')
        self.assertEqual(orca_dev.command_line(["a b", "c"], windows=False), "'a b' c")

    def test_happy_path_dismisses_update_modal(self):
        fake = FakeOrca({("terminal", "create"): [CREATED],
                         ("terminal", "read"): [screen("Update available! 0.162 -> 0.163", "Press enter to continue"), screen("Ask Codex")],
                         ("orchestration", "dispatch"): [DISPATCHED]})
        code, out = spawn(fake)
        self.assertEqual(code, 0)
        self.assertEqual(out, {"stage": "done", "handle": "term_9", "task_id": "task_1", "dispatch_id": "ctx_7",
                               "request_id": RID, "dismissed": ["codex-update-prompt"], "agent": "codex",
                               "screen": None, "error": None})
        create = fake.called("terminal", "create")[0]
        self.assertEqual(create[create.index("--title") + 1], "demo/review-quality-F1")
        self.assertEqual(create[create.index("--worktree") + 1], "active")
        self.assertEqual(shlex.split(create[create.index("--command") + 1]), orca_dev.build_argv("codex", "gpt-6-astra", "high"))
        self.assertEqual(fake.called("terminal", "send")[0][-3:], ["--text", "2", "--json"])
        dispatch = fake.called("orchestration", "dispatch")[0]
        self.assertEqual(dispatch, ["orchestration", "dispatch", "--task", "task_1", "--to", "term_9", "--inject",
                                    "--retry-request", RID, "--json"])

    def test_blocked_reason_from_first_wait_selects_modal(self):
        fake = FakeOrca({("terminal", "create"): [CREATED],
                         ("terminal", "wait"): [(1, {"ok": True, "result": {"wait": {"satisfied": False, "blockedReason": "agent-update-prompt"}}}),
                                                (0, {"ok": True, "result": {"wait": {"satisfied": True}}})],
                         ("terminal", "read"): [screen(""), screen("Ask Codex")],
                         ("orchestration", "dispatch"): [DISPATCHED]})
        code, out = spawn(fake)
        self.assertEqual((code, out["dismissed"]), (0, ["codex-update-prompt"]))

    def test_login_screen_exit_6(self):
        fake = FakeOrca({("terminal", "create"): [CREATED], ("terminal", "read"): [screen("Welcome to Codex", "Sign in with ChatGPT")]})
        code, out = spawn(fake)
        self.assertEqual(code, 6)
        self.assertEqual((out["stage"], out["handle"], out["agent"], out["dispatch_id"]), ("ready", "term_9", "codex", None))
        self.assertIn("Sign in with ChatGPT", out["screen"])
        self.assertEqual(fake.called("orchestration", "dispatch"), [])

    def test_unknown_modal_exit_5(self):
        fake = FakeOrca({("terminal", "create"): [CREATED],
                         ("terminal", "wait"): [(1, {"ok": True, "result": {"wait": {"satisfied": False, "blockedReason": "agent-interactive-prompt"}}})],
                         ("terminal", "read"): [screen("Allow network access? [y/n]")]})
        code, out = spawn(fake)
        self.assertEqual(code, 5)
        self.assertIn("Allow network access", out["screen"])
        self.assertEqual(out["handle"], "term_9")

    def test_unknown_blocked_reason_on_final_wait_exit_5_without_dispatch(self):
        fake = FakeOrca({("terminal", "create"): [CREATED],
                         ("terminal", "wait"): [(0, {"ok": True, "result": {"wait": {"satisfied": True}}}),
                                                (1, {"ok": True, "result": {"wait": {"satisfied": False, "blockedReason": "agent-interactive-prompt"}}})],
                         ("terminal", "read"): [screen("Ask Codex", "Allow command? y/n")],
                         ("orchestration", "dispatch"): [DISPATCHED]})
        code, out = spawn(fake)
        self.assertEqual((code, out["stage"], out["handle"]), (5, "ready", "term_9"))
        self.assertIn("60000", fake.called("terminal", "wait")[1])
        self.assertEqual(fake.called("orchestration", "dispatch"), [])

    def test_refused_send_exit_5(self):
        fake = FakeOrca({("terminal", "create"): [CREATED], ("terminal", "read"): [screen("Hooks need review")],
                         ("terminal", "send"): [(1, {"ok": False, "error": {"message": "agent_prompt_blocked"}})]})
        self.assertEqual(spawn(fake)[0], 5)

    def test_not_ready_exit_1(self):
        fake = FakeOrca({("terminal", "create"): [CREATED], ("terminal", "read"): [screen("$ ")]})
        code, out = spawn(fake)
        self.assertEqual((code, out["stage"], out["handle"]), (1, "ready", "term_9"))

    def test_dispatch_failure_exit_4_keeps_ids(self):
        fake = FakeOrca({("terminal", "create"): [CREATED], ("terminal", "read"): [screen("Ask Codex")],
                         ("orchestration", "dispatch"): [(1, {"ok": False, "error": {"message": "transport lost"}})]})
        code, out = spawn(fake)
        self.assertEqual(code, 4)
        self.assertEqual({k: out[k] for k in ("stage", "handle", "task_id", "request_id", "dispatch_id", "error")},
                         {"stage": "dispatch", "handle": "term_9", "task_id": "task_1", "request_id": RID,
                          "dispatch_id": None, "error": "transport lost"})

    def test_terminal_create_failure_exit_3(self):
        fake = FakeOrca({("terminal", "create"): [(1, {"ok": False, "error": {"message": "no worktree"}})]})
        code, out = spawn(fake)
        self.assertEqual((code, out["stage"], out["handle"], out["error"]), (3, "terminal_create", None, "no worktree"))

    def test_usage_exit_2_without_orca_calls(self):
        for argv in (SPAWN[:-2], ["--agent", "agy", "--model", "m", "--effort", "high", "--title", "t", "--task", "x"],
                     ["--agent", "codex", "--model", "m", "--title", "t", "--task", "x"],
                     ["--agent", "cursor", "--model", "m", "--title", "t", "--task", "x"]):
            with self.subTest(argv=argv):
                fake = FakeOrca()
                code, out = spawn(fake, argv)
                self.assertEqual(code, 2)
                self.assertEqual(fake.calls, [])

    def test_env_prefixes_agent_argv_on_posix(self):
        fake = FakeOrca({("terminal", "create"): [CREATED], ("terminal", "read"): [screen("Claude Code")],
                         ("orchestration", "dispatch"): [DISPATCHED]})
        argv = ["--agent", "claude", "--model", "opus", "--effort", "xhigh", "--title", "t", "--task", "task_1",
                "--env", "TMPDIR=/Volumes/build/tmp", "--env", "CARGO_HOME=/Volumes/build/cargo home"]
        code, out = spawn(fake, argv)
        self.assertEqual(code, 0)
        create = fake.called("terminal", "create")[0]
        self.assertEqual(shlex.split(create[create.index("--command") + 1]),
                         ["env", "TMPDIR=/Volumes/build/tmp", "CARGO_HOME=/Volumes/build/cargo home"]
                         + orca_dev.build_argv("claude", "opus", "xhigh"))

    def test_bad_env_or_env_on_windows_exit_2_without_orca_calls(self):
        for env, windows in (("1BAD=x", False), ("NOVALUE", False), ("=x", False), ("A-B=x", False), ("TMPDIR=x", True)):
            with self.subTest(env=env, windows=windows):
                fake = FakeOrca()
                code, out = spawn(fake, SPAWN + ["--env", env], windows=windows)
                self.assertEqual(code, 2)
                self.assertIn("POSIX" if windows else "--env KEY=VALUE", out["error"])
                self.assertEqual(fake.calls, [])

    def test_agy_uses_its_timeout_and_no_effort(self):
        fake = FakeOrca({("terminal", "create"): [CREATED], ("terminal", "read"): [screen("Antigravity CLI", "> ")],
                         ("orchestration", "dispatch"): [DISPATCHED]})
        code, out = spawn(fake, ["--agent", "agy", "--model", "gemini-3.8-flash-high", "--title", "t", "--task", "task_1"])
        self.assertEqual(code, 0)
        command = fake.called("terminal", "create")[0]
        self.assertNotIn("--effort", command[command.index("--command") + 1])
        self.assertEqual((orca_dev.AGENTS["agy"]["timeout"], orca_dev.AGENTS["codex"]["timeout"], orca_dev.AGENTS["claude"]["timeout"]), (180, 120, 90))


class CloseTests(unittest.TestCase):
    def test_pty_killed(self):
        fake = FakeOrca({("terminal", "close"): [(0, {"ok": True, "result": {"close": {"handle": "term_1", "ptyKilled": True}}})]})
        code, out, err = call(orca_dev.cmd_close, ["term_1"], run=fake)
        self.assertEqual((code, json.loads(out)["evidence"]), (0, "ptyKilled"))
        self.assertEqual(fake.called("terminal", "list"), [])

    def test_absent_from_list_confirms(self):
        fake = FakeOrca({("terminal", "close"): [(1, {"ok": False, "error": {"message": "terminal_stop_unverifiable"}})],
                         ("terminal", "list"): [(0, {"ok": True, "result": {"terminals": [{"handle": "term_2"}], "truncated": False}})]})
        code, out, err = call(orca_dev.cmd_close, ["term_1"], run=fake)
        self.assertEqual((code, json.loads(out)["evidence"]), (0, "absent"))
        self.assertEqual(fake.called("terminal", "list")[0], ["terminal", "list", "--worktree", "current", "--json"])

    def test_still_listed_or_truncated_is_not_confirmed(self):
        for listing in ({"terminals": [{"handle": "term_1"}], "truncated": False}, {"terminals": [], "truncated": True}):
            with self.subTest(listing=listing):
                fake = FakeOrca({("terminal", "close"): [(0, {"ok": True, "result": {"close": {"handle": "term_1", "ptyKilled": False}}})],
                                 ("terminal", "list"): [(0, {"ok": True, "result": listing})]})
                code, out, err = call(orca_dev.cmd_close, ["term_1"], run=fake)
                self.assertEqual((code, json.loads(out)["closed"]), (1, False))


class NoFilesTests(unittest.TestCase):
    def test_helper_creates_no_files_in_cwd(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(tmp)
        template = tmp / "t.md"
        template.write_text("<A>", encoding="utf-8")
        before = sorted(p.name for p in tmp.iterdir())
        fake = FakeOrca({("orchestration", "task-create"): [(0, {"ok": True, "result": {"task": {"id": "task_1"}}})],
                         ("terminal", "create"): [CREATED], ("terminal", "read"): [screen("Ask Codex")],
                         ("orchestration", "dispatch"): [DISPATCHED],
                         ("terminal", "close"): [(0, {"ok": True, "result": {"close": {"ptyKilled": True}}})]})
        self.assertEqual(call(orca_dev.cmd_brief, [str(template), "A=1", "--title", "x"], run=fake)[0], 0)
        self.assertEqual(spawn(fake)[0], 0)
        self.assertEqual(call(orca_dev.cmd_close, ["term_9"], run=fake)[0], 0)
        self.assertEqual(sorted(p.name for p in tmp.iterdir()), before)


install = load("install", SCRIPTS / "install.py")


class FakeRun:
    """Stands in for install.run_cmd: maps (basename, *args) prefixes to (code, stdout)."""

    def __init__(self, table=None):
        self.table = table or {}
        self.calls = []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        key = (os.path.basename(argv[0]),) + tuple(argv[1:])
        for size in range(len(key), 0, -1):
            if key[:size] in self.table:
                return self.table[key[:size]]
        return 127, ""


def which_all(name):
    return "/usr/bin/" + name


def which_none(name):
    return None


READY = json.dumps({"result": {"runtime": {"state": "ready"}}})


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.home, True)

    def skill(self, directory, name):
        path = self.home / directory / name
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("---\nname: %s\n---\n" % name, encoding="utf-8")

    def native(self):
        self.skill(".agents/skills", "orchestration")
        self.skill(".claude/skills", "orca-cli")

    def run_main(self, argv, run=None, which=which_none, windows=False, env=None, src=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = install.main(argv, home=self.home, run=run or FakeRun(), which=which, windows=windows, env=env or {},
                                src=src or SKILL_DIR)
        return code, out.getvalue(), err.getvalue()

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob("*") if p.is_file()}

    def assertUnchanged(self, before):
        after = self.snapshot()
        self.assertEqual(sorted(after), sorted(before))
        self.assertTrue(after == before, [k for k in after if after[k] != before[k]])

    def test_missing_native_skills_prints_install_command_and_exits_1(self):
        self.skill(".codex/skills", "orchestration")
        before = self.snapshot()
        code, out, err = self.run_main([])
        self.assertEqual(code, 1)
        self.assertIn("orca-cli", out)
        self.assertIn("\norca skills install --skill orchestration --skill orca-cli --agent codex,claude-code\n", out)
        self.assertUnchanged(before)

    @unittest.skipIf(os.name == "nt", "creating symlinks needs extra privileges on Windows")
    def test_vendored_strigov_copy_is_not_native(self):
        vendored = self.home / "src" / "orca-strigov" / "skills" / "orchestration"
        vendored.mkdir(parents=True)
        (vendored / "SKILL.md").write_text("x", encoding="utf-8")
        (self.home / ".codex/skills").mkdir(parents=True)
        os.symlink(str(vendored), str(self.home / ".codex/skills/orchestration"))
        self.skill(".agents/skills", "orca-cli")
        self.assertEqual(install.missing_native_skills(self.home), ["orchestration"])
        self.assertIn(self.home / ".codex/skills/orchestration", install.stale_copies(self.home, {}))

    def test_clean_environment_exits_0(self):
        self.native()
        run = FakeRun({("orca", "--version"): (0, "1.4.224\n"), ("orca", "status"): (0, READY),
                       ("codex", "--version"): (0, "codex-cli 0.162.1\n"), ("claude", "--version"): (0, "2.1.300\n"),
                       ("agy", "--version"): (0, "1.0\n"), ("npm", "outdated"): (0, "{}")})
        code, out, err = self.run_main([], run=run, which=which_all)
        self.assertEqual(code, 0, out)
        self.assertIn("orca runtime: ready", out)
        self.assertTrue(out.rstrip().endswith("done."))

    def test_update_notice_never_updates(self):
        self.native()
        run = FakeRun({("orca", "status"): (0, READY), ("npm", "outdated"): (0, json.dumps({"@openai/codex": {"current": "1", "latest": "2"}})),
                       ("brew", "list"): (0, ""), ("brew", "outdated"): (0, "codex\n")})
        code, out, err = self.run_main([], run=run, which=which_all)
        self.assertIn("npm i -g @openai/codex@latest", out)
        self.assertIn("brew upgrade --cask codex", out)
        self.assertFalse([c for c in run.calls if {"upgrade", "install", "i", "update"} & set(c[1:2])])

    def test_agy_missing_is_info_on_windows_only(self):
        self.assertIn(("INFO", "agy not on PATH (native Windows): the implementer starts on its Luna fallback"),
                      install.check_tools(FakeRun(), lambda n: None if n == "agy" else "/x/" + n, True))
        self.assertIn(("WARN", "agy not on PATH"), install.check_tools(FakeRun(), lambda n: None if n == "agy" else "/x/" + n, False))

    def test_repo_trust_for_repo_and_worktrees_preserves_other_keys_and_is_idempotent(self):
        self.native()
        repo = self.home / "work" / "repo"
        worktree = self.home / "work" / "repo-wt"
        repo.mkdir(parents=True)
        worktree.mkdir(parents=True)
        claude = self.home / ".claude.json"
        claude.write_text(json.dumps({"keep": 7, "projects": {"/other": {"keep": True}}}), encoding="utf-8")
        agy = self.home / ".gemini" / "antigravity-cli" / "settings.json"
        agy.parent.mkdir(parents=True)
        agy.write_text(json.dumps({"keep": [1, 2], "trustedWorkspaces": ["/other"]}), encoding="utf-8")
        codex = self.home / ".codex" / "config.toml"
        codex.parent.mkdir(parents=True)
        codex.write_text('model = "x"\n\n[projects."/other"]\ntrust_level = "trusted"\n', encoding="utf-8")
        porcelain = "worktree %s\nHEAD abc\n\nworktree %s\nHEAD def\n" % (repo, worktree)
        run = FakeRun({("git", "-C", str(repo), "worktree"): (0, porcelain)})
        code, out, err = self.run_main(["--repo", str(repo)], run=run, which=lambda n: "/usr/bin/git" if n == "git" else None)
        data = json.loads(claude.read_text(encoding="utf-8"))
        self.assertEqual((data["keep"], data["projects"]["/other"]), (7, {"keep": True}))
        for path in (repo, worktree):
            self.assertTrue(data["projects"][str(path)]["hasTrustDialogAccepted"])
        settings = json.loads(agy.read_text(encoding="utf-8"))
        self.assertEqual(settings["keep"], [1, 2])
        self.assertEqual(settings["trustedWorkspaces"], ["/other", str(repo), str(worktree)])
        self.assertEqual(install.codex_tables(codex.read_text(encoding="utf-8")),
                         {"/other": "trusted", str(repo): "trusted", str(worktree): "trusted"})
        self.assertTrue(codex.read_text(encoding="utf-8").startswith('model = "x"\n\n[projects."/other"]\n'))
        before = self.snapshot()
        self.run_main(["--repo", str(repo)], run=run, which=lambda n: "/usr/bin/git" if n == "git" else None)
        self.assertUnchanged(before)

    def test_check_mode_reports_and_writes_nothing(self):
        self.native()
        repo = self.home / "repo"
        repo.mkdir()
        (self.home / ".claude.json").write_text("{}", encoding="utf-8")
        before = self.snapshot()
        code, out, err = self.run_main(["--check", str(repo)])
        self.assertEqual(code, 1)
        self.assertIn("claude: %s not trusted" % repo, out)
        self.assertIn("agy: ", out)
        self.assertUnchanged(before)

    def test_missing_or_invalid_trust_files_are_warned_not_created(self):
        self.native()
        repo = self.home / "repo"
        repo.mkdir()
        (self.home / ".claude.json").write_text("[1]", encoding="utf-8")
        code, out, err = self.run_main(["--repo", str(repo)])
        self.assertIn("not valid JSON", out)
        self.assertIn("run agy once, then re-run", out)
        self.assertFalse((self.home / ".gemini").exists())
        self.assertEqual((self.home / ".claude.json").read_text(encoding="utf-8"), "[1]")

    def test_windows_keys(self):
        self.assertEqual(install.claude_keys("C:\\repo", True), ["C:/repo"])
        self.assertEqual(install.claude_keys("/x/repo", False), ["/x/repo"])
        data = {"projects": {"C:\\old": {"hasTrustDialogAccepted": True}}}
        changed, lines = install.trust_claude(data, ["C:\\old", "C:\\new"], True, True)
        self.assertTrue(changed)
        self.assertEqual(lines[0], ("OK", "claude: trust set for C:\\old"))
        self.assertEqual(data["projects"]["C:/old"], {"hasTrustDialogAccepted": True})
        self.assertEqual(data["projects"]["C:\\old"], {"hasTrustDialogAccepted": True})
        self.assertEqual(data["projects"]["C:/new"], {"hasTrustDialogAccepted": True})
        self.assertNotIn("C:\\new", data["projects"])
        unchanged, check_lines = install.trust_claude(
            {"projects": {"C:\\old": {"hasTrustDialogAccepted": True}}}, ["C:\\old"], True, False)
        self.assertFalse(unchanged)
        self.assertEqual(check_lines[0][0], "WARN")
        agy = {}
        install.trust_agy(agy, ["C:\\new"], True)
        self.assertEqual(agy["trustedWorkspaces"], ["C:\\new"])

    def test_codex_trust_appends_tables_and_never_edits_one(self):
        text = '[projects."/x/repo2"]\ntrust_level = "trusted"\n\n[projects.\'/x/lit\'] # c\ntrust_level = "trusted"\n'
        self.assertEqual(install.codex_tables(text), {"/x/repo2": "trusted", "/x/lit": "trusted"})
        new, lines = install.trust_codex(text, ["/x/repo2", "/x/lit", "/x/repo"], False, True)
        self.assertEqual(lines, [("OK", "codex: /x/repo2 trusted"), ("OK", "codex: /x/lit trusted"),
                                 ("OK", "codex: trust set for /x/repo")])
        self.assertEqual(new, text + '\n[projects."/x/repo"]\ntrust_level = "trusted"\n')
        self.assertEqual(install.trust_codex(new, ["/x/repo"], False, True), (None, [("OK", "codex: /x/repo trusted")]))
        self.assertEqual(install.trust_codex(new, ["/X/Repo"], False, False)[1][0][0], "WARN")
        other = '[projects."/x/repo"]\ntrust_level = "untrusted"\n[projects]\n"/x/inline" = { trust_level = "trusted" }\n'
        new, lines = install.trust_codex(other, ["/x/repo", "/x/inline"], False, True)
        self.assertIsNone(new)
        self.assertEqual([level for level, _ in lines], ["WARN", "WARN"])
        self.assertEqual(install.trust_codex("", ["/x/repo"], False, False)[0], None)

    def test_codex_trust_on_windows_matches_the_lowercased_key_codex_writes(self):
        live = "[projects.'c:\\users\\me\\appdata\\local\\temp\\orca-smoke']\ntrust_level = \"trusted\"\n"
        self.assertEqual(install.trust_codex(live, ["C:\\Users\\me\\AppData\\Local\\Temp\\orca-smoke"], True, True),
                         (None, [("OK", "codex: C:\\Users\\me\\AppData\\Local\\Temp\\orca-smoke trusted")]))
        mixed = '[projects."C:\\\\Repo"]\ntrust_level = "trusted"\n[projects.\'c:\\repo\']\ntrust_level = "untrusted"\n'
        self.assertEqual(install.trust_codex(mixed, ["C:\\Repo"], True, False)[1][0][0], "OK")
        self.assertEqual(install.trust_codex(live.replace('"trusted"', '"untrusted"'),
                                             ["C:\\Users\\me\\AppData\\Local\\Temp\\orca-smoke"], True, True)[1][0][0], "WARN")
        windows, _ = install.trust_codex("", ["C:\\Users\\me\\repo"], True, True)
        self.assertEqual(windows, "[projects.'c:\\users\\me\\repo']\ntrust_level = \"trusted\"\n")
        self.assertEqual(install.codex_tables(windows), {"c:\\users\\me\\repo": "trusted"})
        quoted, _ = install.trust_codex("", ["C:\\O'Brien"], True, True)
        self.assertEqual(install.codex_tables(quoted), {"c:\\o'brien": "trusted"})

    def test_stale_copies_listed_never_deleted(self):
        self.native()
        self.assertEqual(self.run_main(["--agent", "claude", "--agent", "codex"])[0], 0)
        self.skill(".agents/skills", "orca-dev")  # 1.x: no scripts/
        standalone_2_0 = self.home / "codex-home" / "skills" / "orca-dev"
        shutil.copytree(str(self.home / ".codex/skills/orca-dev"), str(standalone_2_0))
        shutil.rmtree(str(standalone_2_0 / "agents"))
        script = standalone_2_0 / "scripts" / "install.py"
        script.write_text(script.read_text(encoding="utf-8").replace('VERSION = "2.1.0"\n', ""), encoding="utf-8")
        cache = self.home / ".codex/plugins/cache/personal/orca-strigov"
        (cache / "2.0.0+codex.2" / ".codex-plugin").mkdir(parents=True)
        env = {"CODEX_HOME": str(self.home / "codex-home")}
        self.assertEqual(install.stale_copies(self.home, env), [standalone_2_0, self.home / ".agents/skills/orca-dev", cache])
        self.assertEqual(install.stale_copies(self.home, {}), [self.home / ".agents/skills/orca-dev", cache])
        before = self.snapshot()
        code, out, err = self.run_main([])
        self.assertEqual(code, 1)
        self.assertIn("удалить вручную или ответить `y` на вопрос координатора при первом запуске", out)
        self.assertUnchanged(before)

    def test_agent_installs_both_harnesses_without_probes(self):
        run = FakeRun()
        env = {"CODEX_HOME": str(self.home / "codex-home")}
        code, out, err = self.run_main(["--agent", "claude", "--agent", "codex", "--agent", "claude"], run=run, env=env)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(run.calls, [])
        claude, codex = self.home / ".claude/skills/orca-dev", self.home / "codex-home/skills/orca-dev"
        self.assertEqual(out.count("installed at"), 2)
        self.assertIn(str(codex), out)
        self.assertTrue((claude / "SKILL.md").read_text(encoding="utf-8").startswith(
            "---\nname: orca-dev\ndescription: Coordinate"))
        self.assertIn("disable-model-invocation: true\n", (claude / "SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse((claude / "agents").exists())
        self.assertIn("allow_implicit_invocation: false", (codex / "agents/openai.yaml").read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".agents").exists())
        self.assertEqual(install.stale_copies(self.home, env), [])
        before = self.snapshot()
        self.assertEqual(self.run_main(["--agent", "codex"], env=env)[0], 0)
        self.assertUnchanged(before)
        self.assertEqual(sorted(p.name for p in codex.parent.iterdir()), ["orca-dev"])

    def test_agent_from_an_installed_copy(self):
        self.assertEqual(self.run_main(["--agent", "claude"])[0], 0)
        claude = self.home / ".claude/skills/orca-dev"
        code, out, err = self.run_main(["--agent", "claude", "--agent", "codex"], src=claude)
        self.assertEqual(code, 0, out)
        self.assertIn("is this copy, nothing to do", out)
        out_dir = self.home / "bundle"
        install.bundle(SKILL_DIR, out_dir)
        codex = self.home / ".codex/skills/orca-dev"
        self.assertEqual(install.copy_files(codex), install.copy_files(out_dir / "codex/orca-dev"))
        for rel in install.copy_files(codex):
            self.assertEqual((codex / rel).read_bytes(), (out_dir / "codex/orca-dev" / rel).read_bytes(), rel)

    def test_agent_refuses_what_is_not_an_orca_dev_copy(self):
        self.skill(".claude/skills", "orca-dev")  # 1.x-like: no scripts/
        foreign = self.home / ".codex/skills/orca-dev"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("---\nname: something-else\n---\nname: orca-dev\n", encoding="utf-8")
        (foreign / "scripts").mkdir()
        (foreign / "scripts/orca_dev.py").write_text("", encoding="utf-8")
        (foreign / "scripts/install.py").write_text('VERSION = "2.1.0"\n', encoding="utf-8")
        before = self.snapshot()
        code, out, err = self.run_main(["--agent", "claude", "--agent", "codex"])
        self.assertEqual((code, out.count("is not an orca-dev copy")), (1, 2))
        self.assertUnchanged(before)
        shutil.rmtree(str(self.home / ".claude/skills/orca-dev"))
        self.assertEqual(self.run_main(["--agent", "claude"])[0], 0)
        installed = self.home / ".claude/skills/orca-dev"
        for extra in ("notes.txt", "prompts/my-local-task.md", "agents/extra.yaml", "drafts/a.md"):
            (installed / extra).parent.mkdir(exist_ok=True)
            (installed / extra).write_text("mine", encoding="utf-8")
            before = self.snapshot()
            code, out, err = self.run_main(["--agent", "claude"])
            self.assertEqual(code, 1, extra)
            self.assertIn("a reinstall would lose them: " + ("drafts/" if extra.startswith("drafts") else extra), out)
            self.assertUnchanged(before)
            shutil.rmtree(str(installed / "drafts"), True)
            if (installed / extra).exists():
                (installed / extra).unlink()
        (installed / "__pycache__").mkdir()
        (installed / "scripts/__pycache__").mkdir()
        (installed / "scripts/__pycache__/install.cpython-39.pyc").write_bytes(b"x")
        self.assertEqual(self.run_main(["--agent", "claude"])[0], 0)

    @unittest.skipIf(os.name == "nt", "creating symlinks needs extra privileges on Windows")
    def test_agent_refuses_a_copy_with_a_symlink_inside(self):
        self.assertEqual(self.run_main(["--agent", "codex"])[0], 0)
        personal = self.home / "personal"
        personal.mkdir()
        (personal / "keep.md").write_text("mine", encoding="utf-8")
        installed = self.home / ".codex/skills/orca-dev"
        os.symlink(str(personal), str(installed / "notes"))
        os.symlink(str(personal / "keep.md"), str(installed / "prompts" / "keep.md"))
        (installed / "roles.md").unlink()
        os.symlink(str(personal / "keep.md"), str(installed / "roles.md"))
        code, out, err = self.run_main(["--agent", "codex"])
        self.assertEqual(code, 1)
        self.assertIn("notes/", out)
        self.assertIn("prompts/keep.md", out)
        self.assertIn("roles.md", out)
        self.assertTrue(os.path.islink(installed / "notes"))
        self.assertTrue(os.path.islink(installed / "prompts" / "keep.md"))

    @unittest.skipIf(os.name == "nt", "creating symlinks needs extra privileges on Windows")
    def test_agent_refuses_a_symlink(self):
        self.assertEqual(self.run_main(["--agent", "claude"])[0], 0)
        target = self.home / ".claude/skills/orca-dev"
        link = self.home / ".codex/skills/orca-dev"
        link.parent.mkdir(parents=True)
        os.symlink(str(target), str(link))
        before = self.snapshot()
        code, out, err = self.run_main(["--agent", "codex"])
        self.assertEqual(code, 1)
        self.assertIn("is not an orca-dev copy (or is a symlink)", out)
        self.assertTrue(os.path.islink(link))
        self.assertUnchanged(before)

    def test_failed_render_keeps_the_old_copy(self):
        self.assertEqual(self.run_main(["--agent", "claude"])[0], 0)
        before = self.snapshot()
        real = install.render

        def broken(src, harness, dest):
            real(src, harness, dest)
            raise OSError("disk full")
        install.render = broken
        self.addCleanup(setattr, install, "render", real)
        code, out, err = self.run_main(["--agent", "claude"])
        self.assertEqual(code, 1)
        self.assertIn("disk full", out)
        self.assertUnchanged(before)
        self.assertEqual(sorted(p.name for p in (self.home / ".claude/skills").iterdir()), ["orca-dev"])

    def test_failed_swap_restores_the_old_copy(self):
        self.assertEqual(self.run_main(["--agent", "claude"])[0], 0)
        before = self.snapshot()
        real, calls = os.rename, []

        def rename(src, dst):
            calls.append(Path(src).name)
            if len(calls) == 2:
                raise OSError("busy")
            real(src, dst)
        with unittest.mock.patch.object(install.os, "rename", rename):
            code, out, err = self.run_main(["--agent", "claude"])
        self.assertEqual((code, calls[:2]), (1, ["orca-dev", calls[1]]))
        self.assertTrue(calls[1].startswith(".orca-dev.new-"))
        self.assertUnchanged(before)
        self.assertEqual(sorted(p.name for p in (self.home / ".claude/skills").iterdir()), ["orca-dev"])

    def test_mode_conflicts_exit_2_before_writes(self):
        repo = self.home / "repo"
        repo.mkdir()
        before = self.snapshot()
        for argv in (["--check", str(repo), "--agent", "claude"], ["--bundle", str(self.home / "b"), "--agent", "codex"],
                     ["--bundle", str(self.home / "b"), "--repo", str(repo)], ["--agent", "gemini"]):
            self.assertEqual(self.run_main(argv)[0], 2, argv)
        self.assertUnchanged(before)
        self.assertFalse((self.home / ".claude").exists())

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_main(["--repo", str(self.home / "missing")])[0], 2)
        self.assertEqual(self.run_main(["--bogus"])[0], 2)


SKILL_DIR = ROOT / "skills" / "orca-dev"
PROMPTS_DIR = SKILL_DIR / "prompts"
KIB = 1024
# Brief name -> sorted <UPPER_SNAKE> tokens (Contracts, "Brief tokens").
PROMPT_TOKENS = {
    "spec-writer": ["REPO", "SPEC", "TASK"],
    "spec-revise": ["FINDINGS", "SPEC"],
    "spec-review": ["PREVIOUS", "REPO", "SPEC", "TASK"],
    "plan-writer": ["PLAN", "REPO", "SPEC"],
    "plan-revise": ["FINDINGS", "PLAN"],
    "plan-review": ["PLAN", "PREVIOUS", "REPO", "SPEC"],
    "implementer": ["CONTEXT", "REPO", "TASK", "VERIFY"],
    "fix-round": ["FINDINGS", "VERIFY"],
    "review-spec": ["CRITERIA", "DIFF", "PREVIOUS", "REPO"],
    "review-quality": ["DIFF", "PREVIOUS", "REPO", "TASK"],
    "final-review": ["DIFF", "PLAN", "REPO", "SPEC"],
}
FORBIDDEN_WORDS = re.compile(r"\b(HOLD|UNVERIFIABLE)\b")


def brief_text(name):
    return (PROMPTS_DIR / (name + ".md")).read_bytes().decode("utf-8")


class BriefTemplateTests(unittest.TestCase):
    def test_every_brief_lints_fits_and_declares_its_tokens(self):
        for name, tokens in PROMPT_TOKENS.items():
            with self.subTest(brief=name):
                text = brief_text(name)
                self.assertLessEqual(len(text.encode("utf-8")), 2 * KIB)
                self.assertEqual(orca_dev.lint_template(text), [])
                self.assertEqual(orca_dev.template_tokens(text), tokens)
                self.assertNotIn("orchestration send", text)
                self.assertNotIn("orchestration ask", text)
                self.assertIsNone(FORBIDDEN_WORDS.search(text))

    def test_every_brief_fills_by_bare_name(self):
        for name, tokens in PROMPT_TOKENS.items():
            with self.subTest(brief=name):
                argv = [name] + ["%s=value-of-%s" % (t, t.lower()) for t in tokens] + ["--title", "demo/x", "--dry-run"]
                code, out, err = call(orca_dev.cmd_brief, argv)
                self.assertEqual((code, err), (0, ""))
                for t in tokens:
                    self.assertIn("value-of-%s" % t.lower(), out)
                self.assertEqual(orca_dev.template_tokens(out), [])

    def test_brief_rules(self):
        for name in ("implementer", "fix-round"):
            for word in ("DONE", "BLOCKED", "test", "Schedule"):
                self.assertIn(word, brief_text(name), (name, word))
        for name in ("spec-writer", "spec-revise", "plan-writer", "plan-revise"):
            self.assertIn("DONE", brief_text(name), name)
        for name in ("spec-review", "plan-review", "review-spec", "review-quality"):
            for word in ("PASS", "FINDINGS", "blocking", "minor"):
                self.assertIn(word, brief_text(name), (name, word))
        for word in ("PASS", "FINDINGS", "not closed"):
            self.assertIn(word, brief_text("final-review"), word)
        for word in ("## Цель", "## Вне скоупа", "## Критерии приёмки", "## Дизайн", "КОГДА", "ТОГДА", "AC1"):
            self.assertIn(word, brief_text("spec-writer"), word)
        for key in ("spec:", "orca_run:", "status: active", "risk:", "area:", "hard:", "covers:", "verify:",
                    "status: pending", "## F1:"):
            self.assertIn(key, brief_text("plan-writer"), key)
        for name in PROMPT_TOKENS:
            for phrase in ("`--outcome failed` only with a `BLOCKED` subject", "uses `--outcome succeeded`"):
                self.assertIn(phrase, brief_text(name), (name, phrase))
        for name in ("spec-review", "plan-review", "review-spec", "review-quality"):
            self.assertIn("not fixed: {reason}", brief_text(name), name)


class LaunchDocTests(unittest.TestCase):
    def setUp(self):
        self.text = (SKILL_DIR / "launch.md").read_bytes().decode("utf-8")

    def test_size_and_argv_lines_match_helper(self):
        self.assertLessEqual(len(self.text.encode("utf-8")), 8 * KIB)
        for argv in (orca_dev.build_argv("agy", "gemini-3.8-flash-high", None),
                     orca_dev.build_argv("codex", "<model>", "<lvl>"),
                     orca_dev.build_argv("claude", "<opus|sonnet>", "<lvl>")):
            self.assertIn(" ".join(argv), self.text)

    def test_agent_start_tables_match_helper(self):
        for agent, cfg in orca_dev.AGENTS.items():
            for key in ("marker", "busy", "login"):
                if cfg[key]:
                    self.assertIn(cfg[key], self.text, (agent, key))
            self.assertIn("%d s" % cfg["timeout"], self.text, agent)
        for row in orca_dev.MODALS:
            line = next((l for l in self.text.splitlines() if row["id"] in l), "")
            self.assertTrue(line, row["id"])
            for reason in row["reasons"]:
                self.assertIn(reason, line, (row["id"], reason))
            for key in row["keys"]:
                self.assertIn("Enter" if key.get("enter") else "`%s`" % key["text"].encode("unicode_escape").decode("ascii"), line, row["id"])
        self.assertIn("codex login", self.text)

    def test_recipes_present(self):
        for snippet in ("orca_dev.py spawn", "orca_dev.py ready", "orca_dev.py close", "worker-start", "--terminal",
                        "dispatch --task", "--inject", "--retry-request", "request-show", "dispatch-show",
                        "orca terminal show", "orphaned", "worker-release", "retained", "ptyKilled",
                        'check --wait --types "worker_done,escalation,question" --timeout-ms 900000',
                        "/effort high", "Path A", "Path B", "--env KEY=VALUE"):
            self.assertIn(snippet, self.text, snippet)
        for code in range(7):
            self.assertRegex(self.text, r"\|\s*`?%d`?\s*\|" % code)

    def test_windows_section_is_at_most_ten_lines(self):
        self.assertIn("\n## Windows", self.text)
        section = self.text.split("\n## Windows", 1)[1].split("\n## ", 1)[0]
        body = [l for l in section.splitlines()[1:] if l.strip()]
        self.assertLessEqual(len(body), 10)
        self.assertIn("py -3", section)
        self.assertIn("$LASTEXITCODE", section)


REMOVED = [
    "hooks", "bin/lib", "bin/claude-hook.cjs", "bin/wait-agent-ready", "bin/prompt-fill", "bin/protocol-state",
    "bin/coordinator-session", "bin/run-check", "bin/verify-gate", "bin/review-package", "bin/collect-worker-fleet",
    "bin/wait-worker-event", "bin/sdd-workspace", "bin/assemble-release.py", "bin/build-release.py",
    "install.sh", "install.ps1", ".github", "THIRD_PARTY_NOTICES.md", "spikes",
    "skills/orchestration", "skills/orca-cli", "skills/orca-dev/contracts", "skills/orca-dev/references",
    "skills/orca-dev/runtime-contracts.md", "skills/orca-dev/prompt-routing.md", "skills/orca-dev/orca-recipes.md",
    "skills/orca-dev/recipes-windows.md", "skills/orca-dev/coordinator-core.md", "skills/orca-dev/coordinator-start.md",
    "tests/support.py", "tests/fixtures", "tests/test_prompt_fill.py",
    "docs/architecture-runtime.md", "docs/audit-2026-09-02.md", "docs/controlled-pipeline-validation.md",
    "docs/fixture-import-rules.md", "docs/host-adapters.md", "docs/install-plugin.md", "docs/install-windows.md",
    "docs/phase2-smoke.md", "docs/plugin-validation.md", "docs/plugin-work-plan.md", "docs/runtime-platforms.md",
    "docs/smoke-runs.md", "docs/upstream-orca-claude-prompt-race.md", "docs/spikes", "docs/tasks",
    "docs/plans/2026-09-12-orca-dev-controlled-pipeline.md", "docs/plans/2026-09-28-path-b-consolidation.md",
    "docs/plans/2026-10-03-c6-transition-checker.md",
    "docs/plans/finished/2026-09-01-todo-cli-edit-csv-export.md",
    "docs/plans/finished/2026-09-01-todo-concurrency-csv-import.md",
    "docs/plans/finished/2026-09-01-todo-json-persistence.md",
    "docs/reviews/orca-dev-controlled-pipeline-phase-1.md", "docs/reviews/todo-cli-edit-csv-export-Ф2.md",
    "docs/reviews/todo-concurrency-csv-import-Ф2.md",
    "bin", "install.py", "plugin.json", ".codex-plugin", ".claude-plugin",
]


def names(directory):
    return sorted(p.name for p in directory.iterdir() if not p.name.startswith(".") and p.name != "__pycache__")


def read(rel):
    return (ROOT / rel).read_bytes().decode("utf-8")


class LayoutTests(unittest.TestCase):
    def test_v2_tree(self):
        self.assertEqual(names(ROOT), ["AGENTS.md", "LICENSE", "README.md", "README.ru.md", "assets", "docs", "skills", "tests"])
        self.assertEqual(names(ROOT / "skills"), ["orca-dev"])
        self.assertEqual(names(SKILL_DIR), ["LICENSE", "SKILL.md", "launch.md", "prompts", "roles.md", "scripts"])
        self.assertEqual(names(SCRIPTS), ["install.py", "orca_dev.py"])
        self.assertEqual(read("LICENSE"), read("skills/orca-dev/LICENSE"))
        self.assertEqual(names(PROMPTS_DIR), sorted(n + ".md" for n in PROMPT_TOKENS))
        self.assertEqual(names(ROOT / "tests"), ["test_orca_dev.py"])
        for rel in REMOVED:
            self.assertFalse(os.path.lexists(ROOT / rel), rel)
        self.assertTrue((ROOT / "docs/specs/2026-10-14-orca-dev-v2-design.md").is_file())
        shells = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                  if ".git" not in p.parts and p.suffix in (".sh", ".ps1")]
        self.assertEqual(shells, [])

    def test_size_limits(self):
        for rel, kib in (("skills/orca-dev/SKILL.md", 18), ("skills/orca-dev/roles.md", 5), ("skills/orca-dev/launch.md", 8)):
            self.assertLessEqual(len(read(rel).encode("utf-8")), kib * KIB, rel)
        for rel, limit in (("README.md", 200), ("README.ru.md", 200), ("AGENTS.md", 30)):
            self.assertLessEqual(len(read(rel).splitlines()), limit, rel)

    def test_no_hold_or_unverifiable_anywhere_in_the_skill(self):
        for path in SKILL_DIR.rglob("*.md"):
            self.assertIsNone(FORBIDDEN_WORDS.search(path.read_bytes().decode("utf-8")), path)

    def test_skill_md_anchors(self):
        text = read("skills/orca-dev/SKILL.md")
        self.assertTrue(text.startswith("---\nname: orca-dev\ndescription: "))
        self.assertIn("Invoking `$orca-dev` (Codex) or `/orca-dev` (Claude Code) is the user's explicit request", text)
        self.assertIn("Only on an explicit $orca-dev or /orca-dev;", text)
        for anchor in ("<skill>/scripts/orca_dev.py", "<skill>/scripts/install.py", "orca skills get orchestration", "orca status --json",
                       "run-create", "run-use", "python3", "py -3", "orca_dev.py brief", "orca_dev.py spawn",
                       "orca_dev.py close", "roles.md", "launch.md", "--set-file", "orca_run:", "implementer:",
                       "covers:", "verify:", "risk:", "hard:", "git rev-parse HEAD", "git merge --no-ff",
                       "git merge --abort", "git add -A", "git status --porcelain", "worker-list --run",
                       "worker-read --dispatch", "check --wait", "request-show",
                       "принять как есть / ещё раунд / стоп", "повторить позже / заменить на",
                       "закоммитить как есть / отложить", "ждать дальше / остановить и заменить / стоп",
                       "продолжить F", "терминал", "не закрылся", "the subject decides"):
            self.assertIn(anchor, text, anchor)
        for name in PROMPT_TOKENS:
            self.assertIn(name, text, name)
        for token in sorted({t for tokens in PROMPT_TOKENS.values() for t in tokens}):
            self.assertIn(token, text, token)

    def test_roles_md_anchors(self):
        text = read("skills/orca-dev/roles.md")
        for anchor in ("gpt-6-astra", "xhigh", "gemini-3.8-flash-high", "gpt-6-luna", "max", "gpt-6.1-sol", "opus",
                       "sonnet", "medium", "ultra", "--agent claude --model opus --effort xhigh",
                       "--agent codex --model gpt-6-astra --effort xhigh", "--agent agy --model gemini-3.8-flash-high",
                       "--agent codex --model gpt-6-luna --effort max", "--agent codex --model gpt-6.1-sol --effort high"):
            self.assertIn(anchor, text, anchor)

    def test_readmes_and_agents(self):
        for rel in ("README.md", "README.ru.md"):
            text = read(rel)
            for anchor in ("orca skills install --skill orchestration --skill orca-cli --agent codex,claude-code",
                           "skills/orca-dev/scripts/install.py --agent", "--repo", "$orca-dev", "/orca-dev",
                           "docs/specs/2026-10-14-orca-dev-v2-design.md", "gemini-3.8-flash-high", "gpt-6-astra",
                           "release"):
                self.assertIn(anchor, text, (rel, anchor))
            for gone in ("/orca-strigov:orca-dev", "plugin-creator", "marketplace"):
                self.assertNotIn(gone, text, (rel, gone))
        agents = read("AGENTS.md")
        for anchor in ("python3 -m unittest discover tests", "launch.md", "roles.md",
                       "skills/orca-dev/scripts/orca_dev.py", "scripts/install.py"):
            self.assertIn(anchor, agents, anchor)
        self.assertNotIn("bin/orca_dev.py", agents)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = self.tmp / "out"
        self.assertEqual([level for level, _ in install.bundle(SKILL_DIR, self.out)], ["OK", "OK"])

    def zip_name(self, harness):
        return self.out / ("orca-dev-%s-v%s.zip" % (harness, install.VERSION))

    def test_trees_and_zips_match_and_are_reproducible(self):
        again = self.tmp / "again"
        install.bundle(SKILL_DIR, again)
        prompts = sorted("prompts/" + n + ".md" for n in PROMPT_TOKENS)
        for harness, extra in (("claude", []), ("codex", ["agents/openai.yaml"])):
            tree = self.out / harness / "orca-dev"
            self.assertEqual(install.copy_files(tree), sorted(list(install.SHIP_FILES) + prompts + extra))
            with zipfile.ZipFile(str(self.zip_name(harness))) as z:
                self.assertEqual(z.namelist(), ["orca-dev/" + rel for rel in install.copy_files(tree)])
                for rel in install.copy_files(tree):
                    self.assertEqual(z.read("orca-dev/" + rel), (tree / rel).read_bytes(), rel)
            self.assertEqual(self.zip_name(harness).read_bytes(),
                             (again / self.zip_name(harness).name).read_bytes())
            with zipfile.ZipFile(str(self.zip_name(harness))) as z:
                self.assertEqual({i.date_time for i in z.infolist()}, {(1980, 1, 1, 0, 0, 0)})
        with self.assertRaises(OSError):
            install.render_skill_md("---\nname: orca-dev\n---\nno invocation line\n", "claude")

    def test_each_harness_copy_names_only_its_invocation(self):
        claude = (self.out / "claude/orca-dev/SKILL.md").read_text(encoding="utf-8")
        codex = (self.out / "codex/orca-dev/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Only on an explicit /orca-dev;", claude)
        self.assertIn("Invoking `/orca-dev` is the user's explicit request", claude)
        self.assertNotIn("$orca-dev", claude.split("\n## ", 1)[0])
        self.assertIn("Only on an explicit $orca-dev;", codex)
        self.assertIn("Invoking `$orca-dev` is the user's explicit request", codex)
        self.assertNotIn("disable-model-invocation", codex)
        self.assertNotIn("/orca-dev", codex.split("\n## ", 1)[0])
        for harness in install.HARNESSES:
            tree = self.out / harness / "orca-dev"
            for rel in install.copy_files(tree):
                text = (tree / rel).read_bytes().decode("utf-8")
                for gone in ("<plugin>", "bin/orca_dev", "/orca-strigov:orca-dev", "plugin.json"):
                    self.assertNotIn(gone, text, (harness, rel, gone))

    def test_render_is_the_same_from_any_copy(self):
        for first, second in (("claude", "codex"), ("codex", "claude")):
            dest = self.tmp / (first + "-to-" + second)
            install.render(self.out / first / "orca-dev", second, dest)
            ref = self.out / second / "orca-dev"
            self.assertEqual(install.copy_files(dest), install.copy_files(ref))
            for rel in install.copy_files(ref):
                self.assertEqual((dest / rel).read_bytes(), (ref / rel).read_bytes(), rel)

    def test_unpacked_zip_runs_from_a_foreign_cwd(self):
        for harness in install.HARNESSES:
            unpacked = self.tmp / ("unpacked-" + harness)
            with zipfile.ZipFile(str(self.zip_name(harness))) as z:
                z.extractall(str(unpacked))
            helper = unpacked / "orca-dev" / "scripts" / "orca_dev.py"
            p = subprocess.run([sys.executable, "-I", str(helper), "brief", "implementer", "REPO=/abs/repo", "TASK=t",
                                "VERIFY=v", "CONTEXT=c", "--title", "x", "--dry-run"],
                               capture_output=True, cwd=str(self.tmp))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn(b"/abs/repo", p.stdout)
            p = subprocess.run([sys.executable, "-I", str(unpacked / "orca-dev" / "scripts" / "install.py"), "--bundle",
                                str(self.tmp / ("rebundle-" + harness))], capture_output=True, cwd=str(self.tmp))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual((self.tmp / ("rebundle-" + harness) / self.zip_name("codex").name).read_bytes(),
                             self.zip_name("codex").read_bytes())

    def test_bundle_refuses_a_dirty_or_inner_output(self):
        self.assertEqual(install.bundle(SKILL_DIR, self.out)[0][0], "ERROR")
        self.assertEqual(install.bundle(SKILL_DIR, SKILL_DIR / "out")[0][0], "ERROR")
        self.assertFalse((SKILL_DIR / "out").exists())

#!/usr/bin/env python3
"""orca-strigov 2.0 helper: brief, spawn, ready, close.

Usage (macOS/Linux: python3, Windows: py -3):
  orca_dev.py brief <template> [KEY=VALUE ...] [--set-file KEY=PATH ...] --title T [--run ID] [--dry-run]
  orca_dev.py spawn --agent agy|codex|claude --model M [--effort E] --title T --task TASK_ID [--worktree active]
  orca_dev.py ready <handle> <agy|codex|claude|marker> [timeout-s]
  orca_dev.py close <handle>

Stdlib only. Every Orca call is subprocess.run([...]) with an argument list,
never a shell. Supported floor: Python 3.10; the code also runs on the macOS
system python3 (3.9), so no 3.10-only syntax is used.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

PLUGIN = Path(__file__).resolve().parents[1]
PROMPTS = PLUGIN / "skills" / "orca-dev" / "prompts"

ANGLE = re.compile(r"<([^<>\n]*)>")
UPPER_SNAKE = re.compile(r"[A-Z][A-Z0-9_]*")
POLL_S = 2.0
READ_FAIL_LIMIT = 5
DISMISS_LIMIT = 3
SCREEN_TAIL = 15

# Readiness markers, busy markers, login screens and timeouts per agent (launch.md "Agent start").
AGENTS = {
    "agy": {"marker": "Antigravity", "busy": "not signed in", "login": "Select login method", "login_after": 20, "timeout": 180},
    "codex": {"marker": "Ask Codex", "busy": "Starting MCP servers", "login": "Sign in with ChatGPT", "login_after": 0, "timeout": 120},
    "claude": {"marker": "Claude Code", "busy": None, "login": "/login", "login_after": 0, "timeout": 90},
}

# Known startup modals (launch.md "Agent start" table). Screen markers match case-insensitively;
# reasons are Orca `terminal wait` blockedReason tokens (legacy codex-* and agent-neutral spellings).
# Keys are best-known values; the smoke run pins them against real screens.
MODALS = [
    {"id": "codex-update-prompt", "agent": "codex", "screen": ["update available"],
     "reasons": ["codex-update-prompt", "agent-update-prompt"], "keys": [{"text": "2"}, {"enter": True}]},
    {"id": "codex-hooks-review-prompt", "agent": "codex", "screen": ["hooks need review"],
     "reasons": ["codex-hooks-review-prompt", "agent-hooks-review-prompt"], "keys": [{"text": "2"}, {"enter": True}]},
    {"id": "claude-trust-folder", "agent": "claude", "screen": ["trust this folder", "trust the files in this folder"],
     "reasons": ["agent-trust-workspace", "codex-trust-workspace"], "keys": [{"enter": True}]},
    {"id": "agy-trust-folder", "agent": "agy", "screen": ["trust this folder"],
     "reasons": ["agent-trust-workspace", "codex-trust-workspace"], "keys": [{"enter": True}]},
]
MODAL_BY_ID = {row["id"]: row for row in MODALS}

Runner = Callable[[List[str], float], Tuple[int, Optional[dict], str]]


class Usage(Exception):
    """Bad arguments: exit code 2."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


# ---------------------------------------------------------------- orca runner

def run_orca(args: List[str], timeout: float) -> Tuple[int, Optional[dict], str]:
    """Run `orca <args>`; return (exit code, parsed stdout JSON or None, raw stdout+stderr)."""
    exe = shutil.which("orca")
    if not exe:
        return 127, None, "orca not on PATH"
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, None, "orca %s timed out after %ss" % (" ".join(args[:2]), int(timeout))
    except OSError as exc:
        return 126, None, str(exc)
    try:
        data = json.loads(p.stdout)
    except ValueError:
        data = None
    return p.returncode, data if isinstance(data, dict) else None, (p.stdout + p.stderr).strip()


def dig(data, *keys):
    """data[k1][k2]... or None."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def orca_error(code: int, data: Optional[dict], text: str) -> str:
    message = dig(data, "error", "message")
    if isinstance(message, str) and message:
        return message
    return text[-500:] if text else "orca exited with code %d" % code


# ---------------------------------------------------------------- brief

def lint_template(text: str) -> List[str]:
    """Angle tokens that are not <UPPER_SNAKE> (sorted, unique, with brackets)."""
    return sorted({m.group(0) for m in ANGLE.finditer(text) if not UPPER_SNAKE.fullmatch(m.group(1))})


def template_tokens(text: str) -> List[str]:
    """UPPER_SNAKE names used as <NAME> (sorted, unique)."""
    return sorted({m.group(1) for m in ANGLE.finditer(text) if UPPER_SNAKE.fullmatch(m.group(1))})


def fill_template(text: str, values: Dict[str, str]) -> Tuple[str, List[str]]:
    """One-pass literal substitution of <NAME> tokens; values are never rescanned.

    Returns (filled text, sorted names of template tokens without a value)."""
    def sub(m):
        name = m.group(1)
        if UPPER_SNAKE.fullmatch(name) and name in values:
            return values[name]
        return m.group(0)
    unfilled = [name for name in template_tokens(text) if name not in values]
    return ANGLE.sub(sub, text), unfilled


def resolve_template(arg: str) -> Path:
    path = Path(arg)
    if path.is_file():
        return path
    path = PROMPTS / (arg if arg.endswith(".md") else arg + ".md")
    if path.is_file():
        return path
    raise Usage("template not found: " + arg)


def read_utf8(path: Path) -> str:
    """UTF-8 text with a leading BOM dropped; line endings are kept byte-for-byte."""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except OSError as exc:
        raise Usage("cannot read %s: %s" % (path, exc))
    except UnicodeDecodeError:
        raise Usage("not UTF-8: %s" % path)


def parse_values(pairs: List[str], set_files: List[str], allowed: List[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    items = [(p, False) for p in pairs] + [(p, True) for p in set_files]
    for item, from_file in items:
        key, sep, value = item.partition("=")
        if not sep or not UPPER_SNAKE.fullmatch(key):
            raise Usage("expected KEY=VALUE with an UPPER_SNAKE key: " + item)
        if key in values:
            raise Usage("duplicate key: " + key)
        if key not in allowed:
            raise Usage("unknown key %s; template tokens: %s" % (key, ", ".join(allowed) or "none"))
        values[key] = read_utf8(Path(value)) if from_file else value
    return values


def cmd_brief(argv: List[str], run: Runner = run_orca) -> int:
    parser = Parser(prog="orca_dev.py brief")
    parser.add_argument("template")
    parser.add_argument("pairs", nargs="*")
    parser.add_argument("--set-file", action="append", default=[])
    parser.add_argument("--title", required=True)
    parser.add_argument("--run")
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_intermixed_args(argv)
        template = read_utf8(resolve_template(args.template))
    except Usage as exc:
        print("brief: " + str(exc), file=sys.stderr)
        return 2
    bad = lint_template(template)
    if bad:
        print("brief: template has non-<UPPER_SNAKE> angle tokens: " + " ".join(bad), file=sys.stderr)
        return 1
    try:
        values = parse_values(args.pairs, args.set_file, template_tokens(template))
    except Usage as exc:
        print("brief: " + str(exc), file=sys.stderr)
        return 2
    text, unfilled = fill_template(template, values)
    if unfilled:
        print("brief: unfilled tokens: " + " ".join("<%s>" % n for n in unfilled), file=sys.stderr)
        return 1
    if args.dry_run:
        sys.stdout.write(text)
        return 0
    call = ["orchestration", "task-create", "--spec", text, "--task-title", args.title]
    if args.run:
        call += ["--run", args.run]
    code, data, raw = run(call + ["--json"], 60)
    task_id = dig(data, "result", "task", "id")
    if code != 0 or not isinstance(task_id, str):
        print("brief: task-create failed: " + orca_error(code, data, raw), file=sys.stderr)
        return 3
    print(task_id)
    return 0


# ---------------------------------------------------------------- ready

def view(lines: List[str], is_screen: bool, n: int) -> str:
    """Rendered frame: the whole frame is current state. Stream: only the last n lines count."""
    return "\n".join(lines if is_screen else lines[-n:])


def classify(agent: str, lines: List[str], is_screen: bool, elapsed: float,
             blocked_reason: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Pure readiness verdict: state in ready|busy|modal|needs_login|blocked|waiting, modal id or None."""
    cfg = AGENTS.get(agent)
    text25 = view(lines, is_screen, 25)
    text20 = view(lines, is_screen, 20)
    lower25 = text25.lower()
    if cfg and cfg["login"] in text25:
        return {"state": "needs_login" if elapsed >= cfg["login_after"] else "busy", "modal": None}
    for row in MODALS:
        if row["agent"] != agent:
            continue
        if any(m in lower25 for m in row["screen"]) or (blocked_reason is not None and blocked_reason in row["reasons"]):
            return {"state": "modal", "modal": row["id"]}
    if blocked_reason:
        return {"state": "blocked", "modal": None}
    marker = cfg["marker"] if cfg else agent
    busy = bool(cfg and cfg["busy"] and cfg["busy"] in text20)
    if marker in text25 and not busy:
        return {"state": "ready", "modal": None}
    return {"state": "busy" if busy else "waiting", "modal": None}


def read_screen(run: Runner, handle: str) -> Tuple[bool, List[str], bool, str]:
    """(ok, lines, is_screen, error). Rendered screen first; stream read if the host cannot render."""
    code, data, raw = run(["terminal", "read", "--terminal", handle, "--screen", "--limit", "80", "--json"], 30)
    term = dig(data, "result", "terminal")
    if code != 0 or not isinstance(term, dict):
        code, data, raw = run(["terminal", "read", "--terminal", handle, "--limit", "80", "--json"], 30)
        term = dig(data, "result", "terminal")
        if code != 0 or not isinstance(term, dict):
            return False, [], False, orca_error(code, data, raw)
    tail = [x for x in (term.get("tail") or []) if isinstance(x, str)]
    return True, tail, term.get("source") == "screen", ""


def probe_blocked(run: Runner, handle: str) -> Optional[str]:
    """blockedReason reported by a short tui-idle wait, or None."""
    code, data, raw = run(["terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", "2000", "--json"], 30)
    reason = dig(data, "result", "wait", "blockedReason")
    return reason if isinstance(reason, str) and reason else None


def send_keys(run: Runner, handle: str, keys: List[dict]) -> bool:
    """Each step is one `terminal send` (text alone, or Enter alone). False if Orca refuses any step."""
    for key in keys:
        call = ["terminal", "send", "--terminal", handle]
        if "text" in key:
            call += ["--text", key["text"]]
        if key.get("enter"):
            call.append("--enter")
        code, data, raw = run(call + ["--json"], 30)
        if code != 0 or dig(data, "result", "send", "accepted") is False:
            return False
    return True


def tail_text(lines: List[str]) -> str:
    return "\n".join(lines[-SCREEN_TAIL:])


def wait_ready(run: Runner, handle: str, agent: str, timeout_s: float, blocked_reason: Optional[str] = None,
               clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Poll until the agent TUI is ready. Returns {"code", "dismissed", "screen", "error"}.

    code: 0 ready; 1 timeout; 3 five failed reads in a row; 5 unknown or undismissable modal; 6 login screen."""
    start = clock()
    dismissed: List[str] = []
    attempts: Dict[str, int] = {}
    lines: List[str] = []
    fails = 0
    error = ""

    def result(code, err=None):
        return {"code": code, "dismissed": dismissed, "screen": tail_text(lines), "error": err}

    while True:
        ok, new_lines, is_screen, error = read_screen(run, handle)
        if not ok:
            fails += 1
            if fails >= READ_FAIL_LIMIT:
                return result(3, "terminal read failing %d times: %s" % (fails, error))
        else:
            fails = 0
            lines = new_lines
            verdict = classify(agent, lines, is_screen, clock() - start, blocked_reason)
            blocked_reason = None
            state = verdict["state"]
            if state == "ready":
                data = run(["terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", "60000", "--json"], 90)[1]
                final = dig(data, "result", "wait", "blockedReason")
                if not (isinstance(final, str) and final):
                    return result(0)
                # The final wait saw a block: re-read and classify with it (known modal -> dismiss, login -> 6, unknown -> 5).
                blocked_reason = final
                continue
            if state == "needs_login":
                return result(6, "%s shows a login screen" % agent)
            if state == "blocked":
                return result(5, "unknown modal on %s" % handle)
            if state == "modal":
                modal = verdict["modal"]
                attempts[modal] = attempts.get(modal, 0) + 1
                if attempts[modal] > DISMISS_LIMIT:
                    return result(5, "modal %s persists after %d dismissals" % (modal, DISMISS_LIMIT))
                if not send_keys(run, handle, MODAL_BY_ID[modal]["keys"]):
                    return result(5, "orca refused terminal send for modal %s" % modal)
                if modal not in dismissed:
                    dismissed.append(modal)
        if clock() - start >= timeout_s:
            return result(1, "%s not ready on %s after %ss" % (agent, handle, int(timeout_s)))
        began = clock()
        blocked_reason = probe_blocked(run, handle)
        rest = POLL_S - (clock() - began)
        if rest > 0:
            sleep(rest)


def cmd_ready(argv: List[str], run: Runner = run_orca, clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep) -> int:
    if len(argv) not in (2, 3) or not argv[0] or not argv[1]:
        print("usage: orca_dev.py ready <handle> <agy|codex|claude|marker> [timeout-s]", file=sys.stderr)
        return 2
    timeout = argv[2] if len(argv) == 3 else "120"
    if not timeout.isdigit():
        print("ready: timeout-s must be a non-negative integer, got %r" % timeout, file=sys.stderr)
        return 2
    outcome = wait_ready(run, argv[0], argv[1], float(timeout), clock=clock, sleep=sleep)
    if outcome["code"] == 0:
        print(json.dumps({"dismissed": outcome["dismissed"]}, ensure_ascii=False))
    else:
        print("ready: " + str(outcome["error"]), file=sys.stderr)
        if outcome["screen"]:
            print(outcome["screen"], file=sys.stderr)
    return outcome["code"]


# ---------------------------------------------------------------- spawn

def build_argv(agent: str, model: str, effort: Optional[str]) -> List[str]:
    """Agent argv exactly as launch.md lists it."""
    if agent == "agy":
        return ["agy", "--model", model, "--dangerously-skip-permissions"]
    if agent == "codex":
        return ["codex", "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust",
                "-m", model, "-c", "model_reasoning_effort=%s" % effort, "-c", "features.multi_agent=false"]
    if agent == "claude":
        return ["claude", "--dangerously-skip-permissions", "--model", model, "--effort", str(effort)]
    raise Usage("unknown agent: " + agent)


def command_line(argv: List[str], windows: bool) -> str:
    """The --command string for the host OS: shlex.join on POSIX, list2cmdline on Windows."""
    return subprocess.list2cmdline(argv) if windows else shlex.join(argv)


def cmd_spawn(argv: List[str], run: Runner = run_orca, clock: Callable[[], float] = time.monotonic,
              sleep: Callable[[float], None] = time.sleep, windows: bool = os.name == "nt",
              new_request_id: Callable[[], str] = lambda: str(uuid.uuid4())) -> int:
    out = {"stage": None, "handle": None, "task_id": None, "dispatch_id": None, "request_id": None,
           "dismissed": [], "agent": None, "screen": None, "error": None}

    def emit(code: int) -> int:
        print(json.dumps(out, ensure_ascii=False))
        return code

    parser = Parser(prog="orca_dev.py spawn")
    parser.add_argument("--agent", required=True, choices=sorted(AGENTS))
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort")
    parser.add_argument("--title", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--worktree", default="active")
    try:
        args = parser.parse_args(argv)
        out["agent"], out["task_id"] = args.agent, args.task
        if args.agent == "agy" and args.effort:
            raise Usage("agy takes no --effort: the level is part of the model id")
        if args.agent != "agy" and not args.effort:
            raise Usage("--effort is required for " + args.agent)
        command = command_line(build_argv(args.agent, args.model, args.effort), windows)
    except Usage as exc:
        out["error"] = str(exc)
        return emit(2)

    out["stage"] = "terminal_create"
    code, data, raw = run(["terminal", "create", "--worktree", args.worktree, "--title", args.title,
                           "--command", command, "--json"], 60)
    handle = dig(data, "result", "terminal", "handle")
    if code != 0 or not isinstance(handle, str) or not handle:
        out["error"] = orca_error(code, data, raw)
        return emit(3)
    out["handle"] = handle

    out["stage"] = "ready"
    code, data, raw = run(["terminal", "wait", "--terminal", handle, "--for", "tui-idle",
                           "--timeout-ms", "180000", "--json"], 200)
    reason = dig(data, "result", "wait", "blockedReason")
    outcome = wait_ready(run, handle, args.agent, AGENTS[args.agent]["timeout"],
                         reason if isinstance(reason, str) and reason else None, clock=clock, sleep=sleep)
    out["dismissed"] = outcome["dismissed"]
    if outcome["code"] != 0:
        out["screen"], out["error"] = outcome["screen"], outcome["error"]
        return emit({1: 1, 3: 1, 5: 5, 6: 6}[outcome["code"]])

    out["stage"] = "dispatch"
    out["request_id"] = new_request_id()
    code, data, raw = run(["orchestration", "dispatch", "--task", args.task, "--to", handle, "--inject",
                           "--retry-request", out["request_id"], "--json"], 120)
    dispatch_id = dig(data, "result", "dispatch", "id")
    if code != 0 or not isinstance(dispatch_id, str) or not dispatch_id:
        out["error"] = orca_error(code, data, raw)
        return emit(4)
    out["dispatch_id"], out["stage"] = dispatch_id, "done"
    return emit(0)


# ---------------------------------------------------------------- close

def cmd_close(argv: List[str], run: Runner = run_orca) -> int:
    if len(argv) != 1 or not argv[0]:
        print("usage: orca_dev.py close <handle>", file=sys.stderr)
        return 2
    handle = argv[0]
    out = {"handle": handle, "closed": False, "evidence": None, "error": None}
    code, data, raw = run(["terminal", "close", "--terminal", handle, "--json"], 60)
    if code == 0 and dig(data, "result", "close", "ptyKilled") is True:
        out.update(closed=True, evidence="ptyKilled")
        print(json.dumps(out, ensure_ascii=False))
        return 0
    if code != 0:
        out["error"] = orca_error(code, data, raw)
    lcode, ldata, lraw = run(["terminal", "list", "--worktree", "current", "--json"], 60)
    rows = dig(ldata, "result", "terminals")
    if lcode == 0 and isinstance(rows, list) and dig(ldata, "result", "truncated") is not True:
        if handle not in {r.get("handle") for r in rows if isinstance(r, dict)}:
            out.update(closed=True, evidence="absent", error=None)
            print(json.dumps(out, ensure_ascii=False))
            return 0
        out["error"] = out["error"] or "terminal still listed after close"
    else:
        out["error"] = out["error"] or "terminal list failed: " + orca_error(lcode, ldata, lraw)
    print(json.dumps(out, ensure_ascii=False))
    return 1


# ---------------------------------------------------------------- main

COMMANDS = {"brief": cmd_brief, "spawn": cmd_spawn, "ready": cmd_ready, "close": cmd_close}


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(__doc__.strip().split("\n\n")[1], file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", newline="")
    sys.exit(main(sys.argv[1:]))

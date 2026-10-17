#!/usr/bin/env python3
"""orca-strigov 2.0 install checks (one file for macOS, Linux and Windows).

  python3 install.py                  read-only checks (Windows: py -3 install.py)
  python3 install.py --repo <path>    + trust <path> and its git worktrees for Claude Code, Antigravity and Codex
  python3 install.py --check <path>   report trust only, change nothing
--repo/--check may repeat. Exit: 0 clean, 1 any WARN (or native Orca skills missing), 2 usage.
Writes only ~/.claude.json, ~/.gemini/antigravity-cli/settings.json and ~/.codex/config.toml (appends
a table, never edits one), and only with --repo.
Deletes nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
SKILL_DIRS = (".codex/skills", ".claude/skills", ".agents/skills")
NATIVE_SKILLS = ("orchestration", "orca-cli")
INSTALL_CMD = "orca skills install --skill orchestration --skill orca-cli --agent codex,claude-code"
STALE_HINT = "удалить вручную или ответить `y` на вопрос координатора при первом запуске"
CACHE = Path(".codex/plugins/cache/personal/orca-strigov")
CODEX_TABLE = re.compile(r"""^\[\s*projects\s*\.\s*("(?:[^"\\]|\\.)*"|'[^']*')\s*\]\s*(?:#.*)?$""")
CODEX_TRUST = re.compile(r"""^trust_level\s*=\s*["']([^"']*)["']\s*(?:#.*)?$""")

Line = Tuple[str, str]
Run = Callable[[List[str], float], Tuple[int, str]]


class Usage(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def run_cmd(argv: List[str], timeout: float) -> Tuple[int, str]:
    """(exit code, stdout); 127 when the program cannot start, 124 on timeout."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""
    return p.returncode, p.stdout


def plugin_version() -> str:
    try:
        return str(json.loads((HERE / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError):
        return "?"


def is_strigov_copy(path: Path) -> bool:
    """True when the entry resolves into an orca-strigov checkout or plugin cache (a vendored copy)."""
    try:
        return "orca-strigov" in str(path.resolve())
    except OSError:
        return False


def missing_native_skills(home: Path) -> List[str]:
    missing = []
    for name in NATIVE_SKILLS:
        found = any((home / d / name / "SKILL.md").is_file() and not is_strigov_copy(home / d / name) for d in SKILL_DIRS)
        if not found:
            missing.append(name)
    return missing


def manifest_version(directory: Path) -> Optional[str]:
    try:
        return str(json.loads((directory / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version"))
    except (OSError, ValueError, AttributeError):
        return None


def stale_copies(home: Path, version: str) -> List[Path]:
    """Old orca-dev / vendored orchestration / orca-cli entries and old plugin-cache copies."""
    stale = []
    for d in SKILL_DIRS:
        for name in ("orca-dev", "orchestration", "orca-cli"):
            entry = home / d / name
            if not os.path.lexists(entry):
                continue
            if name == "orca-dev" or is_strigov_copy(entry):
                stale.append(entry)
    cache = home / CACHE
    if cache.is_dir():
        for entry in sorted(cache.iterdir()):
            # Codex caches "<version>+codex.<stamp>": compare the part before "+".
            cached = (manifest_version(entry) or "").split("+")[0]
            if entry.is_dir() and (entry.name.startswith(".") or cached != version):
                stale.append(entry)
    return stale


def claude_keys(path: str, windows: bool) -> List[str]:
    """projects[] keys that count as this path; the first one is written."""
    if not windows:
        return [path]
    return [path.replace("\\", "/")]


def trust_claude(data: dict, paths: List[str], windows: bool, write: bool) -> Tuple[bool, List[Line]]:
    lines: List[Line] = []
    changed = False
    projects = data.get("projects")
    for path in paths:
        keys = claude_keys(path, windows)
        trusted = isinstance(projects, dict) and any(
            isinstance(projects.get(k), dict) and bool(projects[k].get("hasTrustDialogAccepted")) for k in keys)
        if trusted:
            lines.append(("OK", "claude: %s trusted" % path))
            continue
        if not write:
            lines.append(("WARN", "claude: %s not trusted -> the trust dialog will block the worker" % path))
            continue
        if not isinstance(projects, dict):
            projects = data["projects"] = {}
        entry = projects.get(keys[0])
        if not isinstance(entry, dict):
            entry = projects[keys[0]] = {}
        entry["hasTrustDialogAccepted"] = True
        changed = True
        lines.append(("OK", "claude: trust set for %s" % path))
    return changed, lines


def trust_agy(data: dict, paths: List[str], write: bool) -> Tuple[bool, List[Line]]:
    lines: List[Line] = []
    changed = False
    for path in paths:
        listed = data.get("trustedWorkspaces")
        if isinstance(listed, list) and path in listed:
            lines.append(("OK", "agy: %s trusted" % path))
            continue
        if not write:
            lines.append(("WARN", "agy: %s not trusted -> the trust dialog will block the worker" % path))
            continue
        if not isinstance(listed, list):
            listed = data["trustedWorkspaces"] = []
        listed.append(path)
        changed = True
        lines.append(("OK", "agy: trust set for %s" % path))
    return changed, lines


def codex_tables(text: str) -> dict:
    """{path: trust_level or None} for every [projects."<path>"] / [projects.'<path>'] table in config.toml."""
    tables: dict = {}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            current = None
            m = CODEX_TABLE.match(stripped)
            if m:
                raw = m.group(1)
                try:
                    current = raw[1:-1] if raw.startswith("'") else json.loads(raw)
                except ValueError:  # a TOML escape JSON does not know: leave it to the raw-text check
                    continue
                tables.setdefault(current, None)
        elif current is not None:
            m = CODEX_TRUST.match(stripped)
            if m:
                tables[current] = m.group(1)
    return tables


def trust_codex(text: str, paths: List[str], write: bool) -> Tuple[Optional[str], List[Line]]:
    """(new config.toml text or None, lines). Appends a table per untrusted path; never edits an existing one."""
    lines: List[Line] = []
    tables = codex_tables(text)
    added = []
    for path in paths:
        level = tables.get(path, "")
        if level == "trusted":
            lines.append(("OK", "codex: %s trusted" % path))
        elif path in tables or json.dumps(path, ensure_ascii=False) in text or "'%s'" % path in text:
            # A table with another level, or the path in a form this parser does not read: a second table would break the file.
            lines.append(("WARN", "codex: %s has another entry in config.toml -> set trust_level = \"trusted\" by hand" % path))
        elif not write:
            lines.append(("WARN", "codex: %s not trusted -> the trust dialog will block the worker" % path))
        else:
            added.append('[projects.%s]\ntrust_level = "trusted"\n' % json.dumps(path, ensure_ascii=False))
            lines.append(("OK", "codex: trust set for %s" % path))
    if not added:
        return None, lines
    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + "\n".join(added), lines


def write_atomic(file: Path, label: str, content: str) -> List[Line]:
    """Replace one file through a temp file + os.replace, keeping its mode; symlinks are not rewritten."""
    if file.is_symlink():
        return [("WARN", "%s: %s is a symlink -> not rewritten, edit it by hand" % (label, file))]
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=str(file.parent), prefix=".install-py.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        try:
            os.chmod(tmp, file.stat().st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, file)
        tmp = None
    except OSError as exc:
        return [("WARN", "%s: could not write %s (%s)" % (label, file, exc))]
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return []


def update_codex(file: Path, paths: List[str], write: bool) -> List[Line]:
    if not file.is_file():
        return [("WARN", "codex: %s missing -> run codex once, then re-run" % file)]
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [("WARN", "codex: could not read %s (%s)" % (file, exc))]
    new, lines = trust_codex(text, paths, write)
    return lines + (write_atomic(file, "codex", new) if new is not None else [])


def update_json(file: Path, label: str, hint: str, apply: Callable[[dict], Tuple[bool, List[Line]]]) -> List[Line]:
    """Read, apply, and atomically write (temp file + os.replace) one JSON object file."""
    if not file.is_file():
        return [("WARN", "%s: %s missing -> %s" % (label, file, hint))]
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top-level value is not an object")
    except (OSError, ValueError) as exc:
        return [("WARN", "%s: %s is not valid JSON (%s) -> skipped, fix it by hand" % (label, file, exc))]
    changed, lines = apply(data)
    if not changed:
        return lines
    return lines + write_atomic(file, label, json.dumps(data, indent=2, ensure_ascii=False))


def repo_paths(repos: List[Path], run: Run, git: Optional[str]) -> List[str]:
    """Each repo plus its git worktrees, resolved, without duplicates."""
    out: List[str] = []
    for repo in repos:
        candidates = [repo]
        if git:
            code, text = run([git, "-C", str(repo), "worktree", "list", "--porcelain"], 30)
            if code == 0:
                candidates += [Path(line[len("worktree "):]) for line in text.splitlines() if line.startswith("worktree ")]
        for candidate in candidates:
            if candidate.is_dir():
                path = str(candidate.resolve())
                if path not in out:
                    out.append(path)
    return out


def check_tools(run: Run, which: Callable[[str], Optional[str]], windows: bool) -> List[Line]:
    lines: List[Line] = []
    orca = which("orca")
    if orca:
        code, text = run([orca, "--version"], 30)
        lines.append(("OK", "orca %s: %s" % (text.strip() or "?", orca)))
        code, text = run([orca, "status", "--json"], 30)
        try:
            state = json.loads(text)["result"]["runtime"]["state"]
        except (ValueError, KeyError, TypeError):
            state = "unreachable"
        lines.append(("OK", "orca runtime: ready") if state == "ready" else
                     ("WARN", "orca runtime state: %s (run: orca open --json)" % state))
    else:
        lines.append(("WARN", "orca not on PATH"))
    for name in ("codex", "claude", "agy", "git"):
        exe = which(name)
        if not exe:
            if name == "agy" and windows:
                lines.append(("INFO", "agy not on PATH (native Windows): the implementer starts on its Luna fallback"))
            else:
                lines.append(("WARN", "%s not on PATH" % name))
            continue
        label = name
        if name != "git":
            code, text = run([exe, "--version"], 30)
            label += " " + (text.strip().splitlines()[0] if code == 0 and text.strip() else "?")
        lines.append(("OK", "%s: %s" % (label, exe)))
    return lines


def check_updates(run: Run, which: Callable[[str], Optional[str]]) -> List[Line]:
    """One line per outdated agent CLI with the update command; never updates anything."""
    lines: List[Line] = []
    brew = which("brew")
    if brew and run([brew, "list", "--cask", "codex"], 60)[0] == 0:
        code, text = run([brew, "outdated", "--cask", "codex"], 120)
        if "codex" in text:
            lines.append(("WARN", "codex update available -> brew upgrade --cask codex"))
    npm = which("npm")
    if npm:
        code, text = run([npm, "outdated", "-g", "--json"], 120)
        try:
            outdated = json.loads(text or "{}")
        except ValueError:
            outdated = {}
        for package in ("@openai/codex", "@anthropic-ai/claude-code"):
            if isinstance(outdated, dict) and package in outdated:
                lines.append(("WARN", "%s update available -> npm i -g %s@latest" % (package, package)))
    return lines


def emit(lines: List[Line]) -> int:
    for level, message in lines:
        print("  %-4s %s" % (level, message))
    return sum(1 for level, _ in lines if level == "WARN")


def main(argv: Optional[List[str]] = None, home: Optional[Path] = None, run: Run = run_cmd,
         which: Callable[[str], Optional[str]] = shutil.which, windows: bool = os.name == "nt",
         python: Tuple[int, ...] = tuple(sys.version_info[:3])) -> int:
    parser = Parser(prog="install.py", description=__doc__.strip().splitlines()[0])
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--check", action="append", default=[])
    try:
        args = parser.parse_args(argv)
        repos = []
        for raw in args.repo + args.check:
            path = Path(raw).expanduser()
            if not path.is_dir():
                raise Usage("not a directory: " + raw)
            repos.append(path.resolve())
    except Usage as exc:
        print("install.py: %s" % exc, file=sys.stderr)
        return 2
    home = home or Path.home()
    write = not args.check
    version = plugin_version()
    print("orca-strigov %s install checks (%s)" % (version, "install" if write else "check"))
    warnings = emit([("INFO", "python %s at %s (orca-strigov targets Python 3.10+)" % (".".join(map(str, python)), sys.executable))])

    missing = missing_native_skills(home)
    if missing:
        emit([("WARN", "native Orca skills not installed: %s. Install them with:" % ", ".join(missing))])
        print(INSTALL_CMD)
        return 1
    warnings += emit([("OK", "native Orca skills: orchestration, orca-cli")])
    warnings += emit(check_tools(run, which, windows))
    warnings += emit(check_updates(run, which))

    if repos:
        paths = repo_paths(repos, run, which("git"))
        for path in paths:
            print("repo: %s" % path)
        warnings += emit(update_json(home / ".claude.json", "claude", "run claude once in the repo, then re-run",
                                     lambda d: trust_claude(d, paths, windows, write)))
        warnings += emit(update_json(home / ".gemini" / "antigravity-cli" / "settings.json", "agy",
                                     "run agy once, then re-run", lambda d: trust_agy(d, paths, write)))
        warnings += emit(update_codex(home / ".codex" / "config.toml", paths, write))

    stale = stale_copies(home, version)
    if stale:
        warnings += emit([("WARN", "old copy: %s" % p) for p in stale])
        print("  -> %s" % STALE_HINT)
    if warnings:
        print("install.py: %d warning(s)" % warnings)
        return 1
    print("done.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

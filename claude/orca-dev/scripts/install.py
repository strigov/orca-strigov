#!/usr/bin/env python3
"""orca-dev 2.1 install and checks (one file for macOS, Linux and Windows).

  python3 install.py                  read-only checks (Windows: py -3 install.py)
  python3 install.py --agent <a>      install this skill for claude (~/.claude/skills/orca-dev) or codex
                                      ($CODEX_HOME/skills/orca-dev, default ~/.codex/skills/orca-dev); no checks
  python3 install.py --repo <path>    + trust <path> and its git worktrees for Claude Code, Antigravity and Codex
  python3 install.py --check <path>   report trust only, change nothing
  python3 install.py --bundle <dir>   render claude/ and codex/ copies and their zips into an empty <dir>
--agent/--repo/--check may repeat; --agent combines with --repo; --bundle runs alone.
Exit: 0 clean, 1 any WARN or ERROR (or native Orca skills missing), 2 usage.
--agent replaces only a recognized orca-dev copy (edits inside its files are overwritten). --repo writes
only ~/.claude.json, ~/.gemini/antigravity-cli/settings.json and ~/.codex/config.toml (appends a table,
never edits one). Old copies are listed, never deleted.
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
import zipfile
from typing import Callable, List, Mapping, Optional, Tuple

VERSION = "2.1.0"
HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
SKILL_DIRS = (".codex/skills", ".claude/skills", ".agents/skills")
NATIVE_SKILLS = ("orchestration", "orca-cli")
INSTALL_CMD = "orca skills install --skill orchestration --skill orca-cli --agent codex,claude-code"
STALE_HINT = "удалить вручную или ответить `y` на вопрос координатора при первом запуске"
CACHE = Path(".codex/plugins/cache/personal/orca-strigov")
SHIP_FILES = ("SKILL.md", "roles.md", "launch.md", "scripts/orca_dev.py", "scripts/install.py")
OPENAI_YAML = "agents/openai.yaml"
IGNORED = ("__pycache__", ".DS_Store")
DESCRIPTION = ("Coordinate spec-driven development through supervised Orca workers (spec, plan, TDD phases, "
               "double review, commits). Only on an explicit %s; never inside a dispatched Orca worker.")
# Harness -> (invocation, extra frontmatter). Codex turns implicit invocation off in agents/openai.yaml instead.
HARNESSES = {
    "claude": ("/orca-dev", "disable-model-invocation: true\n"),
    "codex": ("$orca-dev", ""),
}
OPENAI_YAML_TEXT = """interface:
  display_name: "Orca Dev"
  short_description: "Spec-driven development through Orca workers"
  default_prompt: "Use $orca-dev to implement my task through supervised Orca workers."
policy:
  allow_implicit_invocation: false
"""
FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
INVOKING = re.compile(r"^Invoking `.*? is the user's explicit request", re.M)
SKILL_NAME = re.compile(r"^name: orca-dev$", re.M)
VERSION_LINE = re.compile(r'^VERSION = "([^"]+)"$', re.M)
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
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


def codex_home(home: Path, env: Mapping[str, str]) -> Path:
    return Path(env["CODEX_HOME"]).expanduser() if env.get("CODEX_HOME") else home / ".codex"


def skill_dest(harness: str, home: Path, env: Mapping[str, str]) -> Path:
    return (home / ".claude" if harness == "claude" else codex_home(home, env)) / "skills" / "orca-dev"


def ship_list(src: Path) -> List[str]:
    """Relative paths a rendered copy is made of, before the harness's own files."""
    prompts = sorted("prompts/" + p.name for p in (src / "prompts").glob("*.md"))
    missing = [rel for rel in SHIP_FILES if not (src / rel).is_file()]
    if missing or not prompts:
        raise OSError("incomplete skill at %s: missing %s" % (src, ", ".join(missing) or "prompts/*.md"))
    return list(SHIP_FILES) + prompts


def render_skill_md(text: str, harness: str) -> str:
    call, extra = HARNESSES[harness]
    head = "---\nname: orca-dev\ndescription: %s\n%s---\n" % (DESCRIPTION % call, extra)
    text, n_head = FRONTMATTER.subn(head, text, count=1)
    text, n_call = INVOKING.subn("Invoking `%s` is the user's explicit request" % call, text, count=1)
    if (n_head, n_call) != (1, 1):
        raise OSError("SKILL.md: frontmatter or the Invoking line not found")
    return text


def render(src: Path, harness: str, dest: Path) -> None:
    """Write the harness copy of the skill at src into the new folder dest (same result from any copy)."""
    files = ship_list(src)
    dest.mkdir()
    for rel in files:
        data = (src / rel).read_bytes()
        if rel == "SKILL.md":
            data = render_skill_md(data.decode("utf-8"), harness).encode("utf-8")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if rel.startswith("scripts/"):
            target.chmod(0o755)
    if harness == "codex":
        (dest / "agents").mkdir()
        (dest / OPENAI_YAML).write_bytes(OPENAI_YAML_TEXT.encode("utf-8"))


def copy_files(path: Path) -> List[str]:
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*")
                  if p.is_file() and not set(p.relative_to(path).parts) & set(IGNORED))


def recognized_version(path: Path) -> Optional[str]:
    """VERSION of a standalone orca-dev copy ("" when it has none); None when path is not one. Never runs its code."""
    if os.path.islink(path) or not path.is_dir() or not (path / "scripts" / "orca_dev.py").is_file():
        return None
    try:
        head = FRONTMATTER.match((path / "SKILL.md").read_text(encoding="utf-8"))
        if not head or not SKILL_NAME.search(head.group(0)):
            return None
        found = VERSION_LINE.search((path / "scripts" / "install.py").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found.group(1) if found else ""


def unexpected(path: Path, allowed: List[str]) -> List[str]:
    """Entries of an installed copy that a reinstall would lose: other files, extra folders, any symlink."""
    folders = {"."} | {os.path.dirname(rel) for rel in allowed}
    found = []
    for root, dirnames, filenames in os.walk(str(path)):  # never follows symlinks
        base = Path(root).relative_to(path).as_posix()
        for name in sorted(dirnames):
            rel = name if base == "." else base + "/" + name
            if name in IGNORED:
                dirnames.remove(name)
            elif os.path.islink(os.path.join(root, name)) or rel not in folders:
                found.append(rel + "/")
                dirnames.remove(name)
        for name in sorted(filenames):
            rel = name if base == "." else base + "/" + name
            if name not in IGNORED and (os.path.islink(os.path.join(root, name)) or rel not in allowed):
                found.append(rel)
    return found


def install_skill(src: Path, harness: str, dest: Path) -> List[Line]:
    """Render into a sibling temp folder, then swap it in; the old copy is kept until the swap succeeds."""
    if os.path.lexists(dest):
        if os.path.realpath(dest) == os.path.realpath(src):
            return [("OK", "%s: %s is this copy, nothing to do" % (harness, dest))]
        if recognized_version(dest) is None:
            return [("ERROR", "%s: %s is not an orca-dev copy (or is a symlink); remove or rename it, then re-run"
                     % (harness, dest))]
        try:
            extra = unexpected(dest, ship_list(src) + [OPENAI_YAML])
        except OSError as exc:
            return [("ERROR", "%s: %s" % (harness, exc))]
        if extra:
            return [("ERROR", "%s: %s has files this version does not ship, a reinstall would lose them: %s; "
                              "move them out, then re-run" % (harness, dest, ", ".join(extra)))]
    stamp = "%d" % os.getpid()
    new, old = dest.with_name(".orca-dev.new-" + stamp), dest.with_name(".orca-dev.old-" + stamp)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        render(src, harness, new)
        if recognized_version(new) != VERSION:
            raise OSError("rendered copy does not verify")
        if os.path.lexists(dest):
            os.rename(str(dest), str(old))
            try:
                os.rename(str(new), str(dest))
            except OSError:
                os.rename(str(old), str(dest))
                raise
            shutil.rmtree(str(old))
        else:
            os.rename(str(new), str(dest))
    except OSError as exc:
        shutil.rmtree(str(new), ignore_errors=True)
        return [("ERROR", "%s: install into %s failed: %s" % (harness, dest, exc))]
    return [("OK", "%s: orca-dev %s installed at %s (start a new session)" % (harness, VERSION, dest))]


def write_zip(tree: Path, zpath: Path) -> None:
    """Stable zip of tree under one top folder orca-dev/: sorted entries, fixed timestamps and modes."""
    with zipfile.ZipFile(str(zpath), "w", zipfile.ZIP_DEFLATED) as z:
        for rel in copy_files(tree):
            info = zipfile.ZipInfo("orca-dev/" + rel, ZIP_TIME)
            info.external_attr = (0o100755 if rel.startswith("scripts/") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (tree / rel).read_bytes())


def bundle(src: Path, out: Path) -> List[Line]:
    out = out.resolve()
    if out == src.resolve() or src.resolve() in out.parents:
        return [("ERROR", "bundle: %s is inside the skill folder %s" % (out, src))]
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        return [("ERROR", "bundle: %s must be absent or an empty folder" % out)]
    lines: List[Line] = []
    created = not out.exists()
    try:
        out.mkdir(parents=True, exist_ok=True)
        for harness in HARNESSES:
            tree = out / harness / "orca-dev"
            tree.parent.mkdir()
            render(src, harness, tree)
            zpath = out / ("orca-dev-%s-v%s.zip" % (harness, VERSION))
            write_zip(tree, zpath)
            lines.append(("OK", "%s: %s and %s" % (harness, tree, zpath)))
    except OSError as exc:
        for child in ([out] if created else list(out.iterdir())):
            shutil.rmtree(str(child), ignore_errors=True) if child.is_dir() else child.unlink()
        return [("ERROR", "bundle failed, nothing left in %s: %s" % (out, exc))]
    return lines


def is_strigov_copy(path: Path) -> bool:
    """True when the entry resolves into an orca-strigov checkout or plugin cache (a vendored copy)."""
    try:
        return "orca-strigov" in path.resolve().parts
    except OSError:
        return False


def missing_native_skills(home: Path) -> List[str]:
    missing = []
    for name in NATIVE_SKILLS:
        found = any((home / d / name / "SKILL.md").is_file() and not is_strigov_copy(home / d / name) for d in SKILL_DIRS)
        if not found:
            missing.append(name)
    return missing


def stale_copies(home: Path, env: Mapping[str, str]) -> List[Path]:
    """orca-dev copies of another version, 1.x and plugin copies, vendored orchestration / orca-cli, the plugin cache."""
    dirs = [home / d for d in SKILL_DIRS]
    if codex_home(home, env) / "skills" not in dirs:
        dirs.insert(1, codex_home(home, env) / "skills")
    stale = []
    for d in dirs:
        for name in ("orca-dev", "orchestration", "orca-cli"):
            entry = d / name
            if not os.path.lexists(entry):
                continue
            if name == "orca-dev" and recognized_version(entry) != VERSION or name != "orca-dev" and is_strigov_copy(entry):
                stale.append(entry)
    if os.path.lexists(home / CACHE):
        stale.append(home / CACHE)
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


def codex_key(name: str, windows: bool) -> str:
    """The TOML key Codex itself writes: on Windows the lowercased path as a literal string."""
    if windows and "'" not in name:
        return "'%s'" % name
    return json.dumps(name, ensure_ascii=False)


def trust_codex(text: str, paths: List[str], windows: bool, write: bool) -> Tuple[Optional[str], List[Line]]:
    """(new config.toml text or None, lines). Appends a table per untrusted path; never edits an existing one.
    On Windows Codex lowercases the whole path, so keys are compared case-insensitively."""
    lines: List[Line] = []
    tables: dict = {}
    for key, level in codex_tables(text).items():
        key = key.lower() if windows else key
        if tables.get(key) != "trusted":
            tables[key] = level
    haystack = text.lower() if windows else text
    added = []
    for path in paths:
        name = path.lower() if windows else path
        level = tables.get(name, "")
        if level == "trusted":
            lines.append(("OK", "codex: %s trusted" % path))
        elif name in tables or json.dumps(name, ensure_ascii=False) in haystack or "'%s'" % name in haystack:
            # A table with another level, or the path in a form this parser does not read: a second table would break the file.
            lines.append(("WARN", "codex: %s has another entry in config.toml -> set trust_level = \"trusted\" by hand" % path))
        elif not write:
            lines.append(("WARN", "codex: %s not trusted -> the trust dialog will block the worker" % path))
        else:
            added.append('[projects.%s]\ntrust_level = "trusted"\n' % codex_key(name, windows))
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


def update_codex(file: Path, paths: List[str], windows: bool, write: bool) -> List[Line]:
    if not file.is_file():
        return [("WARN", "codex: %s missing -> run codex once, then re-run" % file)]
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        return [("WARN", "codex: could not read %s (%s)" % (file, exc))]
    new, lines = trust_codex(text, paths, windows, write)
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
    return sum(1 for level, _ in lines if level in ("WARN", "ERROR"))


def finish(warnings: int) -> int:
    if warnings:
        print("install.py: %d warning(s) or error(s)" % warnings)
        return 1
    print("done.")
    return 0


def main(argv: Optional[List[str]] = None, home: Optional[Path] = None, run: Run = run_cmd,
         which: Callable[[str], Optional[str]] = shutil.which, windows: bool = os.name == "nt",
         python: Tuple[int, ...] = tuple(sys.version_info[:3]), env: Mapping[str, str] = os.environ,
         src: Path = SKILL_ROOT) -> int:
    parser = Parser(prog="install.py", description=__doc__.strip().splitlines()[0])
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--agent", action="append", default=[], choices=sorted(HARNESSES))
    parser.add_argument("--bundle")
    try:
        args = parser.parse_args(argv)
        if args.bundle is not None and (args.agent or args.repo or args.check):
            raise Usage("--bundle runs alone")
        if args.check and args.agent:
            raise Usage("--check changes nothing: drop --agent")
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
    if args.bundle is not None:
        print("orca-dev %s bundle" % VERSION)
        return finish(emit(bundle(src, Path(args.bundle).expanduser())))
    if args.agent:
        print("orca-dev %s install" % VERSION)
        failed = emit([line for harness in dict.fromkeys(args.agent)
                       for line in install_skill(src, harness, skill_dest(harness, home, env))])
        if failed or not repos:
            return finish(failed)
    write = not args.check
    print("orca-dev %s install checks (%s)" % (VERSION, "install" if write else "check"))
    warnings = emit([("INFO", "python %s at %s (orca-dev targets Python 3.10+)" % (".".join(map(str, python)), sys.executable))])

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
        warnings += emit(update_codex(home / ".codex" / "config.toml", paths, windows, write))

    stale = stale_copies(home, env)
    if stale:
        warnings += emit([("WARN", "old copy: %s" % p) for p in stale])
        print("  -> %s" % STALE_HINT)
    return finish(warnings)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())

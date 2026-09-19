#!/usr/bin/env bash
# install.sh — Orca Strigov prerequisites and explicitly requested repo trust.
#
#   ./install.sh                 # read-only plugin/prerequisite/conflict checks
#   ./install.sh --repo <path>   # pre-trust this repo/worktrees for Claude and Antigravity
#   ./install.sh --check <path>  # read-only report, changes nothing
#   ./install.sh --legacy-skill  # explicitly install the old standalone skill (not with plugin)
#   --repo may be given several times. Exit: 0 clean, 1 if any WARN, 2 usage error.
set -u
set -f  # Repo paths are literal; newline splitting below must not expand globs.
here="$(cd "$(dirname "$0")" && pwd -P)"
user_home="${ORCA_DEV_TEST_HOME:-$HOME}"
test_mode="${ORCA_DEV_TEST_HOME:+yes}"
usage(){ sed -n '2,8p' "$0"; }
mode=install; repos=""; legacy=""
add_repo(){
  local p="$1" abs
  abs="$(cd "$p" 2>/dev/null && pwd -P)" || { echo "install.sh: not a directory: $p" >&2; exit 2; }
  case $'\n'"$repos" in *$'\n'"$abs"$'\n'*) return;; esac
  repos="$repos$abs"$'\n'
}
while [ $# -gt 0 ]; do
  case "$1" in
    --repo|--check)
      if [ $# -lt 2 ] || [ -z "$2" ]; then echo "install.sh: $1 requires a path" >&2; usage >&2; exit 2; fi
      [ "$1" = --check ] && mode=check
      add_repo "$2"; shift 2;;
    -h|--help) usage; exit 0;;
    --legacy-skill) legacy=yes; shift;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2;;
  esac
done
nwarn=0
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn(){ nwarn=$((nwarn+1)); printf '  \033[33mWARN\033[0m %s\n' "$*"; }
info(){ printf '  \033[36mINFO\033[0m %s\n' "$*"; }   # informational: not counted, does not affect the exit code
fix(){ printf '  \033[36mFIX\033[0m  %s\n' "$*"; }

echo "Orca Strigov prerequisites ($mode)"

# --- 1. skill link ------------------------------------------------------------
# Python is already a runtime dependency; lstat/unlink never traverses the leaf.
if ! command -v python3 >/dev/null 2>&1; then warn 'python3 not on PATH (required; no installation changes made)'; exit 1; fi
if ! python3 "$here/bin/lib/run_check.py" capabilities; then
  warn 'unsupported runner capabilities (Linux Python 3.9+; macOS Python 3.13+); no installation changes made'
  exit 1
fi
link_output=$(python3 - "$here" "$user_home" "$mode" "$test_mode" "$legacy" <<'PY'
import json, os, pathlib, sys
here, home, mode, test, legacy = sys.argv[1:]
def plain(path):
    p = pathlib.Path(os.path.abspath(path))
    if any(x.is_symlink() for x in (p, *p.parents)):
        raise ValueError('refusing write through symlink: ' + str(p))
home_valid = not test
try:
    if test:
        if not os.path.isabs(home) or not os.path.isdir(home) or os.path.realpath(home) == os.path.realpath(os.path.expanduser('~')):
            raise ValueError('ORCA_DEV_TEST_HOME must be an existing isolated absolute directory')
        plain(home)
        home_valid = True
    if not legacy:
        manifest = pathlib.Path(here) / '.codex-plugin' / 'plugin.json'
        with manifest.open(encoding='utf-8') as f: plugin = json.load(f)
        if plugin.get('name') != 'orca-strigov': raise ValueError('unexpected plugin manifest')
        for name in ('orca-cli', 'orchestration', 'orca-dev'):
            if not (pathlib.Path(here) / 'skills' / name / 'SKILL.md').is_file():
                raise ValueError('missing plugin skill: ' + name)
            for directory in ('.agents', '.codex'):
                candidate = os.path.join(home, directory, 'skills', name)
                if os.path.lexists(candidate):
                    print('WARN:potential duplicate skill: ' + candidate + '; verify disabled or move this exact entry out of discovery before enabling the plugin')
        if not (pathlib.Path(here) / 'hooks' / 'hooks.json').is_file():
            raise ValueError('missing plugin hooks')
        print('OK:complete plugin source: ' + here)
        print('INFO:plugin registration and hook trust are separate; see docs/install-plugin.md')
        print('INFO:no standalone skill links or environment settings written')
        sys.exit(0)
    src = os.path.realpath(os.path.join(here, 'skills', 'orca-dev'))
    target = os.path.join(home, '.codex', 'skills', 'orca-dev')
    print('INFO:skill source: ' + src)
    print('INFO:skill link: ' + target + ' -> ' + (os.readlink(target) if os.path.islink(target) else '(not a link)'))
    points = os.path.islink(target) and os.path.realpath(target) == src
    if not os.path.isdir(src): raise ValueError('skill source missing: ' + src)
    if mode == 'install':
        plain(os.path.dirname(target))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.lexists(target) and not os.path.islink(target):
            raise ValueError(target + ' exists and is not a link; not touching it')
        if not points:
            if os.path.islink(target): os.unlink(target)
            os.symlink(src, target)
        print('OK:skill linked: ' + target + ' -> ' + src)
    elif points: print('OK:skill present: ' + target)
    else: raise ValueError('skill missing or stale: ' + target + ' (run ./install.sh)')
except (OSError, ValueError) as exc:
    print('WARN:' + str(exc))
    if not home_valid: sys.exit(2)
PY
)
link_rc=$?
while IFS= read -r line; do
  case "$line" in OK:*) ok "${line#OK:}";; WARN:*) warn "${line#WARN:}";; INFO:*) info "${line#INFO:}";; esac
done <<<"$link_output"
[ "$link_rc" -eq 2 ] && exit 2
[ "$link_rc" -ne 0 ] && warn 'skill link validation failed'
if [ -n "$legacy" ] && [ -n "${ORCA_DEV_HOME:-}" ]; then
  process_home=$(cd "$ORCA_DEV_HOME" 2>/dev/null && pwd -P)
  if [ "$process_home" = "$here" ]; then ok "Process ORCA_DEV_HOME = $ORCA_DEV_HOME"
  else warn "Process ORCA_DEV_HOME is '$ORCA_DEV_HOME', expected '$here'; restart the parent or export ORCA_DEV_HOME to this checkout for the worker launch"; fi
elif [ -n "$legacy" ]; then info 'Process ORCA_DEV_HOME unset; legacy bootstrap resolves the installed skill link'
else info 'Plugin helpers resolve from the loaded plugin; legacy ORCA_DEV_HOME is not used'; fi
info 'User environment: install.sh does not write shell profiles or persistent environment'
[ -n "$test_mode" ] && info 'isolated test home: external CLI/runtime probes, upgrades and registration are skipped'

# --- 2. CLIs ----------------------------------------------------------------------
for c in orca codex claude agy git python3; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c: $(command -v "$c")"; else warn "$c not on PATH"; fi
done
if [ -z "$test_mode" ] && command -v orca >/dev/null 2>&1; then
  st=$(orca status --json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("result",{}).get("runtime",{}).get("state","?"))' 2>/dev/null)
  [ "$st" = ready ] && ok "orca runtime: ready" || warn "orca runtime state: ${st:-unreachable} (run: orca open --json)"
fi

# --- 3. Codex update prompt ---------------------------------------------------------
if [ -z "$test_mode" ] && command -v brew >/dev/null 2>&1 && brew list --cask codex >/dev/null 2>&1; then
  if brew outdated --cask codex 2>/dev/null | grep -q codex; then
    warn "codex outdated → update prompt will block workers (brew upgrade --cask codex)"
  else ok "codex up to date ($(codex --version 2>/dev/null))"; fi
fi

# --- 4. Codex hooks trust --------------------------------------------------------------
hooks="$user_home/.codex/hooks.json"; cfg="$user_home/.codex/config.toml"
if [ -f "$hooks" ] && [ -f "$cfg" ]; then
  declared=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));h=d.get("hooks",d);print(sum(len(g.get("hooks",[g])) for l in h.values() for g in l))' "$hooks" 2>/dev/null)
  declared=${declared:-0}
  trusted=$(grep -c 'trusted_hash' "$cfg" 2>/dev/null || :)
  trusted=${trusted:-0}
  if [ "$declared" -gt "$trusted" ]; then
    warn "codex hooks: $declared declared, $trusted trusted → 'Hooks need review' will block worker-start for codex"
    fix 'review and explicitly trust the expected hooks in Codex; this script never bypasses hook trust'
  else ok "codex hooks trusted ($trusted/$declared)"; fi
fi
grep -q '^model = "chatgpt-web/pro"' "$cfg" 2>/dev/null && info "codex default model is chatgpt-web/pro — every protocol launch must pass an explicit --model (roles.md does)"

# --- 5. per-repo trust ----------------------------------------------------------------
# trust_json <claude|agy> <file> <mode> <path>... — one atomic read/modify/write per file;
# prints OK:/WARN: lines which the shell maps to ok/warn (so the WARN counter is kept).
PY_TRUST=$(cat <<'PY'
import json, os, sys, tempfile
kind, p, mode = sys.argv[1:4]; paths = sys.argv[4:]
name = {"claude": "claude", "agy": "agy"}[kind]
if not os.path.isfile(p):
    hint = "run claude once in the repo, then re-run" if kind == "claude" else "run agy once, then re-run"
    print("WARN:%s: %s missing → %s" % (name, p, hint)); sys.exit(0)
try:
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    if not isinstance(d, dict):
        raise ValueError("top-level value is not an object")
except (ValueError, OSError) as e:
    print("WARN:%s: %s is not valid JSON (%s) → skipped, fix it by hand" % (name, p, e)); sys.exit(0)
changed = False
for r in paths:
    if kind == "claude":
        projects = d.get("projects")
        if not isinstance(projects, dict): projects = {}
        entry = projects.get(r)
        trusted = isinstance(entry, dict) and bool(entry.get("hasTrustDialogAccepted"))
    else:
        tw = d.get("trustedWorkspaces")
        trusted = isinstance(tw, list) and r in tw
    if trusted:
        print("OK:%s: %s trusted" % (name, r)); continue
    if mode != "install":
        print("WARN:%s: %s not trusted → trust dialog will block the worker" % (name, r)); continue
    if kind == "claude":
        projects = d.setdefault("projects", {})
        if not isinstance(projects, dict): projects = d["projects"] = {}
        entry = projects.get(r)
        if not isinstance(entry, dict): entry = projects[r] = {}
        entry["hasTrustDialogAccepted"] = True
    else:
        tw = d.get("trustedWorkspaces")
        if not isinstance(tw, list): tw = d["trustedWorkspaces"] = []
        tw.append(r)
    changed = True
    print("OK:%s: trust set for %s" % (name, r))
if changed:
    tmp = None
    try:
        from pathlib import Path
        absolute = Path(os.path.abspath(p))
        if any(x.is_symlink() for x in (absolute, *absolute.parents)):
            raise OSError('refusing write through symlink: ' + p)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(p)), prefix=".install-sh.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        try: os.chmod(tmp, os.stat(p).st_mode & 0o777)
        except OSError: pass
        os.replace(tmp, p); tmp = None
    except OSError as e:
        print("WARN:%s: could not write %s (%s)" % (name, p, e))
    finally:
        if tmp and os.path.exists(tmp): os.unlink(tmp)
PY
)
trust_json(){
  local out line
  out=$(python3 -c "$PY_TRUST" "$@")
  while IFS= read -r line; do
    case "$line" in
      OK:*) ok "${line#OK:}";;
      WARN:*) warn "${line#WARN:}";;
      '') ;;
      *) echo "$line";;
    esac
  done <<<"$out"
}

if [ -n "$repos" ]; then
  # every git worktree of each repo needs its own trust entry (trust is keyed by exact path)
  paths=""
  add_path(){ case $'\n'"$paths" in *$'\n'"$1"$'\n'*) ;; *) paths="$paths$1"$'\n';; esac; }
  while IFS= read -r repo; do
    [ -n "$repo" ] || continue
    add_path "$repo"
    nwt=0
    while IFS= read -r wt; do
      [ -n "$wt" ] || continue
      wt="$(cd "$wt" 2>/dev/null && pwd -P)" || continue
      [ "$wt" = "$repo" ] && continue
      add_path "$wt"; nwt=$((nwt+1))
    done <<EOF
$(git -C "$repo" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p')
EOF
    echo "repo: $repo ($nwt extra worktree(s))"
  done <<EOF
$repos
EOF
  # shellcheck disable=SC2086  # $paths is newline-separated; paths never contain newlines
  old_ifs=$IFS; IFS=$'\n'; set -- $paths; IFS=$old_ifs
  trust_json claude "$user_home/.claude.json" "$mode" "$@"
  trust_json agy "$user_home/.gemini/antigravity-cli/settings.json" "$mode" "$@"
  while IFS= read -r repo; do
    [ -n "$repo" ] || continue
    if [ -z "$test_mode" ] && command -v orca >/dev/null 2>&1; then
      orca repo list --json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if any(r.get("path")==sys.argv[1] for r in d.get("result",{}).get("repos",[])) else 1)' "$repo" \
        && ok "orca: $repo registered" || warn "orca: repo not registered (orca repo add --path $repo --json)"
    fi
    if printf '%s' "$repo" | LC_ALL=C grep -q '[^ -~]'; then warn "repo path contains non-ASCII characters — expect trust/prefix bugs; prefer an ASCII path"; fi
  done <<EOF
$repos
EOF
fi

# --- 6. bridge (optional, Pro planner) ------------------------------------------------
if [ -z "$test_mode" ] && command -v pgrep >/dev/null 2>&1 && pgrep -f "codex-chatgpt-web.*cli.js serve" >/dev/null 2>&1; then ok "codex-chatgpt-web bridge running (opt-in --planner pro available)"; else info "codex-chatgpt-web bridge not running (opt-in --planner pro disabled; default planner is configured in roles.md)"; fi

if [ "$nwarn" -gt 0 ]; then echo "install.sh: $nwarn warning(s)"; exit 1; fi
echo "done."

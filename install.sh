#!/usr/bin/env bash
# install.sh — install the orca-dev skill for the Codex coordinator and clear the
# known worker-startup blockers for one or more repositories.
#
#   ./install.sh                 # link skill into ~/.codex/skills/orca-dev, check CLIs
#   ./install.sh --repo <path>   # + pre-trust <path> (and its git worktrees) for Claude Code and Antigravity
#   ./install.sh --check <path>  # read-only report, changes nothing
#   --repo may be given several times. Exit: 0 clean, 1 if any WARN, 2 usage error.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
usage(){ sed -n '2,8p' "$0"; }
mode=install; repos=""
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
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2;;
  esac
done
nwarn=0
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn(){ nwarn=$((nwarn+1)); printf '  \033[33mWARN\033[0m %s\n' "$*"; }
info(){ printf '  \033[36mINFO\033[0m %s\n' "$*"; }   # informational: not counted, does not affect the exit code
fix(){ printf '  \033[36mFIX\033[0m  %s\n' "$*"; }

echo "orca-dev install ($mode)"

# --- 1. skill link ------------------------------------------------------------
src="$here/skills/orca-dev"; target="$HOME/.codex/skills/orca-dev"
if [ ! -d "$src" ]; then
  warn "skill source missing: $src"
elif [ "$mode" = install ]; then
  mkdir -p "$HOME/.codex/skills"
  if [ -L "$target" ]; then
    if [ "$(readlink "$target")" = "$src" ]; then ok "skill already linked: $target -> $src"
    else rm -f "$target" && ln -s "$src" "$target" && ok "skill linked: $target -> $src" || warn "could not link $target"; fi
  elif [ -e "$target" ]; then
    warn "$target exists and is not a symlink — not touching it; move it away and re-run"
  else
    ln -s "$src" "$target" && ok "skill linked: $target -> $src" || warn "could not link $target"
  fi
else
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$src" ]; then ok "skill present: $target"
  elif [ -e "$target" ]; then warn "skill at $target does not point to $src"
  else warn "skill not installed (run ./install.sh)"; fi
fi

# --- 2. CLIs ----------------------------------------------------------------------
for c in orca codex claude agy jq python3; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c: $(command -v "$c")"; else warn "$c not on PATH"; fi
done
if command -v orca >/dev/null 2>&1; then
  st=$(orca status --json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("result",{}).get("runtime",{}).get("state","?"))' 2>/dev/null)
  [ "$st" = ready ] && ok "orca runtime: ready" || warn "orca runtime state: ${st:-unreachable} (run: orca open --json)"
fi

# --- 3. Codex update prompt ---------------------------------------------------------
if command -v brew >/dev/null 2>&1 && brew list --cask codex >/dev/null 2>&1; then
  if brew outdated --cask codex 2>/dev/null | grep -q codex; then
    if [ "$mode" = install ]; then brew upgrade --cask codex >/dev/null 2>&1 && ok "codex upgraded ($(codex --version 2>/dev/null))" || warn "codex upgrade failed — the TUI will show an update prompt that blocks workers"
    else warn "codex outdated → update prompt will block workers (brew upgrade --cask codex)"; fi
  else ok "codex up to date ($(codex --version 2>/dev/null))"; fi
fi

# --- 4. Codex hooks trust --------------------------------------------------------------
hooks="$HOME/.codex/hooks.json"; cfg="$HOME/.codex/config.toml"
if [ -f "$hooks" ] && [ -f "$cfg" ]; then
  declared=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));h=d.get("hooks",d);print(sum(len(g.get("hooks",[g])) for l in h.values() for g in l))' "$hooks" 2>/dev/null)
  declared=${declared:-0}
  trusted=$(grep -c 'trusted_hash' "$cfg" 2>/dev/null || :)
  trusted=${trusted:-0}
  if [ "$declared" -gt "$trusted" ]; then
    warn "codex hooks: $declared declared, $trusted trusted → 'Hooks need review' will block worker-start for codex"
    fix "press '2. Trust all and continue' once in a Codex terminal inside Orca, or use Path B (--dangerously-bypass-hook-trust) per orca-recipes.md"
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
  trust_json claude "$HOME/.claude.json" "$mode" "$@"
  trust_json agy "$HOME/.gemini/antigravity-cli/settings.json" "$mode" "$@"
  while IFS= read -r repo; do
    [ -n "$repo" ] || continue
    if command -v orca >/dev/null 2>&1; then
      orca repo list --json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if any(r.get("path")==sys.argv[1] for r in d.get("result",{}).get("repos",[])) else 1)' "$repo" \
        && ok "orca: $repo registered" || warn "orca: repo not registered (orca repo add --path $repo --json)"
    fi
    if printf '%s' "$repo" | LC_ALL=C grep -q '[^ -~]'; then warn "repo path contains non-ASCII characters — expect trust/prefix bugs; prefer an ASCII path"; fi
  done <<EOF
$repos
EOF
fi

# --- 6. bridge (optional, Pro planner) ------------------------------------------------
if pgrep -f "codex-chatgpt-web.*cli.js serve" >/dev/null 2>&1; then ok "codex-chatgpt-web bridge running (opt-in --planner pro available)"; else info "codex-chatgpt-web bridge not running (opt-in --planner pro disabled; default planner is configured in roles.md)"; fi

if [ "$nwarn" -gt 0 ]; then echo "install.sh: $nwarn warning(s)"; exit 1; fi
echo "done."

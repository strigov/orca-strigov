#!/usr/bin/env bash
# install.sh — install the orca-dev skill for the Codex coordinator and clear the
# known worker-startup blockers for one repository.
#
#   ./install.sh                 # link skill into ~/.codex/skills/orca-dev, check CLIs
#   ./install.sh --repo <path>   # + pre-trust <path> for Claude Code and Antigravity
#   ./install.sh --check <path>  # read-only report, changes nothing
set -u
here="$(cd "$(dirname "$0")" && pwd)"
mode=install; repo=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) repo="$2"; shift 2;;
    --check) mode=check; repo="$2"; shift 2;;
    -h|--help) sed -n '2,8p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$*"; }
warn(){ printf '  \033[33mWARN\033[0m %s\n' "$*"; }
fix(){ printf '  \033[36mFIX\033[0m  %s\n' "$*"; }
[ -n "$repo" ] && repo="$(cd "$repo" && pwd)"

echo "orca-dev install ($mode)"

# --- 1. skill link ------------------------------------------------------------
target="$HOME/.codex/skills/orca-dev"
if [ "$mode" = install ]; then
  mkdir -p "$HOME/.codex/skills"
  if [ -L "$target" ] || [ -e "$target" ]; then rm -rf "$target"; fi
  ln -s "$here/skills/orca-dev" "$target" && ok "skill linked: $target -> $here/skills/orca-dev"
else
  [ -e "$target" ] && ok "skill present: $target" || warn "skill not installed (run ./install.sh)"
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
  declared=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));h=d.get("hooks",d);print(sum(len(g.get("hooks",[g])) for l in h.values() for g in l))' "$hooks" 2>/dev/null || echo 0)
  trusted=$(grep -c 'trusted_hash' "$cfg" 2>/dev/null || echo 0)
  if [ "${declared:-0}" -gt "${trusted:-0}" ]; then
    warn "codex hooks: $declared declared, $trusted trusted → 'Hooks need review' will block worker-start for codex"
    fix "press '2. Trust all and continue' once in a Codex terminal inside Orca, or use Path B (--dangerously-bypass-hook-trust) per orca-recipes.md"
  else ok "codex hooks trusted ($trusted/$declared)"; fi
fi
grep -q '^model = "chatgpt-web/pro"' "$cfg" 2>/dev/null && warn "codex default model is chatgpt-web/pro — every protocol launch must pass an explicit --model (roles.md does)"

# --- 5. per-repo trust ----------------------------------------------------------------
if [ -n "$repo" ]; then
  cj="$HOME/.claude.json"
  if [ -f "$cj" ]; then
    if python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));sys.exit(0 if d.get("projects",{}).get(sys.argv[2],{}).get("hasTrustDialogAccepted") else 1)' "$cj" "$repo"; then
      ok "claude: $repo trusted"
    elif [ "$mode" = install ]; then
      python3 - "$cj" "$repo" <<'PY' && ok "claude: trust set for $repo"
import json,sys
p,repo=sys.argv[1],sys.argv[2]; d=json.load(open(p))
d.setdefault("projects",{}).setdefault(repo,{})["hasTrustDialogAccepted"]=True
json.dump(d,open(p,"w"),indent=2,ensure_ascii=False)
PY
    else warn "claude: $repo not trusted → trust dialog will block the worker"; fi
  fi
  ag="$HOME/.gemini/antigravity-cli/settings.json"
  if [ -f "$ag" ]; then
    if python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));sys.exit(0 if sys.argv[2] in d.get("trustedWorkspaces",[]) else 1)' "$ag" "$repo"; then
      ok "agy: $repo trusted"
    elif [ "$mode" = install ]; then
      python3 - "$ag" "$repo" <<'PY' && ok "agy: trust set for $repo"
import json,sys
p,repo=sys.argv[1],sys.argv[2]; d=json.load(open(p))
d.setdefault("trustedWorkspaces",[]).append(repo)
json.dump(d,open(p,"w"),indent=2,ensure_ascii=False)
PY
    else warn "agy: $repo not in trustedWorkspaces → trust prompt will block the worker"; fi
  fi
  if command -v orca >/dev/null 2>&1; then
    orca repo list --json 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if any(r.get("path")==sys.argv[1] for r in d.get("result",{}).get("repos",[])) else 1)' "$repo" \
      && ok "orca: repo registered" || warn "orca: repo not registered (orca repo add --path $repo --json)"
  fi
  if printf '%s' "$repo" | LC_ALL=C grep -q '[^ -~]'; then warn "repo path contains non-ASCII characters — expect trust/prefix bugs; prefer an ASCII path"; fi
fi

# --- 6. bridge (optional, Pro planner) ------------------------------------------------
if pgrep -f "codex-chatgpt-web.*cli.js serve" >/dev/null 2>&1; then ok "codex-chatgpt-web bridge running (Pro planner available)"; else warn "codex-chatgpt-web bridge not running → planning profile 'standard'"; fi

echo "done."

# Pro (`chatgpt-web/pro`) bridge — incidents and operation

Read only when the bridge planner is explicitly opted in. The role facts (when `pro` is
selected, its fallback and the explicit `--model` rule) stay in [../roles.md](../roles.md).

- Runs through the `codex-chatgpt-web` bridge (ChatGPT Temporary Chat + tunnel-backed tool calls). One planning turn observed at 9–27 minutes. Bridge cap: 5 concurrent browser turns — the planner is always the only one.
- **Windows (bridge 4.0.8, observed 2026-09-02):** Pro's tool calls run through `cmd.exe /d /c`, not PowerShell. The model writes bash-isms (`\|` alternation, `^|` pipes, `$(...)`) that cmd rejects, so a file-heavy task degrades into dozens of failed or fragmentary `findstr` calls; large files also come back truncated over the tunnel. That fills the Codex context, Codex starts a compaction, the bridge runs the compaction as a browser turn ("remote compact task"), and that turn is fragile — seen failing with `ChatGPT ended the turn with 'Something went wrong'` and then `ChatGPT web login is expired or the Temporary Chat surface is unavailable` while the doctor stayed `ready`. Only the cmd.exe multiplier is Windows-specific; the tunnel's per-message cap (`maxMessageChars≈78k`) and the fragile browser-side compaction are properties of the bridge on every platform. Consequence everywhere, worst on Windows: use Pro for **plan writing only** (a short, mostly generative turn — 9 tool calls in the macOS smoke); never for reviews of large plans or any role that must read many files. A `remote compact task` failure is an availability failure → one retry in a fresh terminal, then fallback to `astra`.
- Failure modes seen: `turn_token invalid, expired, or revoked` mid-turn; ChatGPT DOM drift. Both are availability failures → **one retry in a FRESH terminal** (a new Codex thread = a new Temporary Chat; the same terminal would reuse the retained chat that already contains the failure, and the worker then gives up before its first command — observed 2026-09-01), then fall back to the default profile and tell the user.
- Mechanism of the token failure (bridge 4.0.7, upstream issue miuuyy/codex-chatgpt-web#274): the bridge marks the browser turn completed while the ChatGPT model is still in its tool loop; every later tool claim is rejected. It is triggered by long runs of `codex_tool_inventory` discovery calls between real tool calls — the model hunting for an `orca` tool that does not exist. The prompt templates therefore say explicitly that `orca` is a shell command; keep that line when editing a template. Direct shell/patch calls without discovery chains stayed inside the safe window in every test (single call, 4 sequential calls, resumed thread, `ultra`).
- Telling the two apart: `grep 'valid=false' ~/Library/Application\ Support/Codex\ Web\ GPT/logs/launcher.jsonl` (Windows: `Select-String valid=false "$env:APPDATA\Codex Web GPT\logs\launcher.jsonl"`) shows the rejected claims with their `retiredTurn`; a worker report claiming the token was rejected "before the first command" with no `valid=false` line at that time is the model giving up, not the bridge.

## Preflight (orca-recipes.md §7)

When the user explicitly chooses `--planner pro`:

```bash
pgrep -f "codex-chatgpt-web.*cli.js serve" >/dev/null && echo bridge-up || echo bridge-down
# optional, ~2 s: full self-check of the bridge (browser login, proxy, tunnel, connector)
V=$(ls -d ~/.codex-chatgpt-web/versions/*-darwin-arm64 2>/dev/null | tail -1)
[ -n "$V" ] && "$V/runtime/bun" "$V/app/cli.js" status | tail -1   # → "Doctor result: ready"
```

On Windows (PowerShell):

```powershell
$up = @(Get-CimInstance Win32_Process -Filter "Name='bun.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'codex-chatgpt-web.*cli\.js serve' }).Count -gt 0
if ($up) { 'bridge-up' } else { 'bridge-down' }
$V = (Get-ChildItem "$HOME\.codex-chatgpt-web\versions" -Directory -ErrorAction SilentlyContinue | Where-Object Name -like '*-win32-*' | Sort-Object Name | Select-Object -Last 1).FullName
if ($V) { pwsh -NoProfile -Command "Remove-Item Env:CODEX_HOME -ErrorAction SilentlyContinue; & '$V\runtime\bun.exe' '$V\app\cli.js' status | Select-Object -Last 1" }
```

Bridge down or doctor not `ready` → fall back to the default `astra` profile.


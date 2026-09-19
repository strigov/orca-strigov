# Codex and Claude Code hosts

Version 1.1 shares the three skills, worker roles, C6 validator and C8 state
machine. Only plugin loading and provider-session behavior differ. Antigravity
remains a worker, not a supported coordinator host.

| Host | Manifest / hook selection | Binding |
| --- | --- | --- |
| Codex | `plugin.json` → `extensions.com.openai.hooks` → `hooks/codex.json` | `CODEX_THREAD_ID`; existing `.sessions/<id>.json` paths retained |
| Claude Code | `.claude-plugin/plugin.json`; auto-discovered `hooks/hooks.json` | explicit hook `session_id`, `host: claude`; `.sessions/claude/<id>.json` |

`.codex-plugin/plugin.json` remains present for metadata compatibility. The
portable manifest is required: its OpenAI extension replaces default hook
discovery, so Codex does not execute the Claude hooks as a second guard. The
Claude manifest does not redundantly declare the default hooks file. Package all
three manifests and keep their versions aligned. The archive builder updates
all three together.

Codex uses the existing POSIX/native Windows commands. Claude uses Node.js 18+
exec-form arguments to avoid shell interpretation of plugin paths. The adapter
selects Python on POSIX and native PowerShell on Windows; it never installs a
dependency or disables execution policy. Failed runtime launch blocks Stop and
covered editing tools only for a bound coordinator; workers and subagents are
exempt, while unbound sessions and diagnostic tools receive a diagnostic without
a denial. Installing Node, enabling hooks and trusting their commands remain
explicit setup operations.

Codex exposes `Interrupt`, which records a user pause. Claude does not: user
interruption skips Stop. An open Claude turn followed by another real user prompt
therefore produces an `unreconciled_turn` hold, without claiming what caused the
missing Stop. The coordinator must read the user's current intent before explicit
resume. Compaction cannot clear this hold. A status-only response does not
authorize dispatch. The adapter never restarts an agent or writes a fake receipt.

This is bounded continuation, not a guarantee against provider shutdown, context
loss, budget exhaustion or arbitrary shell writes. Synthetic integration cases
do not establish live multi-model acceptance. Keep the disposable two-phase
smoke in [the installation guide](install-plugin.md#smoke-check-before-relying-on-it)
as a separate operational check. Earlier evidence in `plugin-validation.md` is
unchanged and does not certify the new adapter.

Provider contracts used for this implementation:

- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins): portable manifest and explicit hook override.
- [Claude plugin reference](https://code.claude.com/docs/en/plugins-reference): default hook discovery and plugin paths.
- [Claude hooks](https://code.claude.com/docs/en/hooks): exec-form arguments, session identity and interruption behavior.

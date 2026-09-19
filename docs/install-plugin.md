# Install and migrate to the Orca Strigov plugin

> [!CAUTION]
> **Mandatory: remove the native Orca skills before enabling this plugin.**
> Remove the old `orca-cli`, `orchestration` and any standalone `orca-dev` from
> active skill discovery. Do not load both instruction stacks. Keep the three
> replacements inside `orca-strigov`, Orca itself, its CLI and its runtime hooks.
> Follow [the removal checklist](#remove-the-instruction-conflict-not-the-runtime) first.

This repository is a Codex and Claude Code plugin root, not a marketplace.
Install the **whole folder**: `plugin.json`, `.codex-plugin/plugin.json`,
`.claude-plugin/plugin.json`, all three `skills/`, `hooks/`, `bin/` and
their companion files. Copying just `orca-dev/SKILL.md` is not an installation.
The release ZIP is `orca-strigov-<version>.zip`; its single root is
`orca-strigov/`, matching the manifest name. Source changes are not published or
installed merely because this repository was edited.

## Install from the maintained marketplaces

Complete the mandatory removal checklist first. Codex CLI 0.155.0 or newer is
the tested packaging baseline; it must support portable `plugin.json` and its
OpenAI hook override. Do not remove that manifest or fall back to the Claude
default hooks in an older Codex. Claude Code 2.1.278 is the tested baseline;
its hooks additionally require Node.js 18+ on PATH. No dependency is installed
automatically. Worker CLIs and platform prerequisites still apply.

For Codex:

```sh
codex plugin marketplace add https://github.com/strigov/strigov-codex-plugins.git
codex plugin add orca-strigov@strigov-codex-plugins
```

If a marketplace with that name is already configured locally, do not add a
second conflicting source: use the existing catalog, or explicitly migrate its
registration. Creating a public repository does not change a local registration.

For Claude Code:

```text
/plugin marketplace add https://github.com/strigov/strigov-cc-plugins.git
/plugin install orca-strigov@strigov-cc-plugins
```

An HTTPS catalog entry does not make a private source public: GitHub access is
required while the plugin source is private. Review/enable the plugin hooks in
the chosen host and start a fresh session inside Orca. Use `$orca-dev <task>` in
Codex, or `/orca-strigov:orca-dev <task>` in Claude Code. Do not simultaneously
activate another development coordinator (for example superpowers-strigov-ver)
for the same objective; its pipeline cannot own the same work alongside Orca.

The shared protocol and host differences are in [host-adapters.md](host-adapters.md).

## Initial personal installation

Use Codex's `plugin-creator` skill to register the complete local plugin in your
personal marketplace. A concrete request to Codex is:

> Install the complete Orca Strigov plugin from <absolute checkout or extracted
> folder> into my personal marketplace, using plugin-creator. Preserve its
> manifest, three skills, hooks and helpers. Do not recreate a standalone
> orca-dev link. Show existing duplicate skills before changing them. Do not
> disable hook trust or remove Orca's runtime integration hooks.

The following is the underlying CLI flow, to run **only when installation is
authorized**, not as a repository test. It needs the bundled `plugin-creator`
scripts from your Codex installation:

1. Inspect the destination and personal marketplace first. For an existing
   marketplace use `python3 <plugin-creator>/scripts/read_marketplace_name.py`;
   stop on an invalid name. If `~/plugins/orca-strigov` or its marketplace entry
   already exists, use the update flow below, not `--force` over unknown files.
2. For a new entry run
   `python3 <plugin-creator>/scripts/create_basic_plugin.py orca-strigov --with-marketplace`.
   This creates `~/plugins/orca-strigov` and registers `./plugins/orca-strigov`
   in `~/.agents/plugins/marketplace.json`. On Windows these paths are under
   your user profile; use `python` if that is the installed executable.
3. Copy/extract the complete plugin bundle into that newly created plugin
   directory, replacing the generated **scaffold**, not an unrelated plugin.
   In particular replace its placeholder manifest with this bundle's manifest.
   Keep both hidden host manifests, root `plugin.json` and both hook configs.
4. Validate it with
   `python3 <plugin-creator>/scripts/validate_plugin.py <absolute-plugin-directory>`.
   Read the actual marketplace name, then run
   `codex plugin add orca-strigov@<that-marketplace-name>`.
5. Review and explicitly trust the plugin's commands in Codex, and start a new
   Codex thread inside Orca. Check that all three plugin skills are available.

Do **not** run `codex plugin marketplace add` for the default personal
marketplace: it is discovered implicitly. For an explicitly chosen non-default
marketplace, register that marketplace root with `codex plugin marketplace add
<root>` first, then install using its verified name. The repository root itself
has no marketplace catalog and cannot be passed off as one. `codex plugin
install <path>` is not a command in the verified CLI (0.155.0).

## Remove the instruction conflict, not the runtime

Before enabling the plugin, inspect the effective host skill catalog and the
exact entries under `.agents/skills/`, `.codex/skills/`, `.claude/skills/`, project-local skill
folders and other enabled plugins. **Remove the old `orchestration`, `orca-cli`
and standalone `orca-dev` entries from active discovery. This is mandatory:
do not enable the plugin while they remain discoverable.** For a filesystem
entry, remove the old entry after preserving
its backup outside discovery; for skills supplied by another plugin, disable
that conflicting provider. Do not delete the replacements inside `orca-strigov`.
A backup within a scanned skills directory can still be discovered: store it
elsewhere. Preserve
the original bytes and link targets for rollback. Do not recursively delete a
shared skills directory or follow a symlink to its source.

The bundled replacements contain the full baseline references, not stubs that
fetch the old instructions. Optional native device, Linear and environment
skills are not orchestration prerequisites and need not be deleted. If you
remove them, their specialized integrations are not promised by these three
skills. Recheck duplicates after an Orca integration update: it may restore
its skill stubs.

Keep Orca installed, its CLI available and orchestration enabled. Keep Orca's
existing hooks, terminal identity, Dispatch capability delivery, messaging and
readiness integration. The plugin's hooks add role/continuation checks; they do
not replace Orca's runtime transport. Do not replace `~/.codex/hooks.json` with
this plugin's hooks file. Do not run the coordinator with hook-trust bypass to
avoid reviewing the new commands.

## Prerequisites and safe checks

`install.sh` / `install.ps1` now check the plugin source, possible duplicate skill
entries and prerequisites. They do **not** register the plugin or create old
skill links by default. `--check <repo>` / `-Check <repo>` is read-only.
`--repo <repo>` / `-Repo <repo>` explicitly grants Claude/Antigravity trust for
that repository and its worktrees; it changes their trust files, not plugin
registration. No CLI upgrades or hook-trust changes are automatic.

Legacy-only link installation is still available behind `--legacy-skill` /
`-LegacySkill`, with its old compatibility semantics. Do not use it alongside
the plugin: it restores a duplicate and does not install this plugin's hooks.
Plugin helpers resolve relative to the **loaded plugin**, ignoring stale
`ORCA_DEV_HOME` and old skill junctions.

## Update and rollback

For an existing authorized local installation, read its marketplace name and
confirm that the entry points to the plugin source being updated. Preserve a
copy of the previous complete version. Update the whole bundle together, run
the plugin validator, then use the bundled
`update_plugin_cachebuster.py <plugin-directory>` (default cachebuster) and
`codex plugin add orca-strigov@<verified-marketplace-name>`. Start a new thread;
an existing coordinator cannot be assumed to have reloaded all instructions.
Never hand-edit marketplace/config files to bypass a failed install.

To roll back, disable this plugin, restore the recorded prior version/skill
entries, and start a new thread. Do not re-enable both instruction stacks at
once. Preserve `.superpowers/sdd` evidence and existing worker assignments;
installation changes do not authorize cancelling live work.

## Smoke check before relying on it

Use a disposable Git repository and a bounded task with two phases. Confirm:
three skills resolve from one plugin; a new implementation binds the main
session before work; the coordinator dispatches rather than edits source;
worker sessions follow their live assignment; after phase one it advances to
phase two; resume/compaction restores the role; a status question and explicit
user pause work; final Stop requires completion evidence. Inspect the actual
hook result and immutable C6/C8 artifacts. A directory/JSON validator is not
this end-to-end test. Current evidence and unrun checks are listed in
[plugin-validation.md](plugin-validation.md).

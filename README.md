<p align="center">
  <strong>English</strong> · <a href="README.ru.md">Русский</a>
</p>

<p align="center">
  <img src="assets/readme/hero.svg" width="100%" alt="orca-strigov — from a clear spec to reviewed code. Specify, build, verify, review, commit.">
</p>

<p align="center">
  <strong>Codex + Claude Code</strong> &nbsp; / &nbsp; Native Orca orchestration &nbsp; / &nbsp; Standalone skills
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> · <a href="#how-it-works">Workflow</a> · <a href="#the-team">Models</a> · <a href="#reference">Reference</a>
</p>

# Your task. A coordinated team. Reviewed code.

**orca-strigov** is a standalone development skill for Codex and Claude Code that turns a development request into a supervised workflow in [Orca](https://orca.dev). A coordinator assigns work to agents, runs project checks, and sends changes through two sequential reviews before committing.

You describe the result. The `orca-dev` skill handles the spec, plan, implementation phases, review rounds, and handoffs.

| What you get | How it works |
|---|---|
| **A shared definition of done** | Larger tasks start with a spec and acceptance criteria that you approve. |
| **Checks after implementation** | The coordinator inspects the diff and runs the verification commands. |
| **Two review perspectives** | Opus checks the requirements; Astra checks code quality. |
| **Visible progress** | Completed phases become Git commits; the final report maps results to acceptance criteria. |
| **Bounded retries** | Fix rounds have limits, model fallbacks are announced, and unresolved decisions return to you. |

## Quick start

### 1. Install for your agent

With **Python 3.9+** and **Git**, clone the repository and install either or both variants:

```sh
git clone https://github.com/strigov/orca-strigov.git
cd orca-strigov
python3 skills/orca-dev/scripts/install.py --agent codex --agent claude
```

Use just one `--agent` option if you only need one variant. Installation copies a self-contained skill; it does not require a running Orca instance or change project trust.

| Agent | Install location | Invocation |
|---|---|---|
| Codex | `~/.codex/skills/orca-dev` (or `$CODEX_HOME/skills/orca-dev` when set) | `$orca-dev` |
| Claude Code | `~/.claude/skills/orca-dev` | `/orca-dev` |

**Updates:** rerun the install command from the updated source. Recognized installations are replaced, including edits inside shipped files; keep your customizations elsewhere before updating. Symlinks, unrecognized destination folders and copies holding files or symlinks the new version does not ship are refused, so nothing of yours is lost silently. The installer prints the final path and does not install a second copy in `~/.agents/skills`.

<details>
<summary><strong>Prefer a ready-made download?</strong></summary>

[GitHub Releases](https://github.com/strigov/orca-strigov/releases) provide separate `orca-dev-codex-v2.1.0.zip` and `orca-dev-claude-v2.1.0.zip` archives. Extract your archive, then run `python3 orca-dev/scripts/install.py --agent codex` (or `--agent claude`). Each ZIP contains one `orca-dev/` folder with everything it needs.

The [release branch](https://github.com/strigov/orca-strigov/tree/release) contains the same rendered skills under `codex/orca-dev/` and `claude/orca-dev/`, plus the source commit in its README. You can clone it with `git clone --branch release --single-branch https://github.com/strigov/orca-strigov.git`, then run the installer inside the chosen variant.

</details>

### 2. Prepare Orca and the worker CLIs

To **run the workflow**, use a running **Orca 1.4.224+**, Git, and the `codex`, `claude`, and `agy` CLIs with signed-in accounts for the model presets. The Python helpers use only the standard library.

Install Orca's native skills:

```sh
orca skills install --skill orchestration --skill orca-cli --agent codex,claude-code
```

### 3. Check setup and trust your project

From the source checkout, replace the path with the repository **you want agents to work on**:

```sh
python3 skills/orca-dev/scripts/install.py --repo "/absolute/path/to/your-project"
```

The `--repo` mode checks the environment and configures trust for that project and its Git worktrees. Trust settings are written only to `~/.claude.json`, `~/.gemini/antigravity-cli/settings.json`, and `~/.codex/config.toml`. If a settings file is missing, launch the corresponding CLI once and rerun the command. For a downloaded or installed copy, use its own `scripts/install.py` path.

For read-only environment checks, run the installer with no arguments. Add `--check "/absolute/path/to/your-project"` to inspect project trust without changing it. Exit code `1` means there are warnings to inspect. `--check` cannot be combined with installation or bundling.

<details>
<summary><strong>Windows setup</strong></summary>

Use PowerShell and replace `python3` with `py -3`:

```powershell
py -3 skills/orca-dev/scripts/install.py --agent codex --agent claude
py -3 skills/orca-dev/scripts/install.py --repo "C:\path\to\your-project"
```

Use absolute Windows project paths. If `agy` is absent on native Windows, the implementer starts on the Codex Luna fallback. Native Windows `agy` support is unverified.

</details>

### 4. Give the coordinator a task

Start a new agent session after installation. In a **Codex conversation**:

```text
$orca-dev fix the empty-state layout in the task list
```

In a **Claude Code conversation**:

```text
/orca-dev add CSV export to the report page
```

The skill starts **only when explicitly invoked**. An ordinary chat request does not activate it, and dispatched workers follow their own briefs.

## How it works

### Small task → quick path

For an estimated **two code files or fewer**, with no schema, migration, security, or public API change:

```text
Implement → Run checks → Opus review → Astra review → Commit
```

Merging already accepted branches also uses the quick path. No separate spec or plan is created.

### Larger task → spec and phases

```text
Spec → Your approval → Plan → Implementation phases → Final review
                              └ each phase: build → checks → Opus → Astra → commit
```

1. **Agree on the result.** Opus writes the spec; Astra reviews it. You approve the acceptance criteria with «ок» before planning starts.
2. **Break it into phases.** Opus writes a plan; Astra reviews it. Each phase names its criteria and verification commands.
3. **Implement and verify.** An agent works through the phase using the TDD instructions in its brief; the coordinator checks the diff and runs the commands.
4. **Review twice.** Opus checks whether the criteria are met, then Astra reviews code quality. Blocking findings go back for fixes and another review cycle.
5. **Record the result.** Accepted phases are committed. A final Opus review checks the full result against the spec.

**You stay in control.** Commits are automatic after clean review unless you disable autocommit in your task. Ask to see the plan first if you want an additional approval point. Exhausted fix budgets and unresolved blockers lead to a concrete choice: accept, allow another round, or stop.

**Resume a larger task** by invoking `orca-dev` with the plan path or slug. The coordinator uses the plan, Git history, and Orca's run state. Quick-path tasks restart from the beginning.

## The team

The skill ships with fixed model presets. Their source of truth, including exact effort levels and fallback rules, is [roles.md](skills/orca-dev/roles.md).

| Assignment | Default model | Effort / fallback |
|---|---|---|
| Write the spec and plan | Claude `opus` | `xhigh`; revisions at `high` |
| Review the spec and plan | Codex `gpt-6-astra` | `xhigh` |
| Backend and quick-path implementation | Antigravity `gemini-3.8-flash-high` | If unavailable: Codex `gpt-6-luna` at `max` |
| Hard phases and one complexity escalation | Codex `gpt-6.1-sol` | `high` |
| Frontend implementation | Claude `opus` | `high`; `sonnet` at `medium` for phases touching ≤2 files |
| Requirements review and final review | Claude `opus` | `high`; phase review uses `xhigh` for risky work or the last fix round |
| Code quality review | Codex `gpt-6-astra` | `high` |

Review order is always **Opus → Astra**. Reviewers are never swapped automatically. Implementation has up to three fix rounds, then one escalation to Sol with three more; phases that start on Sol have no further escalation.

## One source, two agent variants

Orca owns runs, tasks, dispatches, and worker lifecycle. The skill adds the development workflow, model choices, task briefs, and launch helper. It has **one skill**, **two Python files**, and **no hooks or separate state machine**.

```text
skills/orca-dev/
├── SKILL.md          Coordinator workflow
├── roles.md          Models, effort levels, fallbacks
├── launch.md         Agent startup and terminal lifecycle
├── prompts/          11 task briefs
└── scripts/
    ├── orca_dev.py   Brief rendering, worker startup, readiness, cleanup
    └── install.py    Installation, bundles, environment checks, project trust
tests/                Standard-library unit tests
```

Both variants share the same workflow. Codex includes `agents/openai.yaml` with `allow_implicit_invocation: false`; Claude Code uses `disable-model-invocation: true` in its frontmatter. Neither starts automatically from an ordinary request.

**Build release bundles:** from the source checkout, run `python3 skills/orca-dev/scripts/install.py --bundle /absolute/path/to/output`. The output directory must be absent or empty and outside the source skill folder. This standalone mode creates both variant folders and ZIPs without runtime checks or trust changes.

## Reference

- [Coordinator instructions](skills/orca-dev/SKILL.md) — workflow, approvals, fix budgets, and resume rules.
- [Model presets](skills/orca-dev/roles.md) — exact models, efforts, and alternatives.
- [Launch reference](skills/orca-dev/launch.md) — CLI flags, permission bypass settings, readiness checks, and failure handling.
- [Design and acceptance criteria](docs/specs/2026-10-14-orca-dev-v2-design.md) — the v2 design and v2.1 installation contract, in Russian.

**Tests:** from the source checkout, run `python3 -m unittest discover tests` (Windows: `py -3 -m unittest discover tests`). No running Orca instance is needed. Helper code must remain compatible with Python 3.9.

**Migrating from the plugin:** install the standalone skill, finish any active coordinator task, then remove the old Codex plugin with `codex plugin remove orca-strigov@personal`. Remove only confirmed old copies reported by the installer; installation does not clean them up automatically. Start a new session and check that only one current `orca-dev` is available. Existing v2.0.0 releases remain historical downloads. Older 1.x hooks, receipts, ledgers, and bundled native skills are no longer part of the distribution.

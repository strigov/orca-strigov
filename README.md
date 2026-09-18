<p align="center">
  <a href="./README.md">English</a> · <a href="./README.ru.md">Русский</a>
</p>

<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="orca-dev turns one product request into a plan, implementation, verification, and independent review in Orca">
</p>

<p align="center">
  <a href="https://github.com/strigov/orca-strigov/actions/workflows/runtime.yml"><img alt="Runtime contracts" src="https://github.com/strigov/orca-strigov/actions/workflows/runtime.yml/badge.svg"></a>
  <a href="https://github.com/strigov/orca-strigov/releases/latest"><img alt="Download release ZIP" src="https://img.shields.io/badge/download-release%20ZIP-2A9D8F"></a>
  <img alt="macOS, Linux, and Windows" src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-172033">
</p>

`orca-dev` helps you build software with several AI models inside
[Orca](https://orca.dev). You describe what the product should do. The system turns that request
into a plan, code, tests, and independent reviews — while keeping evidence of what was checked.

It is designed for experienced engineers **and for vibe coders who can describe the desired
result but do not yet know how to judge architecture, tests, or implementation details.** It does
not replace product decisions, but it adds a disciplined engineering process around your request.

## The simple version

You ask:

> Add password reset. It should work by email, expire after 15 minutes, and be understandable on mobile.

Then `orca-dev` coordinates five steps:

1. **Plan** — one AI studies the project and breaks the request into safe stages.
2. **Build** — another AI changes the code and writes tests.
3. **Verify** — real commands run and their complete logs are saved.
4. **Review** — independent AI families look for mistakes and risky assumptions.
5. **Deliver** — accepted work is recorded in Git with traceable evidence.

The key rule is simple: **the AI that writes a change is not the only AI allowed to judge it.**

## Is this for me?

Use `orca-dev` if any of these sound familiar:

- you can explain the feature you want, but are not confident reviewing the generated code;
- a single AI chat often says “done” before everything is actually tested;
- you want several models to work together without writing every prompt yourself;
- you need to know what ran, what passed, and what could not be verified;
- your change spans several files, platforms, or stages and should not be handled as one giant edit.

This is a local development workflow, not a hosted no-code service. Initial setup requires Orca,
Git, and the model CLIs listed below. After setup, ordinary use starts with a plain-language request.

## Install

### 1. Install the required apps

You need:

- [Orca](https://orca.dev) with orchestration enabled;
- Git 2.36 or newer;
- Codex CLI, Claude Code, and Antigravity CLI (`agy`) for the default worker roles;
- macOS/Linux: Bash 3.2+, Python 3.9+ on Linux or Python 3.13+ on macOS;
- native Windows: PowerShell 5.1 or 7. Python is not required by the runtime helpers.

You must sign in to each model CLI once before Orca can use it. The installer checks the setup and
prints clear `OK`, `INFO`, or `WARN` lines. It does not upgrade apps or change unrelated settings.

### 2. Download the correct ZIP

The easiest installation does not require Git commands:

1. Open [the latest release](https://github.com/strigov/orca-strigov/releases/latest).
2. Expand **Assets**.
3. Download **`orca-dev-<version>.zip`**. Do not choose GitHub's automatic “Source code” ZIP.
4. Extract it to a permanent folder such as `Documents/orca-dev`. The installed skill points to
   this folder, so do not delete or move it later without reinstalling.

Each release also contains `orca-dev-<version>.zip.sha256` for download verification.

### 3. Run the installer

macOS, Linux, or WSL2 — open Terminal in the extracted folder:

```bash
./install.sh
./install.sh --repo /path/to/your/project
```

Native Windows — open PowerShell in the extracted folder:

```powershell
.\install.ps1
.\install.ps1 -Repo C:\path\to\your\project
```

Replace the example project path with the folder of the app you want to build. The second command
allows worker CLIs to open that project and its Git worktrees. Run it once for each project.

If a script is blocked on Windows, see the exact PowerShell command and WSL2 alternative in the
[Windows installation guide](docs/install-windows.md).

### 4. Confirm that setup is ready

These checks do not modify anything:

```bash
./install.sh --check /path/to/your/project
```

```powershell
.\install.ps1 -Check C:\path\to\your\project
```

- `OK` — ready;
- `INFO` — useful context, no action required;
- `WARN` — fix this item before relying on the workflow.

The command exits with code `1` while warnings remain, so an incomplete setup cannot look successful.

<details>
<summary><strong>Prefer Git? Install from the repository</strong></summary>

macOS, Linux, or WSL2:

```bash
git clone https://github.com/strigov/orca-strigov.git ~/orca-strigov
cd ~/orca-strigov
./install.sh
./install.sh --repo /path/to/your/project
```

Native Windows:

```powershell
git clone https://github.com/strigov/orca-strigov.git $HOME\orca-strigov
cd $HOME\orca-strigov
.\install.ps1
.\install.ps1 -Repo C:\path\to\your\project
```

Use this route if you want to update with `git pull` or contribute changes.

</details>

## First use

1. Open your app's repository in Orca.
2. Start a **Codex terminal** in that repository.
3. Describe the outcome in normal language:

```text
Implement password reset. It must work by email, expire after 15 minutes,
look good on mobile, include tests, and update the user documentation.
```

Implementation requests activate `orca-dev` automatically. You can also invoke it explicitly:

```text
$orca-dev Implement password reset with tests and documentation.
```

You can watch the worker terminals appear in Orca. The coordinator reports meaningful transitions
and asks you only when a product choice, missing access, or new authorization is required.

### How to write a good request without engineering jargon

Include four things when you know them:

- **who** will use the feature;
- **what** they should be able to do;
- **what must not happen**;
- **how you will recognize success**.

For example: “A customer can export their invoices to CSV. The export must not expose another
customer's data. It should work from the billing page and include a short help note.” The planning
worker translates this into technical steps and surfaces missing decisions.

## What the protocol protects

A passing test is not enough if it ran against the wrong files. A reviewer cannot approve code from
its own model family. A timeout does not prove that a worker stopped. `orca-dev` records source
identity, commands, logs, reviews, and ownership so common multi-agent failures do not disappear
inside a confident summary.

<details>
<summary><strong>Roles and engineering controls</strong></summary>

| Role | Job |
| --- | --- |
| Coordinator | Dispatches work, reconciles evidence, and performs Git bookkeeping |
| Plan writer / reviewer | Produces and independently checks the implementation plan |
| Implementer | Changes code and tests for one authorized phase |
| Gate | Runs declared verification commands and records complete evidence |
| Primary / control reviewer | Reviews the delivery from independent perspectives |
| Diagnosis | Investigates blockers without silently broadening the task |
| Final reviewer | Checks the complete branch before delivery |

Review and fix loops have explicit limits. The exact model, effort, fallback, and independence
rules live only in [`skills/orca-dev/roles.md`](skills/orca-dev/roles.md).

</details>

## Platform status

| Platform | Runtime path | Current repository evidence |
| --- | --- | --- |
| Linux | Bash + Python 3.9+ | Ubuntu integration suite in GitHub Actions |
| macOS | Bash + Python 3.13+ | Native macOS CI scenario and capability checks |
| Windows | Native PowerShell 5.1/7 | Separate Windows PowerShell and `pwsh` integration jobs |
| WSL2 | Linux path inside the distro | Helpers supported; Orca/model CLI availability depends on the environment |

See the [platform contract](docs/runtime-platforms.md) and
[controlled pipeline validation](docs/controlled-pipeline-validation.md) for exact evidence and
known limits. Historical smoke runs are observations, not current certification.

## Release ZIPs

Publishing a GitHub Release triggers [the release workflow](.github/workflows/release.yml), which
attaches:

```text
orca-dev-<version>.zip
orca-dev-<version>.zip.sha256
```

The ZIP contains installers, runtime helpers, skill files, and user documentation. Tests,
historical plans, and experiments stay in the source repository and are deliberately excluded.

## Repository map

```text
skills/orca-dev/       protocol, role matrix, worker prompts, and contracts
bin/                   POSIX and native PowerShell runtime helpers
docs/                  installation, platform, validation, and historical evidence
tests/                 isolated integration and maintenance tests
install.sh             installer for macOS, Linux, and WSL2
install.ps1            installer for native Windows
assets/readme/         GitHub README visuals
```

For protocol internals, start with [`skills/orca-dev/SKILL.md`](skills/orca-dev/SKILL.md).

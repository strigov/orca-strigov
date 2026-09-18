# Runtime platforms and maintenance validation

One semantic contract is implemented by POSIX Python/Bash and native PowerShell.
All C6 changes update both backends and runtime-contracts.md together. Automatic
coordinator activation on implementation requests is preserved; maintenance and
dispatched workers follow AGENTS.md's exception. The entrypoint is smaller, but
coordinator-core is always loaded: no token savings measurement is claimed.

| Platform | Contract | Validation in this maintenance environment |
| --- | --- | --- |
| Linux | Python 3.9+, Bash 3.2+, Git 2.36+ | Ubuntu WSL available; exact versions/results in implementation evidence |
| macOS | Python 3.13+, real `/bin/bash`, Git 2.36+, libproc and host/boot identity | **NOT_RUN**, no native Mac host; CI scenario added |
| Windows | PowerShell 5.1 or 7, Git 2.36+; no Python runtime dependency | Both native shells available; Python 3.11 only drives tests/packaging |

C6 requires `git worktree list --porcelain -z` to parse literal worktree records.
The NUL-delimited mode was added in [Git 2.36 release notes](https://raw.githubusercontent.com/git/git/v2.36.0/Documentation/RelNotes/2.36.0.txt).

Python exposes macOS waitid from 3.13. The runner checks capabilities before its
useful fork and preserves WNOWAIT until its process group is cleared. Darwin
identity uses libproc's microsecond process start time, kernel boot-session UUID
and gethostuuid. Unknown identity fails closed; PID existence alone is insufficient.
Recovery observes a previous group and never signals it. Host/boot mismatch remains
unknown even when a local PID is absent. These are implementation facts, not a
claim of native Darwin acceptance. [Python waitid](https://docs.python.org/3/library/os.html#os.waitid),
[Apple proc_bsdinfo ABI](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/proc_info.h).

Only verified root-owned macOS aliases `/var`, `/tmp`, `/etc` to their exact
`/private` targets are canonicalized. Deeper/user symlinks in owned artifact paths
remain rejected. Normal temporary directories, spaces, Cyrillic, live owners,
zero/nonzero exit, timeout/cancel, surviving descendants, killed supervisor,
idempotent repeated requests and PID-reuse/host/boot fixtures are in the native
CI suite. Windows/WSL results do not replace its macOS job.

## Reproducible maintenance package

Run `python bin/assemble-release.py --repo <absolute-worktree> --base <full-SHA>
--out <new-absolute-output-outside-repo>`. On native Windows invoke the installed
Python executable explicitly. The builder reads Git base blobs and the selected
working files, leaves the real checkout/index unchanged, and emits `files/`,
`changes.patch` and `manifest.json`. Review and use `git apply --check` before
applying. It exports text maintenance changes; changed binary files fail clearly.

Patch syntax is written as UTF-8 bytes with LF, independently of global Git
configuration and Windows text translation. The repository text policy normalizes
CRLF source files without adding a missing final newline. Tests apply the same
patch to LF/CRLF checkouts and compare canonical bytes, including additions and
deletions with missing final newlines. The utility contains no model mapping;
roles.md remains its sole source. `.gitattributes` establishes LF for scripts,
Python, Markdown and YAML; existing PowerShell UTF-8 BOMs are preserved. Tests
verify Git executable modes for Bash entrypoints.

## Evidence levels

`python -B -m unittest discover -s tests -v` is the complete deterministic
integration suite. `ORCA_TEST_SHELL` selects the actual shell;
`ORCA_TEST_ARTIFACTS` retains full owned fixture artifacts. Installer tests use
ORCA_DEV_TEST_HOME and verify that real user settings are unchanged; they never
replace HOME, USERPROFILE or CODEX_HOME. CI uploads environment and command logs.
Directed tests precede one integrated run per available platform; unchanged full
suites are repeated only for a concrete failure, source change or required replay.

Synthetic lifecycle fixtures are explicitly labeled. The maintenance worker
uses real Orca lifecycle for its own task, while live C6 workflow acceptance is
coordinated separately. No prepared state or fixture is described as a live run.

## C7 waiter validation — 2026-09-19

This targeted maintenance check ran on native macOS (Darwin), `/bin/bash`
3.2.57 and Python 3.14.6. It does not replace the earlier C3–C6 platform evidence.

| Exact command | Result |
| --- | --- |
| `python3 -B -m unittest discover -s tests -p test_worker_wait.py -v` | PASS, 11 tests, including shared positive/negative subcases |
| `python3 -B -m unittest discover -s tests -p test_release_archive.py -v` | PASS, 3 tests |
| `/bin/bash -n bin/wait-worker-event` | PASS, exit 0 |
| `python3 /Users/strigov/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/orca-dev` | PASS, `Skill is valid!` |
| `git diff --check` | PASS, exit 0 |

The waiter fixtures use a finite synthetic CLI in owned temporary directories,
never a real Orca inbox. They cover whole mixed FIFO batches, raw receipt bytes,
silent keepalives/empty waits, one-shot coordinator-authorized acknowledgment,
scoped paginated health checks, stale/no-action continuation, exit/attention,
malformed evidence, disconnects, nonzero exits and refusal to overwrite receipts.
The selected CLI's live guide and `orchestration check --help` were read; this
does not constitute a live delivery test or a measured token-savings benchmark.

Native Windows PowerShell 5.1/7: **NOT_RUN** (neither shell is available on this
host). The native port uses the same fixture scenarios through the existing
Windows CI matrix. Linux: **NOT_RUN** for this change. Full repository suite and
live worker lifecycle: **NOT_RUN**; only the directed checks above were run.

Changed files for this maintenance change:

- Runtime: `bin/wait-worker-event`, `bin/lib/wait_worker_event.py`,
  `bin/wait-worker-event.ps1`.
- Skill: `skills/orca-dev/SKILL.md`, `coordinator-core.md`, `orca-recipes.md`,
  `runtime-contracts.md` in that same directory.
- Packaging/tests: `bin/build-release.py`, `tests/test_release_archive.py`,
  `tests/test_worker_wait.py`, `tests/fixtures/orca_wait_cli.py`.
- Documentation: `docs/install-windows.md`, `docs/runtime-platforms.md`.

The local installed skill is already a symlink to this checkout, so no installer,
global hook/configuration change, worker launch, commit or push was performed.

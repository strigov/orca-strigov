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

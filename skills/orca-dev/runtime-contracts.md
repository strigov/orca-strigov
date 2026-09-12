# Runtime contracts

## C3 — one local command owner

`bin/run-check run SPEC_JSON` blocks until exit/interruption. Native Windows uses
`bin/run-check.ps1` with the same positional arguments; it needs PowerShell 5.1
or 7 on Windows 10+, not Python. Bash uses Python 3 stdlib. Resolve these paths
from the current checkout or a process-only `ORCA_DEV_HOME`.

Create the plan workspace with the existing `sdd-workspace` entry point first.
Write a UTF-8 JSON file (not interpolated shell code) with this shape:

```json
{
  "schema_version": 1,
  "run_id": "unit-unique-attempt",
  "owner": {"kind": "local", "id": "caller-unique-id"},
  "cwd": "/absolute/repo",
  "command": "exact shell command, including newlines and Unicode",
  "shell": "/absolute/path/to/bash",
  "run_dir": "/absolute/repo/.superpowers/sdd/plan/checks/unit-unique-attempt",
  "timeout_seconds": 120,
  "cancel_grace_seconds": 2,
  "no_progress_seconds": 30,
  "progress_file": null,
  "resource_key": null
}
```

Windows paths and shell must be absolute too; choose `powershell.exe` or
`pwsh.exe`. POSIX supports `bash -c` / `sh -c`. `run_id` is 1–100 ASCII letters,
digits, `_` or `-`, starting with a letter or digit. An Orca owner is exactly
`{kind:"orca", orca_run_id, task_id, dispatch_id, terminal_handle}` with values
from the live dispatch; never put a capability in this file. Standalone and
gate calls use a unique local owner. A new command attempt gets a new id.
Duplicate identical specs return the existing observation without a new child;
a mismatch or an incomplete initial binding fails closed. Owner metadata binds
the local run; it is not an authentication boundary against another process
running as the same OS user.

Artifacts in the exclusive `checks/<run_id>/` directory:

| Artifact | Meaning |
|---|---|
| `request.json` | Bound spec with exact command, cwd, shell, owner and policy |
| `stdout.log`, `stderr.log` | Full streams written as received, without an in-memory output accumulator |
| `status.json` | Atomically replaced observation, including supervisor PID/start identity, tree, timestamps, duration, diagnostic counters and log paths |
| `cancel.json` | Owner's durable stop request |
| `result.json` | Atomic final record; actual command `exit_code` or null, reason, `cleanup_verified`, `logs_complete` |

The command's own buffering still applies; cross-stream ordering is not exact.
Stdin is closed (`/dev/null` or `NUL`). PowerShell preserves the final native
exit status and a failed final PowerShell operation. No successful outer shell
exit substitutes for a missing/unknown result. `run` and `wait` return the
command code for a confirmed `exited` record, 124 for `interrupted`, 125 for
running/unknown/invalid operations. POSIX signal exits map to 128 + signal.
Inspect the JSON as well as the return code: a command can itself exit 124/125.

`wait RUN_DIR [WAIT_SECONDS]` waits for completion or a **new** diagnostic event
(default 60 seconds); zero reads the current observation. It is a read-only
observation, not a transfer of ownership. `cancel RUN_DIR OWNER_JSON` takes a
file containing exactly the bound owner object and writes a request, returning
0 only for receipt. The owner must then wait for completion and inspect cleanup.
Use this interface from the same owning worker. The coordinator receives that
worker's significant diagnosis/result rather than becoming a second observer.

States are `waiting-resource`, `running`, `exited`, `interrupted`, `unknown`.
`stalled` is only a diagnostic flag. A small (at most 4096-byte) optional UTF-8
`progress_file` carries a counter/stage; changed content resets the diagnostic
interval. Without it, meaningful progress is `unknown`: log output is only
`output_activity`, PID existence only liveness. A no-progress threshold produces
one diagnostic event until the next progress change; it never kills a process
or frees its resource. A missing progress file is not evidence of progress.

Deadline includes time waiting for the resource. `timeout_seconds: null` means
explicitly no deadline, as for legacy gate commands; new expensive checks need
a finite policy in their plan. `no_progress_seconds: null` disables that
diagnostic. Nonnegative finite seconds are accepted. Cancellation/deadline
requests stop, permits `cancel_grace_seconds`, then forcibly stops only the
owned tree and verifies cleanup (up to two further seconds). POSIX sends TERM,
then KILL to its private process group. Windows publishes `cancel.json` (also
available as `ORCA_CHECK_CANCEL_FILE` to a cooperative command), then terminates
the Job Object after grace. It does not guess a console interrupt API.

POSIX records the group before allowing the command to execute and pins the
leader PID until cleanup; a live group after supervisor death remains locked.
Linux recovery verifies boot/start-tick identity and group membership, including
live grandchildren, rather than testing only the supervisor PID. Exited zombies
cannot use the resource. If start identity is unavailable on a POSIX host,
recovery remains unknown/locked; it is not inferred from an old timestamp.
Normal foreground completion still checks the group. Commands deliberately
escaping the POSIX group are outside this local process-group contract.

Windows creates the command inside a named Job Object using the OS job-list
creation attribute, before it runs, with kill-on-last-handle-close and no
breakaway. Helpers are hidden. Start timestamps distinguish reused PIDs. On
owner loss, observers never invent the lost command's exit code or complete
logs; the job must be proven empty/destroyed before a stale lock is reclaimed.
Unverifiable ownership/tree state preserves the lock. No cleanup traverses an
artifact symlink or junction, and the runner never recursively deletes run data.

One optional `resource_key` serializes the declared heavy local resource across
the repository's two worktrees. Its lock key hashes the canonical Git common
directory plus the resource name, in local user temp storage. It is not a
distributed lock, writer lock, queue, or daemon. No key means no resource
serialization; the existing one-writer-per-worktree rule still applies. Locks
are exclusive, bound to run/owner, and never expire by age. Recovery requires
positive owner-exit and whole-tree cleanup evidence; missing or malformed
evidence preserves the lock. Do not manually remove an unknown lock to retry.

Both verify-gate entry points create unique HEAD/BASE runs in the existing plan
workspace, keeping the legacy invocation, verdict lines and exit meanings.
They classify only confirmed exits, reading at most 64 KiB / 200 trailing lines
per stream; displayed failure tails remain bounded. Reports include log paths.
Unknown BASE trees retain their worktree for diagnosis. No snapshot/evidence
reuse is implemented by C3.

The owner normally blocks in one shell call. If its harness requires a command
terminal, use the same runner there and the current, verified Orca
`terminal wait --terminal <handle> --for exit --timeout-ms ...` interface for
that terminal. This is not an arbitrary PID API. Read `orca skills get
orchestration` from the live executable for worker lifecycle; settlement uses
`orchestration check --wait`, never a new scheduler, monitoring agent or model
timer. Keep heartbeat/ask/check/worker_done obligations from the live preamble.
After a diagnostic event, use one bounded diagnosis and the recorded policy;
silence alone grants neither cancellation nor a replacement writer.

Behavior checks use `python -B -m unittest discover -s tests -p test_runner.py`
on Windows (PS5.1 by default). Run the same command separately with a
process-only `ORCA_TEST_SHELL` pointing to `pwsh.exe` for required PS7 coverage;
each shell's module has its own three-minute bound. POSIX uses `python3` and
the actual Bash entry point. Test helpers use Python only as a driver and put
all synthetic children under a parent watchdog; they never run installation
fixtures or change user configuration.

# C7 — worker event waiter

Part of [runtime-contracts.md](../runtime-contracts.md); load only when the index says so.

## C7 — worker event waiter

`bin/wait-worker-event REQUEST_JSON` (native Windows: `wait-worker-event.ps1`)
keeps empty coordinator inbox waits inside one process. POSIX uses Python stdlib;
Windows uses PowerShell 5.1/7 without Python. It does not supervise test processes
or replace C3, C6, worker heartbeats, launch readiness or lifecycle acceptance.

Write this UTF-8 request in the existing plan workspace:

```json
{
  "schema_version": 1,
  "orca_argv": ["/absolute/path/to/the-selected-orca"],
  "run_id": "<actual Run>",
  "dispatch_ids": ["<awaited Dispatch>"],
  "output_dir": "/absolute/plan-workspace/wait-<fresh-attempt>",
  "terminal": null,
  "ack_delivery_id": null
}
```

Use the same executable that provided the live orchestration reference, with no
fallback or guessed executable. `orca_argv` is an argv prefix, never shell code.
IDs come from real receipts. Omit/null `terminal` in the coordinator's own Orca
terminal; outside it, name that coordinator's actual handle. `dispatch_ids` is
the nonempty unique set currently awaited, excluding old retained terminals.
The absolute output leaf must be new, with an existing parent inside the plan
workspace. Reuse refuses rather than overwriting an earlier receipt. Only one
inbox consumer may run for this coordinator Run.

The helper issues `check --run ... --wait --types "worker_done,escalation,question"
--timeout-ms 540000 --json`. It saves each invocation's exact stdout in
`NNNNNN-check.json` and stderr/keepalive output in `NNNNNN-check.stderr.log`;
fleet calls use `NNNNNN-worker-list.*`. `request.json` retains original request
bytes. It does not merge streams, parse only the last line of pretty JSON, or
rewrite receipts. An invalid receipt or nonzero CLI exit returns immediately,
with the evidence path; no blind retry after an ambiguous mutation.

Empty timed-out responses renew silently. After three, enumerate
`worker-list --run ... --include-remote --limit 100 --json`, following every
cursor and verifying the scope, count and unique Dispatch IDs. For awaited
Dispatches, return attention on `exited`, `attention.requiresAction:true` or a
non-`none` nextAction. Live and stale-only/no-action observations keep waiting;
missing Dispatches, incomplete projections or paging errors need diagnosis.
This is a local diagnostic result, never a fabricated Orca lifecycle message.
Unverifiable evidence never proves process death or authorizes another writer.
Fleet receipts here are Run-scoped diagnostics, not C6's complete all-Run fleet.

Stdout contains one JSON line: `schema_version`, `event`, `run_id`, `receipt`,
`output_dir`, plus `delivery_id`, attention `dispatch_ids`, or error `reason`.
Exit 0 = `delivery`, 2 = `attention`, 1 = `error` (early request errors may omit
paths/Run). Read all fleet pages from the output directory for attention. A
Delivery returns in full even when it contains older heartbeat/status messages;
the wake filter cannot discard FIFO mail. No automatic acknowledgment of new
messages, replies, `nextAction` execution, stop, release or retry is performed.

Only after processing an entire Delivery through the existing C6/ownership
rules may the coordinator set `ack_delivery_id` in a new request. It is sent on
the first `check` only, so acknowledgment and the next wait stay together without
discarding a returned batch. On transport error, retain the raw response and
follow live Orca mutation recovery; never assume the acknowledgment failed.

Synthetic shared behavior fixtures: `python3 -B -m unittest discover -s tests
-p test_worker_wait.py -v`; Windows uses `python` and `ORCA_TEST_SHELL` selecting
each native PowerShell. The fixtures launch only a finite local fake CLI and
write in owned temporary directories; they never access real Orca or settings.

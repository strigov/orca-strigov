# Long-wait probe

- Command: `time orca orchestration check --wait --types status --timeout-ms 300000 --json`
- Wall-clock time reported by `time`: `5:00.14 total`
- Exit code: `0`
- Completion: the command completed on its own after its configured 300,000 ms wait.
- Tool harness: the process was not killed and did not time out in the tool harness; there was no harness timeout message.

## JSON output

```json
{
  "id": "68b40c28-7ea4-4974-b5e6-2da20424bce1",
  "ok": true,
  "result": {
    "runId": "run_b3ecea3efaa9",
    "dispatchId": "ctx_300f8ef6d352",
    "messages": [],
    "count": 0,
    "timedOut": true,
    "cancelled": false,
    "connectionLost": false,
    "mutation": {
      "requestId": "e6a9b95e-21f8-402e-8004-5bd93f87a620",
      "replayed": false
    }
  },
  "_meta": {
    "runtimeId": "f55a52de-f97b-4827-8d74-cc7485d77a3f"
  }
}
```

During the wait, the CLI also emitted periodic keepalive JSON objects such as:

```json
{"_keepalive":true,"_heartbeat":true,"elapsedMs":285023,"deadlineMs":300000}
```

"""C7 coordinator inbox waiter. Only Orca check and scoped worker-list calls."""
import json
from pathlib import Path
import subprocess
import sys

WAIT_MS = 540000
WAKE_TYPES = "worker_done,escalation,question"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def text(value):
    return isinstance(value, str) and bool(value.strip())


class Waiter:
    def __init__(self, request_path):
        raw = Path(request_path).read_bytes()
        self.spec = s = json.loads(raw.decode("utf-8-sig"))
        require(isinstance(s, dict) and type(s.get("schema_version")) is int and
                s["schema_version"] == 1, "invalid request schema")
        require(isinstance(s.get("orca_argv"), list) and s["orca_argv"] and
                all(text(v) for v in s["orca_argv"]), "orca_argv must name the selected CLI")
        require(text(s.get("run_id")), "run_id is required")
        require(isinstance(s.get("dispatch_ids"), list) and s["dispatch_ids"] and
                all(text(v) for v in s["dispatch_ids"]) and
                len(set(s["dispatch_ids"])) == len(s["dispatch_ids"]), "dispatch_ids must be unique and nonempty")
        for key in ("terminal", "ack_delivery_id"):
            require(s.get(key) is None or text(s[key]), "invalid " + key)
        require(text(s.get("output_dir")), "output_dir is required")
        self.directory = Path(s["output_dir"])
        require(self.directory.is_absolute(), "output_dir must be absolute")
        # A fresh leaf prevents overwriting receipts, including on interrupted resume.
        self.directory.mkdir()
        (self.directory / "request.json").write_bytes(raw)
        self.sequence = 0
        self.last_receipt = None

    def call(self, arguments):
        self.sequence += 1
        stem = self.directory / ("%06d-%s" % (self.sequence, arguments[1]))
        receipt = stem.with_suffix(".json")
        stderr = stem.with_suffix(".stderr.log")
        self.last_receipt = str(receipt)
        with receipt.open("xb") as out, stderr.open("xb") as err:
            completed = subprocess.run(self.spec["orca_argv"] + arguments,
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        require(completed.returncode == 0, "Orca CLI exit %s; inspect %s" % (completed.returncode, stderr))
        require(receipt.stat().st_size <= 16 * 1024 * 1024, "oversize Orca receipt: " + str(receipt))
        envelope = json.loads(receipt.read_bytes().decode("utf-8-sig"))
        require(isinstance(envelope, dict) and envelope.get("ok") is True and
                isinstance(envelope.get("result"), dict), "Orca error or invalid receipt: " + str(receipt))
        return envelope["result"]

    def fleet(self):
        cursor = None
        cursors = set()
        workers = {}
        total = None
        while True:
            args = ["orchestration", "worker-list", "--run", self.spec["run_id"],
                    "--include-remote", "--limit", "100", "--json"]
            if cursor is not None:
                args += ["--cursor", cursor]
            result = self.call(args)
            scope = result.get("scope") or {}
            require(scope.get("run") == self.spec["run_id"] and
                    scope.get("source") == "flag", "fleet scope mismatch")
            page = result.get("page") or {}
            count = page.get("total")
            require(type(count) is int and count >= 0 and (total is None or count == total),
                    "inconsistent fleet total")
            total = count
            rows = result.get("workers")
            require(isinstance(rows, list), "missing fleet workers")
            for row in rows:
                require(isinstance(row, dict) and text(row.get("dispatchId")), "invalid fleet row")
                require(row["dispatchId"] not in workers, "duplicate fleet dispatch")
                workers[row["dispatchId"]] = row
            require(type(page.get("hasMore")) is bool, "missing fleet pagination")
            if not page["hasMore"]:
                require(len(workers) == total, "incomplete fleet")
                break
            cursor = page.get("nextCursor")
            require(rows and text(cursor) and cursor not in cursors and len(workers) < total,
                    "invalid fleet cursor")
            cursors.add(cursor)
        alerts = []
        for dispatch in self.spec["dispatch_ids"]:
            row = workers.get(dispatch)
            require(row is not None, "expected dispatch missing from fleet: " + dispatch)
            projection = row.get("projection") or {}
            liveness = projection.get("liveness") or {}
            attention = projection.get("attention") or {}
            action = projection.get("nextAction") or {}
            require(liveness.get("verdict") in ("live", "exited", "unverifiable") and
                    type(attention.get("requiresAction")) is bool and text(action.get("kind")),
                    "incomplete fleet projection: " + dispatch)
            if (liveness["verdict"] == "exited" or attention["requiresAction"] or
                    action["kind"] != "none"):
                alerts.append(dispatch)
        return alerts

    def run(self):
        empty = 0
        ack = self.spec.get("ack_delivery_id")
        while True:
            args = ["orchestration", "check", "--run", self.spec["run_id"], "--wait",
                    "--types", WAKE_TYPES, "--timeout-ms", str(WAIT_MS), "--json"]
            if self.spec.get("terminal"):
                args += ["--terminal", self.spec["terminal"]]
            if ack:
                args += ["--ack", ack]
            result = self.call(args)
            # Acknowledgment was explicitly authorized by the coordinator. Never
            # repeat it across empty windows or acknowledge newly delivered mail.
            ack = None
            require(result.get("runId") == self.spec["run_id"], "inbox Run mismatch")
            require(not result.get("cancelled") and not result.get("connectionLost"),
                    "Orca wait cancelled or disconnected")
            messages = result.get("messages")
            require(isinstance(messages, list) and type(result.get("count")) is int and
                    result["count"] == len(messages), "invalid message batch")
            if messages:
                require(text(result.get("deliveryId")), "missing Delivery identity")
                # Whole FIFO batch, even if it contains older statuses/heartbeats.
                return 0, self.output("delivery", delivery_id=result["deliveryId"])
            require(result.get("timedOut") is True and not result.get("deliveryId"),
                    "unexpected empty response; refusing a busy loop")
            empty += 1
            if empty == 3:
                alerts = self.fleet()
                if alerts:
                    return 2, self.output("attention", dispatch_ids=alerts)
                empty = 0

    def output(self, event, **fields):
        return dict(schema_version=1, event=event, run_id=self.spec["run_id"],
                    receipt=self.last_receipt, output_dir=str(self.directory), **fields)


def main():
    waiter = None
    try:
        require(len(sys.argv) == 2, "usage: wait-worker-event REQUEST_JSON")
        waiter = Waiter(sys.argv[1])
        code, result = waiter.run()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        code = 1
        result = dict(schema_version=1, event="error", reason=str(error))
        if waiter is not None:
            result.update(run_id=waiter.spec["run_id"], receipt=waiter.last_receipt,
                          output_dir=str(waiter.directory))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())

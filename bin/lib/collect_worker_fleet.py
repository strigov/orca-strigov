"""C6 read-only inventory collector; raw receipts never transit a terminal/model."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def text(value):
    return isinstance(value, str) and bool(value.strip())


class Collector:
    def __init__(self, request_path):
        raw = Path(request_path).read_bytes()
        self.spec = s = json.loads(raw.decode("utf-8-sig"))
        require(isinstance(s, dict) and type(s.get("schema_version")) is int and
                s["schema_version"] == 1, "invalid request schema")
        require(isinstance(s.get("orca_argv"), list) and s["orca_argv"] and
                all(text(v) for v in s["orca_argv"]), "orca_argv must name the selected CLI")
        require(text(s.get("output_dir")), "output_dir is required")
        self.directory = Path(s["output_dir"])
        require(self.directory.is_absolute(), "output_dir must be absolute")
        self.directory.mkdir()  # Exclusive fresh leaf; never overwrite an old receipt.
        (self.directory / "request.json").write_bytes(raw)
        self.receipt = None
        # The identity-less marker prevents the CLI from guessing a sibling's
        # active pane after removing the inherited coordinator identity. This
        # child only lists workers; never use this environment for lifecycle verbs.
        self.env = dict(os.environ)
        for name in ("ORCA_TERMINAL_HANDLE", "ORCA_PANE_KEY"):
            self.env.pop(name, None)
        self.env["ORCA_STRUCTURED_SESSION"] = "1"

    def run(self):
        refs = []
        cursor = None
        cursors, dispatches, receipts = set(), set(), set()
        total = runtime = None
        while True:
            stem = self.directory / ("%06d-worker-list" % (len(refs) + 1))
            self.receipt = str(stem.with_suffix(".json"))
            stderr = stem.with_suffix(".stderr.log")
            args = ["orchestration", "worker-list", "--limit", "100", "--json"]
            if cursor is not None:
                args += ["--cursor", cursor]
            with open(self.receipt, "xb") as out, stderr.open("xb") as err:
                completed = subprocess.run(self.spec["orca_argv"] + args, env=self.env,
                                           stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            require(completed.returncode == 0, "Orca CLI exit %s; inspect %s" % (completed.returncode, stderr))
            require(Path(self.receipt).stat().st_size <= 16 * 1024 * 1024, "oversize Orca receipt")
            raw = Path(self.receipt).read_bytes()
            envelope = json.loads(raw.decode("utf-8-sig"))
            require(isinstance(envelope, dict) and envelope.get("ok") is True and
                    isinstance(envelope.get("result"), dict), "Orca error or invalid receipt")
            identity = envelope.get("id")
            require(text(identity) and identity not in receipts, "missing or duplicate receipt id")
            receipts.add(identity)
            observed_runtime = (envelope.get("_meta") or {}).get("runtimeId")
            require(text(observed_runtime) and (runtime is None or runtime == observed_runtime),
                    "missing or changed Orca runtime")
            runtime = observed_runtime
            result = envelope["result"]
            scope = result.get("scope") or {}
            require(scope.get("source") == "all" and scope.get("run") is None,
                    "fleet scope is not all Runs; stop, do not create a terminal or rewrite scope")
            require(not result.get("partialHostErrors"), "partial fleet observation")
            page = result.get("page") or {}
            count = page.get("total")
            require(type(count) is int and count >= 0 and (total is None or total == count),
                    "inconsistent fleet total")
            total = count
            require(type(page.get("limit")) is int and page["limit"] == 100, "unexpected fleet page limit")
            rows = result.get("workers")
            require(isinstance(rows, list) and len(rows) <= 100, "invalid fleet workers")
            for row in rows:
                require(isinstance(row, dict) and text(row.get("dispatchId")), "invalid fleet row")
                require(row["dispatchId"] not in dispatches, "duplicate fleet dispatch")
                dispatches.add(row["dispatchId"])
            refs.append(dict(path=self.receipt, sha256=hashlib.sha256(raw).hexdigest(), cursor=cursor))
            require(type(page.get("hasMore")) is bool, "missing fleet pagination")
            cursor = page.get("nextCursor")
            if not page["hasMore"]:
                require(cursor is None and len(dispatches) == total, "incomplete fleet")
                break
            require(rows and len(dispatches) < total and text(cursor) and cursor not in cursors,
                    "invalid fleet cursor")
            cursors.add(cursor)
        manifest = self.directory / "fleet.json"
        with manifest.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(dict(schema_version=1, fleet=refs, runtime_id=runtime,
                           worker_count=total, page_count=len(refs)), stream, ensure_ascii=False)
            stream.write("\n")
        return dict(schema_version=1, event="collected", fleet_file=str(manifest),
                    output_dir=str(self.directory), worker_count=total, page_count=len(refs))


def main():
    collector = None
    try:
        require(len(sys.argv) == 2, "usage: collect-worker-fleet REQUEST_JSON")
        collector = Collector(sys.argv[1])
        result, code = collector.run(), 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        result, code = dict(schema_version=1, event="error", reason=str(error)), 1
        if collector is not None:
            result.update(receipt=collector.receipt, output_dir=str(collector.directory))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())

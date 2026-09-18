"""Synthetic CLI only: consume a finite response list inside an owned fixture."""
import json
from pathlib import Path
import sys
import time

scenario, journal = map(Path, sys.argv[1:3])
arguments = sys.argv[3:]
index = len(journal.read_text(encoding="utf-8").splitlines()) if journal.exists() else 0
with journal.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(arguments, ensure_ascii=False) + "\n")
steps = json.loads(scenario.read_text(encoding="utf-8"))
if index >= len(steps) or arguments[:2] != ["orchestration", steps[index]["command"]]:
    sys.stderr.write("unexpected CLI invocation\n")
    sys.exit(90)
step = steps[index]
sys.stderr.write('{"_keepalive":true,"_heartbeat":true}\n')
sys.stderr.flush()
time.sleep(step.get("delay", 0))
raw = step.get("raw", json.dumps(step.get("response"), ensure_ascii=False, indent=2) + "\r\n")
encoded = raw.encode("utf-8")
(journal.parent / ("emitted-%06d.bin" % (index + 1))).write_bytes(encoded)
sys.stdout.buffer.write(encoded)
sys.exit(step.get("exit", 0))

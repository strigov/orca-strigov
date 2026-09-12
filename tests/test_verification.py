"""C4 behavior on real files, tools and owned short commands; <=3min/module."""
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

from support import VerificationFixture, WINDOWS, read_json, write_json


class VerificationTests(unittest.TestCase):
    def setUp(self): self.fx = VerificationFixture()
    def tearDown(self): self.fx.close()

    def test_snapshot_raw_bytes_dirty_index_untracked_and_declared_inputs(self):
        f = self.fx; root = f.git.root
        initial = f.snapshot(); self.assertTrue(initial["valid"], initial)
        path = root / "tracked.txt"
        path.write_bytes(b"different\r\n")
        dirty = f.snapshot(); self.assertNotEqual(initial["snapshot_id"], dirty["snapshot_id"])
        self.assertEqual(dirty["snapshot_id"], f.snapshot()["snapshot_id"])
        f.git.git("add", "tracked.txt")
        staged = f.snapshot(); self.assertNotEqual(dirty["snapshot_id"], staged["snapshot_id"])
        # Raw line endings differ even when Git's normalized blob is identical.
        path.write_bytes(b"different\n")
        self.assertNotEqual(staged["snapshot_id"], f.snapshot()["snapshot_id"])
        p = root / "новый file.txt"; p.write_bytes(b"one")
        untracked = f.snapshot(); p.rename(root / "renamed.txt")
        renamed = f.snapshot(); self.assertNotEqual(untracked["snapshot_id"], renamed["snapshot_id"])
        path.unlink(); self.assertNotEqual(renamed["snapshot_id"], f.snapshot()["snapshot_id"])
        (root / ".gitignore").write_text("ignored-input/\n", encoding="utf-8")
        ignored = root / "ignored-input"; ignored.mkdir(); data = ignored / "data"; data.write_bytes(b"a")
        declared = f.snapshot(inputs=[str(ignored)]); undeclared = f.snapshot()
        data.write_bytes(b"b")
        self.assertEqual(undeclared["snapshot_id"], f.snapshot()["snapshot_id"])
        self.assertNotEqual(declared["snapshot_id"], f.snapshot(inputs=[str(ignored)])["snapshot_id"])
        self.assertFalse(f.snapshot(inputs=[str(root / "absent")])["valid"])

    def test_service_artifacts_excluded_but_tracked_sources_never_hidden(self):
        f=self.fx; before=f.snapshot()
        (f.workspace / "mutable.log").write_text("service output")
        self.assertEqual(before["snapshot_id"], f.snapshot()["snapshot_id"])
        tracked=f.workspace / "real-source.txt"; tracked.write_text("source")
        f.git.git("add", "-f", str(tracked))
        first=f.snapshot(); tracked.write_text("changed source")
        self.assertNotEqual(first["snapshot_id"], f.snapshot()["snapshot_id"])

    def test_matching_evidence_skips_execution_and_binds_origin(self):
        f=self.fx; counter, code=f.counter_code()
        rc, first=f.verified_run(code=code, declaration={"hermetic": True})
        self.assertEqual(rc,0,first); self.assertTrue(first["evidence"]["reusable"],first)
        index=f.git.root/".git/index"; before=index.read_bytes()
        tracked=f.git.root/"tracked.txt"; stamp=tracked.stat()
        os.utime(tracked, ns=(stamp.st_atime_ns, stamp.st_mtime_ns+2_000_000_000))
        f.git.git("update-index", "--refresh")
        self.assertNotEqual(before,index.read_bytes(),"real Git stat-cache refresh required")
        rc, second=f.verified_run(code=code, declaration={"hermetic": True})
        self.assertEqual(rc,0,second); self.assertEqual(counter.read_text(),"1")
        self.assertEqual(second["evidence"]["origin_run_id"],first["run_id"])
        self.assertEqual(f.helper("validate-evidence", Path(second["run_dir"])/"result.json")[0],0)

    def test_changed_snapshot_definition_environment_tool_and_base_reject_reuse(self):
        f=self.fx; counter, code=f.counter_code()
        env_name="ORCA_TEST_C4_VALUE"; previous=os.environ.get(env_name); os.environ[env_name]="a"
        declaration={"hermetic":True,"environment":[env_name, {"tool":sys.executable,"version_args":["--version"]}]}
        try:
            rc, first=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,first)
            (f.git.root/"tracked.txt").write_bytes(b"changed")
            rc, changed=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,changed)
            os.environ[env_name]="b"
            rc, env=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,env)
            rc, definition=f.verified_run(code=code+"; print('new definition')",declaration=declaration); self.assertEqual(rc,0,definition)
            prov=dict(kind="BASE",base_sha="a"*40,preparation="git-worktree-add-detach",linked_dependencies=[])
            rc, base=f.verified_run(code=code,declaration=declaration,provenance=prov); self.assertEqual(rc,125,base)
            for result in (changed,env,definition,base): self.assertIsNone(result["evidence"]["origin_run_id"])
            self.assertEqual(counter.read_text(),"5")
            unknown=dict(declaration,environment=[{"tool":"orca-definitely-missing-tool", "version_args":["--version"]}])
            rc, tool=f.verified_run(code=code,declaration=unknown)
            self.assertEqual(rc,125,tool); self.assertFalse(tool["evidence"]["valid"])
        finally:
            if previous is None: os.environ.pop(env_name,None)
            else: os.environ[env_name]=previous

    def test_nonhermetic_and_required_replay_execute_physically(self):
        f=self.fx; counter,code=f.counter_code()
        for declaration in ({}, {}, {"hermetic":True,"independent_replay":True}, {"hermetic":True,"independent_replay":True}):
            rc,r=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,r)
            self.assertIsNone(r["evidence"]["origin_run_id"])
        self.assertEqual(counter.read_text(),"4")
        self.assertEqual(r["evidence"]["repeat_reason"],"required-independent-replay")

    def test_changed_executable_bytes_reject_reuse(self):
        f=self.fx; counter,code=f.counter_code(); tool=f.base/("tool.exe" if WINDOWS else "tool")
        if WINDOWS: shutil.copyfile(sys.executable,tool)
        else: tool.write_text("#!/bin/sh\nprintf 'version-one\\n'\n"); tool.chmod(0o755)
        declaration={"hermetic":True,"environment":[{"tool":str(tool),"version_args":[] if WINDOWS else ["--version"]}]}
        rc,first=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,first)
        self.assertTrue(all(t["version"] for t in first["evidence"]["environment"]["tools"]))
        with tool.open("ab") as stream: stream.write(b"\n# changed executable bytes\n")
        rc,second=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,second)
        self.assertIsNone(second["evidence"]["origin_run_id"]); self.assertEqual(counter.read_text(),"2")

    def test_mutation_and_detectable_restore_never_pass(self):
        f=self.fx; path=f.git.root/"tracked.txt"
        for restore in (False,True):
            path.write_bytes(b"baseline\n")
            code=("from pathlib import Path; import os; p=Path('tracked.txt'); s=p.stat(); b=p.read_bytes(); p.write_bytes(b'write')")
            if restore: code+="; p.write_bytes(b); os.utime(p,ns=(s.st_atime_ns,s.st_mtime_ns))"
            rc,r=f.verified_run(code=code,declaration={"hermetic":True})
            self.assertEqual(rc,125,r); self.assertEqual(r["exit_code"],0)
            self.assertIn("input-mutation",r["evidence"]["invalidation_reasons"])

    def test_corrupt_logs_or_record_cannot_be_accepted_or_reused(self):
        f=self.fx; counter,code=f.counter_code()
        rc,first=f.verified_run(code=code,declaration={"hermetic":True}); self.assertEqual(rc,0,first)
        result=Path(first["run_dir"])/"result.json"
        Path(first["stdout_log"]).write_bytes(b"broken log")
        self.assertNotEqual(f.helper("validate-evidence",result)[0],0)
        rc,second=f.verified_run(code=code,declaration={"hermetic":True}); self.assertEqual(rc,0,second)
        self.assertEqual(counter.read_text(),"2")
        second["exit_code"]=7; path=Path(second["run_dir"])/"result.json"; write_json(path,second)
        self.assertNotEqual(f.helper("validate-evidence",path)[0],0)

    def test_phase_checkpoint_legacy_parser_and_unsupported_objects(self):
        f=self.fx; plan=f.base/"plan.md"; out=f.base/"parsed.json"
        plan.write_text('''---
verify: ["echo top", 'echo other'] # legacy flow
phases:
  - id: Ф1
    verify: []
  - id: Ф2
    verify:
      - | # literal
        echo first
        echo second
      - 'echo quoted # literal' # comment
      - {"id":"final", "command":"echo final", "checkpoint":"final"}
---
''',encoding="utf-8")
        def parse(phase, checkpoint):
            r=f.helper("parse",plan,out,phase,checkpoint); self.assertEqual(r[0],0,r)
            return read_json(out) if WINDOWS else [json.loads(v) for v in out.read_bytes().split(b"\0") if v]
        self.assertEqual(parse("Ф1","final"),[])
        commands=parse("Ф2","directed"); self.assertEqual(len(commands),2)
        self.assertEqual(commands[0]["command"],"echo first\necho second")
        self.assertEqual(len(parse("Ф2","final")),3)
        self.assertNotEqual(f.helper("parse",plan,out,"missing","final")[0],0)
        plan.write_text('---\nverify:\n  - {"command":"echo unsafe", "unknown":true}\n---\n',encoding="utf-8")
        self.assertNotEqual(f.helper("parse",plan,out,"","final")[0],0)

    def test_gate_reuse_replay_mutation_and_legacy_verdict_lines(self):
        f=self.fx; counter, code=f.counter_code()
        declaration={"id":"count","command":f.python(code),"hermetic":True,"timeout_seconds":9}
        for count in (1,1):
            rc,out,err=f.gate([declaration]); self.assertEqual(rc,0,(out,err)); self.assertEqual(out.splitlines()[0],"GATE_OK")
            self.assertEqual(out.splitlines()[1],"verify: 1 cmd(s) | passed: 1 | failed: 0 | inherited: 0 | judgment: 0")
            self.assertEqual(counter.read_text(),str(count)); self.assertIn("evidence:",out)
        declaration["independent_replay"]=True
        rc,out,err=f.gate([declaration]); self.assertEqual(rc,0,(out,err)); self.assertEqual(counter.read_text(),"2")
        rc,out,err=f.gate([f.python("from pathlib import Path; Path('tracked.txt').write_text('mutated')")])
        self.assertEqual(rc,4,(out,err)); self.assertEqual(out.splitlines()[0],"NEEDS_JUDGMENT")


if __name__ == "__main__": unittest.main()

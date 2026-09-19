"""C4 behavior on real files, tools and owned short commands; <=3min/module."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

from support import VerificationFixture, ROOT, WINDOWS, command, read_json, write_json


class VerificationTests(unittest.TestCase):
    def setUp(self): self.fx = VerificationFixture()
    def tearDown(self): self.fx.close()

    def test_snapshot_raw_bytes_dirty_index_untracked_and_declared_inputs(self):
        f = self.fx; root = f.git.root
        prefix = 'from pathlib import Path; import subprocess; root=Path(' + repr(str(root)) + '); '
        ignored = root / "ignored-input"
        # Every intermediate snapshot still runs the public CLI against real bytes.
        steps = [
            ('', []),
            ("(root/'tracked.txt').write_bytes(b'different\\r\\n')", []),
            ('', []),
            ("subprocess.run(['git','add','tracked.txt'],check=True,timeout=5)", []),
            ("(root/'tracked.txt').write_bytes(b'different\\n')", []),
            ("(root/'новый file.txt').write_bytes(b'one')", []),
            ("(root/'новый file.txt').rename(root/'renamed.txt')", []),
            ("(root/'tracked.txt').unlink()", []),
            ("(root/'.gitignore').write_text('ignored-input/\\n',encoding='utf-8'); "
             "(root/'ignored-input').mkdir(); (root/'ignored-input/data').write_bytes(b'a')", [str(ignored)]),
            ('', []),
            ("(root/'ignored-input/data').write_bytes(b'b')", []),
            ('', [str(ignored)]),
            ('', [str(root/'absent')]),
        ]
        captures = f.snapshots([(prefix + prep if prep else '', inputs) for prep, inputs in steps])
        initial, dirty, same, staged, lf, untracked, renamed, deleted, declared, undeclared, hidden, changed, absent = captures
        self.assertTrue(all(s["valid"] for s in captures[:-1]), captures)
        self.assertNotEqual(initial["snapshot_id"], dirty["snapshot_id"])
        self.assertEqual(dirty["snapshot_id"], same["snapshot_id"])
        self.assertNotEqual(dirty["snapshot_id"], staged["snapshot_id"])
        # Raw line endings differ even when Git's normalized blob is identical.
        self.assertNotEqual(staged["snapshot_id"], lf["snapshot_id"])
        self.assertNotEqual(untracked["snapshot_id"], renamed["snapshot_id"])
        self.assertNotEqual(renamed["snapshot_id"], deleted["snapshot_id"])
        self.assertEqual(undeclared["snapshot_id"], hidden["snapshot_id"])
        self.assertNotEqual(declared["snapshot_id"], changed["snapshot_id"])
        self.assertFalse(absent["valid"])

    def test_service_artifacts_excluded_but_tracked_sources_never_hidden(self):
        f=self.fx
        prefix = 'from pathlib import Path; import subprocess; ws=Path(' + repr(str(f.workspace)) + '); '
        before, service, first, changed = f.snapshots([
            ('', []),
            (prefix + "(ws/'mutable.log').write_text('service output')", []),
            (prefix + "p=ws/'real-source.txt'; p.write_text('source'); "
             "subprocess.run(['git','add','-f',str(p)],check=True,timeout=5)", []),
            (prefix + "(ws/'real-source.txt').write_text('changed source')", []),
        ])
        self.assertTrue(all(s['valid'] for s in (before, service, first, changed)))
        self.assertEqual(before["snapshot_id"], service["snapshot_id"])
        self.assertNotEqual(first["snapshot_id"], changed["snapshot_id"])

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
        absent_name="ORCA_TEST_C4_ABSENT"; previous_absent=os.environ.pop(absent_name,None)
        declaration={"hermetic":True,"environment":[env_name, absent_name, {"tool":sys.executable,"version_args":["--version"]}]}
        try:
            rc, first=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,first)
            self.assertEqual(first["evidence"]["environment"]["variables"][absent_name],hashlib.sha256(b"null").hexdigest())
            (f.git.root/"tracked.txt").write_bytes(b"changed")
            rc, changed=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,changed)
            self.assertEqual(first["evidence"]["environment"],changed["evidence"]["environment"])
            os.environ[env_name]="b"
            rc, env=f.verified_run(code=code,declaration=declaration); self.assertEqual(rc,0,env)
            self.assertNotEqual(first["evidence"]["environment"]["fingerprint"],env["evidence"]["environment"]["fingerprint"])
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
            if previous_absent is not None: os.environ[absent_name]=previous_absent

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

    def test_copied_evidence_must_match_sealed_result(self):
        f=self.fx
        rc,negative=f.verified_run(code="raise SystemExit(7)")
        self.assertEqual(rc,7,negative)
        original=Path(negative['run_dir'])/'result.json'; original_bytes=original.read_bytes()
        copied=f.workspace/'copied-result.json'
        # A faithful copy remains valid evidence of the negative outcome.
        write_json(copied,negative)
        reply=f.helper('validate-evidence',copied)
        self.assertEqual(reply[0],0,(reply,negative))
        write_json(copied,dict(negative,exit_code=0))
        self.assertNotEqual(f.helper('validate-evidence',copied)[0],0)
        write_json(copied,dict(negative,duration_seconds=negative['duration_seconds']+0.001))
        self.assertNotEqual(f.helper('validate-evidence',copied)[0],0)
        self.assertEqual(original.read_bytes(),original_bytes)
        if WINDOWS:
            # Deterministic serialization fixture over the completed owned run:
            # fix only its enclosing timestamp and seal, then exercise the live
            # in-memory shape. This fixture is not presented as live evidence.
            quote=lambda value: "'"+str(value).replace("'","''")+"'"
            script=f.workspace/'sealed-timestamp-fixture.ps1'
            script.write_text("$ErrorActionPreference='Stop'\n. "+quote(ROOT/'bin/lib/verification.ps1')+
                "\n$path="+quote(original)+"\n$st=V-Load $path\n"+
                "$st.started_at='2026-09-15T18:30:57.1234560Z'\nV-Save $path $st\n"+
                "V-Save (Join-Path $st.run_dir 'result.sha256') (V-Hash ([IO.File]::ReadAllBytes($path)))\n"+
                "if (-not (V-EvidenceValid $st)) { throw 'literal timestamp differs from sealed JSON' }\n"+
                "$st.exit_code=0\nif (V-EvidenceValid $st) { throw 'changed outcome borrowed the seal' }\n",
                encoding='utf-8-sig')
            rc,out,err=command([f.shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)],f.git.root)
            self.assertEqual(rc,0,(out,err))

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
        outputs = [f.base / ('parsed-' + str(i) + '.json') for i in range(4)]
        results = f.helpers([('parse',(plan,dest,phase,checkpoint),'') for dest,(phase,checkpoint) in zip(outputs,
                            [('Ф1','final'),('Ф2','directed'),('Ф2','final'),('missing','final')])])
        for result in results[:3]: self.assertEqual(result[0],0,result)
        def parsed(path):
            return read_json(path) if WINDOWS else [json.loads(v) for v in path.read_bytes().split(b"\0") if v]
        self.assertEqual(parsed(outputs[0]),[])
        commands=parsed(outputs[1]); self.assertEqual(len(commands),2)
        self.assertEqual(commands[0]["command"],"echo first\necho second")
        self.assertEqual(len(parsed(outputs[2])),3)
        self.assertNotEqual(results[3][0],0)
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

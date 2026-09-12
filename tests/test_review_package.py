"""Full C5 bytes, bounded parts, stale detection and real-index preservation."""
import hashlib
import os
from pathlib import Path
import unittest

from support import VerificationFixture, command, read_json, write_json


class ReviewPackageTests(unittest.TestCase):
    def setUp(self): self.fx=VerificationFixture()
    def tearDown(self): self.fx.close()

    def package(self, head="WORKTREE", output=None, base=None):
        f=self.fx; out=output or f.workspace/"review.diff"
        result=command(f.argv("review-package",base or f.git.base,head,out),f.git.root)
        return result,out,Path(str(out)+".manifest.json")

    def test_complete_untracked_unicode_and_dirty_index_preserved(self):
        f=self.fx; root=f.git.root; index=root/".git/index"
        (root/"tracked.txt").write_bytes(b"staged\n"); f.git.git("add","tracked.txt")
        before=index.read_bytes(); (root/"tracked.txt").write_bytes(b"working\r\n")
        (root/"новый file.txt").write_text("new Unicode body\n",encoding="utf-8")
        (result,out,path)=self.package(); self.assertEqual(result[0],0,result)
        m=read_json(path); self.assertTrue(m["complete"]); self.assertTrue(m["index_preserved"])
        self.assertEqual(before,index.read_bytes()); self.assertIn(b"new Unicode body",out.read_bytes())
        self.assertEqual({f["path"] for f in m["files"]},{"tracked.txt","новый file.txt"})
        self.assertTrue(next(x for x in m["files"] if x["path"]=="новый file.txt")["untracked"])
        self.assertEqual(len(m["parts"]),1); self.assertEqual(Path(m["parts"][0]["path"]),out)
        self.assertEqual(f.helper("validate-package",path)[0],0)
        self.assertTrue(all(x["authorship"]=="unknown" for x in m["files"]))

    def test_stat_cache_refresh_preserves_package_but_semantic_index_change_invalidates(self):
        f=self.fx; root=f.git.root; index=root/".git/index"
        (root/"new file.txt").write_bytes(b"reviewed source\n")
        before=index.read_bytes(); entries=f.git.git("ls-files", "--stage")
        result,_,path=self.package(); self.assertEqual(result[0],0,result)
        self.assertEqual(before,index.read_bytes(),"package must preserve raw real index")
        m=read_json(path); tracked=root/"tracked.txt"; stamp=tracked.stat()
        os.utime(tracked,ns=(stamp.st_atime_ns,stamp.st_mtime_ns+2_000_000_000))
        f.git.git("update-index", "--refresh")
        self.assertNotEqual(before,index.read_bytes(),"refresh must rewrite the stat cache")
        self.assertEqual(entries,f.git.git("ls-files", "--stage"))
        refreshed=f.snapshot(exclusions=m["exclusions"])
        self.assertTrue(refreshed["valid"],refreshed)
        self.assertEqual(m["snapshot_id"],refreshed["snapshot_id"])
        self.assertNotEqual(m["snapshot_after"]["mutation_witness"],refreshed["mutation_witness"])
        self.assertEqual(f.helper("validate-package",path)[0],0)
        # Change only the semantic index mode, keeping working bytes untouched.
        f.git.git("update-index", "--chmod=+x", "tracked.txt")
        self.assertNotEqual(entries,f.git.git("ls-files", "--stage"))
        self.assertNotEqual(m["snapshot_id"],f.snapshot(exclusions=m["exclusions"])["snapshot_id"])
        self.assertNotEqual(f.helper("validate-package",path)[0],0)

    def test_full_multipart_oversize_binary_and_missing_or_stale_parts(self):
        f=self.fx; root=f.git.root
        (root/"large.txt").write_bytes(b"long-line-"*17000+b"\nLAST-TAIL-MARKER\n")
        (root/"binary.bin").write_bytes(bytes(range(256))*10)
        result,out,path=self.package(); self.assertEqual(result[0],0,result)
        m=read_json(path); self.assertGreater(len(m["parts"]),2)
        joined=b"".join(Path(p["path"]).read_bytes() for p in m["parts"])
        self.assertEqual(joined,out.read_bytes()); self.assertIn(b"LAST-TAIL-MARKER",joined)
        self.assertIn(b"GIT binary patch",joined); self.assertGreaterEqual(len(m["limitations"]),2)
        self.assertTrue(all(r["inspection_required"] for r in m["files"]))
        self.assertEqual(f.helper("validate-package",path)[0],0)
        part=Path(m["parts"][-1]["path"]); saved=part.read_bytes(); part.unlink()
        self.assertNotEqual(f.helper("validate-package",path)[0],0)
        part.write_bytes(saved); (root/"large.txt").write_bytes(b"stale source")
        self.assertNotEqual(f.helper("validate-package",path)[0],0)

    def test_real_source_under_superpowers_is_included_and_output_not_self_included(self):
        f=self.fx; source=f.git.root/".superpowers/actual-source.txt"; source.write_text("source outside sdd")
        out=f.git.root/"review-output.diff"
        result,out,path=self.package(output=out); self.assertEqual(result[0],0,result)
        m=read_json(path); self.assertEqual([x["path"] for x in m["files"]],[".superpowers/actual-source.txt"])
        result,_,path=self.package(output=out); self.assertEqual(result[0],0,result)
        self.assertEqual(f.helper("validate-package",path)[0],0)

    def test_empty_range_and_bad_base_preserve_index(self):
        f=self.fx; index=f.git.root/".git/index"; before=index.read_bytes()
        result,out,path=self.package(head=f.git.base)
        self.assertEqual(result[0],1,result); self.assertTrue(result[1].startswith("EMPTY "))
        result,_,_=self.package(base="not-a-real-base")
        self.assertEqual(result[0],2,result); self.assertEqual(before,index.read_bytes())

    def test_git_failure_after_temp_index_and_manifest_tampering(self):
        f=self.fx; root=f.git.root; index=root/".git/index"
        # Force a real output error after the temporary index was populated.
        (root/"tracked.txt").write_text("changed")
        result,out,path=self.package(); self.assertEqual(result[0],0,result)
        before=index.read_bytes(); m=read_json(path); m["base"]="0"*40; write_json(path,m)
        self.assertNotEqual(f.helper("validate-package",path)[0],0)
        # A directory at the literal output path fails after index staging/copy.
        blocked=f.workspace/"output-directory"; blocked.mkdir()
        result,_,error_manifest=self.package(output=blocked)
        self.assertNotEqual(result[0],0,result); self.assertEqual(before,index.read_bytes())
        self.assertFalse(read_json(error_manifest)["complete"])

    def test_receipt_bound_families_contracts_and_ignored_inputs_remain_explicit(self):
        f=self.fx; root=f.git.root; (root/"tracked.txt").write_text("changed")
        ignored=f.workspace/"declared-build-input"; ignored.write_bytes(b"actual ignored input")
        receipt=f.base/"write-receipt.json"
        write_json(receipt,{"result":{"runId":"run-fixture","taskId":"task-fixture","dispatchId":"dispatch-fixture"}})
        binding=dict(files=["tracked.txt"],receipt_path=str(receipt),receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                     run_id="run-fixture",task_id="task-fixture",dispatch_id="dispatch-fixture")
        out=f.workspace/"review.diff"
        write_json(str(out)+".provenance.json",dict(schema_version=1,writes=[dict(binding,family="family-a"),dict(binding,family="family-b")],
                                                  contracts=[dict(id="C-fixture",producer=["tracked.txt"],consumer=["consumer.txt"])],inputs=[str(ignored)]))
        result,out,path=self.package(output=out); self.assertEqual(result[0],0,result)
        m=read_json(path); self.assertEqual(m["files"][0]["author_families"],["family-a","family-b"])
        self.assertEqual(m["files"][0]["authorship"],"requires-family-validation")
        self.assertEqual(m["coverage"]["contracts"][0]["consumer"],["consumer.txt"])
        self.assertEqual(m["declared_inputs"][0]["record"]["sha256"],hashlib.sha256(ignored.read_bytes()).hexdigest())
        self.assertEqual(f.helper("validate-package",path)[0],0)
        receipt.write_bytes(b"changed receipt"); self.assertNotEqual(f.helper("validate-package",path)[0],0)


if __name__ == "__main__": unittest.main()

"""Portable capability fixtures plus native POSIX lifecycle scenarios."""
import copy
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

from support import ROOT, WINDOWS, RunnerFixture, read_json, selected_shell, until

sys.path.insert(0, str(ROOT/'bin/lib'))
import posix_runtime as runtime
import run_check as runner


class CapabilityTests(unittest.TestCase):
    def test_unsupported_version_before_useful_spawn(self):
        with mock.patch.object(runtime.sys, 'platform', 'darwin'), mock.patch.object(runtime.sys, 'version_info', (3,12)), \
             mock.patch.object(runner.os, 'fork', create=True) as fork:
            with self.assertRaisesRegex(ValueError, 'requires Python 3.13'):
                runner.run({})
            fork.assert_not_called()

    @unittest.skipIf(WINDOWS, 'POSIX capability symbols')
    def test_missing_waitid_before_useful_spawn(self):
        with mock.patch.object(runner.os, 'fork') as fork:
            original=os.waitid
            try:
                del os.waitid
                with self.assertRaisesRegex(ValueError, 'missing runner capabilities: waitid'):
                    runner.run({})
                fork.assert_not_called()
            finally: os.waitid=original

    def test_host_boot_pid_reuse_and_unknown_identity(self):
        record=dict(pid=42,start='first',host='H',boot='B')
        with mock.patch.object(runner, 'host_boot', return_value=('H','B')):
            for current,expected in [(record,True),(dict(record,start='reused'),False),(None,None),(False,False)]:
                with mock.patch.object(runner,'identity',return_value=current):
                    self.assertIs(runner.alive(record),expected)
        for pair in [('foreign','B'),('H','other-boot')]:
            with mock.patch.object(runner,'host_boot',return_value=pair), mock.patch.object(runner,'identity',return_value=False):
                self.assertIsNone(runner.alive(record))
                self.assertIsNone(runner.tree_clear(dict(tree=dict(kind='posix-group',pgid=42,leader=record))))


@unittest.skipIf(WINDOWS, 'POSIX native runner; Windows has its own backend suite')
class NativePosixTests(unittest.TestCase):
    def setUp(self): self.f=RunnerFixture(selected_shell())
    def tearDown(self): self.f.close()

    def test_capabilities_live_identity_and_cyrillic_path(self):
        self.assertTrue(runtime.capabilities()['identity'])
        own=runtime.identity(os.getpid());self.assertIs(runner.alive(own),True)
        path,spec=self.f.spec("import time; print('проверка'); time.sleep(.6)")
        renamed=path.with_name('задание с пробелами.json');path.rename(renamed)
        proc=self.f.start(renamed)
        state=until(lambda: read_json(Path(spec['run_dir'])/'status.json'))
        self.assertIs(runner.alive(state['supervisor']),True)
        self.assertEqual(proc.finish()[0],0)

    def test_live_descendant_after_leader_exit(self):
        marker=self.f.base/'descendant.pid'
        leaf="import os,time,pathlib;pathlib.Path("+repr(str(marker))+").write_text(str(os.getpid()));time.sleep(8)"
        # Background child keeps the group alive after its shell leader exits.
        command=self.f.python(leaf)+' & sleep 0.4; exit 0'
        path,spec=self.f.spec(command=command)
        proc=self.f.start(path);pid=int(until(lambda: marker.read_text()))
        self.assertEqual(proc.finish()[0],124)
        result=read_json(Path(spec['run_dir'])/'result.json')
        self.assertEqual(result['reason'],'descendants-after-exit')
        self.assertTrue(result['cleanup_verified'])
        until(lambda: runtime.identity(pid) is False)

    @unittest.skipUnless(sys.platform=='darwin', 'native macOS NOT_RUN on this host')
    def test_darwin_system_temp_alias_and_foreign_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            canonical=Path(tmp).resolve()
            alias=Path('/var')/canonical.relative_to('/private/var') if canonical.is_relative_to('/private/var') else canonical
            self.assertEqual(runner.safe(alias),canonical)
            link=canonical/'foreign';link.symlink_to(canonical,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'symlink'):
                runner.safe(alias/'foreign'/'report.json')


if __name__ == '__main__': unittest.main()

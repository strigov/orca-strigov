"""Installer acceptance is isolated before the first install-mode invocation."""
import os
from pathlib import Path
import unittest

from support import InstallFixture, WINDOWS, command, directory_state, read_json


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.f = InstallFixture()
        self.addCleanup(self.f.close)

    def test_correct_stale_dangling_link_and_worktree_trust(self):
        f = self.f
        old = f.base / 'old target ü'; old.mkdir()
        sentinel = old / 'keep.txt'; sentinel.write_bytes(b'outside link')
        f.link(f.target, old)
        before = directory_state(f.home)
        rc, out, err = f.install(check=True)
        self.assertEqual(rc, 1, (out, err))
        self.assertEqual(directory_state(f.home), before)
        rc, out, err = f.install()
        self.assertIn('skill linked', out, (rc, out, err))
        self.assertEqual(f.target.resolve(), (f.checkout / 'skills/orca-dev').resolve())
        self.assertEqual(sentinel.read_bytes(), b'outside link')
        trusted = read_json(f.home / '.claude.json')
        self.assertEqual(trusted['unrelated'], {'keep': 7})
        self.assertEqual(trusted['projects']['/unrelated'], {'keep': True})
        for p in (f.git.root, f.git.other):
            self.assertTrue(trusted['projects'][str(p).replace('\\','/')]['hasTrustDialogAccepted'])
        agy = read_json(f.home / '.gemini/antigravity-cli/settings.json')
        self.assertEqual(agy['keep'], [1,2])
        self.assertIn('/unrelated', agy['trustedWorkspaces'])
        for p in (f.git.root, f.git.other): self.assertIn(str(p), agy['trustedWorkspaces'])
        if WINDOWS:
            self.assertEqual(Path(read_json(f.env_file)['ORCA_DEV_HOME']), f.checkout)
            self.assertTrue(read_json(f.env_file)['keep'])
        before = directory_state(f.home)
        f.install(check=True)
        self.assertEqual(directory_state(f.home), before)
        f.install()  # Idempotent installation does not rewrite unrelated data.
        self.assertEqual(directory_state(f.home), before)
        # Remove only the owned leaf link, then make a truly dangling link.
        (os.rmdir if WINDOWS else os.unlink)(f.target)
        empty = f.base / 'deleted target'; empty.mkdir()
        f.link(f.target, empty); empty.rmdir()
        before = directory_state(f.home)
        self.assertEqual(f.install(check=True)[0], 1)
        self.assertEqual(directory_state(f.home), before)
        rc, out, err = f.install()
        self.assertIn('skill linked', out, (rc, out, err))
        self.assertEqual(f.target.resolve(), (f.checkout / 'skills/orca-dev').resolve())
        self.assertFalse(empty.exists())
        self.assertEqual(sentinel.read_bytes(), b'outside link')
        # Resolve the installed source and run its sibling binary with no global env change.
        spec, request = f.spec()
        binary = f.target.resolve().parents[1] / 'bin' / ('run-check.ps1' if WINDOWS else 'run-check')
        argv = ([f.shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File']
                if WINDOWS else [f.shell]) + [str(binary), 'run', str(spec)]
        rc, out, err = command(argv, f.git.root, env=f.env)
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(read_json(Path(request['run_dir']) / 'result.json')['exit_code'], 0)

    def test_plain_directory_and_foreign_parent_are_never_removed(self):
        f = self.f
        f.target.mkdir(); (f.target / 'mine').write_bytes(b'preserve')
        setting = f.env_file.read_bytes()
        rc, out, err = f.install()
        self.assertEqual(rc, 1, (out, err))
        self.assertIn('not a link', out)
        self.assertEqual((f.target / 'mine').read_bytes(), b'preserve')
        self.assertEqual(f.env_file.read_bytes(), setting)
        foreign = f.base / 'foreign'; foreign.mkdir()
        (foreign / 'mine').write_bytes(b'foreign')
        alternate = f.base / 'alternate home'; alternate.mkdir()
        f.link(alternate / '.codex', foreign)
        env = dict(f.env, ORCA_DEV_TEST_HOME=str(alternate))
        before = directory_state(foreign)
        rc, out, err = f.install(env=env)
        self.assertEqual(rc, 1, (out, err))
        self.assertIn('refusing write through', out)
        self.assertEqual(directory_state(foreign), before)
        redirected = f.base / 'redirected home'; f.link(redirected, f.home)
        before = directory_state(f.home)
        self.assertEqual(f.install(env=dict(f.env, ORCA_DEV_TEST_HOME=str(redirected)))[0], 2)
        self.assertEqual(directory_state(f.home), before)

    def test_stale_process_is_diagnosed_without_rewriting_configuration(self):
        f = self.f; f.install()
        self.assertEqual(f.target.resolve(), (f.checkout / 'skills/orca-dev').resolve())
        before = directory_state(f.home)
        rc, out, err = f.install(check=True, env=dict(f.env, ORCA_DEV_HOME=str(f.base / 'old checkout')))
        self.assertEqual(rc, 1, (out, err))
        self.assertIn('Process ORCA_DEV_HOME', out)
        self.assertIn('restart', out)
        self.assertIn('User', out)
        self.assertEqual(directory_state(f.home), before)

    def test_required_dependency_missing_is_nonzero_and_read_only(self):
        f = self.f
        empty = f.base / 'empty PATH'; empty.mkdir()
        before = directory_state(f.home)
        rc, out, err = f.install(check=True, env=dict(f.env, PATH=str(empty)))
        self.assertEqual(rc, 1, (out, err))
        self.assertIn('git not on PATH' if WINDOWS else 'python3 not on PATH', out)
        self.assertEqual(directory_state(f.home), before)


if __name__ == '__main__': unittest.main()

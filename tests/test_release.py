"""Reproducible release bytes and patch application across checkout EOL modes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from support import ROOT

spec = importlib.util.spec_from_file_location('assemble_release', ROOT / 'bin/assemble-release.py')
release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_lf_crlf_checkout_and_missing_final_newline(self):
        with tempfile.TemporaryDirectory(prefix='release-') as tmp:
            root = Path(tmp); repo = root / 'source'; repo.mkdir()
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
            def git(*args, cwd=repo):
                p = subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false',
                                    '-c', 'core.hooksPath=', *args], cwd=cwd, env=env, capture_output=True)
                self.assertEqual(p.returncode, 0, (args, p.stdout, p.stderr)); return p.stdout
            git('init', '-q')
            (repo/'file with space.md').write_bytes(b'first\nlast')
            (repo/'delete.md').write_bytes(b'delete without newline')
            (repo/'untouched.ini').write_bytes(b'unchanged\n')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD').decode().strip()
            (repo/'file with space.md').write_bytes(b'first\nchanged last')
            (repo/'delete.md').unlink()
            (repo/'new.md').write_bytes(b'new without newline')
            first = root/'candidate-lf'; release.assemble(repo, base, first)
            (repo/'file with space.md').write_bytes(b'first\r\nchanged last')
            (repo/'untouched.ini').write_bytes(b'unchanged\r\n')
            second = root/'candidate-crlf'; release.assemble(repo, base, second)
            self.assertEqual((first/'changes.patch').read_bytes(), (second/'changes.patch').read_bytes())
            self.assertNotIn(b'\r\n', (first/'changes.patch').read_bytes())
            for eol in ('false', 'true'):
                checkout = root/('checkout-'+eol)
                git('-c', 'core.autocrlf='+eol, 'clone', '-q', '--no-local', str(repo), str(checkout))
                # Checkout configuration is explicit and local to this fixture.
                git('config', 'core.autocrlf', eol, cwd=checkout)
                if eol == 'true':
                    (checkout/'file with space.md').write_bytes(b'first\r\nlast')
                    (checkout/'delete.md').write_bytes(b'delete without newline')
                git('-c', 'core.autocrlf='+eol, 'apply', '--check', str(first/'changes.patch'), cwd=checkout)
                git('-c', 'core.autocrlf='+eol, 'apply', str(first/'changes.patch'), cwd=checkout)
                for name in ('file with space.md', 'new.md'):
                    self.assertEqual(release.canonical(name, (checkout/name).read_bytes()), (first/'files'/name).read_bytes())
                self.assertFalse((checkout/'delete.md').exists())
                self.assertFalse((checkout/'file with space.md').read_bytes().endswith(b'\n'))

    def test_runtime_executable_modes_and_text_policy(self):
        rows = release.git(ROOT, 'ls-files', '--stage', '-z').split(b'\0')
        for row in rows:
            if not row: continue
            meta, raw = row.split(b'\t'); name = raw.decode()
            if name == 'install.sh' or (name.startswith('bin/') and '/' not in name[4:] and '.' not in Path(name).name):
                self.assertTrue(meta.startswith(b'100755 '), name)
                self.assertNotIn(b'\r\n', (ROOT/name).read_bytes(), name)
        self.assertIn('*.py text eol=lf', (ROOT/'.gitattributes').read_text())


if __name__ == '__main__': unittest.main()

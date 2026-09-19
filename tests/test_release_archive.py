import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_release", ROOT / "bin" / "build-release.py")
BUILD_RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_RELEASE)


class ReleaseArchiveTests(unittest.TestCase):
    def test_archive_is_compact_reproducible_and_installable(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "orca-strigov-1.2.3.zip"
            second = Path(tmp) / "copy.zip"
            count, digest, checksum = BUILD_RELEASE.build_release(ROOT, "1.2.3", first)
            BUILD_RELEASE.build_release(ROOT, "1.2.3", second)

            self.assertGreater(count, 20)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertIn(digest, checksum.read_text(encoding="ascii"))

            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                prefix = "orca-strigov/"
                manifest = json.loads(archive.read(prefix + ".codex-plugin/plugin.json"))
                self.assertEqual(manifest['name'], 'orca-strigov')
                self.assertEqual(manifest['version'], '1.2.3')
                for extra in ('plugin.json', '.claude-plugin/plugin.json'):
                    self.assertEqual(json.loads(archive.read(prefix + extra))['version'], '1.2.3')
                for skill in ('orca-dev', 'orchestration', 'orca-cli'):
                    self.assertIn(prefix + 'skills/' + skill + '/SKILL.md', names)
                for bundled in ('hooks/hooks.json', 'hooks/codex.json', 'bin/claude-hook.cjs', 'THIRD_PARTY_NOTICES.md',
                                'bin/coordinator-session', 'bin/coordinator-session.ps1',
                                'bin/lib/coordinator_session.py', 'docs/install-plugin.md'):
                    self.assertIn(prefix + bundled, names)
                self.assertIn(prefix + "README.md", names)
                self.assertIn(prefix + "README.ru.md", names)
                self.assertIn(prefix + "assets/readme/hero.svg", names)
                self.assertIn(prefix + "install.sh", names)
                self.assertIn(prefix + "install.ps1", names)
                self.assertIn(prefix + "skills/orca-dev/SKILL.md", names)
                self.assertIn(prefix + "bin/verify-gate", names)
                self.assertIn(prefix + "bin/collect-worker-fleet", names)
                self.assertIn(prefix + "bin/collect-worker-fleet.ps1", names)
                self.assertIn(prefix + "bin/lib/collect_worker_fleet.py", names)
                self.assertIn(prefix + "bin/wait-worker-event", names)
                self.assertIn(prefix + "bin/wait-worker-event.ps1", names)
                self.assertIn(prefix + "bin/lib/wait_worker_event.py", names)
                self.assertNotIn(prefix + "bin/build-release.py", names)
                self.assertFalse(any(name.endswith("/.DS_Store") for name in names))
                self.assertFalse(any(name.startswith(prefix + "tests/") for name in names))
                self.assertFalse(any(name.startswith(prefix + "docs/plans/") for name in names))
                executables = {
                    "install.sh",
                    "bin/collect-worker-fleet",
                    "bin/coordinator-session",
                    "bin/protocol-state",
                    "bin/review-package",
                    "bin/run-check",
                    "bin/sdd-workspace",
                    "bin/verify-gate",
                    "bin/wait-agent-ready",
                    "bin/wait-worker-event",
                }
                for info in archive.infolist():
                    with self.subTest(path=info.filename):
                        expected = 0o100755 if info.filename[len(prefix):] in executables else 0o100644
                        self.assertEqual(info.create_system, 3)
                        self.assertEqual(info.external_attr >> 16, expected)

    def test_archive_is_identical_without_source_executable_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            files = BUILD_RELEASE.release_files(ROOT)
            for relative in files:
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
                target.chmod(0o600)

            first = root / "without-executable-bits.zip"
            BUILD_RELEASE.build_release(source, "1.2.3", first)
            for relative in files:
                (source / relative).chmod(0o755)
            second = root / "with-executable-bits.zip"
            BUILD_RELEASE.build_release(source, "1.2.3", second)

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_version_rejects_path_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                BUILD_RELEASE.build_release(ROOT, "../bad", Path(tmp) / "bad.zip")


if __name__ == "__main__":
    unittest.main()

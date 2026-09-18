import importlib.util
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
            first = Path(tmp) / "orca-dev-1.2.3.zip"
            second = Path(tmp) / "copy.zip"
            count, digest, checksum = BUILD_RELEASE.build_release(ROOT, "1.2.3", first)
            BUILD_RELEASE.build_release(ROOT, "1.2.3", second)

            self.assertGreater(count, 20)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertIn(digest, checksum.read_text(encoding="ascii"))

            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                prefix = "orca-dev-1.2.3/"
                self.assertIn(prefix + "README.md", names)
                self.assertIn(prefix + "README.ru.md", names)
                self.assertIn(prefix + "assets/readme/hero.svg", names)
                self.assertIn(prefix + "install.sh", names)
                self.assertIn(prefix + "install.ps1", names)
                self.assertIn(prefix + "skills/orca-dev/SKILL.md", names)
                self.assertIn(prefix + "bin/verify-gate", names)
                self.assertNotIn(prefix + "bin/build-release.py", names)
                self.assertFalse(any(name.endswith("/.DS_Store") for name in names))
                self.assertFalse(any(name.startswith(prefix + "tests/") for name in names))
                self.assertFalse(any(name.startswith(prefix + "docs/plans/") for name in names))
                install_mode = archive.getinfo(prefix + "install.sh").external_attr >> 16
                self.assertNotEqual(install_mode & 0o111, 0)

    def test_version_rejects_path_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                BUILD_RELEASE.build_release(ROOT, "../bad", Path(tmp) / "bad.zip")


if __name__ == "__main__":
    unittest.main()

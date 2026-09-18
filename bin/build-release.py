#!/usr/bin/env python3
"""Build the compact end-user ZIP attached to GitHub Releases."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import zipfile


RELEASE_PATHS = (
    Path("README.md"),
    Path("README.ru.md"),
    Path("assets/readme"),
    Path("install.sh"),
    Path("install.ps1"),
    Path("skills/orca-dev"),
    Path("bin/lib"),
    Path("bin/collect-worker-fleet"),
    Path("bin/collect-worker-fleet.ps1"),
    Path("bin/protocol-state"),
    Path("bin/protocol-state.ps1"),
    Path("bin/review-package"),
    Path("bin/review-package.ps1"),
    Path("bin/run-check"),
    Path("bin/run-check.ps1"),
    Path("bin/sdd-workspace"),
    Path("bin/sdd-workspace.ps1"),
    Path("bin/verify-gate"),
    Path("bin/verify-gate.ps1"),
    Path("bin/wait-agent-ready"),
    Path("bin/wait-agent-ready.ps1"),
    Path("bin/wait-worker-event"),
    Path("bin/wait-worker-event.ps1"),
    Path("docs/install-windows.md"),
    Path("docs/runtime-platforms.md"),
    Path("docs/controlled-pipeline-validation.md"),
)
# ZIP permissions are part of the release format, independent of checkout
# permissions (Windows does not expose Unix executable bits).
EXECUTABLE_PATHS = frozenset((
    Path("install.sh"),
    Path("bin/collect-worker-fleet"),
    Path("bin/protocol-state"),
    Path("bin/review-package"),
    Path("bin/run-check"),
    Path("bin/sdd-workspace"),
    Path("bin/verify-gate"),
    Path("bin/wait-agent-ready"),
    Path("bin/wait-worker-event"),
))
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def release_files(repo):
    files = []
    for relative in RELEASE_PATHS:
        source = repo / relative
        if not source.exists():
            raise FileNotFoundError("required release input is missing: " + str(relative))
        if source.is_symlink():
            raise ValueError("release input must not be a symlink: " + str(relative))
        if source.is_file():
            files.append(relative)
            continue
        for root, dirs, names in os.walk(source):
            root_path = Path(root)
            dirs[:] = sorted(name for name in dirs if name != "__pycache__")
            for name in sorted(names):
                path = root_path / name
                if path.is_symlink():
                    raise ValueError("release input must not be a symlink: " + str(path.relative_to(repo)))
                if name == ".DS_Store" or path.suffix in (".pyc", ".pyo"):
                    continue
                files.append(path.relative_to(repo))
    return sorted(set(files), key=lambda item: item.as_posix())


def build_release(repo, version, output):
    repo = repo.resolve()
    output = output.resolve()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("version may contain only letters, digits, dots, dashes, and underscores")
    if output.exists():
        raise FileExistsError("output already exists: " + str(output))
    if repo == output or repo in output.parents:
        raise ValueError("output ZIP must be outside the source checkout")

    files = release_files(repo)
    prefix = "orca-dev-{}/".format(version)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in files:
            source = repo / relative
            info = zipfile.ZipInfo(prefix + relative.as_posix(), ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o755 if relative in EXECUTABLE_PATHS else 0o644
            info.external_attr = (0o100000 | mode) << 16
            archive.writestr(info, source.read_bytes())

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text("{}  {}\n".format(digest, output.name), encoding="ascii")
    return len(files), digest, checksum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    count, digest, checksum = build_release(args.repo, args.version, args.out)
    print("wrote {} files to {}".format(count, args.out.resolve()))
    print("sha256 {}".format(digest))
    print("checksum {}".format(checksum))


if __name__ == "__main__":
    main()

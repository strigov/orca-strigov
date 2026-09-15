#!/usr/bin/env python3
"""Export a local text maintenance candidate and LF patch without touching Git state.

Python 3.9+ and Git are maintenance dependencies, not Windows runtime dependencies.
Git blobs are the base; source files use the repository's explicit LF text policy.
No model mapping, checkout/index writes, commit, installation or network access.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess


def git(repo, *args):
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.check_output(['git', '--no-optional-locks', '-c', 'core.autocrlf=false',
                                    '-c', 'core.quotepath=false', '-C', str(repo), *args], env=env, timeout=30)


def canonical(name, data):
    text = Path(name).suffix in ('.md', '.py', '.sh', '.ps1', '.yml', '.yaml')
    text = text or name in ('.gitattributes', '.gitignore') or (name.startswith('bin/') and not Path(name).suffix)
    return data.replace(b'\r\n', b'\n') if text else data


def quoted(path):
    # Git's C-style quoted UTF-8 paths, including tabs, quotes and non-ASCII.
    return '"' + ''.join(chr(b) if 32 <= b < 127 and b not in (34, 92) else '\\%03o' % b
                         for b in path.encode('utf-8')) + '"'


def emit_patch(originals, candidate, modes):
    chunks = []
    for name in sorted(set(originals) | set(candidate)):
        before, after = originals.get(name), candidate.get(name)
        if before == after: continue
        if any(b'\0' in data for data in (before or b'', after or b'')):
            raise ValueError('binary changes require a Git binary release path: ' + name)
        chunks.append('diff --git ' + quoted('a/' + name) + ' ' + quoted('b/' + name) + '\n')
        if before is None: chunks.append('new file mode ' + modes.get(name, '100644') + '\n')
        if after is None: chunks.append('deleted file mode ' + modes.get(name, '100644') + '\n')
        for line in difflib.unified_diff((before or b'').decode('utf-8').splitlines(keepends=True),
                                        (after or b'').decode('utf-8').splitlines(keepends=True),
                                        fromfile=quoted('a/' + name) if before is not None else '/dev/null',
                                        tofile=quoted('b/' + name) if after is not None else '/dev/null'):
            chunks.append(line)
            if not line.endswith('\n'): chunks.append('\n\\ No newline at end of file\n')
    # write_bytes prevents Windows text-mode newline translation in hunk syntax.
    return ''.join(chunks).encode('utf-8')


def assemble(repo, base, out):
    repo = Path(git(repo, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    out = out.resolve()
    if out == repo or repo in out.parents: raise ValueError('output must be outside source checkout')
    if out.exists(): raise FileExistsError('output must be new: ' + str(out))
    base = git(repo, 'rev-parse', '--verify', base + '^{commit}').decode().strip()
    originals = {}; modes = {}
    for row in git(repo, 'ls-tree', '-r', '-z', base).split(b'\0'):
        if not row: continue
        meta, raw = row.split(b'\t', 1); mode, kind, oid = meta.decode().split(); name = raw.decode('utf-8')
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('unsupported release entry: ' + name)
        modes[name] = mode; originals[name] = git(repo, 'cat-file', 'blob', oid)
    names = {n.decode('utf-8') for n in git(repo, 'ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0') if n}
    candidate = {}
    for name in sorted(names):
        path = repo / name
        if path.is_symlink(): raise ValueError('linked release input: ' + name)
        if path.is_file():
            data = canonical(name, path.read_bytes())
            # A pre-policy checkout may translate unchanged non-policy text.
            # Preserve its base blob instead of emitting an unrelated EOL diff.
            if data.replace(b'\r\n', b'\n') == originals.get(name): data = originals[name]
            candidate[name] = data
    patch = emit_patch(originals, candidate, modes)
    out.mkdir(parents=True)
    for name, data in candidate.items():
        path = out / 'files' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        path.chmod(int(modes.get(name, '100644'), 8) & 0o777)
    (out / 'changes.patch').write_bytes(patch)
    changed = [dict(path=n, mode=modes.get(n, '100644'), deleted=n not in candidate,
                    sha256=hashlib.sha256(candidate[n]).hexdigest() if n in candidate else None)
               for n in sorted(set(originals) | set(candidate)) if originals.get(n) != candidate.get(n)]
    manifest = dict(schema_version=1, base_commit=base, source_head=git(repo, 'rev-parse', 'HEAD').decode().strip(),
                    patch_sha256=hashlib.sha256(patch).hexdigest(), changed=changed, runtime_certification='NOT_CLAIMED')
    (out / 'manifest.json').write_bytes((json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(assemble(args.repo, args.base, args.out), ensure_ascii=False))

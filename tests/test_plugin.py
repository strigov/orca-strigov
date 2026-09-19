"""Plugin structure, local reference closure and extracted-runtime smoke.

No marketplace, user config, real Orca or provider session is changed. The
smoke invokes packaged hooks against an owned Git fixture, not a live LLM.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import zipfile

from support import ROOT, WINDOWS, ProtocolFixture, installation_state, write_json

SPEC = importlib.util.spec_from_file_location('plugin_release', ROOT / 'bin/build-release.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class PluginTests(unittest.TestCase):
    def test_exactly_three_skills_and_cohesive_discovery(self):
        manifest = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], ROOT.name)
        self.assertEqual(manifest['skills'], './skills/')
        self.assertNotIn('hooks', manifest)  # Default hooks/hooks.json discovery.
        expected = {'orca-cli', 'orchestration', 'orca-dev'}
        paths = list((ROOT / 'skills').glob('*/SKILL.md'))
        self.assertEqual({p.parent.name for p in paths}, expected)
        for path in paths:
            text = path.read_text(encoding='utf-8-sig')
            self.assertEqual(re.search(r'^name: (.+)$', text, re.M)[1], path.parent.name)
            self.assertIn('description:', text.split('---', 2)[1])

    def test_reference_closure_and_no_runtime_stock_loader(self):
        for path in (ROOT / 'skills').rglob('*.md'):
            text = path.read_text(encoding='utf-8-sig')
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if ':' in target or target.startswith('#'):
                    continue
                target = target.split('#')[0]
                with self.subTest(path=str(path.relative_to(ROOT)), target=target):
                    self.assertTrue((path.parent / target).is_file(), 'missing bundled reference')
            if path.name != 'upstream.md':  # Provenance contains export commands, not runtime routing.
                self.assertIsNone(re.search(r'^\s*(?:orca|ORCA|"\$ORCA") skills get\b', text, re.M), str(path))
        self.assertEqual(len(list((ROOT / 'skills/orchestration/references').glob('*.md'))), 7)
        self.assertEqual(len(list((ROOT / 'skills/orca-cli/references').glob('*.md'))), 3)

    def test_hook_commands_have_native_windows_and_bounded_execution(self):
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text())['hooks']
        self.assertEqual(set(hooks), {'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop', 'Interrupt'})
        for groups in hooks.values():
            for group in groups:
                for hook in group['hooks']:
                    self.assertEqual(hook['type'], 'command')
                    self.assertIn('${PLUGIN_ROOT}/bin/coordinator-session', hook['command'])
                    self.assertIn('${PLUGIN_ROOT}/bin/coordinator-session.ps1', hook['commandWindows'])
                    self.assertNotIn('bash', hook['commandWindows'])
                    self.assertNotIn('bypass', hook['commandWindows'].lower())
                    self.assertLessEqual(hook['timeout'], 30)
                    self.assertFalse(hook.get('async', False))

    def test_extracted_plugin_hooks_run_without_native_skills(self):
        before = installation_state()
        fixture = ProtocolFixture()
        self.addCleanup(fixture.close)
        with tempfile.TemporaryDirectory(prefix='orca-plugin-') as tmp:
            archive = Path(tmp) / 'bundle.zip'
            BUILDER.build_release(ROOT, '1.0.0', archive)
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(Path(tmp) / 'extracted')
            plugin = Path(tmp) / 'extracted/orca-strigov'
            script = plugin / 'bin' / ('coordinator-session.ps1' if WINDOWS else 'coordinator-session')
            argv = ([fixture.shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
                    if WINDOWS else [fixture.shell, str(script)])
            env = dict(os.environ, CODEX_THREAD_ID='extracted-plugin', ORCA_STRIGOV_WORKER='0',
                       ORCA_DEV_HOME=str(Path(tmp) / 'nonexistent-old-installation'))
            request = Path(tmp) / 'binding.json'
            write_json(request, dict(session_id='extracted-plugin', worktree=str(fixture.git.root),
                                     workspace=str(fixture.workspace), objective='Two authorized phases'))
            bound = subprocess.run(argv + ['bind', str(request)], cwd=fixture.git.root, env=env,
                                   capture_output=True, timeout=30)
            self.assertEqual(bound.returncode, 0, bound.stdout + bound.stderr)
            payload = dict(hook_event_name='Stop', session_id='extracted-plugin', cwd=str(fixture.git.root))
            result = subprocess.run(argv + ['hook'], cwd=fixture.git.root, env=env, capture_output=True,
                                    input=json.dumps(payload).encode(), timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['decision'], 'block')
            self.assertFalse((Path(tmp) / 'nonexistent-old-installation').exists())
        self.assertEqual(installation_state(), before)


if __name__ == '__main__':
    unittest.main()

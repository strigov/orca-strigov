"""Plugin structure, local reference closure and extracted-runtime smoke.

No marketplace, user config, real Orca or provider session is changed. The
smoke invokes packaged hooks against an owned Git fixture, not a live LLM.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
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
        self.assertNotIn('hooks', manifest)  # Portable OpenAI extension owns hooks.
        portable = json.loads((ROOT / 'plugin.json').read_text())
        claude = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        for candidate in (portable, claude):
            for key in ('name', 'version', 'description'):
                self.assertEqual(candidate[key], manifest[key])
        self.assertEqual(portable['extensions']['com.openai']['hooks'], './hooks/codex.json')
        self.assertNotIn('hooks', claude)  # Claude auto-loads only hooks/hooks.json.
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
        hooks = json.loads((ROOT / 'hooks/codex.json').read_text())['hooks']
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

    def test_claude_hooks_use_exec_form_and_native_adapter(self):
        hooks = json.loads((ROOT / 'hooks/hooks.json').read_text())['hooks']
        self.assertEqual(set(hooks), {'SessionStart', 'UserPromptSubmit', 'PreToolUse', 'Stop'})
        for groups in hooks.values():
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0]['hooks']), 1)
            command = groups[0]['hooks'][0]
            self.assertEqual(command['command'], 'node')
            self.assertEqual(command['args'], ['${CLAUDE_PLUGIN_ROOT}/bin/claude-hook.cjs'])
            self.assertNotIn('commandWindows', command)
            self.assertLessEqual(command['timeout'], 30)
        adapter = ROOT / 'bin/claude-hook.cjs'
        code = 'const a=require(process.argv[1]);console.log(JSON.stringify([a.invocation("win32"),a.failure("Stop",true),a.failure("PreToolUse",true,"Write")]));'
        result = subprocess.run(['node', '-e', code, str(adapter)], capture_output=True, timeout=10, check=True)
        windows, stop, edit = json.loads(result.stdout)
        self.assertEqual(windows[0], 'powershell.exe')
        self.assertEqual(windows[1][-3:], ['hook', '--host', 'claude'])
        self.assertFalse(any('bypass' in arg.lower() or 'bash' in arg.lower() for arg in windows[1]))
        self.assertEqual(stop['decision'], 'block')
        self.assertEqual(edit['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_claude_adapter_runtime_failure_blocks_stop_and_edits(self):
        # Keep the adapter executable but remove its runtime from this owned tree.
        fixture = ProtocolFixture()
        self.addCleanup(fixture.close)
        binding = fixture.git.root / '.superpowers/sdd/.sessions/claude/bound.json'
        binding.parent.mkdir(parents=True)
        write_json(binding, {})  # Even a broken binding must not silently bypass recovery.
        with tempfile.TemporaryDirectory(prefix='orca-missing-runtime-') as tmp:
            adapter = Path(tmp) / 'claude-hook.cjs'
            shutil.copyfile(ROOT / 'bin/claude-hook.cjs', adapter)
            for event in ('Stop', 'PreToolUse'):
                payload = dict(hook_event_name=event, session_id='bound', cwd=str(fixture.git.root), tool_name='Write')
                result = subprocess.run(['node', str(adapter)], input=json.dumps(payload).encode(),
                                        env=dict(os.environ, ORCA_STRIGOV_WORKER='0'), capture_output=True, timeout=30, check=True)
                value = json.loads(result.stdout)
                if event == 'Stop':
                    self.assertEqual(value['decision'], 'block')
                else:
                    self.assertEqual(value['hookSpecificOutput']['permissionDecision'], 'deny')
            for fields, worker in (({'session_id': 'unbound'}, '0'), ({'agent_id': 'child'}, '0'), ({}, '1'),
                                   ({'hook_event_name': 'PreToolUse', 'tool_name': 'Read'}, '0')):
                sample = dict(payload, **fields)
                result = subprocess.run(['node', str(adapter)], input=json.dumps(sample).encode(),
                                        env=dict(os.environ, ORCA_STRIGOV_WORKER=worker), capture_output=True, timeout=30, check=True)
                value = json.loads(result.stdout)
                self.assertNotIn('decision', value)
                self.assertNotIn('permissionDecision', value.get('hookSpecificOutput', {}))

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
            write_json(request, dict(host='claude', session_id='claude-extracted', worktree=str(fixture.git.root),
                                     workspace=str(fixture.workspace), objective='Two authorized phases'))
            bound = subprocess.run(argv + ['bind', str(request)], cwd=fixture.git.root, env=env,
                                   capture_output=True, timeout=30)
            self.assertEqual(bound.returncode, 0, bound.stdout + bound.stderr)
            payload['session_id'] = 'claude-extracted'
            result = subprocess.run(['node', str(plugin / 'bin/claude-hook.cjs')], cwd=fixture.git.root,
                                    env=env, capture_output=True, input=json.dumps(payload).encode(), timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('no C6 checkpoint', json.loads(result.stdout)['reason'])
            self.assertFalse((Path(tmp) / 'nonexistent-old-installation').exists())
        self.assertEqual(installation_state(), before)


if __name__ == '__main__':
    unittest.main()

"""C8 shared native/POSIX tests: real C6 + isolated Git, no real Orca/LLM.

Hook stdin is synthetic and never sent to a provider. The Windows matrix runs
this same file against the native PowerShell entrypoint.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest

from support import ProtocolFixture, read_json, write_json


class CoordinatorSessionTests(unittest.TestCase):
    def setUp(self):
        self.f = ProtocolFixture(quickfix=self._testMethodName.startswith('test_complete'))
        self.addCleanup(self.f.close)
        self.sid = 'c8-fixture'
        self.env = dict(os.environ, CODEX_THREAD_ID=self.sid, ORCA_STRIGOV_WORKER='0')
        self.env.pop('ORCA_TERMINAL_HANDLE', None)
        self.base = dict(session_id=self.sid, worktree=str(self.f.git.root))
        self.binding = dict(self.base, workspace=str(self.f.workspace), objective='Implement both phases, review and deliver')
        self.saved = self.f.git.root / '.superpowers/sdd/.sessions' / (self.sid + '.json')

    def call(self, action, request=None, expected=0, env=None):
        source = self.f.save(request or self.base)
        result = subprocess.run(self.f.argv('coordinator-session', action, source['path']),
                                cwd=self.f.git.root, env=env or self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout.decode('utf-8-sig'))

    def hook(self, event='Stop', **fields):
        payload = dict(hook_event_name=event, session_id=self.sid, cwd=str(self.f.git.root), **fields)
        result = subprocess.run(self.f.argv('coordinator-session', 'hook'), input=json.dumps(payload).encode(),
                                cwd=self.f.git.root, env=self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.decode('utf-8-sig'))

    def bind(self):
        return self.call('bind', self.binding)

    def checkpoint(self, proposal):
        reference = self.f.save(copy.deepcopy(proposal))
        self.call('checkpoint', dict(self.base, proposal=reference))
        return reference

    def test_unbound_and_worker_sessions_are_not_trapped(self):
        self.assertEqual(self.hook(), {})
        self.assertEqual(self.hook('SessionStart', source='startup'), {})
        self.assertFalse(self.saved.exists())
        self.bind()
        self.env['ORCA_STRIGOV_WORKER'] = '1'
        self.assertEqual(self.hook(), {})
        self.call('bind', self.binding, expected=2)
        self.env['ORCA_STRIGOV_WORKER'] = '0'
        self.assertEqual(self.hook('SubagentStop', agent_id='child'), {})

    def test_binding_is_idempotent_and_session_scoped(self):
        first = self.bind()
        self.assertEqual(first, self.bind())
        self.call('bind', dict(self.binding, objective='Unrelated objective'), expected=2)
        self.call('bind', dict(self.binding, session_id='someone-else'), expected=2)
        self.assertEqual(read_json(self.saved), first)
        self.assertEqual(self.hook('Stop', agent_id='different-worker'), {})

    def test_resume_and_compact_restore_role_without_rebinding(self):
        self.bind()
        for source in ('resume', 'compact'):
            result = self.hook('SessionStart', source=source)
            self.assertIn(str(self.saved), result['hookSpecificOutput']['additionalContext'])
            self.assertEqual(read_json(self.saved)['status'], 'active')
        self.assertEqual(self.hook(last_assistant_message='Готово, создана ветка следующей фазы')['decision'], 'block')

    def test_missing_checkpoint_cannot_claim_done(self):
        self.bind()
        result = self.hook(last_assistant_message='All work complete')
        self.assertEqual(result['decision'], 'block')
        self.assertIn('no C6 checkpoint', result['reason'])

    def test_continuation_loop_is_bounded_and_auto_prompt_is_not_user(self):
        self.bind()
        for attempt in range(4):
            result = self.hook(stop_hook_active=attempt > 0)
            self.assertEqual(result['decision'], 'block')
            self.hook('UserPromptSubmit', prompt=result['reason'])
        saved = read_json(self.saved)
        self.assertEqual(saved['status'], 'held')
        self.assertEqual(saved['hold']['kind'], 'no_progress')
        self.assertIn('incomplete', self.hook()['systemMessage'])
        self.call('resume')
        self.assertEqual(read_json(self.saved)['status'], 'active')

    def test_new_phase_starts_with_implementation_not_gate(self):
        self.bind()
        self.f.state['active'] = None
        self.checkpoint(dict(schema_version=1, action='resume', state=self.f.state))
        self.assertEqual(read_json(self.saved)['progress']['barrier'], 'awaiting_implementation')
        self.assertIn('awaiting_implementation', self.hook()['reason'])

    def test_active_worker_means_reconcile_wait_not_duplicate(self):
        self.bind()
        self.f.report_input()
        self.checkpoint(dict(schema_version=1, action='resume', state=self.f.state))
        self.assertIn('existing active Dispatch', self.hook()['reason'])

    def test_accepted_implementation_still_requires_gate(self):
        self.bind()
        self.checkpoint(self.f.report_input())
        result = self.hook()
        self.assertEqual(result['decision'], 'block')
        self.assertIn('awaiting_gate', result['reason'])

    def test_phase_commit_and_advance_require_next_implementation(self):
        f = self.f
        next_phase = ('  - id: F2\n    risk: none\n    base: pending\n'
                      '    consumes: ["C1"]\n    produces: []\n')
        f.plan.write_text(f.plan.read_text().replace('---\nFixture plan.', next_phase + '---\nFixture plan.'))
        f.state['plan'] = f.reference(f.plan)
        f.git.git('add', 'plan.md')
        self.bind()
        self.assertEqual(f.validate(f.report_input())[0], 0)
        proofs = f.gate_evidence(); gate_art = f.gate_snapshot
        self.assertEqual(f.validate(f.report_input('gate', artifact=gate_art,
                                                 extra='EVIDENCE: ' + json.dumps(proofs)))[0], 0)
        art, coverage = f.package_ref()
        for role in ('review-primary', 'review-control'):
            self.assertEqual(f.validate(f.report_input(role, 'Anthropic', artifact=art, coverage=coverage))[0], 0)
        self.assertEqual(f.validate(action='prepare-commit', artifact=art, fleet=f.fleet())[0], 0)
        fact = f.commit(art)
        confirmed = dict(schema_version=1, action='confirm-commit', state=f.state,
                         artifact=art, commit=fact, fleet=f.fleet())
        self.checkpoint(confirmed)
        self.assertIn('ready_next_phase', self.hook()['reason'])
        self.assertEqual(f.validate(confirmed)[0], 0)
        advance = dict(schema_version=1, action='advance', state=f.state,
                       artifact=art, commit=fact, fleet=f.fleet())
        self.checkpoint(advance)
        result = self.hook(last_assistant_message='Phase one committed, branch for phase two ready')
        self.assertEqual(result['decision'], 'block')
        self.assertIn('awaiting_implementation', result['reason'])
        self.assertEqual(read_json(self.saved)['progress']['phase'], 'F2')

    def test_editor_guard_blocks_source_allows_workspace(self):
        self.bind()
        denied = self.hook('PreToolUse', tool_name='apply_patch', tool_input={'command':
            '*** Begin Patch\n*** Update File: tracked.txt\n@@\n-old\n+new\n*** End Patch'})
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        denied = self.hook('PreToolUse', tool_name='Write', tool_input={'file_path': str(self.f.git.root / 'src/app.py')})
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        allowed = self.hook('PreToolUse', tool_name='Write', tool_input={'file_path': str(self.f.workspace / 'prompt.md')})
        self.assertNotIn('permissionDecision', allowed['hookSpecificOutput'])
        escaped = self.hook('PreToolUse', tool_name='Write', tool_input={'file_path': str(self.f.workspace / '../../../tracked.txt')})
        self.assertEqual(escaped['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_user_pause_status_only_and_evidenced_blocker(self):
        self.bind()
        self.call('hold', dict(self.base, kind='blocked', reason='missing access'), expected=2)
        evidence = self.f.save('User asked only for status', '.md')
        self.call('hold', dict(self.base, kind='status_only', reason='Status answer only', evidence=evidence))
        self.assertNotIn('decision', self.hook())
        self.hook('UserPromptSubmit', prompt='Continue the authorized plan')
        self.assertEqual(self.hook()['decision'], 'block')
        self.hook('Interrupt')
        self.hook('SessionStart', source='resume')
        self.assertEqual(read_json(self.saved)['hold']['kind'], 'user_pause')
        self.assertNotIn('decision', self.hook())

    def test_mutated_hold_cannot_silently_release_stop(self):
        self.bind()
        evidence = self.f.save('Actual missing authority', '.md')
        self.call('hold', dict(self.base, kind='needs_authority', reason='Needs approval', evidence=evidence))
        Path(evidence['path']).write_text('Replaced evidence')
        self.assertEqual(self.hook()['decision'], 'block')

    def test_heartbeat_checkpoint_preserves_pending_worker(self):
        self.bind()
        proposal = copy.deepcopy(self.f.report_input())
        event = read_json(proposal['event']['path'])
        event['result']['message']['type'] = 'heartbeat'
        proposal['event'] = self.f.save(event)
        self.checkpoint(proposal)
        self.assertIn('existing active Dispatch', self.hook()['reason'])

    def test_stale_plan_can_be_repaired_without_allowing_source(self):
        self.bind()
        self.f.state['active'] = None
        self.checkpoint(dict(schema_version=1, action='resume', state=self.f.state))
        plan = Path(self.f.state['plan']['path'])
        plan.write_text(plan.read_text() + '\nChanged bookkeeping\n')
        allowed = self.hook('PreToolUse', tool_name='Write', tool_input={'file_path': str(plan)})
        self.assertNotIn('permissionDecision', allowed['hookSpecificOutput'])
        self.assertEqual(self.hook()['decision'], 'block')

    def test_mutated_checkpoint_and_outside_proposal_are_rejected(self):
        self.bind()
        self.f.state['active'] = None
        proposal = dict(schema_version=1, action='resume', state=self.f.state)
        reference = self.checkpoint(proposal)
        Path(reference['path']).write_text('{}')
        result = self.hook()
        self.assertEqual(result['decision'], 'block')
        self.assertIn('hash mismatch', result['reason'])
        outside = self.f.base / 'outside.json'; write_json(outside, proposal)
        self.call('checkpoint', dict(self.base, proposal=self.f.reference(outside)), expected=2)

    def test_complete_needs_actual_commit_and_rechecks_late_source_change(self):
        f = self.f; self.bind()
        art = f.snapshot_ref()
        self.assertEqual(f.validate(f.report_input('quickfix', artifact=art))[0], 0)
        self.assertEqual(f.validate(action='prepare-commit', artifact=art, fleet=f.fleet())[0], 0)
        fact = f.commit(art)
        proposal = dict(schema_version=1, action='confirm-commit', state=f.state,
                        artifact=art, commit=fact, fleet=f.fleet())
        self.checkpoint(proposal)
        self.assertEqual(self.hook(), {})
        (f.git.root / 'tracked.txt').write_text('Late unreviewed source edit')
        self.assertEqual(self.hook()['decision'], 'block')

    def test_plan_completion_requires_delivery_and_separate_completion_commit(self):
        f = self.f; self.bind()
        art, _ = f.package_ref()
        fact = f.commit(art)
        f.state['phase_commits'] = [dict(fact, phase='F1')]
        f.state['step'] = 'final-review'
        art, coverage = f.package_ref()
        self.assertEqual(f.validate(f.report_input('review-final', 'Anthropic', artifact=art, coverage=coverage))[0], 0)
        self.assertEqual(f.validate(action='finish-checkpoint', artifact=art, fleet=f.fleet())[0], 0)
        self.checkpoint(dict(schema_version=1, action='resume', state=f.state))
        self.assertIn('awaiting_delivery', self.hook()['reason'])
        proofs = f.gate_evidence(); delivered = f.gate_snapshot
        self.assertEqual(f.validate(f.report_input('gate', artifact=delivered, extra='EVIDENCE: ' + json.dumps(proofs)))[0], 0)
        self.assertEqual(f.validate(action='finish-checkpoint', artifact=delivered, fleet=f.fleet())[0], 0)
        self.checkpoint(dict(schema_version=1, action='resume', state=f.state))
        self.assertIn('awaiting_completion_commit', self.hook()['reason'])
        f.plan.write_text(f.plan.read_text().replace('status: implementing', 'status: done'))
        f.git.git('add', 'plan.md'); f.state['plan'] = f.reference(f.plan)
        proofs = f.gate_evidence(); completed = f.gate_snapshot
        self.assertEqual(f.validate(f.report_input('gate', artifact=completed, extra='EVIDENCE: ' + json.dumps(proofs)))[0], 0)
        completion = f.commit(completed)
        self.assertNotEqual(fact['sha'], completion['sha'])
        proposal = dict(schema_version=1, action='complete', state=f.state,
                        artifact=completed, commit=completion, fleet=f.fleet())
        self.checkpoint(proposal)
        self.assertEqual(self.hook(), {})
        self.assertEqual(f.validate(proposal)[0], 0)
        self.checkpoint(dict(schema_version=1, action='resume', state=f.state))
        self.assertIn('resume-only', self.hook()['reason'])


if __name__ == '__main__':
    unittest.main()

"""Shared POSIX/native Windows recovery fixtures; only disposable Git trees and synthetic receipts.

The same tests select protocol-state.ps1 on Windows through ProtocolFixture.
No Orca calls, live workspace writes or global configuration changes.
"""
import copy
import json
import os
from pathlib import Path
import unittest

from support import ProtocolFixture, ROOT, command, read_json


class ObservationRecoveryTests(unittest.TestCase):
    def setUp(self): self.f = ProtocolFixture()
    def tearDown(self): self.f.close()

    def fixture(self, writer=False):
        f = self.f
        assignment = f.assignment('implementer' if writer else 'review-primary', 'Anthropic', round=1 if writer else 3)
        assignment.update(task_id='task_recovery', dispatch_id='ctx_recovery', model='opus')
        art, coverage = f.package_ref()
        findings = [dict(id='RP-B1', kind='blocking', issue='data loss', location='tracked.txt:1',
                         change='retain data', risk='DATA_LOSS', **{'class': 'MUST_FIX_NOW'})]
        data = copy.deepcopy(f.report_input(role=assignment['role'], artifact=art, coverage=coverage, assignment=assignment,
                                          token='DONE' if writer else 'REVIEW_BLOCKING', findings=findings))
        old = read_json(f.claude_observation('ctx_recovery', 'task_recovery')['path'])
        old['result']['terminal']['ptyId'] = 'fixture-pty'
        old['result']['worker']['state'] = 'unsupervised'  # legitimate injected Path B, never rewritten
        path = f.workspace / 'initial.jsonl'
        f.claude_transcript(path, 'task_recovery', 'ctx_recovery')
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        for row in rows: row['timestamp'] = '2026-10-05T05:01:00.000Z'
        initial = f.save(''.join(json.dumps(r) + '\n' for r in rows), '.jsonl')
        bound = dict(f.save(old), model_evidence=dict(initial, kind='claude-transcript'))
        rows.append(dict(type='system', sessionId='fixture-session', timestamp='2026-10-05T05:18:07.000Z',
                         cwd=str(f.git.root)))
        # Exercise raw-byte hashes before BOM/CRLF parsing as well as completion coverage.
        full = f.workspace / 'full.jsonl'
        full.write_bytes(('\ufeff' + ''.join(json.dumps(r) + '\r\n' for r in rows)).encode('utf-8'))
        proof = dict(f.reference(full), kind='claude-transcript')
        current = copy.deepcopy(old)
        current['result']['dispatch'].update(status='completed', completedAt='2026-10-05T05:18:06.701Z')
        current['result']['projection'].update(provider=None, workspace=None)
        current['result']['terminal'] = None
        current['result']['projection']['liveness'] = dict(verdict='unverifiable')
        data['state']['active']['bound_observation'] = bound
        data['state']['rounds']['fused_review'] = 3
        data['bound_observation'] = bound
        data['observation'] = dict(f.save(current), model_evidence=proof)
        event = read_json(data['event']['path'])
        event['result']['message']['from_handle'] = f.CLAUDE_HANDLE
        data['event'] = f.save(event)
        return data, old, current, rows

    def result(self, data, code=0, reason=''):
        output = self.f.workspace / 'untouched-output.json'
        output.write_bytes(b'previous state')
        result = self.f.validate(data, output=output)
        self.assertEqual(result[:2], (code, ['VALID', 'INVALID', 'UNVERIFIABLE'][code]), result)
        if code:
            self.assertIn(reason, result[2]['reason'])
            self.assertEqual(output.read_bytes(), b'previous state')
        return result[2]

    def test_same_completed_dispatch_preserves_findings_and_bytes(self):
        data, old, current, _ = self.fixture()
        refs = [data['report'], data['artifact'], data['event'], data['observation'],
                data['bound_observation'], data['bound_observation']['model_evidence'], data['observation']['model_evidence']]
        before = {r['path']: Path(r['path']).read_bytes() for r in refs}
        state = self.result(data)['state']
        entry = state['accepted'][-1]
        self.assertEqual(entry['token'], 'REVIEW_BLOCKING')
        self.assertEqual(entry['findings'][0]['risk'], 'DATA_LOSS')
        self.assertEqual(entry['family'], 'Anthropic')
        self.assertEqual(entry['bound_observation'], data['bound_observation'])
        self.assertEqual(state['rounds'], data['state']['rounds'])
        self.assertEqual(state['cap_extensions'], data['state']['cap_extensions'])
        self.assertIsNone(state['active'])
        self.assertEqual(current['result']['worker']['state'], 'unsupervised')
        self.assertEqual(before, {p: Path(p).read_bytes() for p in before})

    def test_legacy_binding_and_writer_provenance(self):
        data, _, _, _ = self.fixture(writer=True)
        data['state']['active'].pop('bound_observation')
        self.result(data, 2, 'missing facts')
        data['bound_dispatch'] = self.f.save(dict(action='bind-dispatch', observation=data['bound_observation']))
        state = self.result(data)['state']
        self.assertEqual(state['provenance'][-1]['path'], data['bound_observation']['path'])
        self.assertEqual(state['provenance'][-1]['sha256'], data['bound_observation']['sha256'])
        self.assertEqual(state['provenance'][-1]['model_evidence'], data['observation']['model_evidence'])
        self.assertEqual(state['authors']['tracked.txt'], ['Anthropic'])
        self.assertEqual(state['accepted'][-1]['bound_dispatch'], data['bound_dispatch'])

    def test_shared_negative_receipt_cases(self):
        data, old, current, _ = self.fixture()
        cases = read_json(ROOT / 'tests/fixtures/observation-recovery.json')
        immutable = {p: p.read_bytes() for p in self.f.workspace.iterdir() if p.is_file()}
        for spec in cases:
            with self.subTest(spec['name']):
                proposal = copy.deepcopy(data)
                raw = copy.deepcopy(current if spec['target'] == 'current' else old)
                target = raw['result']
                for key in spec['path'][:-1]: target = target[key]
                target[spec['path'][-1]] = spec['value']
                ref = self.f.save(raw)
                if spec['target'] == 'current':
                    proposal['observation'] = dict(ref, model_evidence=data['observation']['model_evidence'])
                else:
                    bound = dict(ref, model_evidence=data['bound_observation']['model_evidence'])
                    proposal['bound_observation'] = proposal['state']['active']['bound_observation'] = bound
                self.result(proposal, spec['code'], spec['reason'])
        self.assertEqual(immutable, {p: p.read_bytes() for p in immutable})

    def test_missing_reference_proof_switch_and_original_binding(self):
        data, _, _, rows = self.fixture()
        missing = copy.deepcopy(data); missing.pop('bound_observation')
        self.result(missing, 2, 'observation worktree mismatch')
        wrong = copy.deepcopy(data); wrong['bound_observation'] = dict(wrong['bound_observation'], sha256='0' * 64)
        self.result(wrong, 1, 'differs from original')
        partial = copy.deepcopy(data)
        partial['observation']['model_evidence'] = data['bound_observation']['model_evidence']
        self.result(partial, 2, 'does not cover Dispatch completion')
        absent = copy.deepcopy(data); absent['observation'].pop('model_evidence')
        self.result(absent, 2, 'missing facts')
        switched = copy.deepcopy(data)
        rows.append(dict(type='assistant', sessionId='fixture-session', cwd=str(self.f.git.root),
                         timestamp='2026-10-05T05:18:08Z', message=dict(model='claude-sonnet-5-5')))
        switched['observation']['model_evidence'] = dict(self.f.save(''.join(json.dumps(r)+'\n' for r in rows), '.jsonl'), kind='claude-transcript')
        self.result(switched, 1, 'conflicting actual model facts')
        model = copy.deepcopy(data); model['state']['active']['model'] = 'sonnet'
        self.result(model, 1, 'actual completion differs from proposal')
        unbound = copy.deepcopy(data); unbound['state']['active']['dispatch_id'] = None
        self.result(unbound, 0)  # stale worker_done is ignored, never binds the pending intent
        bind = copy.deepcopy(data); bind['action'] = 'bind-dispatch'
        self.result(bind, 1, 'accept-report only')
        resume = copy.deepcopy(data); resume['action'] = 'resume'
        self.result(resume, 1, 'accept-report only')

    def test_normal_current_receipt_accepts_partial_bind_proof_with_independence(self):
        data, old, current, _ = self.fixture()
        complete = copy.deepcopy(current)
        complete['result']['terminal'] = old['result']['terminal']
        complete['result']['projection'].update(provider=old['result']['projection']['provider'],
                                               workspace=old['result']['projection']['workspace'])
        data['observation'] = dict(self.f.save(complete), model_evidence=data['observation']['model_evidence'])
        data.pop('bound_observation')
        partial = copy.deepcopy(data)
        partial['observation']['model_evidence'] = data['state']['active']['bound_observation']['model_evidence']
        self.result(partial)
        without_time = copy.deepcopy(partial)
        complete['result']['dispatch'].pop('completedAt')
        without_time['observation'] = dict(self.f.save(complete), model_evidence=partial['observation']['model_evidence'])
        self.result(without_time)
        self.result(data)
        independent = copy.deepcopy(partial)
        independent['state']['authors']['tracked.txt'] = ['Anthropic']
        self.result(independent, 1, 'same-family review')

    def test_fresh_bind_records_exact_original_reference(self):
        data, _, _, _ = self.fixture(writer=True)
        active = copy.deepcopy(data['state']['active']); active['dispatch_id'] = None
        active.pop('bound_observation')
        bind = dict(schema_version=1, action='bind-dispatch', state=dict(data['state'], active=active),
                    observation=data['bound_observation'])
        state = self.result(bind)['state']
        self.assertEqual(state['active']['bound_observation'], data['bound_observation'])

    def path_a(self, data, reuse=False, model='opus'):
        proposal = copy.deepcopy(data)
        bound = {k: proposal['bound_observation'][k] for k in ('path', 'sha256')}
        bound['start'] = self.f.launch_receipt('task_recovery', 'ctx_recovery', 'reused' if reuse else 'created',
                                             model=None if reuse else model)
        if reuse:
            bound['origin_start'] = self.f.launch_receipt('task_origin', 'ctx_origin', 'created', model=model)
        proposal['bound_observation'] = proposal['state']['active']['bound_observation'] = bound
        return proposal

    def test_path_a_and_reused_alias_models_agree_with_full_completion_proof(self):
        data, _, current, _ = self.fixture()
        for reuse in (False, True):
            for current_model in (None, 'claude-opus-5-5'):
                with self.subTest(reuse=reuse, current_model=current_model):
                    proposal = self.path_a(data, reuse)
                    raw = copy.deepcopy(current)
                    if current_model is not None:
                        raw['result']['projection']['provider'] = dict(id='claude', model=current_model)
                    proposal['observation'] = dict(self.f.save(raw), model_evidence=data['observation']['model_evidence'])
                    refs = [proposal['bound_observation'], proposal['bound_observation']['start'],
                            proposal['observation'], proposal['observation']['model_evidence']]
                    if reuse: refs.append(proposal['bound_observation']['origin_start'])
                    before = {r['path']: Path(r['path']).read_bytes() for r in refs}
                    state = self.result(proposal)['state']
                    self.assertEqual(state['accepted'][-1]['family'], 'Anthropic')
                    self.assertEqual(state['accepted'][-1]['token'], 'REVIEW_BLOCKING')
                    self.assertEqual(before, {p: Path(p).read_bytes() for p in before})

    def test_different_full_models_reach_actual_comparison_and_reject(self):
        data, _, current, rows = self.fixture()
        # One model in each proof, but different full ids: this reaches agreement,
        # rather than failing earlier on a switch inside one transcript window.
        different = copy.deepcopy(data)
        for row in rows:
            if row.get('type') == 'assistant': row['message']['model'] = 'claude-opus-5-6'
        different['observation']['model_evidence'] = dict(self.f.save(''.join(json.dumps(r)+'\n' for r in rows), '.jsonl'), kind='claude-transcript')
        self.result(different, 1, 'conflicting actual model facts')
        bound_full = self.path_a(data, model='claude-opus-5-6')
        self.result(bound_full, 1, 'conflicting actual model facts')
        # The original alias agrees with both full ids; a present current full id
        # must still agree exactly with the completion transcript.
        alias = self.path_a(data)
        raw = copy.deepcopy(current)
        raw['result']['projection']['provider'] = dict(id='claude', model='claude-opus-5-6')
        alias['observation'] = dict(self.f.save(raw), model_evidence=data['observation']['model_evidence'])
        self.result(alias, 1, 'conflicting actual model facts')
        raw['result']['projection']['provider']['model'] = 7
        malformed = self.path_a(data)
        malformed['observation'] = dict(self.f.save(raw), model_evidence=data['observation']['model_evidence'])
        self.result(malformed, 1, 'conflicting current provider: model')

    def test_exact_legacy_binding_action_reference_and_existing_binding_conflicts(self):
        data, _, _, _ = self.fixture()
        legacy = copy.deepcopy(data); legacy['state']['active'].pop('bound_observation')
        mismatch = dict(data['bound_observation'], sha256='0' * 64)
        for action, ref, reason in [('resume', data['bound_observation'], 'requires original bind-dispatch'),
                                    ('bind-dispatch', mismatch, 'differs from original bind-dispatch')]:
            proposal = copy.deepcopy(legacy)
            proposal['bound_dispatch'] = self.f.save(dict(action=action, observation=ref))
            self.result(proposal, 1, reason)
        for action, ref in [('resume', data['bound_observation']), ('bind-dispatch', mismatch)]:
            proposal = copy.deepcopy(data)
            proposal['bound_dispatch'] = self.f.save(dict(action=action, observation=ref))
            self.result(proposal, 1, 'conflicting original bind-dispatch')
        good = copy.deepcopy(data)
        good['bound_dispatch'] = self.f.save(dict(action='bind-dispatch', observation=data['bound_observation']))
        self.result(good)
        only = copy.deepcopy(good); only.pop('bound_observation')
        self.result(only, 1, 'bound-dispatch recovery without bound observation')
        missing = copy.deepcopy(legacy)
        missing['bound_dispatch'] = self.f.save(dict(observation=data['bound_observation']))
        self.result(missing, 2, 'missing facts')

    def test_recovery_fields_are_forbidden_on_other_actions(self):
        data, _, _, _ = self.fixture()
        for action in ('dispatch', 'bind-dispatch', 'record-author', 'resume', 'reconcile-intent', 'record-gate'):
            with self.subTest(action=action):
                proposal = copy.deepcopy(data); proposal['action'] = action
                self.result(proposal, 1, 'accept-report only')

    def test_timestamp_completeness_short_circuits_without_skipping_models(self):
        data, _, _, rows = self.fixture()
        bad = dict(type='system', sessionId='fixture-session', timestamp='malformed timestamp')
        def proof(window):
            return dict(self.f.save(''.join(json.dumps(r)+'\n' for r in window), '.jsonl'), kind='claude-transcript')
        before = copy.deepcopy(data)
        before['observation']['model_evidence'] = proof(rows[:-1] + [bad] + rows[-1:])
        self.result(before, 2)
        after = copy.deepcopy(data)
        after['observation']['model_evidence'] = proof(rows + [bad])
        self.result(after)
        switched = copy.deepcopy(data)
        late_model = dict(type='assistant', sessionId='fixture-session', timestamp='malformed timestamp',
                          message=dict(model='claude-sonnet-5-5'))
        switched['observation']['model_evidence'] = proof(rows + [late_model])
        self.result(switched, 1, 'conflicting actual model facts')


class ProviderRecoveryTests(unittest.TestCase):
    """Antigravity and Codex workers recover through their own completion-covering proofs."""
    CONVERSATION = 'c0ffee00-1111-2222-3333-444455556666'
    LATE_AGY = dict(step_index=9, source='MODEL', type='PLANNER_RESPONSE', status='DONE', created_at='2026-10-05T05:18:07Z', content='done')
    LATE_CODEX = dict(timestamp='2026-10-05T05:18:07.000Z', type='event_msg', payload=dict(type='task_complete'))

    def setUp(self): self.f = ProtocolFixture()
    def tearDown(self): self.f.close()

    def agy_proof(self, models=('gemini-3.8-flash-high',), dispatch='ctx_recovery', created_at='2026-10-05T05:01:00Z', after=None,
                  captured_at='2026-10-05T05:20:00.000000Z'):
        f = self.f; f.serial += 1
        t, l = f.agy_home(f.workspace / ('agy-' + str(f.serial)), self.CONVERSATION, 'task_recovery', dispatch, models=models,
                          created_at=created_at, after=[self.LATE_AGY] if after is None else after)
        proof = dict(f.reference(t), kind='antigravity-log', conversation_id=self.CONVERSATION, log=f.reference(l))
        if captured_at is not None: proof['capture'] = f.agy_capture(proof, captured_at)
        return proof

    def codex_proof(self, models=('gpt-6-luna',), cwd=None, after=None, dispatch='ctx_recovery'):
        f = self.f; f.serial += 1
        path = f.codex_rollout(f.workspace / ('rollout-' + str(f.serial) + '.jsonl'), 'task_recovery', dispatch, models=models, cwd=cwd,
                               after=[self.LATE_CODEX] if after is None else after)
        return dict(f.reference(path), kind='codex-rollout')

    def preamble(self, dispatch, task='task_next'):
        return ('You are working inside Orca, a multi-agent IDE. You are a dispatched worker.\nYour task ID is: ' + task + '\n'
                '  orca orchestration send --from ' + self.f.CLAUDE_HANDLE + ' --type worker_done --task-id ' + task + ' --dispatch-id ' + dispatch + '\n')

    def codex_next(self, model='gpt-6-astra', timestamp='2026-10-05T05:30:00.000Z'):
        """The next Dispatch injected into the same Codex terminal: its own turn context, then its preamble."""
        return [dict(timestamp=timestamp, type='turn_context', payload=dict(turn_id='next', cwd=str(self.f.git.root), model=model)),
                dict(timestamp=timestamp, type='response_item', payload=dict(type='message', role='user',
                     content=[dict(type='input_text', text=self.preamble('ctx_next'))]))]

    def provider_fixture(self, provider, writer=False):
        f = self.f
        family = dict(antigravity='Google', codex='OpenAI')[provider]
        assignment = f.assignment('implementer' if writer else 'review-primary', family, round=1 if writer else 3)
        assignment.update(task_id='task_recovery', dispatch_id='ctx_recovery')
        files = f.git.git('-c', 'core.quotePath=false', 'diff', '--name-only', f.state['base']).splitlines()
        art, coverage = f.package_ref(families={'Anthropic': files})
        findings = [dict(id='RP-B1', kind='blocking', issue='data loss', location='tracked.txt:1',
                         change='retain data', risk='DATA_LOSS', **{'class': 'MUST_FIX_NOW'})]
        data = copy.deepcopy(f.report_input(role=assignment['role'], artifact=art, coverage=coverage, assignment=assignment,
                                          token='DONE' if writer else 'REVIEW_BLOCKING', findings=findings))
        receipt = f.agy_observation if provider == 'antigravity' else f.codex_observation
        old = read_json(receipt('ctx_recovery', 'task_recovery')['path'])
        old['result']['terminal']['ptyId'] = 'fixture-pty'
        old['result']['worker']['state'] = 'unsupervised'  # legitimate injected Path B, never rewritten
        bound = f.save(old)
        if provider == 'antigravity':  # the original bind proof: no completion facts needed then
            bound = dict(bound, model_evidence=self.agy_proof(created_at=None, after=(), captured_at=None))
        current = copy.deepcopy(old)
        current['result']['dispatch'].update(status='completed', completedAt='2026-10-05T05:18:06.701Z')
        current['result']['projection'].update(provider=None, workspace=None)
        current['result']['terminal'] = None
        current['result']['projection']['liveness'] = dict(verdict='unverifiable')
        proof = self.agy_proof() if provider == 'antigravity' else self.codex_proof()
        data['state']['active']['bound_observation'] = bound
        data['state']['rounds']['fused_review'] = 3
        data['bound_observation'] = bound
        data['observation'] = dict(f.save(current), model_evidence=proof)
        event = read_json(data['event']['path'])
        event['result']['message']['from_handle'] = f.CLAUDE_HANDLE
        data['event'] = f.save(event)
        return data, old, current

    def result(self, data, code=0, reason=''):
        output = self.f.workspace / 'untouched-output.json'
        output.write_bytes(b'previous state')
        result = self.f.validate(data, output=output)
        self.assertEqual(result[:2], (code, ['VALID', 'INVALID', 'UNVERIFIABLE'][code]), result)
        if code:
            self.assertIn(reason, result[2]['reason'])
            self.assertEqual(output.read_bytes(), b'previous state')
        return result[2]

    def proposal(self, data, proof):
        changed = copy.deepcopy(data); changed['observation']['model_evidence'] = proof
        return changed

    def test_reviewer_recovery_preserves_findings_and_bytes(self):
        for provider, family in (('antigravity', 'Google'), ('codex', 'OpenAI')):
            with self.subTest(provider=provider):
                data, old, current = self.provider_fixture(provider)
                refs = [data['report'], data['artifact'], data['event'], data['observation'], data['bound_observation'],
                        data['observation']['model_evidence']]
                before = {r['path']: Path(r['path']).read_bytes() for r in refs}
                state = self.result(data)['state']
                entry = state['accepted'][-1]
                self.assertEqual((entry['token'], entry['family'], entry['findings'][0]['risk']), ('REVIEW_BLOCKING', family, 'DATA_LOSS'))
                self.assertEqual(entry['bound_observation'], data['bound_observation'])
                self.assertEqual(state['rounds'], data['state']['rounds'])
                self.assertIsNone(state['active'])
                self.assertEqual(before, {p: Path(p).read_bytes() for p in before})

    def test_writer_recovery_provenance(self):
        data, _, _ = self.provider_fixture('antigravity', writer=True)
        state = self.result(data)['state']
        self.assertEqual(state['provenance'][-1], dict(path=data['bound_observation']['path'], sha256=data['bound_observation']['sha256'],
                                                      model_evidence=data['observation']['model_evidence']))
        self.assertEqual(state['authors']['tracked.txt'], ['Google'])
        self.f.state = self.f.v2_state()
        data, _, _ = self.provider_fixture('codex', writer=True)
        data['state']['active'].pop('bound_observation')  # legacy bound state
        data['bound_dispatch'] = self.f.save(dict(action='bind-dispatch', observation=data['bound_observation']))
        state = self.result(data)['state']
        # Orca reported the Codex model at bind time: provenance keeps the original receipt, never the rollout.
        self.assertEqual(state['provenance'][-1], data['bound_observation'])
        self.assertEqual(state['authors']['tracked.txt'], ['OpenAI'])

    def test_antigravity_completion_and_model_negatives(self):
        data, _, _ = self.provider_fixture('antigravity')
        foreign = dict(step_index=5, source='USER_EXPLICIT', type='USER_INPUT', status='DONE', created_at='2026-10-05T05:10:00Z',
                       content='<USER_REQUEST>\n' + self.preamble('ctx_next') + '</USER_REQUEST>')
        cases = [(self.agy_proof(after=()), 2, 'model proof does not cover Dispatch completion'),
                 (data['bound_observation']['model_evidence'], 2, 'recovery requires the Antigravity capture record'),
                 (self.agy_proof(after=[foreign, self.LATE_AGY]), 2, 'model proof does not cover Dispatch completion'),
                 (self.agy_proof(models=('gemini-3.8-flash-high', 'gemini-3.7-flash-high')), 1, 'conflicting actual model facts'),
                 (self.agy_proof(models=('gemini-3.7-flash-high',)), 1, 'conflicting actual model facts'),
                 (self.agy_proof(dispatch='ctx_other'), 2, 'no Orca preamble for this Dispatch in Antigravity transcript'),
                 (dict(self.agy_proof(), kind='claude-transcript'), 1, 'model evidence kind does not match provider'),
                 (self.codex_proof(), 1, 'model evidence kind does not match provider'),
                 (dict(self.agy_proof(), kind='gemini-session'), 2, 'recovery requires a completion-covering model proof')]
        for proof, code, reason in cases:
            with self.subTest(reason=reason, kind=proof['kind']):
                self.result(self.proposal(data, proof), code, reason)
        model = copy.deepcopy(data); model['state']['active']['model'] = 'gemini-3.7-flash-high'
        self.result(model, 1, 'actual completion differs from proposal')
        for action in ('bind-dispatch', 'resume'):
            proposal = copy.deepcopy(data); proposal['action'] = action
            self.result(proposal, 1, 'accept-report only')

    def shared(self, name):
        return read_json(ROOT / 'tests/fixtures/provider-recovery.json')[name]

    def window(self, tokens):
        """A Codex rollout from the shared window vocabulary (see tests/fixtures/provider-recovery.json)."""
        f = self.f; early = '2026-10-05T05:01:00.000Z'
        def message(role, text):
            kind = 'output_text' if role == 'assistant' else 'input_text'
            return dict(timestamp=early, type='response_item', payload=dict(type='message', role=role, content=[dict(type=kind, text=text)]))
        rows = [dict(timestamp=early, type='session_meta', payload=dict(id='fixture-codex-session', cwd=str(f.git.root)))]
        for token in tokens:
            name, _, value = token.partition(':')
            if name in ('ctx', 'ctx-outside'):
                cwd = str(f.git.other if name == 'ctx-outside' else f.git.root)
                rows.append(dict(timestamp=early, type='turn_context', payload=dict(turn_id='turn-' + str(len(rows)), cwd=cwd, model=value)))
            elif name == 'preamble':
                rows.append(message('user', self.preamble(value) if value else self.preamble('ctx_recovery', 'task_recovery')))
            elif name in ('user', 'assistant'): rows.append(message(name, 'continue' if name == 'user' else 'ok'))
            elif name == 'work': rows.append(dict(timestamp=early, type='response_item', payload=dict(type='function_call', name='exec', arguments='{}')))
            else:
                self.assertEqual(name, 'late'); rows.append(self.LATE_CODEX)
        return dict(self.f.save(''.join(json.dumps(r) + '\n' for r in rows), '.jsonl'), kind='codex-rollout')

    def test_shared_codex_windows(self):
        data, _, _ = self.provider_fixture('codex')
        for case in self.shared('codex_windows'):
            with self.subTest(case['name']):
                self.result(self.proposal(data, self.window(case['rows'])), case['code'], case['reason'])

    def test_shared_antigravity_captures(self):
        data, _, _ = self.provider_fixture('antigravity')
        bound_log = data['bound_observation']['model_evidence']['log']
        for case in self.shared('antigravity_captures'):
            with self.subTest(case['name']):
                # The live log may have resolved another model after bind; only the fresh capture shows it.
                proof = self.agy_proof(models=tuple(case.get('models', ['gemini-3.8-flash-high'])), captured_at=None)
                if case['capture'] is not None: proof['capture'] = self.f.agy_capture(proof, **case['capture'])
                if case['log'] == 'bound':
                    self.assertNotEqual(proof['log']['sha256'], bound_log['sha256'])
                    proof['log'] = bound_log  # a fresh transcript paired with the original bind-time log
                self.result(self.proposal(data, proof), case['code'], case['reason'])

    def test_codex_completion_span_and_cwd(self):
        data, _, _ = self.provider_fixture('codex')
        # The next Dispatch's own turn context lies outside this Dispatch's window, after its completion.
        self.result(self.proposal(data, self.codex_proof(after=[self.LATE_CODEX] + self.codex_next())))
        cases = [(self.codex_proof(after=()), 2, 'model proof does not cover Dispatch completion'),
                 (self.codex_proof(models=('gpt-6-astra',)), 1, 'conflicting actual model facts'),
                 (self.codex_proof(models=()), 2, 'no Orca preamble for this Dispatch in Codex rollout'),
                 (self.codex_proof(dispatch='ctx_other'), 2, 'no Orca preamble for this Dispatch in Codex rollout'),
                 (dict(self.codex_proof(), kind='claude-transcript'), 1, 'model evidence kind does not match provider'),
                 (self.agy_proof(), 1, 'model evidence kind does not match provider')]
        for proof, code, reason in cases:
            with self.subTest(reason=reason, kind=proof['kind']):
                self.result(self.proposal(data, proof), code, reason)
        model = copy.deepcopy(data); model['state']['active']['model'] = 'gpt-6-astra'
        self.result(model, 1, 'actual completion differs from proposal')
        for action in ('bind-dispatch', 'resume'):
            proposal = copy.deepcopy(data); proposal['action'] = action
            self.result(proposal, 1, 'accept-report only')

    def test_codex_rollout_is_never_ordinary_model_evidence(self):
        data, old, current = self.provider_fixture('codex')
        rollout = data['observation']['model_evidence']
        complete = copy.deepcopy(current)
        complete['result'].update(terminal=old['result']['terminal'])
        complete['result']['projection'].update(provider=old['result']['projection']['provider'], workspace=old['result']['projection']['workspace'])
        ordinary = copy.deepcopy(data); ordinary.pop('bound_observation')
        ordinary['observation'] = dict(self.f.save(complete), model_evidence=rollout)
        self.result(ordinary, 1, 'codex-rollout model evidence only in observation recovery')
        unreported = copy.deepcopy(complete); unreported['result']['projection']['provider']['model'] = None
        ordinary['observation'] = dict(self.f.save(unreported), model_evidence=rollout)
        self.result(ordinary, 1, 'codex-rollout model evidence only in observation recovery')
        active = copy.deepcopy(data['state']['active']); active['dispatch_id'] = None; active.pop('bound_observation')
        bind = dict(schema_version=1, action='bind-dispatch', state=dict(data['state'], active=active),
                    observation=dict(data['bound_observation'], model_evidence=rollout))
        self.result(bind, 1, 'codex-rollout model evidence only in observation recovery')
        recovery = copy.deepcopy(data)
        recovery['bound_observation'] = recovery['state']['active']['bound_observation'] = dict(data['bound_observation'], model_evidence=rollout)
        self.result(recovery, 1, 'codex-rollout model evidence only in observation recovery')

    def test_claude_worker_rejects_other_provider_proofs(self):
        data, _, _, _ = ObservationRecoveryTests.fixture(self)
        for proof in (self.codex_proof(), self.agy_proof()):
            with self.subTest(kind=proof['kind']):
                self.result(self.proposal(data, proof), 1, 'model evidence kind does not match provider')

    def build(self, kind, env, *args):
        rc, text, err = command(self.f.argv('protocol-state', kind + '-model-evidence', *map(str, args)), self.f.git.root, env=env)
        rows = text.splitlines(); self.assertEqual(len(rows), 2, (rc, text, err))
        return rc, rows[0], json.loads(rows[1])

    def test_codex_builder_finds_one_rollout_and_feeds_recovery(self):
        f = self.f; data, old, _ = self.provider_fixture('codex')
        home = f.workspace / 'codex-home'; env = dict(os.environ, CODEX_HOME=str(home))
        current, bound = data['observation']['path'], data['bound_observation']['path']
        day = home / 'sessions' / '2026' / '10' / '05'
        rc, _, result = self.build('codex', env, current, f.workspace / 'none.jsonl', bound)
        self.assertEqual((rc, result['reason']), (2, 'no Codex rollout with this Dispatch preamble'))
        f.codex_rollout(day / 'rollout-unrelated.jsonl', 'task_recovery', 'ctx_unrelated')
        source = f.codex_rollout(day / 'rollout-worker.jsonl', 'task_recovery', 'ctx_recovery', after=[self.LATE_CODEX])
        rc, _, result = self.build('codex', env, current, f.workspace / 'two-args.jsonl')
        self.assertEqual((rc, result['reason']), (1, 'model evidence kind does not match provider'))
        self.assertFalse((f.workspace / 'two-args.jsonl').exists())
        rc, token, result = self.build('codex', env, current, f.workspace / 'rollout.jsonl', bound)
        self.assertEqual((rc, token, result['model'], result['source']), (0, 'VALID', 'gpt-6-luna', str(source)), result)
        proof = result['model_evidence']
        self.assertEqual((proof['kind'], Path(proof['path']).read_bytes()), ('codex-rollout', source.read_bytes()))
        self.result(self.proposal(data, proof))
        # The intact bind-time receipt needs no bound observation.
        rc, token, result = self.build('codex', env, bound, f.workspace / 'intact.jsonl')
        self.assertEqual((rc, result['model']), (0, 'gpt-6-luna'), result)
        other = copy.deepcopy(old); other['result']['dispatch']['processIncarnation'] = 'other:incarnation'
        rc, _, result = self.build('codex', env, current, f.workspace / 'x.jsonl', f.save(other)['path'])
        self.assertEqual((rc, result['reason']), (1, 'bound observation identity mismatch: processIncarnation'))
        claude = read_json(current); claude['result']['projection']['provider'] = dict(id='claude')
        rc, _, result = self.build('codex', env, f.save(claude)['path'], f.workspace / 'y.jsonl', bound)
        self.assertEqual((rc, result['reason']), (1, 'conflicting current provider: id'))
        rc, _, result = self.build('codex', env, current, proof['path'], bound)
        self.assertEqual((rc, result['reason']), (2, 'snapshot output must be a new absolute file'))
        f.codex_rollout(day / 'rollout-fork.jsonl', 'task_recovery', 'ctx_recovery')
        rc, _, result = self.build('codex', env, current, f.workspace / 'twice.jsonl', bound)
        self.assertEqual(rc, 2); self.assertIn('several Codex rollouts claim this Dispatch', result['reason'])
        self.assertFalse((f.workspace / 'twice.jsonl').exists())

    def test_antigravity_builder_bound_argument_feeds_recovery(self):
        f = self.f; data, old, _ = self.provider_fixture('antigravity')
        home = f.workspace / 'agy-home'; env = dict(os.environ, ORCA_AGY_HOME=str(home))
        current, bound = data['observation']['path'], data['bound_observation']['path']
        f.agy_home(home, self.CONVERSATION, 'task_recovery', 'ctx_recovery', created_at='2026-10-05T05:01:00Z', after=[self.LATE_AGY])
        rc, _, result = self.build('antigravity', env, current, f.workspace / 'two-args.jsonl')
        self.assertEqual((rc, result['reason']), (1, 'model evidence only for an unreported model'))
        rc, token, result = self.build('antigravity', env, current, f.workspace / 'agy.jsonl', bound)
        self.assertEqual((rc, token, result['model']), (0, 'VALID', 'gemini-3.8-flash-high'), result)
        proof = result['model_evidence']
        self.assertEqual(proof['conversation_id'], self.CONVERSATION)
        # The capture record binds both frozen copies and is taken after them (here: after the fixture completion).
        capture = read_json(proof['capture']['path'])
        self.assertEqual(proof['capture']['path'], str(f.workspace / 'agy.jsonl') + '.capture.json')
        self.assertEqual({k: capture[k] for k in ('kind', 'conversation_id', 'transcript_sha256', 'log_sha256')},
                         dict(kind='antigravity-capture', conversation_id=self.CONVERSATION, transcript_sha256=proof['sha256'],
                              log_sha256=proof['log']['sha256']))
        self.assertRegex(capture['captured_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$')
        self.assertGreater(capture['captured_at'], '2026-10-05T05:18:07')
        self.result(self.proposal(data, proof))
        (f.workspace / 'taken.jsonl.capture.json').write_text('{}', encoding='utf-8')
        rc, _, result = self.build('antigravity', env, current, f.workspace / 'taken.jsonl', bound)
        self.assertEqual((rc, result['reason']), (2, 'snapshot output must be a new absolute file'))
        self.assertFalse((f.workspace / 'taken.jsonl').exists())
        other = copy.deepcopy(old); other['result']['dispatch']['taskId'] = 'other-task'
        rc, _, result = self.build('antigravity', env, current, f.workspace / 'x.jsonl', f.save(other)['path'])
        self.assertEqual((rc, result['reason']), (1, 'bound observation identity mismatch: taskId'))
        rc, _, result = self.build('antigravity', env, current, f.workspace / 'y.jsonl', bound, bound)
        self.assertEqual(rc, 1); self.assertIn('usage: protocol-state antigravity-model-evidence', result['reason'])


if __name__ == '__main__': unittest.main()

"""Shared POSIX/native Windows recovery fixtures; only disposable Git trees and synthetic receipts.

The same tests select protocol-state.ps1 on Windows through ProtocolFixture.
No Orca calls, live workspace writes or global configuration changes.
"""
import copy
import json
from pathlib import Path
import unittest

from support import ProtocolFixture, ROOT, read_json


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


if __name__ == '__main__': unittest.main()

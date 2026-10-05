"""Maintenance regressions: identical byte inputs through Python and native C6."""
import copy
import json
from pathlib import Path
import sys
import unittest

from support import ProtocolFixture, ROOT, WINDOWS, command


class MaintenanceTests(unittest.TestCase):
    def setUp(self): self.f = ProtocolFixture()
    def tearDown(self): self.f.close()

    def both(self, data, code=0, reason=''):
        f = self.f
        path = f.save(data)['path']
        drivers = [[sys.executable, '-B', str(ROOT / 'bin/lib/protocol_state.py'), 'validate', path]]
        if WINDOWS:
            native = f.argv('protocol-state', 'validate', path)
            # Native C4 manifests carry Windows file identities/modes. Python's
            # POSIX C4 implementation is not a Windows runtime. Report-only plan
            # cases exercise both parsers with exactly the same raw bytes.
            if data.get('artifact', {}).get('kind') in ('package', 'snapshot'):
                drivers = [native]
            else: drivers.append(native)
        results = []
        for argv in drivers:
            rc, out, err = command(argv, f.git.root)
            print(json.dumps(dict(argv=argv, code=rc, stdout=out, stderr=err)), flush=True)
            result = json.loads(out.splitlines()[1])
            self.assertEqual(rc, code, result)
            self.assertIn(reason, result.get('reason', ''))
            results.append(result)
        if len(results) > 1: self.assertEqual(results[0], results[1])
        if code == 0: f.state = results[0]['state']
        return results[0]

    def case(self, action='resume', **fields):
        return copy.deepcopy(dict(schema_version=1, action=action, state=self.f.state, **fields))

    def plan_step(self):
        f = self.f; f.state.update(phase=None, step='plan')
        f.state['plan_authors'] = f.state['provenance'] = [f.observation(f.assignment('plan-writer'))]
        return f.plan_artifact()

    def test_crlf_report_bytes_and_original_hash(self):
        f = self.f; art = self.plan_step()
        for role, family, extra in [('plan-reviewer', 'Anthropic', '## Проверка\nКириллица в отчёте'),
                                    ('implementer', 'OpenAI', 'FIX_EVIDENCE: {"tests":["T"],"commands":["C"],"outputs":["O"]}')]:
            data = f.report_input(role, family, artifact=art, round=2, extra=extra)
            p = Path(data['report']['path'])
            p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            data['report'] = f.reference(p)
            self.both(data)
            p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
            self.both(data, 1, 'hash mismatch')  # the same delivery, re-validated from its own prior state
            p.write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))

    def test_first_plan_writer_to_independent_review(self):
        f = self.f; f.plan.unlink(); f.git.git('reset', '-q')
        f.state.update(phase=None, step='plan', plan=dict(path=str(f.plan), sha256=None, structure=None))
        self.assertEqual(self.both(self.case())['state']['barrier'], 'awaiting_plan_writer')
        p = f.assignment('plan-writer'); p['dispatch_id'] = None
        self.both(self.case('dispatch', proposed=dict(p, role='implementer'), fleet=f.fleet()), 1, 'only a plan-writer')
        self.both(self.case('dispatch', proposed=p, fleet=f.fleet()))
        self.both(self.case('bind-dispatch', observation=f.observation(dict(p, dispatch_id='first-writer'), 'running')))
        f.plan.write_bytes(('---\nprotocol_version: 2\norca_run: fixture-run\nplan_base: ' + f.git.base +
                            '\nstatus: draft\ncontracts: []\nphases:\n  - id: F1\n    risk: none\n'
                            '    consumes: []\n    produces: []\n---\nActual first plan.\n').encode())
        art = f.plan_artifact()
        data = f.report_input('plan-writer', token='PLAN_WRITTEN', artifact=art, assignment=f.state['active'])
        self.both(data, 1, 'assigned plan mismatch')  # the writer's plan reaches the state only with its fresh reference
        data['plan'] = f.plan_ref()
        self.assertEqual(self.both(data)['state']['barrier'], 'awaiting_plan_review')
        reviewer = f.assignment('plan-reviewer', 'Anthropic'); reviewer['dispatch_id'] = None
        self.both(self.case('dispatch', proposed=reviewer, artifact=art, fleet=f.fleet()))
        self.both(self.case('bind-dispatch', observation=f.observation(dict(reviewer, dispatch_id='first-review'), 'running')))
        self.both(f.report_input('plan-reviewer', 'Anthropic', artifact=art, assignment=f.state['active']))
        self.assertEqual((len(f.state['provenance']), f.state['barrier']), (1, 'awaiting_commit'))

    def test_ledger_status_never_resolves_without_decision_or_check(self):
        f = self.f; art = self.plan_step()
        finding = dict(id='CV1', kind='cannot_verify', issue='assertion not run', location='plan.md',
                       check='fixture assertion command', expect='exit 0 proves the assertion')
        self.assertEqual(self.both(f.report_input('plan-reviewer', 'Anthropic', artifact=art, findings=[finding]))['state']['barrier'],
                         'awaiting_resolution')
        ledger = f.workspace / 'ledger.json'
        for status in ('fixed', 'resolved', 'closed', 'verified-by-controller'):
            ledger.write_text(json.dumps([dict(id='CV1', decision='ACCEPTED', status=status, closure=dict(path='/receipt', sha256='0' * 64))]))
            self.assertEqual(self.both(self.case(ledger=f.reference(ledger)))['state']['barrier'], 'awaiting_resolution')
        ledger.write_text(json.dumps([dict(id='CV1', decision='DEFER')]))
        self.assertEqual(self.both(self.case(ledger=f.reference(ledger)))['state']['barrier'], 'awaiting_commit')

    def test_cannot_verify_alone_is_not_a_blocking_verdict(self):
        f = self.f; art, coverage = f.package_ref()
        rc, result = f.verified_run(code="raise SystemExit(7)")
        self.assertEqual(rc, 7)
        finding = dict(id='CV-negative', kind='cannot_verify', issue='check failed', location='tracked.txt',
                       check=result['command'], expect='exit 0')
        data = f.report_input('review-control', 'Anthropic', token='REVIEW_BLOCKING', artifact=art, coverage=coverage, findings=[finding])
        self.both(data, 1, 'findings/verdict conflict')
        self.both(f.report_input('review-control', 'Anthropic', artifact=art, coverage=coverage, findings=[finding]))
        self.both(f.report_input('review-primary', 'Google', artifact=art, coverage=coverage))
        rc, passed = f.verified_run(code="print('assertion holds')"); self.assertEqual(rc, 0, passed)
        self.both(self.case('record-gate', artifact=art, evidence=[f.reference(Path(passed['run_dir']) / 'result.json')]))
        ledger = f.workspace / 'ledger.json'
        # The literal CHECK failed; another command's passing result does not close it either (review finding 5).
        for run in (result, passed):
            ledger.write_text(json.dumps([dict(id='CV-negative', check=str(Path(run['run_dir']) / 'result.json'))]))
            self.both(self.case('prepare-commit', artifact=art, fleet=f.fleet(), ledger=f.reference(ledger)), 1,
                      'unresolved findings: CV-negative')
        ledger.write_text(json.dumps([dict(id='CV-negative', decision='DEFER')]))
        self.both(self.case('prepare-commit', artifact=art, fleet=f.fleet(), ledger=f.reference(ledger)))

    def test_each_attempt_has_its_own_immutable_report(self):
        f = self.f; art = f.snapshot_ref(); saved = []
        for i in range(3):
            a = f.assignment(); a['fix'] = i > 0
            extra = '' if i == 0 else 'FIX_EVIDENCE: {"tests":["assertion"],"commands":["command"],"outputs":["pass"]}\n## Fix round 1\nCurrent fixes.'
            data = f.report_input(artifact=art, extra=extra, assignment=a)
            self.both(data); saved.append(data['report'])
        self.assertEqual(len({r['path'] for r in saved}), 3)
        self.assertEqual([r['report'] for r in f.state['accepted']], saved)
        reused = f.report_input(artifact=art, assignment=dict(f.assignment(), fix=True),
                                extra='FIX_EVIDENCE: {"tests":["a"],"commands":["c"],"outputs":["p"]}')
        event = json.loads(Path(reused['event']['path']).read_text())
        payload = json.loads(event['result']['message']['payload']); payload['reportPath'] = saved[0]['path']
        event['result']['message']['payload'] = json.dumps(payload)
        self.both(dict(reused, report=saved[0], event=f.save(event)), 1, 'report path already bound to an accepted attempt')


if __name__ == '__main__': unittest.main()

"""Short delivery paths over real helpers; no duplicate contention scenario."""
import copy
import json
from pathlib import Path
import unittest

from support import ProtocolFixture, read_json


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f = ProtocolFixture()
        self.addCleanup(self.f.close)

    def proposal(self, action, **fields):
        return copy.deepcopy(dict(schema_version=1, action=action, state=self.f.state, **fields))

    def valid(self, data):
        result = self.f.validate(data)
        self.assertEqual(result[0], 0, result)
        return result

    def test_fix_gate_package_reports_commit_and_resume(self):
        f = self.f; source = f.git.root / 'tracked.txt'
        source.write_text('broken\n'); f.git.git('add', 'tracked.txt')
        declaration = dict(id='delivery', checkpoint='integration', timeout_seconds=9,
            hermetic=True, independent_replay=True,
            command=f.python("from pathlib import Path; import sys; print('delivery check'); sys.exit(7 if Path('tracked.txt').read_text().strip() == 'broken' else 0)"))
        failed = f.gate([declaration], '--checkpoint', 'integration')
        self.assertNotEqual(failed[0], 0, failed)
        self.assertEqual(failed[1].splitlines()[0], 'GATE_FAIL', failed)
        source.write_text('fixed\n'); f.git.git('add', 'tracked.txt')
        passed = f.gate([declaration], '--checkpoint', 'integration')
        self.assertEqual(passed[0], 0, passed)
        self.assertEqual(passed[1].splitlines()[0], 'GATE_OK', passed)
        self.assertTrue(passed[1].splitlines()[1].startswith('verify:'), passed)
        results = [p for p in (f.git.root / '.superpowers/sdd').rglob('result.json')
                   if read_json(p).get('exit_code') == 0 and read_json(p).get('cwd') == str(f.git.root)]
        self.assertEqual(len(results), 1, results)
        result = read_json(results[0]); self.assertTrue(result['evidence']['valid'])
        self.assertIsNone(result['evidence']['origin_run_id'])
        art, coverage = f.package_ref()
        self.assertEqual(f.helper('validate-package', art['path'])[0], 0)
        self.valid(f.report_input('gate', artifact=art, extra='EVIDENCE: ' + json.dumps([f.reference(results[0])])))
        self.valid(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        data = f.report_input('review-control', 'Anthropic', artifact=art, coverage=coverage)
        resume = f.workspace / 'resume.json'; resume.write_bytes(b'previous resume')
        bad = copy.deepcopy(data); bad['state']['active']['artifact_id'] = 'wrong'
        self.assertNotEqual(f.validate(bad, output=resume)[0], 0)
        self.assertEqual(resume.read_bytes(), b'previous resume')
        self.valid(data)
        batch = [self.proposal('prepare-commit', artifact=art, fleet=f.fleet()),
                 self.proposal('confirm-commit', artifact=art, fleet=f.fleet(),
                               commit=dict(sha='f'*40, base=f.git.base, artifact=art))]
        outcomes = f.validate_many(batch, previous=True)
        self.assertEqual([r[0] for r in outcomes], [0,2], outcomes)
        self.assertEqual(f.state['barrier'], 'awaiting_commit')
        fact = f.commit(art)  # Only the owned fixture acquires this commit.
        outcomes = f.validate_many([self.proposal('confirm-commit', artifact=art, commit=fact, fleet=f.fleet()),
                                   self.proposal('resume')], previous=True, outputs=[resume, resume])
        self.assertEqual([r[0] for r in outcomes], [0,0], outcomes)
        self.assertEqual(f.state['barrier'], 'awaiting_final_review')
        self.assertEqual(len(f.state['phase_commits']), 1)

    def test_two_worktree_integration_and_incomplete_delivery_rejected(self):
        f = self.f
        producer = f.git.other / 'tracked.txt'; producer.write_text('producer\n')
        declaration = dict(id='two-worktree', checkpoint='integration', timeout_seconds=9,
            hermetic=True, independent_replay=True, inputs=[str(producer)],
            command=f.python("from pathlib import Path; assert Path('tracked.txt').read_text().strip() == 'candidate'; assert Path(" + repr(str(producer)) + ").read_text().strip() == 'producer'; print('INTEGRATED')"))
        result = f.gate([declaration], '--checkpoint', 'integration')
        self.assertEqual(result[0], 0, result)
        art, coverage = f.package_ref()
        self.assertEqual(f.helper('validate-package', art['path'])[0], 0)
        fact = f.commit(art); f.state['phase_commits'] = [dict(phase='F1', step='phase', sha=fact['sha'], base=fact['base'], candidate='recorded')]
        art, coverage = f.package_ref()
        # A partial review cannot satisfy both sides of the package contract.
        partial = copy.deepcopy(coverage); partial['contracts'] = []
        f.state['step'] = 'final-review'
        data = f.report_input('review-final', 'Anthropic', artifact=art, coverage=partial)
        self.valid(data)
        refused = f.validate(action='finish-checkpoint', artifact=art, fleet=f.fleet())
        self.assertEqual(refused[0], 2, refused)
        self.assertIn('incomplete contract', str(refused))
        self.assertNotEqual(f.state['barrier'], 'complete')
        # The same public gate must reject an unavailable required tool and a deadline.
        missing = dict(declaration, id='missing', environment=[{'tool':'orca-required-tool-does-not-exist','version_args':['--version']}])
        timed = dict(declaration, id='budget', timeout_seconds=0.3,
                     command=f.python("import time; time.sleep(2)"))
        for check in (missing, timed):
            result = f.gate([check], '--checkpoint', 'integration')
            self.assertNotEqual(result[0], 0, result)
            self.assertFalse(result[1].startswith('GATE_OK'), result)
        # A report cannot turn failed evidence into GATE_OK.
        paths = list((f.git.root / '.superpowers/sdd').rglob('result.json'))
        bad = next(p for p in paths if read_json(p).get('reason') == 'deadline')
        report = f.report_input('gate', artifact=art, extra='EVIDENCE: ' + json.dumps([f.reference(bad)]))
        self.assertNotEqual(f.validate(report)[0], 0)


if __name__ == '__main__': unittest.main()

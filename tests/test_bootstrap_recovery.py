"""First-plan retries: a failed first writer is retried; readers wait for the plan.

C6 v2 has no bootstrap step or request record: the plan step starts with the plan
path only. Receipts are synthetic; each native validator reads the same bytes.
"""
import copy
import json
import sys
import unittest

from support import ProtocolFixture, ROOT, WINDOWS, command, read_json


class FirstPlanRetryTests(unittest.TestCase):
    def setUp(self):
        f = self.f = ProtocolFixture(); f.plan.unlink(); f.git.git('reset', '-q')
        f.state.update(phase=None, step='plan', plan=dict(path=str(f.plan), sha256=None, structure=None))

    def tearDown(self): self.f.close()

    def case(self, action='resume', **fields):
        return copy.deepcopy(dict(schema_version=1, action=action, state=self.f.state, **fields))

    def both(self, data, code=0, reason=''):
        f = self.f; path = f.save(data)['path']
        drivers = [[sys.executable, '-B', str(ROOT / 'bin/lib/protocol_state.py'), 'validate', path]]
        if WINDOWS: drivers.append(f.argv('protocol-state', 'validate', path))
        results = []
        for argv in drivers:
            rc, out, err = command(argv, f.git.root); rows = out.splitlines()
            self.assertEqual(len(rows), 2, (rc, out, err)); result = json.loads(rows[1])
            print(json.dumps(dict(driver=argv[0], action=data['action'], code=rc, reason=result.get('reason'),
                                  barrier=result.get('state', {}).get('barrier'))), flush=True)
            results.append((rc, result))
        for rc, result in results:
            self.assertEqual(rc, code, result); self.assertIn(reason, result.get('reason', ''))
        if len(results) > 1: self.assertEqual(results[0], results[1])
        if not code: f.state = results[0][1]['state']
        return results[0][1]

    def writer(self):
        f = self.f; p = f.assignment('plan-writer'); p['dispatch_id'] = None
        self.assertEqual(self.both(self.case('dispatch', proposed=p, fleet=f.fleet()))['state']['barrier'], 'awaiting_writer')
        self.both(self.case('bind-dispatch', observation=f.observation(dict(p, dispatch_id=p['task_id'] + '-dispatch'), 'running')))

    def draft(self, orca_run='fixture-run'):
        f = self.f
        f.plan.write_bytes(('---\nprotocol_version: 2\norca_run: ' + orca_run + '\nplan_base: ' + f.git.base +
                            '\nstatus: draft\ncontracts: []\nphases:\n  - id: F1\n    risk: none\n'
                            '    consumes: []\n    produces: []\n---\nActual plan.\n').encode())
        return f.plan_artifact()

    def failed(self, token):
        f = self.f
        data = f.report_input('plan-writer', token=token, artifact=False, assignment=f.state['active'],
                              extra='## Reason\nA required fixture clarification is missing.' if token == 'BLOCKED' else '')
        event = read_json(data['event']['path']); message = event['result']['message']
        payload = json.loads(message['payload']); payload.update(outcome='failed', filesModified=[])
        message['payload'] = json.dumps(payload); data['event'] = f.save(event)
        return data

    def retry_then_review(self, failed):
        f = self.f
        self.assertEqual(self.both(self.case())['state']['barrier'], 'awaiting_plan_writer')
        reader = f.assignment('plan-reviewer', 'Anthropic'); reader['dispatch_id'] = None
        self.both(self.case('dispatch', proposed=reader, fleet=f.fleet()), 1, 'only a plan-writer may start before the plan exists')
        self.writer(); art = self.draft()
        data = f.report_input('plan-writer', token='PLAN_WRITTEN', artifact=art, assignment=f.state['active'])
        data['plan'] = f.plan_ref()
        self.assertEqual(self.both(data)['state']['barrier'], 'awaiting_plan_review')
        self.assertEqual([(r['role'], r['token']) for r in f.state['accepted']], [('plan-writer', failed), ('plan-writer', 'PLAN_WRITTEN')])
        self.both(self.case('dispatch', proposed=reader, artifact=art, fleet=f.fleet()))
        self.both(self.case('bind-dispatch', observation=f.observation(dict(reader, dispatch_id=reader['task_id'] + '-dispatch'), 'running')))
        self.assertEqual(self.both(f.report_input('plan-reviewer', 'Anthropic', artifact=art, assignment=f.state['active']))['state']['barrier'],
                         'awaiting_commit')
        self.assertEqual(len(f.state['provenance']), 2)

    def test_blocked_first_writer_can_resume_and_retry(self):
        self.writer(); self.both(self.failed('BLOCKED')); self.retry_then_review('BLOCKED')

    def test_needs_authorization_first_writer_can_resume_and_retry(self):
        self.writer(); self.both(self.failed('NEEDS_AUTHORIZATION')); self.retry_then_review('NEEDS_AUTHORIZATION')

    def test_first_plan_must_carry_the_supplied_run_and_base(self):
        f = self.f; self.writer(); art = self.draft(orca_run='other-run')
        data = f.report_input('plan-writer', token='PLAN_WRITTEN', artifact=art, assignment=f.state['active'])
        data['plan'] = f.plan_ref()
        self.both(data, 1, 'plan/run/base mismatch')
        f.plan.write_bytes(f.plan.read_bytes().replace(b'plan_base: ' + f.git.base.encode() + b'\n', b''))
        data['plan'] = f.plan_ref()
        self.both(data, 2, 'missing plan metadata: plan_base')


if __name__ == '__main__': unittest.main()

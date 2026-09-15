"""First-plan retries retain failed evidence and never unlock readers early.

Receipts are synthetic; each native validator reads the same immutable bytes.
"""
import copy
import json
from pathlib import Path
import sys
import unittest

from support import ProtocolFixture, ROOT, WINDOWS, command, read_json


class BootstrapRecoveryTests(unittest.TestCase):
    def setUp(self):
        f=self.f=ProtocolFixture();f.plan.unlink();f.git.git('reset','-q')
        request=dict(schema_version=1,run_id='fixture-run',worktree_id='fixture-worktree',
                     plan_base=f.git.base,plan_path=str(f.plan),request='Implement the fixture task.')
        f.state.update(plan=None,phase=None,step='bootstrap',authorization=f.save(request))

    def tearDown(self): self.f.close()

    def case(self, action='resume', **fields):
        return copy.deepcopy(dict(schema_version=1,action=action,state=self.f.state,**fields))

    def both(self, data, code=0, reason=''):
        f=self.f;path=f.save(data)['path']
        drivers=[[sys.executable,'-B',str(ROOT/'bin/lib/protocol_state.py'),'validate',path]]
        if WINDOWS: drivers.append(f.argv('protocol-state','validate',path))
        results=[]
        for argv in drivers:
            rc,out,err=command(argv,f.git.root);rows=out.splitlines()
            self.assertEqual(len(rows),2,(rc,out,err));result=json.loads(rows[1])
            print(json.dumps(dict(driver=argv[0],action=data['action'],code=rc,
                                  reason=result.get('reason'),step=result.get('state',{}).get('step'))),flush=True)
            results.append((rc,result))
        for rc,result in results:
            self.assertEqual(rc,code,result);self.assertIn(reason,result.get('reason',''))
        if len(results)>1: self.assertEqual(results[0],results[1])
        if not code: f.state=results[0][1]['state']
        return results[0][1]

    def request_artifact(self): return dict(self.f.state['authorization'],kind='request')

    def writer(self):
        f=self.f;p=f.assignment('plan-writer');p['dispatch_id']=None
        self.both(self.case('dispatch',proposed=p,artifact=self.request_artifact(),fleet=f.fleet()))
        bound=dict(p,dispatch_id=p['task_id']+'-dispatch')
        self.both(self.case('bind-dispatch',observation=f.observation(bound,'running')))

    def draft(self, missing_hash=False):
        f=self.f
        text=('---\nprotocol_version: 2\norca_run: fixture-run\nplan_base: '+f.git.base+'\n'+
              ('' if missing_hash else 'request_sha256: '+f.state['authorization']['sha256']+'\n')+
              'status: draft\ncontracts: []\nphases:\n  - id: F1\n    risk: none\n    base: '+f.git.base+
              '\n    consumes: []\n    produces: []\n---\nActual plan.\n')
        f.plan.write_bytes(text.encode());archive=Path(f.save('', '.md')['path'])
        archive.write_bytes(f.plan.read_bytes())
        return f.reference(f.plan),dict(f.reference(archive),kind='plan',source_path=str(f.plan))

    def response(self, token, art, plan=None):
        f=self.f;data=f.report_input('plan-writer',token=token,artifact=art,assignment=f.state['active'],
                                    extra='## Reason\nA required fixture clarification is missing.' if token=='BLOCKED' else '')
        if plan: data['plan']=plan
        if token in ('BLOCKED','NEEDS_AUTHORIZATION'):
            event=read_json(data['event']['path']);message=event['result']['message']
            payload=json.loads(message['payload']);payload.update(outcome='failed',filesModified=[])
            message['payload']=json.dumps(payload);data['event']=f.save(event)
        return data

    def reject_reader(self, art):
        p=self.f.assignment('plan-reviewer','Anthropic');p['dispatch_id']=None
        self.both(self.case('dispatch',proposed=p,artifact=art,fleet=self.f.fleet()),1,'bootstrap')

    def retry_then_review(self, old_report):
        f=self.f;old_bytes=Path(old_report['path']).read_bytes()
        self.both(self.case());self.reject_reader(self.request_artifact())
        self.writer();plan,art=self.draft();self.both(self.response('PLAN_WRITTEN',art,plan))
        self.assertEqual(f.state['step'],'plan')
        self.assertEqual(f.state['report_history'][0]['report'],old_report)
        self.assertEqual(Path(old_report['path']).read_bytes(),old_bytes)
        p=f.assignment('plan-reviewer','Anthropic');p['dispatch_id']=None
        self.both(self.case('dispatch',proposed=p,artifact=art,fleet=f.fleet()))
        bound=dict(p,dispatch_id=p['task_id']+'-dispatch')
        self.both(self.case('bind-dispatch',observation=f.observation(bound,'running')))
        self.both(f.report_input('plan-reviewer','Anthropic',artifact=art,assignment=f.state['active']))
        self.assertEqual(len(f.state['provenance']),2)

    def test_blocked_first_writer_can_resume_and_retry(self):
        self.writer();data=self.response('BLOCKED',self.request_artifact());self.both(data)
        self.retry_then_review(data['report'])

    def test_needs_authorization_first_writer_can_resume_and_retry(self):
        self.writer();data=self.response('NEEDS_AUTHORIZATION',self.request_artifact());self.both(data)
        self.retry_then_review(data['report'])

    def test_missing_request_hash_has_identical_unverifiable_result(self):
        self.writer();plan,art=self.draft(missing_hash=True)
        self.both(self.response('PLAN_WRITTEN',art,plan),2,'missing plan metadata: request_sha256')

    def test_failed_bootstrap_history_requires_unchanged_settlement_and_report(self):
        f=self.f;self.writer();data=self.response('BLOCKED',self.request_artifact());self.both(data)
        f.state.pop('report_history')  # Complete older accepted history is sufficient.
        self.both(self.case());complete=copy.deepcopy(f.state)
        f.state['provenance']=[]
        self.both(self.case(),2,'unverifiable bootstrap history')
        f.state=copy.deepcopy(complete)
        report=Path(data['report']['path']);report.write_bytes(report.read_bytes()+b'changed report')
        self.both(self.case(),1,'hash mismatch')

    def test_failed_format_correction_keeps_bootstrap_until_accepted_plan(self):
        f=self.f;self.writer();plan,art=self.draft();data=self.response('PLAN_WRITTEN',art,plan)
        report=Path(data['report']['path'])
        report.write_bytes('\n'.join(l for l in report.read_text(encoding='utf-8').splitlines()
                                    if not l.startswith('BINDING:')).encode())
        data['report']=f.reference(report);self.both(data,1,'BINDING')
        p=f.assignment('plan-writer');p['dispatch_id']=None
        self.both(self.case('format-correction',proposed=p,plan=plan,artifact=art,report=data['report'],
                            observation=data['observation'],outcome='succeeded',files_modified=[],fleet=f.fleet()))
        bound=dict(p,dispatch_id=p['task_id']+'-dispatch')
        self.both(self.case('bind-dispatch',observation=f.observation(bound,'running')))
        failed=self.response('BLOCKED',art);self.both(failed)
        self.reject_reader(art)
        self.assertEqual(f.state['step'],'bootstrap')
        protected=copy.deepcopy(f.state['protected_reports'])
        self.retry_then_review(failed['report'])
        self.assertEqual(f.state['protected_reports'],protected)


if __name__=='__main__': unittest.main()

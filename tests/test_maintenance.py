"""Maintenance regressions: identical byte inputs through Python and native C6."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

from support import ProtocolFixture, ROOT, WINDOWS, command, read_json


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

    def native(self, data, code=0, reason=''):
        rc, token, result = self.f.validate(data)
        print(json.dumps(dict(action=data['action'], code=rc, token=token,
                              reason=result.get('reason'), barrier=result.get('state', {}).get('barrier'))), flush=True)
        self.assertEqual(rc, code, result); self.assertIn(reason, result.get('reason', ''))
        return result

    def test_crlf_report_bytes_and_original_hash(self):
        f = self.f; f.state.update(phase=None, step='plan')
        f.state['provenance'] = [f.observation(f.assignment('plan-writer'))]
        for role, family, extra in [('plan-reviewer', 'Anthropic', '## Проверка\nКириллица в отчёте'),
                                    ('implementer', 'OpenAI', 'FIX_EVIDENCE: {"tests":["T"],"commands":["C"],"outputs":["O"]}')]:
            data = f.report_input(role, family, artifact=dict(f.state['plan'], kind='plan'), round=2, extra=extra)
            p = Path(data['report']['path'])
            p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            data['report'] = f.reference(p)
            self.both(data)
            p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
            self.both(data, 1, 'hash mismatch')
            p.write_bytes(p.read_bytes().replace(b'\n', b'\r\n'))

    def test_bootstrap_request_to_plan_and_independent_review(self):
        f = self.f; f.plan.unlink(); f.git.git('reset', '-q')
        request = dict(schema_version=1, run_id='fixture-run', worktree_id='fixture-worktree',
                       plan_base=f.git.base, plan_path=str(f.plan), request='Implement the authorized fixture task.')
        f.state.update(plan=None, phase=None, step='bootstrap', authorization=f.save(request))
        self.both(self.case())
        art = dict(f.state['authorization'], kind='request')
        p = f.assignment('plan-writer'); p['dispatch_id'] = None
        bad = dict(p, role='implementer')
        self.both(self.case('dispatch', proposed=bad, artifact=art, fleet=f.fleet()), 1, 'bootstrap')
        self.both(self.case('dispatch', proposed=p, artifact=art, fleet=f.fleet()))
        bound = dict(p, dispatch_id='bootstrap-writer')
        self.both(self.case('bind-dispatch', observation=f.observation(bound, 'running')))
        text = ('---\nprotocol_version: 2\norca_run: fixture-run\nplan_base: '+f.git.base+
                '\nrequest_sha256: '+f.state['authorization']['sha256']+
                '\nstatus: draft\ncontracts: []\nphases:\n  - id: F1\n    risk: none\n    base: '+f.git.base+
                '\n    consumes: []\n    produces: []\n---\nActual first plan.\n')
        f.plan.write_bytes(text.encode())
        plan = f.reference(f.plan)
        data = f.report_input('plan-writer', token='PLAN_WRITTEN', artifact=dict(plan, kind='plan'), assignment=f.state['active'])
        data['plan'] = plan
        if self._testMethodName.endswith('_format_correction'):
            report=Path(data['report']['path']);text=report.read_text(encoding='utf-8')
            report.write_bytes('\n'.join(l for l in text.splitlines() if not l.startswith('BINDING:')).encode())
            data['report']=f.reference(report)
            self.both(data,1,'BINDING')
            proposed=f.assignment('plan-writer');proposed['dispatch_id']=None
            correction=self.case('format-correction',proposed=proposed,plan=plan,artifact=dict(plan,kind='plan'),
                                 report=data['report'],observation=data['observation'],outcome='succeeded',files_modified=[],fleet=f.fleet())
            self.both(correction)
            bound=dict(proposed,dispatch_id='corrected-bootstrap-writer')
            self.both(self.case('bind-dispatch',observation=f.observation(bound,'running')))
            data=f.report_input('plan-writer',token='PLAN_WRITTEN',artifact=dict(plan,kind='plan'),assignment=f.state['active'])
        self.both(data)
        self.assertEqual(f.state['step'], 'plan')
        reviewer=f.assignment('plan-reviewer','Anthropic');reviewer['dispatch_id']=None
        self.both(self.case('dispatch',proposed=reviewer,artifact=dict(plan,kind='plan'),fleet=f.fleet()))
        bound=dict(reviewer,dispatch_id='first-independent-review')
        self.both(self.case('bind-dispatch',observation=f.observation(bound,'running')))
        self.both(f.report_input('plan-reviewer', 'Anthropic', artifact=dict(plan, kind='plan'),assignment=f.state['active']))
        self.assertEqual(len(f.state['provenance']), 1)

    def test_bootstrap_report_format_correction(self):
        self.test_bootstrap_request_to_plan_and_independent_review()

    def test_closing_status_without_check_never_removes_barrier(self):
        f = self.f; f.state.update(phase=None, step='plan')
        f.state['provenance'] = [f.observation(f.assignment('plan-writer'))]
        art = dict(f.state['plan'], kind='plan')
        finding = dict(id='CV1', kind='cannot_verify', issue='assertion not run', location='tracked.txt:1',
                       check='fixture assertion command', expect='exit 0 proves the assertion')
        self.both(f.report_input('plan-reviewer', 'Anthropic', artifact=art, findings=[finding]))
        original = copy.deepcopy(f.state)
        for status in ('fixed', 'resolved', 'closed', 'verified-by-controller'):
            f.state = copy.deepcopy(original)
            f.state['ledger'] = f.save([dict(id='CV1', decision='ACCEPTED', status=status)])
            self.both(self.case(), 2, 'closure evidence')

    def test_check_closure_positive_negative_stale_mutated_wrong_and_idempotent(self):
        f = self.f; f.state.update(phase=None, step='plan')
        f.state['provenance'] = [f.observation(f.assignment('plan-writer'))]
        result_ref = f.gate_evidence()[0]; result = read_json(result_ref['path'])
        art = dict(f.state['plan'], kind='plan')
        finding = dict(id='CV1', kind='cannot_verify', issue='assertion not run', location='plan.md',
                       check=result['command'], expect='exit 0 proves the assertion')
        self.native(f.report_input('plan-reviewer', 'Anthropic', artifact=art, findings=[finding]))
        original = copy.deepcopy(f.state)
        proof = dict(schema_version=1, finding_id='CV1', report=f.state['accepted'][0]['report'],
                     artifact=art, result=result_ref, command=finding['check'], expect=finding['expect'])
        for status in ('fixed','resolved','closed','verified-by-controller'):
            f.state = copy.deepcopy(original)
            f.state['ledger'] = f.save([dict(id='CV1', status=status, decision='ACCEPTED', closure=f.save(proof))])
            one = self.native(self.case())['state']
            self.assertEqual(one['closed_ledger_ids'], ['CV1'])
            self.assertEqual(self.native(self.case())['state'], one)
            self.native(self.case('prepare-commit', artifact=f.snapshot_ref(), fleet=f.fleet()))
        for key, value, reason in [('finding_id','OTHER','finding binding'),
                                    ('command','different command','CHECK binding'),
                                    ('expect','different expectation','CHECK binding'),
                                    ('result',dict(result_ref, sha256='0'*64),'hash mismatch')]:
            f.state = copy.deepcopy(original)
            f.state['ledger'] = f.save([dict(id='CV1', status='fixed', closure=f.save(dict(proof, **{key:value})))])
            self.native(self.case(), 1, reason)
        f.state = copy.deepcopy(original)
        f.state['ledger'] = f.save([dict(id='CV1', status='fixed', closure=f.save(proof))])
        log = Path(result['stdout_log']); before = log.read_bytes(); log.write_bytes(b'mutated')
        self.native(self.case(), 1, 'closure CHECK evidence'); log.write_bytes(before)
        (f.git.root/'tracked.txt').write_bytes(b'stale candidate')
        self.native(self.case(), 1, 'stale closure source')

    def test_negative_check_and_review_ok_cannot_verify_barrier(self):
        f = self.f; art, coverage = f.package_ref()
        rc, result = f.verified_run(code="raise SystemExit(7)")
        self.assertEqual(rc, 7)
        finding = dict(id='CV-negative', kind='cannot_verify', issue='check failed', location='tracked.txt',
                       check=result['command'], expect='exit 0')
        self.native(f.report_input('review-control','Anthropic',artifact=art,coverage=coverage,findings=[finding]))
        self.assertEqual(f.state['barrier'], 'awaiting_resolution')
        proof = dict(schema_version=1, finding_id=finding['id'], report=f.state['accepted'][0]['report'], artifact=art,
                     result=f.reference(Path(result['run_dir'])/'result.json'), command=finding['check'], expect=finding['expect'])
        f.state['ledger'] = f.save([dict(id=finding['id'], status='resolved', closure=f.save(proof))])
        self.native(self.case('prepare-commit', artifact=art, fleet=f.fleet()), 1, 'negative closure CHECK')
        # An altered copy cannot borrow the unmodified negative run's seal.
        forged=dict(proof,result=f.save(dict(result,exit_code=0)))
        for status in ('fixed','resolved','closed','verified-by-controller'):
            f.state['ledger']=f.save([dict(id=finding['id'],status=status,closure=f.save(forged))])
            self.native(self.case(),1,'closure CHECK evidence')
        f.state['ledger'] = None
        data=f.report_input('review-control','Anthropic',token='REVIEW_BLOCKING',artifact=art,coverage=coverage,findings=[finding])
        self.native(data, 1, 'findings/verdict conflict')

    def test_three_immutable_reports_same_round_and_retained_terminal(self):
        f=self.f; art=f.snapshot_ref(); saved=[]
        for i in range(3):
            a=f.assignment();a['fix']=i>0
            extra='' if i==0 else 'FIX_EVIDENCE: {"tests":["assertion"],"commands":["command"],"outputs":["pass"]}\n## Fix round 1\nCurrent fixes.'
            data=f.report_input(artifact=art,extra=extra,assignment=a)
            self.native(data);saved.append(data['report'])
        self.assertEqual(len({r['path'] for r in saved}),3)
        self.assertEqual(len(f.state['report_history']),3)
        for r in saved: self.assertEqual(f.reference(r['path']),r)
        p=Path(saved[0]['path']);p.write_bytes(p.read_bytes()+b'mutated accepted report')
        self.native(self.case(),1,'hash mismatch')

    def test_ordinary_plan_finding_closes_with_fix_and_independent_review_without_check(self):
        f=self.f;f.state.update(phase=None,step='plan')
        f.state['provenance']=[f.observation(f.assignment('plan-writer'))]
        def archive():
            path=Path(f.save('', '.md')['path']);path.write_bytes(f.plan.read_bytes())
            return dict(f.reference(path),kind='plan',source_path=str(f.plan))
        art=archive()
        finding=dict(id='B1',kind='blocking',issue='wording changes the scope',location='plan.md',
                     criterion='scope',**{'class':'MUST_FIX_NOW'},change='correct wording',risk='none')
        data=f.report_input('plan-reviewer','Anthropic',token='CHANGES_REQUESTED',artifact=art,findings=[finding])
        self.both(data);origin=data['report']
        f.plan.write_bytes(f.plan.read_bytes()+b'Corrected scope wording.\n');f.state['plan']=f.reference(f.plan)
        repaired=archive()
        fixed=dict(findings=[dict(id='B1',report=origin)])
        data=f.report_input('plan-reviser',token='REVISED',artifact=repaired,round=2,extra='FIX_EVIDENCE: '+json.dumps(fixed))
        self.both(data);fix=data['report']
        data=f.report_input('plan-reviewer','Anthropic',artifact=repaired,round=2)
        self.both(data);review=data['report']
        self.assertEqual(f.state['barrier'],'awaiting_resolution')
        proof=dict(schema_version=1,finding_id='B1',report=origin,artifact=repaired,fix_report=fix,review_report=review)
        for status in ('fixed','resolved','closed','verified-by-controller'):
            f.state['ledger']=f.save([dict(id='B1',status=status,closure=f.save(proof))])
            self.both(self.case());self.assertEqual(f.state['closed_ledger_ids'],['B1'])
        f.state['ledger']=f.save([dict(id='B1',status='fixed',closure=f.save(dict(proof,fix_report=review)))])
        self.both(self.case(),1,'successful fix')

    def tracks(self, conflict=False):
        f=self.f
        phase=lambda i,cons='[]',prod='[]': ('  - id: F'+str(i)+'\n    risk: none\n    base: '+f.git.base+
                                            '\n    consumes: '+cons+'\n    produces: '+prod+'\n')
        f.plan.write_bytes(('---\nprotocol_version: 2\norca_run: fixture-run\nplan_base: '+f.git.base+
                           '\ncontracts: ["C1"]\nphases:\n'+phase(1,prod='["C1"]' if conflict else '[]')+
                           phase(2,cons='["C1"]' if conflict else '[]')+phase(3)+'---\nTracks.\n').encode())
        f.git.git('add','--all')
        f.git.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','-c','core.hooksPath=','commit','-qm','group start')
        head=f.git.git('rev-parse','HEAD').strip();f.state['plan']=f.reference(f.plan)
        group=dict(schema_version=1,run_id='fixture-run',parent_worktree=str(f.git.root),parent_head=head,
                   plan=f.state['plan'],tracks=[])
        for i in (1,2,3):
            p=f.base/('child worktree '+str(i))
            f.git.git('worktree','add','--detach','-q',str(p),head)
            group['tracks'].append(dict(id='T'+str(i),worktree=str(p),worktree_id='child-'+str(i),phase='F'+str(i),base=head))
        f.state.update(phase=None,step='plan')
        return group

    def test_track_count_git_records_unrelated_bad_base_and_target_binding(self):
        f=self.f;group=self.tracks();first=copy.deepcopy(group);first['tracks']=first['tracks'][:2]
        f.state['track_group']=f.save(first);self.both(self.case())
        f.state['track_group']=f.save(group);self.both(self.case(),1,'two active child tracks')
        bad=copy.deepcopy(first);bad['tracks'][0]['base']=f.git.base
        f.state['track_group']=f.save(bad);self.both(self.case(),1,'track BASE')
        f.state['track_group']=f.save(first)
        f.state.update(worktree=first['tracks'][0]['worktree'],worktree_id='wrong-id',phase='F1',base=first['parent_head'])
        self.both(self.case(),2,'TARGET track binding')

    def test_track_resume_merged_completed_and_incomplete(self):
        f=self.f;group=self.tracks();t=group['tracks'][0];path=Path(t['worktree'])
        # Real accepted staged snapshot and commit in the first child, then merge.
        (path/'tracked.txt').write_bytes(b'completed track\n')
        f.git.git('-C',str(path),'add','tracked.txt')
        saved_root=f.git.root; saved_workspace=f.workspace
        f.git.root=path;f.workspace=path/'.superpowers/sdd/runner-fixture';f.workspace.mkdir(parents=True)
        (f.workspace.parent/'.gitignore').write_bytes(b'*\n')
        art=f.snapshot_ref();fact=f.commit(art);f.git.root=saved_root;f.workspace=saved_workspace
        f.git.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false','-c','core.hooksPath=',
                  'merge','--no-ff','-m','merge completed track',fact['sha'])
        f.state['track_group']=f.save(group);f.state['track_commits']=[dict(fact,track_id=t['id'])]
        self.native(self.case());self.assertEqual(len(f.state['track_commits']),1)
        self.native(self.case())

    def test_parallel_producer_consumer_conflict(self):
        f=self.f;group=self.tracks(conflict=True);group['tracks']=group['tracks'][:2]
        f.state['track_group']=f.save(group)
        self.both(self.case(),1,'producer/consumer conflict')


if __name__ == '__main__': unittest.main()

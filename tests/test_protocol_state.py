"""C6 bounded deterministic protocol inputs and real owned Git commit barriers."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import unittest

from support import ProtocolFixture, command, read_json, write_json


class ProtocolTests(unittest.TestCase):
    def setUp(self): self.f = ProtocolFixture(quickfix=self._testMethodName.startswith('test_quickfix'))
    def tearDown(self): self.f.close()

    def valid(self, data=None, **kwargs):
        r = self.f.validate(data, **kwargs)
        self.assertEqual(r[:2], (0, 'VALID'), r)
        return r[2]

    def reject(self, data=None, code=1, contains='', **kwargs):
        f = self.f; output = f.workspace / 'preserved-resume.json'
        output.write_bytes(b'previous complete record')
        r = f.validate(data, output=output, **kwargs)
        self.assertEqual(r[0], code, r)
        self.assertIn(contains, r[2]['reason'])
        self.assertEqual(output.read_bytes(), b'previous complete record')
        return r[2]

    def case(self, data=None, action='resume', **fields):
        return copy.deepcopy(data or dict(schema_version=1, action=action, state=self.f.state, **fields))

    def batch(self, cases, previous=False):
        # Each rejection still exercises RESUME_OUT preservation through the real CLI.
        outputs=[Path(self.f.save('previous complete record')['path']) if code else None for _,code,_ in cases]
        results=self.f.validate_many([data for data,_,_ in cases], previous=previous, outputs=outputs)
        for result,(_,code,why),output in zip(results,cases,outputs):
            self.assertEqual(result[:2],(code,['VALID','INVALID','UNVERIFIABLE'][code]),result)
            if code:
                self.assertIn(why,result[2]['reason'])
                self.assertEqual(output.read_bytes(),b'previous complete record')
        return [r[2] for r in results]

    def test_accept_resume_binding_hash_and_stale_source(self):
        f = self.f; data = f.report_input(); out = f.workspace / 'resume.json'
        result = self.valid(data, output=out)
        self.assertEqual(result['state'], read_json(out))
        self.assertEqual(f.state['barrier'], 'awaiting_gate')
        self.assertEqual(len(f.state['accepted']), 1)
        bad = copy.deepcopy(data)
        report = Path(bad['report']['path']); text = report.read_text()
        report.write_text(text.replace('"role": "implementer"', '"role": "gate"'))
        stale=copy.deepcopy(bad)
        bad['report'] = f.reference(report)
        for r,why in zip(f.validate_many([stale,bad]),['hash mismatch','binding']):
            self.assertEqual(r[0],1,r);self.assertIn(why,r[2]['reason'])
        report.write_text(text); bad['report'] = f.reference(report)
        (f.git.root / 'tracked.txt').write_text('late hook mutation')
        self.reject(bad, contains='stale snapshot')

    def test_subject_leads_with_the_report_token_and_may_explain_after_it(self):
        # Bureau F4 r5 (2026-09-28): the worker sent "DONE_WITH_CONCERNS: R4-B2 fixed, ..." while report line 1
        # was the bare token; exact equality rejected it and format-correction found no report defect.
        f = self.f; data = f.report_input(); good = read_json(data['event']['path'])['result']['message']
        def with_subject(subject):
            msg = copy.deepcopy(good); msg['subject'] = subject
            case = copy.deepcopy(data); case['event'] = f.save(dict(ok=True, result=dict(message=msg))); return case
        self.batch([(with_subject(s), 1, 'report path/subject mismatch') for s in
                    ('DONE_WITH_CONCERNS', 'DONEX', 'DONE_WITH_CONCERNS: DONE', '', ': DONE', ' DONE')])
        self.valid(with_subject('DONE: R4-B2 fixed, R4-B1 prepared without launch'))
        self.assertEqual(len(f.state['accepted']), 1)

    def test_duplicate_stale_heartbeat_empty_wait_and_whole_delivery(self):
        f = self.f; data = f.report_input(); good = read_json(data['event']['path'])['result']['message']
        old = copy.deepcopy(good); old['id'] = 'old'; old['payload'] = json.dumps(dict(taskId='old', dispatchId='old'))
        beat = dict(id='beat', type='heartbeat', payload=None)
        data['event'] = f.save(dict(ok=True, result=dict(deliveryId='delivery-fixture', messages=[old, beat, good])))
        cases=[dict(data,message_id=x) for x in ['old','beat',good['id'],good['id']]]
        cases.append(dict(data,event=f.save(dict(ok=True,result=dict(messages=[],timedOut=True)))))
        results=f.validate_many(cases,previous=True)
        self.assertTrue(all(r[0]==0 for r in results),results)
        self.assertEqual([r[2]['decision'] for r in results],['stale','not-completion','accepted','duplicate','not-completion'])
        self.assertEqual(results[0][2]['state']['accepted'],[])
        self.assertEqual(results[1][2]['state']['processed']['deliveries'],[])
        self.assertEqual(results[2][2]['state']['processed']['deliveries'],['delivery-fixture'])
        self.assertEqual(len(f.state['accepted']),1)

    def test_role_format_fields_risk_and_single_correction(self):
        f = self.f; art, coverage = f.package_ref()
        data = f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage)
        p = Path(data['report']['path']); p.write_text(p.read_text().replace('SPEC: OK\n', ''))
        data['report'] = f.reference(p)
        defective=self.case(data)
        proposed = f.assignment('review-primary', 'Anthropic'); proposed['dispatch_id'] = None
        fix = dict(schema_version=1, action='format-correction', state=f.state, proposed=proposed,
                   artifact=art, report=data['report'], observation=data['observation'], outcome='succeeded', files_modified=[], fleet=f.fleet())
        bound = dict(proposed, dispatch_id='corrected-dispatch')
        results=self.batch([(defective,1,'SPEC/QUALITY'),(self.case(fix),0,''),
                           (self.case(action='bind-dispatch', observation=f.observation(bound)),0,'')],previous=True)
        self.assertEqual(results[0]['next_action'],'format-correction')
        self.assertEqual(f.state['rounds']['fused_review'], 0)
        data = f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage)
        f.state['format_corrections'][f.state['active']['dispatch_id']] = 1
        p = Path(data['report']['path']); p.write_text(p.read_text().replace('QUALITY: OK\n', '')); data['report'] = f.reference(p)
        repeated=self.case(data)
        finding = dict(id='F', kind='blocking', issue='defect', location='tracked.txt:1',
                       authorization_relation='outside plan', why_now='breaks contract', minimal_fix='remove')
        data = f.report_input('review-control', 'Anthropic', 'REVIEW_BLOCKING', art, coverage, [finding])
        f.state.pop('format_lock', None)
        missing=self.case(data)
        finding['risk'] = 'SECURITY'
        data = f.report_input('review-control', 'Anthropic', 'REVIEW_BLOCKING', art, coverage, [finding])
        results=self.batch([(repeated,1,'SPEC/QUALITY'),(missing,1,'finding fields'),(self.case(data),0,'')])
        self.assertEqual(results[0]['next_action'],'protocol-blocker')
        self.assertEqual(results[2]['decision'],'risk-escalation')

    def test_plan_simplicity_risk_contracts_legacy_and_fix_evidence(self):
        f = self.f
        data = f.report_input('implementer', round=2)
        cases=[(self.case(data),1,'FIX_EVIDENCE')]
        f.state['phase'] = None; f.state['step'] = 'plan'
        data = f.report_input('plan-reviewer', 'Anthropic', artifact=dict(f.state['plan'], kind='plan'))
        p = Path(data['report']['path']); p.write_text(p.read_text().replace('SIMPLICITY: OK', ''))
        data['report'] = f.reference(p); cases.append((self.case(data),1,'SIMPLICITY'))
        original = f.plan.read_text()
        for old, new, code, reason in [('risk: none', 'risk: mystery', 1, 'risk'),
                                      ('consumes: []', 'consumes: ["C1"]', 1, 'earlier producer'),
                                      ('protocol_version: 2', 'protocol_version: 1', 2, 'legacy')]:
            s=copy.deepcopy(f.state);s['plan']=f.save(original.replace(old,new),'.md')
            cases.append((dict(schema_version=1,action='resume',state=s),code,reason))
        s=copy.deepcopy(f.state);s['active']=None;s['plan']=f.save(original.replace('    risk: none\n',''),'.md')
        cases.append((dict(schema_version=1,action='resume',state=s),1,'risk'))
        self.assertEqual(self.batch(cases)[-1]['next_action'],'format-correction')

    def test_all_caps_and_unverified_done_barrier(self):
        f = self.f
        cases=[]
        for key, cap in [('plan_review',4), ('fused_review',4), ('final_review',2), ('gate_fix',2)]:
            s=copy.deepcopy(f.state);s['rounds'][key]=cap+1
            cases.append(dict(schema_version=1,action='resume',state=s))
            f.state['rounds'][key]=cap
        s=copy.deepcopy(f.state);s['format_corrections']['bad']=2
        cases.append(dict(schema_version=1,action='resume',state=s))
        f.state['format_corrections'] = {}
        art=f.snapshot_ref(); p=f.assignment('plan-reviewer', 'Anthropic', round=5);p['dispatch_id']=None
        self.batch([(d,1,'cap') for d in cases]+[(self.case(action='dispatch',proposed=p,artifact=art,fleet=f.fleet()),1,'round cap/sequence')])
        f.plan.write_text(f.plan.read_text().replace('status: implementing', 'status: done'))
        f.state['plan'] = f.reference(f.plan); f.state['step'] = 'completion'
        pending=self.case()
        f.state['commit_barrier'] = dict(confirmed_sha=f.git.base)
        results=self.batch([(pending,0,''),(self.case(),2,'unverified commit barrier')])
        self.assertEqual(results[0]['state']['barrier'],'awaiting_completion_commit')

    def test_fleet_live_unknown_external_retained_pages_and_pending(self):
        f = self.f; artifact = f.snapshot_ref(); proposed = f.assignment(family='Anthropic'); proposed['dispatch_id'] = None
        w = dict(dispatchId='prior', dispatchStatus='running', terminalState='retained', resource=dict(ownershipState='owned'),
                 projection=dict(workspace=dict(id='fixture-worktree'), evidence=dict(durable=True), liveness=dict(verdict='live')))
        cases=[]
        for change, why in [({}, 'prior writer'), ({'dispatchStatus':'unknown'}, 'prior writer'),
                            ({'terminalState':'release_unknown'}, 'release'), ({'resource':dict(ownershipState='external')}, 'external')]:
            cases.append((dict(schema_version=1,action='dispatch',state=f.state,proposed=proposed,artifact=artifact,fleet=f.fleet([dict(w,**change)])),why))
        cases.append((dict(schema_version=1,action='dispatch',state=f.state,proposed=proposed,artifact=artifact,
                          fleet=f.fleet([],total=1,hasMore=True,nextCursor='next')),'incomplete fleet'))
        no_workspace=dict(w,projection=dict(w['projection'],workspace=None))
        cases.append((self.case(action='dispatch',proposed=proposed,artifact=artifact,fleet=f.fleet([no_workspace])),'unknown fleet workspace'))
        self.batch([(self.case(d),2,why) for d,why in cases])
        cases=[]
        for status in ['completed','failed']:
            cases.append((self.case(action='dispatch',proposed=proposed,artifact=artifact,
                                   fleet=f.fleet([dict(no_workspace,dispatchStatus=status)])),0,''))
        for change in [dict(dispatchStatus='unknown'),dict(dispatchStatus='completed',terminalState='release_pending'),
                       dict(dispatchStatus='failed',resource=dict(ownershipState='user_owned'))]:
            cases.append((self.case(action='dispatch',proposed=proposed,artifact=artifact,
                                   fleet=f.fleet([dict(no_workspace,**change)])),2,'unknown fleet workspace'))
        original=copy.deepcopy(f.state);self.batch(cases);f.state=original
        fleet = f.fleet([dict(w, dispatchStatus='completed')])
        actual = dict(proposed, dispatch_id='new-bound');start=f.start_receipt(actual)
        observed=f.observation(actual,'running',model=None,start=start)
        bind=self.case(action='bind-dispatch',observation=observed)
        results=self.batch([(self.case(action='dispatch',proposed=proposed,artifact=artifact,fleet=fleet),0,''),
                            (self.case(action='dispatch',proposed=proposed,artifact=artifact,fleet=f.fleet()),2,'unbound writer intent'),
                            (bind,0,'')],previous=True)
        self.assertEqual(f.state['write_ownership'], ['new-bound'])
        bind['state']=results[0]['state'];cases=[]
        for key in ['runId','taskId','dispatchId']:
            wrong=read_json(start['path']);wrong['result'][key]='stale-fixture-id'
            cases.append((dict(bind,observation=dict(observed,start=f.save(wrong))),1,'worker-start identity mismatch'))
        cases.append((dict(bind,observation=dict(observed,start=dict(start,sha256='0'*64))),1,'hash mismatch'))
        cases.append((dict(bind,observation=f.observation(actual,'running',model=None)),2,'unknown actual model family'))
        cases.append((dict(bind,observation=f.observation(actual,'running',model=f.model('OpenAI'),start=start)),1,'conflicting actual model facts'))
        self.batch(cases)
        missing=read_json(start['path']);missing['result']['launch']['requested']=dict(model=actual['model']);missing['result']['launch']['effective']['model']=None
        cases=[(dict(bind,observation=dict(observed,start=f.save(missing))),2,'missing effective launch model')]
        data=f.report_input(artifact=artifact);data['observation']=f.observation(f.state['active'], model='unrecognized-fixture-model')
        cases.append((self.case(data),2,'unknown actual model family'));self.batch(cases)

    def test_mixed_family_and_contract_sides_require_independent_coverage(self):
        f = self.f; art, coverage = f.package_ref({'OpenAI':['tracked.txt','plan.md'], 'Anthropic':['tracked.txt']}, start_families=['Anthropic'])
        data = f.report_input('review-final', 'Anthropic', artifact=art, coverage=coverage)
        f.state['step'] = 'final-review'
        same_family=self.case(data)
        data = f.report_input('review-final', 'Google', artifact=art, coverage=coverage)
        self.batch([(same_family,1,'same-family'),(self.case(data),0,'')])
        # Real phase commit binds the staged bytes; no prepared metadata can replace it.
        fact = f.commit(art); f.state['phase_commits'] = [dict(fact, phase='F1')]
        # Check historical accepted artifact after commit via prepare snapshot's equal files.
        current, current_coverage = f.package_ref({'OpenAI':['tracked.txt','plan.md'], 'Anthropic':['tracked.txt']}, start_families=['Anthropic'])
        coverage = current_coverage; coverage['contracts'][0]['consumer'] = []
        data = f.report_input('review-final', 'Google', artifact=current, coverage=coverage, round=2)
        self.batch([(self.case(data),0,''),
                    (self.case(action='finish-checkpoint',artifact=current,fleet=f.fleet()),2,'incomplete contract')],previous=True)

    def test_gate_requires_durable_logs_and_actual_snapshot(self):
        f = self.f; records = f.gate_evidence(); art = f.gate_snapshot
        data = f.report_input('gate', artifact=art, extra='EVIDENCE: ' + json.dumps(records))
        self.valid(data)
        st = read_json(records[0]['path']); Path(st['stdout_log']).write_bytes(b'tampered')
        data = f.report_input('gate', artifact=art, extra='EVIDENCE: ' + json.dumps(records))
        self.reject(data, contains='runner evidence')

    def test_quickfix_exact_file_actual_commit_recovery_and_hook_change(self):
        f = self.f
        art = f.snapshot_ref(); data = f.report_input('quickfix', artifact=art)
        event=read_json(data['event']['path']); payload=json.loads(event['result']['message']['payload'])
        payload['filesModified']=['tracked.txt','outside.txt'];event['result']['message']['payload']=json.dumps(payload)
        bad=dict(data,event=f.save(event))
        self.batch([(self.case(bad),1,'exactly one file'),(self.case(data),0,''),
                    (self.case(action='prepare-commit',artifact=art,fleet=f.fleet()),0,''),
                    (self.case(action='confirm-commit',artifact=art,commit=dict(sha='f'*40,base=f.git.base,artifact=art),fleet=f.fleet()),2,'commit')],previous=True)
        self.assertEqual(f.state['barrier'], 'awaiting_commit')
        fact = f.commit(art)
        cases=[dict(schema_version=1,action='confirm-commit',state=f.state,artifact=art,commit=fact,fleet=f.fleet()),
               dict(schema_version=1,action='resume',state=f.state),
               dict(schema_version=1,action='confirm-commit',state=f.state,artifact=art,commit=fact,fleet=f.fleet())]
        results=f.validate_many(cases,previous=True)
        self.assertTrue(all(r[0]==0 for r in results),results)
        self.assertEqual(results[1][2]['state']['barrier'],'complete')
        self.assertEqual(len(f.state['phase_commits']), 1)
        (f.git.root/'tracked.txt').write_text('hook changed source')
        self.reject(action='confirm-commit', contains='hook/working-tree', artifact=art, commit=fact, fleet=f.fleet())

    def test_final_checkpoint_requires_phase_commit_and_delivery_proof(self):
        f = self.f; f.state['step'] = 'final-review'; art, coverage = f.package_ref()
        data=f.report_input('review-final','Anthropic',artifact=art,coverage=coverage)
        data['observation']=f.observation(f.state['active'],model=None,start=f.start_receipt(f.state['active']))
        self.batch([(self.case(data),0,''),
                    (self.case(action='finish-checkpoint',artifact=art,fleet=f.fleet()),2,'uncommitted phases')],previous=True)
        fact = f.commit(art); f.state['phase_commits'] = [dict(fact, phase='F1')]
        art, coverage = f.package_ref()
        data=f.report_input('review-final','Anthropic',artifact=art,coverage=coverage,round=2)
        self.batch([(self.case(data),0,''),
                    (self.case(action='finish-checkpoint',artifact=art,fleet=f.fleet()),0,''),
                    (self.case(action='finish-checkpoint',artifact=art,fleet=f.fleet()),2,'required report')],previous=True)
        self.assertEqual(f.state['barrier'], 'awaiting_delivery')
        proofs=f.gate_evidence(); delivered=f.gate_snapshot
        data=f.report_input('gate',artifact=delivered,extra='EVIDENCE: '+json.dumps(proofs))
        self.batch([(self.case(data),0,''),
                    (self.case(action='finish-checkpoint',artifact=delivered,fleet=f.fleet()),0,'')],previous=True)
        self.assertEqual(f.state['barrier'],'awaiting_completion_commit')
        f.plan.write_text(f.plan.read_text().replace('status: implementing','status: done'))
        f.git.git('add','plan.md');f.state['plan']=f.reference(f.plan)
        proofs=f.gate_evidence(); completed=f.gate_snapshot
        self.valid(f.report_input('gate', artifact=completed, extra='EVIDENCE: '+json.dumps(proofs)))
        completion=f.commit(completed)
        cases=[dict(schema_version=1,action='complete',state=f.state,artifact=completed,commit=completion,fleet=f.fleet()),
               dict(schema_version=1,action='resume',state=f.state)]
        results=f.validate_many(cases,previous=True)
        self.assertTrue(all(r[0]==0 for r in results),results)
        self.assertEqual(results[1][2]['state']['barrier'],'complete')

    def test_green_script_gate_is_recorded_without_a_gate_worker(self):
        f = self.f; art, coverage = f.package_ref()
        self.valid(f.report_input('implementer', artifact=art))
        rc, result = f.verified_run(code="print('gate')"); self.assertEqual(rc, 0, result)
        proof = f.reference(Path(result['run_dir']) / 'result.json')
        self.valid(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        self.valid(f.report_input('review-control', 'Google', artifact=art, coverage=coverage))
        self.assertEqual(f.state['barrier'], 'awaiting_gate')
        self.batch([(self.case(action='prepare-commit', artifact=art, fleet=f.fleet()), 2, 'required report is missing'),
                    (self.case(action='record-gate', artifact=art, evidence=[]), 2, 'missing executable evidence')])
        results = self.batch([(self.case(action='record-gate', artifact=art, evidence=[proof]), 0, ''),
                              (self.case(action='prepare-commit', artifact=art, fleet=f.fleet()), 0, '')], previous=True)
        self.assertEqual(results[0]['state']['barrier'], 'awaiting_commit')
        self.assertEqual(f.state['commit_barrier']['expected_snapshot'], read_json(art['path'])['snapshot_after']['snapshot_id'])

    def test_script_gate_inputs_match_package_by_source_and_stay_fresh(self):
        f = self.f; dep = f.git.root / 'vendor-input'; dep.mkdir(); (dep / 'lock.txt').write_text('v1\n')
        with open(f.git.root / '.git/info/exclude', 'a', encoding='utf-8') as x: x.write('/vendor-input/\n')
        art, coverage = f.package_ref()
        self.valid(f.report_input('implementer', artifact=art))
        rc, result = f.verified_run(code="print('gate')", declaration=dict(inputs=[str(dep)])); self.assertEqual(rc, 0, result)
        self.assertTrue(any(k.startswith('input:') for k in result['evidence']['source_after']['manifest']['files']))
        proof = f.reference(Path(result['run_dir']) / 'result.json')
        self.valid(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        self.valid(f.report_input('review-control', 'Google', artifact=art, coverage=coverage))
        gate = self.case(action='record-gate', artifact=art, evidence=[proof])
        self.batch([(gate, 0, '')])
        (dep / 'lock.txt').write_text('v2\n')
        self.batch([(gate, 1, 'stale check inputs')])

    def test_user_extends_a_reached_review_cap_by_one_round(self):
        f = self.f; art, coverage = f.package_ref()
        f.state['rounds']['fused_review'] = 4
        f.state['ledger'] = f.save([dict(id='F1-R4-B1', status='open', decision='ESCALATED_TO_HUMAN')])
        proposed = f.assignment('review-primary', 'Anthropic', round=5); proposed['dispatch_id'] = None; proposed['coverage'] = coverage
        def auth(**change):
            record = dict(schema_version=1, run_id='fixture-run', phase='F1', group='fused_review', extra_rounds=1,
                          findings=['F1-R4-B1'], user_decision='5 раунд'); record.update(change)
            return f.save(record)
        dispatch = lambda: self.case(action='dispatch', proposed=proposed, artifact=art, fleet=f.fleet())
        early = copy.deepcopy(f.state); early['rounds']['fused_review'] = 3
        self.batch([(dispatch(), 1, 'round cap/sequence'),
                    (self.case(action='extend-cap', authorization=auth(phase='F2')), 1, 'cap extension binding mismatch'),
                    (self.case(action='extend-cap', authorization=auth(findings=['closed-id'])), 1, 'must name open findings'),
                    (dict(schema_version=1, action='extend-cap', state=early, authorization=auth()), 1, 'before the cap is reached')])
        self.batch([(self.case(action='extend-cap', authorization=auth()), 0, ''), (dispatch(), 0, '')], previous=True)
        self.assertEqual(f.state['rounds']['fused_review'], 5)

    def test_summary_prints_compact_facts_of_state_or_proposal(self):
        f = self.f; state = self.valid(f.report_input())['state']
        saved = f.save(state)['path']; proposal = f.save(dict(schema_version=1, action='resume', state=state))['path']
        for path, head in ((saved, 'mode='), (proposal, 'proposal: action=resume')):
            rc, out, err = command(f.argv('protocol-state', 'summary', path), f.git.root)
            self.assertEqual(rc, 0, (out, err)); rows = out.splitlines()
            self.assertTrue(rows[0].startswith(head), rows[0])
            self.assertIn('barrier=awaiting_gate', out); self.assertIn('  implementer DONE r1 phase', out)
            self.assertLess(len(rows), 40); self.assertLess(len(out), 4000)
        rc, out, err = command(f.argv('protocol-state', 'summary', f.save(dict(no='state'))['path']), f.git.root)
        self.assertEqual(rc, 2, (out, err)); self.assertIn('not a C6 state', out)

    def test_explicitly_empty_cannot_verify_is_not_unstructured(self):
        f = self.f; art, coverage = f.package_ref(); state = copy.deepcopy(f.state); cases = []
        for extra, code, why in [('CANNOT_VERIFY: []', 0, ''), ('CANNOT_VERIFY:', 0, ''),
                                 ('CANNOT_VERIFY: requirement without a check', 1, 'unstructured CANNOT_VERIFY')]:
            f.state = copy.deepcopy(state)
            cases.append((self.case(f.report_input('review-control', 'Anthropic', artifact=art, coverage=coverage, extra=extra)), code, why))
        self.batch(cases)

    def pending_claude(self):
        f = self.f; proposed = f.assignment(family='Anthropic'); proposed['dispatch_id'] = None
        self.batch([(self.case(action='dispatch',proposed=proposed,artifact=f.snapshot_ref(),fleet=f.fleet()),0,'')])
        return proposed, copy.deepcopy(f.state)

    def test_reused_claude_terminal_inherits_origin_launch_model(self):
        f = self.f; proposed, pending = self.pending_claude(); task = proposed['task_id']; d = 'ctx_reuse'
        origin = f.launch_receipt('origin-task', 'ctx_origin', 'created', model=proposed['model'])
        start = f.launch_receipt(task, d, 'reused'); observed = f.claude_observation(d, task)
        def bind(obs=observed, first=origin, current=start):
            return dict(schema_version=1, action='bind-dispatch', state=pending, observation=dict(obs, start=current, origin_start=first))
        results = self.batch([
            (bind(first=f.launch_receipt('origin-task', 'ctx_origin', 'created', model=proposed['model'], handle='term_other')), 1, 'origin terminal handle mismatch'),
            (bind(obs=f.claude_observation(d, task, incarnation='restarted-incarnation')), 1, 'terminal incarnation changed'),
            (bind(first=f.launch_receipt('origin-task', 'ctx_origin', 'created', model=proposed['model'], run_id='other-run')), 1, 'origin worker-start run mismatch'),
            (bind(first=f.launch_receipt('origin-task', 'ctx_origin', 'created')), 2, 'missing origin launch model'),
            (bind(obs=f.claude_observation(d, task, model=f.model('OpenAI'))), 1, 'conflicting actual model facts'),
            (bind(), 0, '')])
        self.assertEqual(results[-1]['state']['active']['dispatch_id'], d)
        self.batch([
            (bind(current=f.launch_receipt(task, d, 'reused', model=proposed['model'])), 1, 'origin chain needs a --terminal reuse'),
            (dict(bind(), observation=dict(observed, origin_start=origin)), 1, 'origin worker-start without current worker-start'),
            (bind(current=f.launch_receipt(task, d, 'created')), 2, 'terminal launch chain mismatch')])

    def test_claude_transcript_evidence_binds_path_b_dispatch_model(self):
        f = self.f; proposed, pending = self.pending_claude(); task = proposed['task_id']; d = 'ctx_pathb'
        observed = f.claude_observation(d, task)
        def evidence(dispatch=d, **kw):
            f.serial += 1
            return dict(f.reference(f.claude_transcript(f.workspace / ('transcript-' + str(f.serial) + '.jsonl'), task, dispatch, **kw)), kind='claude-transcript')
        def bind(proof, obs=observed):
            return dict(schema_version=1, action='bind-dispatch', state=pending, observation=dict(obs, model_evidence=proof))
        good = evidence()
        results = self.batch([
            (bind(dict(good, sha256='0' * 64)), 1, 'hash mismatch'),
            (bind(evidence(dispatch='ctx_other')), 2, 'no Orca preamble for this Dispatch'),
            (bind(evidence(models=('claude-opus-5-5', 'claude-sonnet-5'))), 1, 'conflicting actual model facts'),
            (bind(evidence(cwd=str(f.git.root.parent / 'elsewhere'))), 1, 'cwd outside Dispatch worktree'),
            (bind(evidence(models=('claude-sonnet-5',))), 1, 'actual launch differs from proposal'),
            (bind(good), 0, '')])
        self.assertEqual(results[-1]['state']['active']['dispatch_id'], d)
        later = [json.loads(line) for line in Path(evidence(dispatch='ctx_next', models=('claude-sonnet-5',))['path']).read_text().splitlines()]
        self.batch([
            (bind(evidence(models=('claude-opus-5-5', '<synthetic>', 'claude-opus-5-5'), after=later)), 0, ''),
            (bind(good, obs=f.claude_observation(d, task, model='claude-opus-5-5')), 1, 'model evidence only for an unreported model'),
            (dict(bind(good), observation=dict(observed, model_evidence=good, start=f.launch_receipt(task, d, 'created', model='opus'))), 1, 'model evidence with a launch receipt'),
            (bind(evidence(models=())), 2, 'no model response after Orca preamble')])

    def test_claude_model_evidence_builder_freezes_one_transcript(self):
        f = self.f; task = 'fixture-task-builder'; d = 'ctx_builder'
        home = f.workspace / 'claude-config'; folder = home / 'projects' / re.sub(r'[^a-zA-Z0-9]', '-', str(f.git.root))
        folder.mkdir(parents=True)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home)); observed = f.claude_observation(d, task)
        def build(out):
            rc, out_text, err = command(f.argv('protocol-state', 'claude-model-evidence', observed['path'], out), f.git.root, env=env)
            rows = out_text.splitlines(); self.assertEqual(len(rows), 2, (rc, out_text, err))
            return rc, rows[0], json.loads(rows[1])
        self.assertEqual(build(f.workspace / 'none.jsonl')[:2], (2, 'UNVERIFIABLE'))
        f.claude_transcript(folder / 'other.jsonl', task, 'ctx_unrelated')
        source = f.claude_transcript(folder / 'session.jsonl', task, d)
        rc, token, result = build(f.workspace / 'frozen.jsonl')
        self.assertEqual((rc, token, result['model']), (0, 'VALID', 'claude-opus-5-5'), result)
        frozen = Path(result['model_evidence']['path'])
        self.assertEqual(frozen.read_bytes(), source.read_bytes())
        self.assertEqual(result['model_evidence']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        rc, token, result = build(frozen)
        self.assertEqual((rc, result['reason']), (2, 'snapshot output must be a new absolute file'))
        f.claude_transcript(folder / 'duplicate.jsonl', task, d)
        rc, token, result = build(f.workspace / 'twice.jsonl')
        self.assertEqual(rc, 2); self.assertIn('several Claude transcripts claim this Dispatch', result['reason'])
        self.assertFalse((f.workspace / 'twice.jsonl').exists())

    def pending_agy(self):
        f = self.f; proposed = f.assignment(family='Google'); proposed['dispatch_id'] = None
        self.batch([(self.case(action='dispatch',proposed=proposed,artifact=f.snapshot_ref(),fleet=f.fleet()),0,'')])
        return proposed, copy.deepcopy(f.state)

    def test_antigravity_log_evidence_binds_path_b_dispatch_model(self):
        f = self.f; proposed, pending = self.pending_agy(); task = proposed['task_id']; d = 'ctx_agy'
        observed = f.agy_observation(d, task)
        def evidence(conversation='c0ffee00-1111-2222-3333-444455556666', dispatch=d, **kw):
            f.serial += 1
            t, l = f.agy_home(f.workspace / ('agy-' + str(f.serial)), conversation, task, dispatch, **kw)
            return dict(f.reference(t), kind='antigravity-log', conversation_id=conversation, log=f.reference(l))
        def bind(proof):
            return dict(schema_version=1, action='bind-dispatch', state=pending, observation=dict(observed, model_evidence=proof))
        good = evidence()
        results = self.batch([
            (bind(evidence(dispatch='ctx_other')), 2, 'no Orca preamble for this Dispatch in Antigravity transcript'),
            (bind(evidence(models=('gemini-3.8-flash-high', 'gemini-3.7-flash-high'))), 1, 'conflicting actual model facts'),
            (bind(evidence(created='deadbeef-0000-0000-0000-000000000000')), 2, 'Antigravity log does not own this conversation'),
            (bind(dict(good, kind='claude-transcript')), 1, 'model evidence kind does not match provider'),
            (bind(evidence(models=('gemini-3.7-flash-high',))), 1, 'actual launch differs from proposal'),
            (bind(good), 0, '')])
        self.assertEqual(results[-1]['state']['active']['dispatch_id'], d)

    def test_antigravity_model_evidence_builder_freezes_transcript_and_log(self):
        f = self.f; task = 'fixture-task-agy'; d = 'ctx_agybuild'; home = f.workspace / 'agy-home'
        env = dict(os.environ, ORCA_AGY_HOME=str(home)); observed = f.agy_observation(d, task)
        def build(out):
            rc, text, err = command(f.argv('protocol-state', 'antigravity-model-evidence', observed['path'], out), f.git.root, env=env)
            rows = text.splitlines(); self.assertEqual(len(rows), 2, (rc, text, err))
            return rc, rows[0], json.loads(rows[1])
        self.assertEqual(build(f.workspace / 'none.jsonl')[:2], (2, 'UNVERIFIABLE'))
        f.agy_home(home, 'aaaa0000-0000-0000-0000-000000000001', task, 'ctx_unrelated')
        transcript, log = f.agy_home(home, 'bbbb0000-0000-0000-0000-000000000002', task, d)
        rc, token, result = build(f.workspace / 'agy.jsonl')
        self.assertEqual((rc, token, result['model']), (0, 'VALID', 'gemini-3.8-flash-high'), result)
        proof = result['model_evidence']
        self.assertEqual(proof['conversation_id'], 'bbbb0000-0000-0000-0000-000000000002')
        self.assertEqual(Path(proof['path']).read_bytes(), transcript.read_bytes())
        self.assertEqual(Path(proof['log']['path']).read_bytes(), log.read_bytes())

    def test_full_claude_model_ids_resolve_by_provider_prefix(self):
        f = self.f; artifact = f.snapshot_ref()
        data = f.report_input(artifact=artifact); data['observation'] = f.observation(f.state['active'], model='claude-opus-5-5')
        unknown = copy.deepcopy(data); unknown['observation'] = f.observation(f.state['active'], model='gpt-9-unlisted')
        loose = copy.deepcopy(data); loose['observation'] = f.observation(f.state['active'], model='claude-')
        results = self.batch([(self.case(unknown), 2, 'unknown actual model family'),
                              (self.case(loose), 2, 'unknown actual model family'), (self.case(data), 0, '')])
        self.assertEqual(results[-1]['state']['accepted'][-1]['family'], 'Anthropic')


if __name__ == '__main__': unittest.main()

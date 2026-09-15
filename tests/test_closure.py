"""Ordinary finding closure uses actual accepted order and an explicit fix response.

Orca receipts are synthetic; source/package bytes and the public validators are
real. No timestamp is generated or inferred to establish report chronology.
"""
import copy
import json
import unittest

from support import ProtocolFixture
from pathlib import Path


class ClosureTests(unittest.TestCase):
    def setUp(self): self.f=ProtocolFixture()
    def tearDown(self): self.f.close()

    def validate(self, data=None, code=0, reason=''):
        rc, token, result=self.f.validate(data)
        print(json.dumps(dict(code=rc,token=token,reason=result.get('reason'),
                              closed=result.get('state',{}).get('closed_ledger_ids'))),flush=True)
        self.assertEqual(rc,code,result)
        self.assertIn(reason,result.get('reason',''))
        return result

    def origin(self):
        f=self.f;art,coverage=f.package_ref()
        original=f.report_input('implementer',artifact=art)
        self.validate(original)
        finding=dict(id='B1',kind='blocking',issue='wrong behavior',location='tracked.txt:1',
                     change='correct it',risk='none',**{'class':'MUST_FIX_NOW'})
        report=f.report_input('review-primary','Anthropic',token='REVIEW_BLOCKING',
                              artifact=art,coverage=coverage,findings=[finding])
        self.validate(report)
        return original['report'],report['report'],art,coverage

    def repaired(self, text='repaired\n'):
        (self.f.git.root/'tracked.txt').write_bytes(text.encode())
        self.f.git.git('add','tracked.txt')
        return self.f.package_ref()

    def fix(self, origin, art, addressed=None, round=1):
        f=self.f;a=f.assignment('implementer',round=round);a['fix']=True
        evidence=dict(tests=['focused assertion'],commands=['fixture command'],outputs=['passed'],
                      findings=addressed if addressed is not None else [dict(id='B1',report=origin)])
        data=f.report_input('implementer',artifact=art,assignment=a,
                            extra='FIX_EVIDENCE: '+json.dumps(evidence))
        self.validate(data)
        return data['report']

    def review(self, art, coverage, role='review-primary'):
        data=self.f.report_input(role,'Anthropic',artifact=art,coverage=coverage,round=2)
        self.validate(data)
        self.review_delivery=copy.deepcopy(data)
        return data['report']

    def close(self, origin, fix, review, art, code=0, reason='', resume=False):
        f=self.f;before=copy.deepcopy(f.state)
        for status in ('fixed','resolved','closed','verified-by-controller'):
            f.state=copy.deepcopy(before)
            proof=dict(schema_version=1,finding_id='B1',report=origin,artifact=art,
                       fix_report=fix,review_report=review)
            f.state['ledger']=f.save([dict(id='B1',status=status,closure=f.save(proof))])
            # A redelivered accepted message rechecks the ledger before the
            # duplicate fast path, without requiring historical packages to
            # become current again. Plan revision resume is covered separately.
            data=(dict(schema_version=1,action='resume',state=f.state) if resume
                  else dict(self.review_delivery,state=f.state))
            result=self.validate(data,code=code,reason=reason)
            if not code:
                self.assertEqual(result['state']['closed_ledger_ids'],['B1'])
                self.assertEqual(self.validate(dict(data,state=f.state))['state'],result['state'])

    def test_initial_report_before_finding_is_not_a_fix(self):
        initial,origin,art,coverage=self.origin()
        review=self.review(art,coverage)
        self.close(origin,initial,review,art,1,'closure report order')

    def test_fix_for_wrong_finding_or_report_cannot_close(self):
        _,origin,_,_=self.origin();art,coverage=self.repaired()
        fix=self.fix(origin,art,addressed=[dict(id='OTHER',report=origin)])
        review=self.review(art,coverage)
        self.close(origin,fix,review,art,1,'closure fix finding binding')

    def test_fix_bound_to_another_source_report_cannot_close(self):
        initial,origin,_,_=self.origin();art,coverage=self.repaired()
        fix=self.fix(origin,art,addressed=[dict(id='B1',report=initial)])
        review=self.review(art,coverage)
        self.close(origin,fix,review,art,1,'closure fix finding binding')

    def test_review_before_actual_fix_cannot_close(self):
        _,origin,_,_=self.origin();art,coverage=self.repaired()
        review=self.review(art,coverage)
        fix=self.fix(origin,art)
        self.close(origin,fix,review,art,1,'closure report order')

    def test_fix_on_unrelated_artifact_cannot_close(self):
        _,origin,_,_=self.origin();written,_=self.repaired('first fix\n')
        fix=self.fix(origin,written)
        reviewed,coverage=self.repaired('unrelated later tree\n')
        review=self.review(reviewed,coverage)
        self.close(origin,fix,review,reviewed,1,'closure fix/review snapshot mismatch')

    def test_actual_same_round_fix_response_and_later_review_close(self):
        f=self.f;initial,origin,_,_=self.origin();art,coverage=self.repaired()
        fix=self.fix(origin,art)
        rc,result=f.verified_run(code="from pathlib import Path; assert Path('tracked.txt').read_text() == 'repaired\\n'")
        self.assertEqual(rc,0,result)
        proof=f.reference(Path(result['run_dir'])/'result.json')
        self.validate(f.report_input('gate',artifact=art,round=2,extra='EVIDENCE: '+json.dumps([proof])))
        review=self.review(art,coverage);self.review(art,coverage,role='review-control')
        self.close(origin,fix,review,art,resume=True)
        self.assertNotIn(initial,[r['report'] for r in f.state['accepted']])
        self.assertIn(initial,[r['report'] for r in f.state['report_history']])
        self.validate(dict(schema_version=1,action='prepare-commit',state=f.state,artifact=art,fleet=f.fleet()))
        (f.git.root/'tracked.txt').write_bytes(b'late current-source mutation\n')
        self.validate(code=1,reason='stale closure source')
        f.state['ledger']=None
        self.validate(code=1,reason='stale or incomplete package')

    def test_legacy_ordered_accepted_and_missing_or_reordered_history(self):
        _,origin,_,_=self.origin();art,coverage=self.repaired()
        fix=self.fix(origin,art,round=2)
        review=self.review(art,coverage,role='review-control')
        complete=copy.deepcopy(self.f.state)
        self.f.state.pop('report_history')
        self.close(origin,fix,review,art)
        # Legacy ordered evidence can close the item; it is not full current
        # approval while the retained primary still covers the old package.
        self.validate(code=1,reason='stale or incomplete package')
        self.f.state=copy.deepcopy(complete)
        self.f.state['report_history'].reverse()
        self.close(origin,fix,review,art,1,'closure report order')
        self.f.state=copy.deepcopy(complete)
        self.f.state['report_history']=[r for r in self.f.state['report_history'] if r['report']!=fix]
        self.close(origin,fix,review,art,2,'closure report is not accepted')


if __name__=='__main__': unittest.main()

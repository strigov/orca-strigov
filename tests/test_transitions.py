"""C6 v2 scenario suite: the current transition against the current candidate.

One end-to-end run (plan -> review -> revise -> plan-only commit -> metadata edit ->
phase -> gate -> blocking review -> fix -> re-review -> commit -> final review ->
delivery -> completion) plus a negative case for each hard invariant:
(a) fresh fleet before a writer or a commit, (b) commit tree = accepted candidate,
(c) reviewer family outside every author family. Orca receipts are synthetic;
Git, C4 snapshots/evidence and C5 packages are real and owned by the fixture.
"""
import copy
import json
from pathlib import Path
import unittest

from support import ProtocolFixture, command, read_json


def blocking(id, **extra):
    return dict(dict(id=id, kind='blocking', issue='wrong behaviour', location='tracked.txt:1', change='correct it',
                     risk='none', **{'class': 'MUST_FIX_NOW'}), **extra)


def plan_text(base, body='Fixture plan.\n', phase_status='pending', status='in-progress', phase_base=None, commits=None, risk='none'):
    return ('---\nprotocol_version: 2\norca_run: fixture-run\nplan_base: ' + base + '\nslug: fixture\nstatus: ' + status +
            '\ncontracts: ["C1"]\nphases:\n  - id: F1\n    status: ' + phase_status + '\n    risk: ' + risk + '\n' +
            ('    base: ' + phase_base + '\n' if phase_base else '') + ('    commits: "' + commits + '"\n' if commits else '') +
            '    consumes: []\n    produces: ["C1"]\n---\n' + body)


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.f = ProtocolFixture()
        self.f.state = self.f.v2_state()

    def tearDown(self): self.f.close()

    # -- helpers -------------------------------------------------------------
    def proposal(self, action='resume', **fields):
        return copy.deepcopy(dict(schema_version=1, action=action, state=self.f.state, **fields))

    def ok(self, data=None, barrier=None, **fields):
        data = data or self.proposal(**fields)
        rc, token, result = self.f.validate(copy.deepcopy(data))
        print(json.dumps(dict(action=data['action'], code=rc, reason=result.get('reason'),
                              barrier=result.get('state', {}).get('barrier'))), flush=True)
        self.assertEqual((rc, token), (0, 'VALID'), result)
        if barrier: self.assertEqual(result['state']['barrier'], barrier)
        return result

    def no(self, code, reason, data=None, **fields):
        before = copy.deepcopy(self.f.state)
        data = data or self.proposal(**fields)
        rc, token, result = self.f.validate(copy.deepcopy(data))
        print(json.dumps(dict(action=data['action'], code=rc, reason=result.get('reason'))), flush=True)
        self.assertEqual((rc, token), (code, ['VALID', 'INVALID', 'UNVERIFIABLE'][code]), result)
        self.assertIn(reason, result.get('reason', ''))
        self.assertEqual(self.f.state, before)
        return result

    def assignment(self, role, family='OpenAI', round=1, **extra):
        p = self.f.assignment(role, family, round); p['dispatch_id'] = None; p.update(extra)
        return p

    def worker(self, role, family='OpenAI', assigned=None, deliver=None, round=1, barrier=None, plan=None, fix=False, **report):
        """dispatch -> bind-dispatch -> accept-report for one fresh Task/Dispatch."""
        f = self.f; p = self.assignment(role, family, round, **({'fix': True} if fix else {}))
        if 'coverage' in report and role.startswith('review-'): p['coverage'] = report['coverage']
        self.ok(action='dispatch', proposed=p, fleet=f.fleet(), **({'artifact': assigned} if assigned else {}))
        self.ok(action='bind-dispatch', observation=f.observation(dict(p, dispatch_id=p['task_id'] + '-dispatch'), 'running'))
        art = deliver() if deliver else assigned
        data = f.report_input(role, family, artifact=art, assignment=f.state['active'], **report)
        if plan: data['plan'] = plan()
        return self.ok(data, barrier=barrier)

    def stage(self, text, name='tracked.txt'):
        (self.f.git.root / name).write_text(text, encoding='utf-8'); self.f.git.git('add', name)

    def passing_evidence(self):
        rc, result = self.f.verified_run(code="print('fixture check passed')")
        self.assertEqual(rc, 0, result)
        return [self.f.reference(Path(result['run_dir']) / 'result.json')]

    def failing_result(self):
        rc, result = self.f.verified_run(code='raise SystemExit(3)')
        self.assertEqual(rc, 3, result)
        return str(Path(result['run_dir']) / 'result.json')

    def plan_step(self):
        """Empty plan step: no plan file yet, baseline tree, plan path fixed by the coordinator."""
        f = self.f; f.plan.unlink(); f.git.git('reset', '-q'); f.git.git('checkout', '--', 'tracked.txt')
        f.state.update(step='plan', phase=None, plan=dict(path=str(f.plan), sha256=None, structure=None))

    def phase_ready(self, review_family='Anthropic', control_family='Google'):
        """Phase F1 of the default fixture accepted up to the commit barrier; returns the reviewed package."""
        f = self.f
        self.ok(f.report_input('implementer'), barrier='awaiting_gate')
        art, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence(), barrier='awaiting_review')
        self.ok(f.report_input('review-primary', review_family, artifact=art, coverage=coverage), barrier='awaiting_review')
        self.ok(f.report_input('review-control', control_family, artifact=art, coverage=coverage), barrier='awaiting_commit')
        return art, coverage

    # -- end to end ------------------------------------------------------------
    def test_end_to_end_plan_phase_final_delivery_completion(self):
        f = self.f; base = f.git.base; self.plan_step()
        self.ok(barrier='awaiting_plan_writer')
        self.no(1, 'only a plan-writer may start', action='dispatch', proposed=self.assignment('plan-reviewer', 'Anthropic'), fleet=f.fleet())

        def write(text):
            def deliver():
                f.plan.write_text(text, encoding='utf-8')
                return f.plan_artifact()
            return deliver
        # Plan writer receives plan_base and orca_run up front: reviewed bytes are the committed bytes.
        self.worker('plan-writer', deliver=write(plan_text(base)), token='PLAN_WRITTEN', plan=f.plan_ref, barrier='awaiting_plan_review')
        self.assertEqual(f.state['plan']['sha256'], f.reference(f.plan)['sha256'])
        first = f.plan_artifact()
        p1 = dict(blocking('P1-B1', location='plan.md'), criterion='scope')
        self.worker('plan-reviewer', 'Anthropic', assigned=first, token='CHANGES_REQUESTED', findings=[p1], barrier='awaiting_resolution')
        self.worker('plan-reviser', round=2, assigned=first, deliver=write(plan_text(base, 'Fixture plan, narrowed scope.\n')), token='REVISED',
                    plan=f.plan_ref, barrier='awaiting_plan_review')
        approved = f.plan_artifact()
        self.worker('plan-reviewer', 'Anthropic', assigned=approved, round=2, barrier='awaiting_commit')
        # Plan-only commit: plan_base, exactly the plan path, the approved bytes.
        f.git.git('add', 'plan.md')
        self.ok(action='prepare-commit', artifact=approved, fleet=f.fleet(), barrier='awaiting_commit')
        plan_commit = f.git_commit('docs(plans): add fixture plan')
        self.ok(action='confirm-commit', artifact=approved, commit=dict(sha=plan_commit, base=base), fleet=f.fleet(), barrier='ready_next_phase')
        self.ok(action='advance', barrier='awaiting_implementation')
        self.assertEqual((f.state['phase'], f.state['base'], f.state['accepted']), ('F1', plan_commit, []))
        # Metadata edit after the plan commit: the phase base is recorded only now.
        self.no(1, 'phase/base mismatch')
        f.plan.write_text(plan_text(base, 'Fixture plan, narrowed scope.\n', phase_status='in-progress', phase_base=plan_commit), encoding='utf-8')
        self.ok(plan=f.plan_ref(), barrier='awaiting_implementation')

        # Phase F1: implementation, gate, reviews with one blocking finding.
        def implement(text):
            def deliver():
                self.stage(text); f.git.git('add', 'plan.md')
                return f.snapshot_ref()
            return deliver
        self.worker('implementer', assigned=f.snapshot_ref(), deliver=implement('implemented\n'), barrier='awaiting_gate')
        gate = f.snapshot_ref()
        self.worker('gate', assigned=gate, extra='EVIDENCE: ' + json.dumps(self.passing_evidence()), barrier='awaiting_review')
        art, coverage = f.package_ref()
        self.worker('review-primary', 'Anthropic', assigned=art, token='REVIEW_BLOCKING', findings=[blocking('F1-R1-B1')],
                    coverage=coverage, barrier='awaiting_resolution')
        self.worker('review-control', 'Google', assigned=art, coverage=coverage, barrier='awaiting_resolution')
        self.no(1, 'required report is not positive: review-primary', action='prepare-commit', artifact=art, fleet=f.fleet())
        # Fix -> new candidate -> fresh gate and re-review of that candidate.
        evidence = dict(tests=['focused assertion'], commands=['fixture command'], outputs=['passed'])
        self.worker('implementer', round=2, fix=True, assigned=f.snapshot_ref(), deliver=implement('fixed\n'),
                    extra='FIX_EVIDENCE: ' + json.dumps(evidence), barrier='awaiting_gate')
        self.no(2, 'required report is missing: gate', action='prepare-commit', artifact=f.snapshot_ref(), fleet=f.fleet())
        self.ok(action='record-gate', artifact=f.snapshot_ref(), evidence=self.passing_evidence(), barrier='awaiting_review')
        art, coverage = f.package_ref()
        self.worker('review-primary', 'Anthropic', assigned=art, round=2, coverage=coverage, barrier='awaiting_review')
        self.worker('review-control', 'Google', assigned=art, round=2, coverage=coverage, barrier='awaiting_commit')
        # Bookkeeping before the phase commit moves only plan metadata; the candidate stays accepted.
        f.plan.write_text(plan_text(base, 'Fixture plan, narrowed scope.\n', phase_status='done', phase_base=plan_commit,
                                    commits=plan_commit[:7] + '..'), encoding='utf-8')
        f.git.git('add', 'plan.md')
        self.ok(plan=f.plan_ref(), barrier='awaiting_commit')
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet(), barrier='awaiting_commit')
        phase_commit = f.git_commit('feat: fixture phase F1')
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=phase_commit, base=plan_commit), fleet=f.fleet(),
                barrier='awaiting_final_review')
        self.assertEqual([(c['step'], c['phase']) for c in f.state['phase_commits']], [('plan', None), ('phase', 'F1')])
        self.ok(action='advance', barrier='awaiting_final_review')
        self.assertEqual((f.state['step'], f.state['accepted']), ('final-review', []))

        # Final review -> delivery -> completion.
        final, coverage = f.package_ref()
        self.worker('review-final', 'Google', assigned=final, coverage=coverage, barrier='awaiting_final_review')
        self.ok(action='finish-checkpoint', artifact=final, fleet=f.fleet(), barrier='awaiting_delivery')
        self.assertEqual((f.state['step'], f.state['accepted']), ('delivery', []))
        self.assertIsNotNone(f.state['final_source'])
        delivered = f.snapshot_ref()
        self.ok(action='record-gate', artifact=delivered, evidence=self.passing_evidence(), barrier='awaiting_delivery')
        self.ok(action='finish-checkpoint', artifact=delivered, fleet=f.fleet(), barrier='awaiting_completion_commit')
        f.plan.write_text(plan_text(base, 'Fixture plan, narrowed scope.\n', status='done', phase_status='done', phase_base=plan_commit,
                                    commits=plan_commit[:7] + '..' + phase_commit[:7]), encoding='utf-8')
        f.git.git('add', 'plan.md')
        completed = f.snapshot_ref()
        completion = f.git_commit('docs(plans): complete fixture')
        self.ok(action='complete', artifact=completed, commit=dict(sha=completion, base=phase_commit), fleet=f.fleet(),
                plan=f.plan_ref(), barrier='complete')
        self.no(1, 'completion requires a separate commit', action='complete', artifact=completed,
                commit=dict(sha=completion, base=phase_commit), fleet=f.fleet())

    # -- invariant (a): fresh fleet before a writer or a commit ----------------------
    def test_fleet_must_show_no_live_writer_before_writer_or_commit(self):
        f = self.f
        live = dict(dispatchId='prior-writer', dispatchStatus='running', terminalState='retained', resource=dict(ownershipState='owned'),
                    projection=dict(workspace=dict(id='fixture-worktree'), evidence=dict(durable=False), liveness=dict(verdict='live')))
        writer = self.assignment('implementer')
        self.no(2, 'live or unverifiable prior writer', action='dispatch', proposed=writer, artifact=f.snapshot_ref(), fleet=f.fleet([live]))
        self.no(2, 'unresolved release/external ownership', action='dispatch', proposed=writer, artifact=f.snapshot_ref(),
                fleet=f.fleet([dict(live, resource=dict(ownershipState='external'))]))
        self.no(2, 'unknown fleet workspace', action='dispatch', proposed=writer, artifact=f.snapshot_ref(),
                fleet=f.fleet([dict(live, projection=dict(live['projection'], workspace=None))]))
        art, _ = self.phase_ready()
        for action in ('prepare-commit', 'confirm-commit'):
            self.no(2, 'live or unverifiable prior writer', action=action, artifact=art, fleet=f.fleet([live]),
                    commit=dict(sha='0' * 40, base=f.git.base))
        # A receipt proves freshness once; a settled retained terminal elsewhere is not a writer.
        fleet = f.fleet([dict(live, dispatchStatus='completed', projection=dict(live['projection'], evidence=dict(durable=True)))])
        self.ok(action='prepare-commit', artifact=art, fleet=fleet)
        self.no(2, 'fleet observation already used', action='prepare-commit', artifact=art, fleet=fleet)
        # A frozen writer intent blocks every other proposal until it is bound.
        self.ok(action='dispatch', proposed=writer, artifact=f.snapshot_ref(), fleet=f.fleet(), barrier='awaiting_writer')
        self.no(2, 'unbound writer intent', action='prepare-commit', artifact=art, fleet=f.fleet())

    # -- invariant (b): commit tree = accepted candidate -----------------------------
    def test_commit_tree_must_equal_the_accepted_candidate(self):
        f = self.f; art, _ = self.phase_ready(); accepted = (f.git.root / 'tracked.txt').read_bytes()
        prepare = lambda: self.proposal('prepare-commit', artifact=art, fleet=f.fleet())
        # A hook/formatter change after acceptance makes the reviewed artifact stale.
        (f.git.root / 'tracked.txt').write_bytes(b'hook rewrote this\n')
        self.no(1, 'stale artifact', prepare())
        # The same bytes in the worktree but a different staged blob is not the accepted index.
        self.stage('staged other bytes\n'); (f.git.root / 'tracked.txt').write_bytes(accepted)
        self.no(1, 'unstaged source', prepare())
        f.git.git('add', 'tracked.txt')
        self.ok(prepare(), barrier='awaiting_commit')
        # A commit carrying an extra file is not the candidate, even after the extra file leaves the tree.
        self.stage('extra\n', 'extra.txt'); extra = f.git_commit('feat: with extra')
        f.git.git('rm', '-q', '--cached', 'extra.txt'); (f.git.root / 'extra.txt').unlink()
        confirm = lambda sha=extra, base=f.git.base, a=art: self.proposal('confirm-commit', artifact=a, commit=dict(sha=sha, base=base), fleet=f.fleet())
        self.no(1, 'commit does not contain accepted index/source', confirm())
        f.git.git('reset', '-q', '--soft', f.git.base)
        good = f.git_commit('feat: accepted candidate')
        self.no(2, 'missing full commit identity', confirm(sha=good[:12]))
        self.no(2, 'commit not found', confirm(sha='e' * 40))
        self.no(1, 'base is not a completion commit', confirm(sha=f.git.base))
        self.no(1, 'commit is not above its base on HEAD', confirm(sha=f.git.base, base=good))
        again = f.git_commit('chore: empty', '--allow-empty')
        self.no(1, 'commit base differs from accepted candidate HEAD', confirm(sha=again, base=good))
        f.git.git('reset', '-q', '--soft', good)
        self.ok(confirm(sha=good), barrier='awaiting_final_review')
        self.ok(confirm(sha=good), barrier='awaiting_final_review')  # Recovery after a crash confirms the same commit once.
        self.assertEqual(len(f.state['phase_commits']), 1)
        # The committed plan may differ in bookkeeping lines only.
        f.git.git('reset', '-q', '--soft', f.git.base); f.state['phase_commits'] = []
        original = f.plan.read_bytes()
        f.plan.write_bytes(original.replace(b'Fixture plan.', b'Fixture plan with a widened scope.')); f.git.git('add', 'plan.md')
        widened = f.git_commit('feat: widened plan')
        f.plan.write_bytes(original); f.git.git('add', 'plan.md')
        self.no(1, 'commit changes the plan beyond bookkeeping', confirm(sha=widened))

    def test_commit_needs_positive_reports_on_this_candidate(self):
        f = self.f
        self.ok(f.report_input('implementer'))
        art, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        partial = dict(files=[x for x in coverage['files'] if x != 'tracked.txt'], parts=[], contracts=[])
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=partial), barrier='awaiting_review')
        self.no(2, 'required report is missing: review-control', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=partial), barrier='awaiting_review')
        self.no(2, 'incomplete file coverage', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=dict(coverage, parts=[]), round=2), barrier='awaiting_review')
        self.no(2, 'incomplete part coverage', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=dict(coverage, contracts=[]), round=3), barrier='awaiting_review')
        self.no(2, 'incomplete contract C1:producer', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage, round=4), barrier='awaiting_commit')
        # Approvals of an earlier candidate never carry over to a changed tree.
        self.stage('changed after review\n')
        self.no(1, 'stale artifact', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.no(2, 'required report is missing: gate', action='prepare-commit', artifact=f.snapshot_ref(), fleet=f.fleet())

    def test_plan_only_commit_rules(self):
        f = self.f; base = f.git.base; self.plan_step()
        f.plan.write_text(plan_text(base), encoding='utf-8')
        f.state['plan'] = f.plan_ref()
        f.state['provenance'] = [f.observation(f.assignment('plan-writer'))]
        approved = f.plan_artifact()
        self.ok(f.report_input('plan-reviewer', 'Anthropic', artifact=approved), barrier='awaiting_commit')
        confirm = lambda sha, b=base: self.proposal('confirm-commit', artifact=approved, commit=dict(sha=sha, base=b), fleet=f.fleet())
        f.git.git('add', 'plan.md'); self.stage('extra\n', 'extra.txt'); both = f.git_commit('docs: plan and extra')
        self.no(1, 'plan commit must change only the plan file', confirm(both))
        f.git.git('reset', '-q', '--hard', base)
        f.plan.write_text(plan_text(base, 'Another body.\n'), encoding='utf-8'); f.git.git('add', 'plan.md')
        other = f.git_commit('docs: unreviewed plan bytes')
        f.plan.write_text(plan_text(base), encoding='utf-8')
        self.no(1, 'plan commit blob differs from accepted plan', confirm(other))
        f.git.git('reset', '-q', '--hard', base); f.plan.write_text(plan_text(base), encoding='utf-8'); f.git.git('add', 'plan.md')
        first = f.git_commit('docs: unrelated'); f.plan.write_text(plan_text(base) + 'x', encoding='utf-8'); f.git.git('add', 'plan.md')
        f.git_commit('docs: later'); f.plan.write_text(plan_text(base), encoding='utf-8')
        self.no(1, 'plan commit base differs from plan_base', confirm(f.git.git('rev-parse', 'HEAD').strip(), first))
        f.git.git('reset', '-q', '--hard', base); f.plan.write_text(plan_text(base), encoding='utf-8'); f.git.git('add', 'plan.md')
        self.ok(confirm(f.git_commit('docs(plans): add fixture plan')), barrier='ready_next_phase')

    # -- invariant (c): reviewer family outside every author family ------------------
    def test_reviewer_family_must_differ_from_every_author_family(self):
        f = self.f; art, coverage = f.package_ref(families={'OpenAI': ['tracked.txt'], 'Anthropic': ['plan.md']})
        self.no(1, 'same-family review: tracked.txt', f.report_input('review-primary', 'OpenAI', artifact=art, coverage=coverage))
        self.no(1, 'same-family review: plan.md', f.report_input('review-control', 'Anthropic', artifact=art, coverage=coverage))
        self.no(1, 'same-family review: tracked.txt', action='dispatch', artifact=art, fleet=f.fleet(),
                proposed=self.assignment('review-primary', 'OpenAI', coverage=coverage))
        self.ok(f.report_input('review-primary', 'Google', artifact=art, coverage=coverage))
        # Author families come from the write receipts, never from the claim in the provenance file.
        claimed, coverage = f.package_ref(families={'OpenAI': ['tracked.txt', 'plan.md']}, claims={'OpenAI': 'Anthropic'})
        self.no(1, 'claimed author family differs from launch', f.report_input('review-control', 'Google', artifact=claimed, coverage=coverage))
        unbound, coverage = f.package_ref(families={'OpenAI': ['tracked.txt', 'plan.md']}, claims={'OpenAI': 'OpenAI'}, unbound=True)
        self.no(2, 'unknown write provenance', f.report_input('review-control', 'Google', artifact=unbound, coverage=coverage))
        self.no(2, 'review requires a complete package', f.report_input('review-control', 'Google', artifact=f.snapshot_ref(), coverage=coverage))
        # A plan reviewer is outside every plan author family.
        f.state.update(phase=None, step='plan')
        f.state['provenance'] = [f.observation(f.assignment('plan-writer', 'Anthropic'))]
        plan = f.plan_artifact()
        self.no(1, 'same-family plan review', f.report_input('plan-reviewer', 'Anthropic', artifact=plan))
        self.ok(f.report_input('plan-reviewer', 'Google', artifact=plan), barrier='awaiting_commit')
        f.state['provenance'] = []
        self.no(2, 'unknown plan authors', f.report_input('plan-reviewer', 'Google', artifact=plan, round=2))

    def test_user_waiver_only_where_every_family_authored(self):
        f = self.f; files = ['plan.md', 'tracked.txt']
        art, coverage = f.package_ref(families={'OpenAI': files, 'Anthropic': files, 'Google': files})
        self.no(1, 'same-family review', f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        decision = dict(schema_version=1, run_id='fixture-run', step='phase', phase='F1', files=files, reviewer_family='Anthropic',
                        user_decision='Every family wrote these; let Anthropic review them.')
        waive = lambda artifact=art, **changed: self.proposal('waive-independence', artifact=artifact, authorization=f.save(dict(decision, **changed)))
        self.no(1, 'independence waiver binding mismatch', waive(step='delivery'))
        self.no(1, 'known reviewer family', waive(reviewer_family='Unknown'))
        self.no(1, "independence waiver without the user's decision", waive(user_decision=' '))
        self.no(1, 'every family as author: missing.txt', waive(files=files + ['missing.txt']))
        self.no(1, 'every family as author', waive(artifact=f.package_ref()[0]))
        self.ok(waive())
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        self.no(1, 'same-family review', f.report_input('review-control', 'Google', artifact=art, coverage=coverage))

    # -- resolution model ----------------------------------------------------------
    def test_findings_resolve_by_later_round_ledger_decision_or_passing_check(self):
        f = self.f
        self.ok(f.report_input('implementer'))
        art, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        cv = dict(id='CV1', kind='cannot_verify', issue='not run', location='tracked.txt', check='python3 -c "assert 1"', expect='exit 0')
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage, findings=[cv]))
        self.ok(f.report_input('review-control', 'Google', token='REVIEW_BLOCKING', artifact=art, coverage=coverage,
                               findings=[dict(id='C1-B1', kind='blocking', issue='scope', location='tracked.txt', authorization_relation='outside plan',
                                              why_now='breaks C1', minimal_fix='revert', risk='none')]), barrier='awaiting_resolution')
        # The latest control review still blocks; a ledger decision cannot turn it positive.
        def ledger(*items):
            path = f.workspace / 'ledger.json'; path.write_text(json.dumps(list(items)), encoding='utf-8')
            return f.reference(path)
        self.no(1, 'required report is not positive: review-control', action='prepare-commit', artifact=art, fleet=f.fleet(),
                ledger=ledger(dict(id='C1-B1', decision='REJECTED_BY_SCOPE')))
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage, round=2))
        self.no(1, 'unresolved findings: CV1', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.no(1, 'unresolved findings: CV1', action='prepare-commit', artifact=art, fleet=f.fleet(),
                ledger=ledger(dict(id='CV1', check=self.failing_result())))
        self.assertEqual(self.ok(ledger=ledger(dict(id='CV1', check='relative/result.json')))['state']['barrier'], 'awaiting_resolution')
        forged = f.workspace / 'forged-result.json'; forged.write_text('{"exit_code": 0}', encoding='utf-8')
        self.assertEqual(self.ok(ledger=ledger(dict(id='CV1', check=str(forged))))['state']['barrier'], 'awaiting_resolution')
        passing = str(Path(self.passing_evidence()[0]['path']))
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet(), ledger=ledger(dict(id='CV1', check=passing)))
        for decision in ('DEFER', 'NIT', 'REJECTED_BY_SCOPE'):
            self.ok(ledger=ledger(dict(id='CV1', decision=decision)), barrier='awaiting_commit')
        # Escalation to the user keeps the finding open until the user's decision is recorded as one of the three.
        for decision in ('ACCEPTED', 'ESCALATED_TO_HUMAN'):
            self.ok(ledger=ledger(dict(id='CV1', decision=decision)), barrier='awaiting_resolution')
        self.no(1, 'invalid ledger', ledger=ledger(dict(id='CV1'), dict(id='CV1')))
        self.no(1, 'ledger path differs from state', ledger=f.save([]))

    def test_a_finding_still_listed_by_the_latest_review_stays_open(self):
        f = self.f; art, coverage = self.phase_ready()
        self.ok(f.report_input('review-primary', 'Anthropic', token='REVIEW_BLOCKING', artifact=art, coverage=coverage,
                               findings=[blocking('B1')], round=2), barrier='awaiting_resolution')
        self.stage('fixed\n')
        self.ok(f.report_input('implementer', round=3, extra='FIX_EVIDENCE: {"tests":["t"],"commands":["c"],"outputs":["o"]}'), barrier='awaiting_gate')
        fixed, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=fixed, evidence=self.passing_evidence())
        self.ok(f.report_input('review-control', 'Google', artifact=fixed, coverage=coverage, round=3))
        # Same-round re-review that repeats B1 keeps it open; a later round that omits it resolves it.
        self.ok(f.report_input('review-primary', 'Anthropic', token='REVIEW_BLOCKING', artifact=fixed, coverage=coverage,
                               findings=[blocking('B1')], round=3), barrier='awaiting_resolution')
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=fixed, coverage=coverage, round=4), barrier='awaiting_commit')

    # -- plan reference ------------------------------------------------------------
    def test_plan_bookkeeping_moves_freely_other_edits_need_the_plan_author(self):
        f = self.f; original = f.plan.read_text(encoding='utf-8')
        def edited(old, new):
            f.plan.write_text(original.replace(old, new), encoding='utf-8'); return f.plan_ref()
        for old, new in (('status: implementing', 'status: done'), ('consumes: []', 'status: in-progress\n    commits: "abc.."\n    consumes: []')):
            self.ok(plan=edited(old, new))
            f.plan.write_text(original, encoding='utf-8'); self.ok(plan=f.plan_ref())
        for old, new in (('Fixture plan.', 'Fixture plan, more scope.'), ('risk: none', 'risk: SECURITY'), ('contracts: ["C1"]', 'contracts: ["C1", "C2"]')):
            self.no(1, 'plan change outside the plan author/review path', plan=edited(old, new))
        self.no(1, 'plan path differs from state', plan=dict(f.save(original, '.md'), structure=None))
        f.plan.write_text(original.replace('Fixture plan.', 'Widened.'), encoding='utf-8')
        self.no(1, 'artifact hash mismatch')

    def test_plan_author_rewrites_the_plan_through_accept_report(self):
        f = self.f; f.state.update(phase=None, step='plan')
        f.plan.write_text(f.plan.read_text().replace('Fixture plan.', 'Revised plan.'), encoding='utf-8')
        data = f.report_input('plan-reviser', token='REVISED', artifact=f.plan_artifact(), round=2)
        data['plan'] = f.plan_ref()
        self.ok(data, barrier='awaiting_plan_review')
        self.assertEqual(f.state['plan']['structure'], f.plan_ref()['structure'])
        previous = f.plan_artifact()
        f.plan.write_text(f.plan.read_text().replace('Revised plan.', 'Third plan.'), encoding='utf-8')
        stale = f.report_input('plan-reviser', token='REVISED', artifact=previous, round=3)
        stale['plan'] = f.plan_ref()
        self.no(1, 'assigned plan mismatch', stale)
        snapshot = f.report_input('plan-reviser', token='REVISED', artifact=f.snapshot_ref(), round=3)
        snapshot['plan'] = f.plan_ref()
        self.no(1, 'plan author must deliver the current plan', snapshot)
        # Without the author's report the same rewrite is not bookkeeping.
        self.no(1, 'plan change outside the plan author/review path', plan=f.plan_ref())

    # -- final steps ----------------------------------------------------------------
    def test_final_steps_record_the_reviewed_source_and_a_separate_completion(self):
        f = self.f; art, _ = self.phase_ready()
        self.no(1, 'not a final checkpoint', action='finish-checkpoint', artifact=art, fleet=f.fleet())
        sha = f.commit(art)['sha']
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=sha, base=f.git.base), fleet=f.fleet())
        self.ok(action='advance', barrier='awaiting_final_review')
        final, coverage = f.package_ref()
        self.no(2, 'required report is missing: review-final', action='finish-checkpoint', artifact=final, fleet=f.fleet())
        # A final-fix commit does not invalidate the final review of the same bytes.
        self.stage('final fix\n')
        fixed, coverage = f.package_ref()
        self.ok(f.report_input('review-final', 'Google', artifact=fixed, coverage=coverage))
        self.ok(action='prepare-commit', artifact=fixed, fleet=f.fleet())
        fix = f.git_commit('fix: address final-review findings')
        self.ok(action='confirm-commit', artifact=fixed, commit=dict(sha=fix, base=sha), fleet=f.fleet(), barrier='awaiting_final_review')
        self.ok(action='finish-checkpoint', artifact=fixed, fleet=f.fleet(), barrier='awaiting_delivery')
        final_source = f.state['final_source']
        self.stage('after the final review\n')
        self.no(1, 'delivery covers a different source', action='finish-checkpoint', artifact=f.snapshot_ref(), fleet=f.fleet())
        self.stage('final fix\n')
        self.no(2, 'required report is missing: gate', action='finish-checkpoint', artifact=f.snapshot_ref(), fleet=f.fleet())
        self.ok(action='record-gate', artifact=f.snapshot_ref(), evidence=self.passing_evidence())
        self.ok(action='finish-checkpoint', artifact=f.snapshot_ref(), fleet=f.fleet(), barrier='awaiting_completion_commit')
        self.assertEqual(f.state['final_source'], final_source)
        snapshot = f.snapshot_ref()
        self.no(1, 'completion candidate differs', action='complete', artifact=art, commit=dict(sha=fix, base=sha), fleet=f.fleet())
        f.plan.write_text(f.plan.read_text().replace('status: implementing', 'status: in-progress'), encoding='utf-8'); f.git.git('add', 'plan.md')
        undone = f.git_commit('docs(plans): bookkeeping without done')
        self.no(2, 'final bookkeeping is incomplete', action='complete', artifact=snapshot, commit=dict(sha=undone, base=fix), fleet=f.fleet(), plan=f.plan_ref())
        self.no(1, 'completion requires a separate commit', action='complete', artifact=snapshot, commit=dict(sha=fix, base=sha), fleet=f.fleet(), plan=f.plan_ref())
        f.git.git('reset', '-q', '--soft', fix)
        f.plan.write_text(f.plan.read_text().replace('status: in-progress', 'status: done'), encoding='utf-8'); f.git.git('add', 'plan.md')
        done = f.git_commit('docs(plans): complete fixture')
        self.no(1, 'not a commit step', action='prepare-commit', artifact=snapshot, fleet=f.fleet(), plan=f.plan_ref())
        self.ok(action='complete', artifact=snapshot, commit=dict(sha=done, base=fix), fleet=f.fleet(), plan=f.plan_ref(), barrier='complete')
        self.no(1, 'not a final checkpoint', action='finish-checkpoint', artifact=snapshot, fleet=f.fleet())

    # -- migration -----------------------------------------------------------------
    def test_migrate_keeps_current_phase_entries_and_commits(self):
        f = self.f; state = f.v2_state(); out = f.workspace / 'migrated.json'
        art, coverage = f.package_ref()
        v1 = dict(schema_version=1, mode='plan', plan=f.reference(f.plan), ledger=None, orca_run='fixture-run', plan_base=f.git.base,
                  phase='F1', base=f.git.base, step='phase', worktree=str(f.git.root), worktree_id='fixture-worktree', workspace=str(f.workspace),
                  active=None, rounds=dict(plan_review=1, fused_review=1, final_review=0, gate_fix=0), format_corrections={},
                  accepted=[dict(role='review-primary', token='REVIEW_OK', family='Anthropic', step='phase', artifact_id='x', snapshot_id='y',
                                 binding=dict(round=1, phase='F1', dispatch_id='d1'), report=f.save('r', '.md'), artifact=art,
                                 findings=[], coverage=coverage, evidence=[]),
                            dict(role='plan-reviewer', token='APPROVED', family='Anthropic', step='plan', artifact_id='x', snapshot_id=None,
                                 binding=dict(round=1, phase=None, dispatch_id='d0'), report=f.save('r0', '.md'), artifact=f.plan_artifact(),
                                 findings=[], coverage={}, evidence=[])],
                  processed=dict(messages=['m1'], deliveries=['d']), open_ledger_ids=[], write_ownership=[], phase_commits=[],
                  commit_barrier={}, final={}, provenance=[], report_history=[], used_fleet_ids=['fleet-1'])
        source = f.save(v1)
        rc, text, err = command(f.argv('protocol-state', 'migrate', source['path'], out), f.git.root)
        self.assertEqual(rc, 0, (text, err))
        migrated = read_json(out)
        self.assertEqual({k: migrated[k] for k in state if k not in ('rounds', 'accepted', 'processed_messages', 'used_fleet_ids', 'barrier')},
                         {k: state[k] for k in state if k not in ('rounds', 'accepted', 'processed_messages', 'used_fleet_ids', 'barrier')})
        self.assertEqual([r['role'] for r in migrated['accepted']], ['review-primary'])
        self.assertEqual((migrated['processed_messages'], migrated['used_fleet_ids'], migrated['rounds']['fused_review']), (['m1'], ['fleet-1'], 1))
        f.state = migrated
        self.ok(barrier='awaiting_gate')
        rc, text, err = command(f.argv('protocol-state', 'migrate', source['path'], out), f.git.root)
        self.assertEqual(rc, 2, text); self.assertIn('new absolute file', text)
        self.no(2, 'schema 1 state: run protocol-state migrate', dict(schema_version=1, action='resume', state=v1))


if __name__ == '__main__': unittest.main()

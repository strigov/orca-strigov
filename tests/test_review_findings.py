"""C6 review findings (Codex gpt-6-astra review r1): one scenario per finding, numbered as in the review.

Each scenario follows the shape of the live Bureau runs (multi-phase plans, fix rounds, rejected reports,
fallbacks, a Claude-written frontend beside Gemini/OpenAI backends). Orca receipts are synthetic; Git,
C4 evidence and C5 packages are real and owned by the fixture.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

from support import ProtocolFixture, read_json
import test_transitions
from test_transitions import blocking, plan_text


def two_phases(base, f1=None, f2=None, status='implementing', body='Two-phase fixture plan.\n'):
    """F1 produces C1 (the UI module); F2 consumes it."""
    return ('---\nprotocol_version: 2\norca_run: fixture-run\nplan_base: ' + base + '\nstatus: ' + status +
            '\ncontracts: ["C1"]\nphases:\n  - id: F1\n    risk: none\n' + ('    base: ' + f1 + '\n' if f1 else '') +
            '    consumes: []\n    produces: ["C1"]\n  - id: F2\n    risk: none\n' + ('    base: ' + f2 + '\n' if f2 else '') +
            '    consumes: ["C1"]\n    produces: []\n---\n' + body)


class ReviewFindingTests(unittest.TestCase):
    setUp = test_transitions.TransitionTests.setUp
    tearDown = test_transitions.TransitionTests.tearDown
    proposal = test_transitions.TransitionTests.proposal
    ok = test_transitions.TransitionTests.ok
    no = test_transitions.TransitionTests.no
    assignment = test_transitions.TransitionTests.assignment
    worker = test_transitions.TransitionTests.worker
    stage = test_transitions.TransitionTests.stage
    passing_evidence = test_transitions.TransitionTests.passing_evidence
    failing_result = test_transitions.TransitionTests.failing_result
    plan_step = test_transitions.TransitionTests.plan_step
    phase_ready = test_transitions.TransitionTests.phase_ready

    # -- helpers -------------------------------------------------------------
    def write(self, name, text, stage=True):
        path = self.f.git.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')
        if stage: self.f.git.git('add', name)

    def writer(self, name, text):
        """deliver(): write and stage one file, return the writer's completed snapshot."""
        def deliver():
            self.write(name, text); return self.f.snapshot_ref()
        return deliver

    def baseline_tracked(self):
        """Drop the fixture's unattributed tracked.txt change: every changed file then has an actual writer."""
        self.f.git.git('reset', '-q', 'tracked.txt'); self.f.git.git('checkout', '--', 'tracked.txt')

    def mixed_phase(self):
        """Claude writes the UI, then the OpenAI fallback writes the API, each through dispatch/bind/accept."""
        f = self.f; self.baseline_tracked()
        self.worker('frontend-implementer', 'Anthropic', assigned=f.snapshot_ref(), deliver=self.writer('ui.tsx', 'export const ui = 1\n'))
        self.worker('implementer', 'OpenAI', assigned=f.snapshot_ref(), deliver=self.writer('api.py', 'API = 1\n'), barrier='awaiting_gate')
        contracts = [dict(id='C1', producer=['api.py'], consumer=['ui.tsx'])]
        return contracts

    def mixed_package(self, contracts):
        art, coverage = self.f.package_ref(families={'Anthropic': ['ui.tsx', 'plan.md'], 'OpenAI': ['api.py']}, contracts=contracts)
        return art, coverage

    def cover(self, coverage, files, sides=None):
        """A partial COVERAGE: the named files, all parts, and contract sides limited to those files."""
        contracts = [dict(id=c['id'], **{k: [p for p in c[k] if p in files] for k in ('producer', 'consumer')}) for c in coverage['contracts']]
        return dict(files=list(files), parts=coverage['parts'], contracts=contracts if sides is None else sides)

    def to_final_review(self):
        """Phase F1 accepted, committed and advanced: the final-review step of the one-phase fixture plan."""
        f = self.f; art, _ = self.phase_ready()
        sha = f.commit(art)['sha']
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=sha, base=f.git.base), fleet=f.fleet())
        self.ok(action='advance', barrier='awaiting_final_review')
        return sha

    def gate_failure(self):
        rc, result = self.f.verified_run(code='raise SystemExit(3)')
        self.assertEqual(rc, 3, result)
        return [self.f.reference(Path(result['run_dir']) / 'result.json')]

    # -- 1: an old fleet must not clear a known writer -------------------------------
    def test_01_old_fleet_cannot_clear_a_recorded_writer(self):
        f = self.f; first = self.assignment('implementer', 'Google')
        self.ok(action='dispatch', proposed=first, artifact=f.snapshot_ref(), fleet=f.fleet())
        old = f.fleet()  # an authentic, unused inventory collected before the writer started
        self.ok(action='bind-dispatch', observation=f.observation(dict(first, dispatch_id='D-live'), 'running'), barrier='awaiting_writer')
        fallback = self.assignment('implementer', 'OpenAI')
        self.no(2, 'recorded writer missing from fleet: D-live', action='dispatch', proposed=fallback, artifact=f.snapshot_ref(), fleet=old)
        row = dict(dispatchId='D-live', taskId=first['task_id'], dispatchStatus='running', terminalState='retained', resource=None,
                   projection=dict(workspace=dict(id='fixture-worktree'), evidence=dict(durable=False), liveness=dict(verdict='live')))
        self.no(2, 'live or unverifiable prior writer', action='dispatch', proposed=fallback, artifact=f.snapshot_ref(), fleet=f.fleet([row]))
        settled = dict(row, dispatchStatus='failed', projection=dict(row['projection'], evidence=dict(durable=True)))
        # Settled without an accepted report: its family is recorded before anything replaces it (round-2 finding 2).
        self.no(2, 'writer D-live settled without an accepted report: record-author it first', action='dispatch', proposed=fallback,
                artifact=f.snapshot_ref(), fleet=f.fleet([settled]))
        self.ok(action='record-author', observation=f.observation(dict(first, dispatch_id='D-live'), 'failed'), artifact=f.snapshot_ref())
        self.ok(action='dispatch', proposed=fallback, artifact=f.snapshot_ref(), fleet=f.fleet([settled]), barrier='awaiting_writer')

    # -- 2: a range package reviews the committed tree, from the step base ------------------
    def test_02_range_package_must_be_the_reviewed_tree(self):
        f = self.f
        self.ok(f.report_input('implementer'))
        committed = f.git_commit('feat: implementation for range review')
        art, coverage = f.package_ref(head='HEAD')
        review = lambda a, cov: dict(self.assignment('review-primary', 'Anthropic'), coverage=cov)
        self.ok(action='dispatch', proposed=review(art, coverage), artifact=art, fleet=f.fleet())
        # Dirty source the range diff does not show.
        self.write('tracked.txt', 'unreviewed dirty bytes\n', stage=False)
        dirty, coverage = f.package_ref(head='HEAD')
        self.no(1, 'range package differs from its reviewed tree', action='dispatch', proposed=review(dirty, coverage), artifact=dirty, fleet=f.fleet())
        f.git.git('checkout', '--', 'tracked.txt')
        # A requested HEAD older than the captured one.
        self.write('later.txt', 'later commit\n'); f.git_commit('feat: later commit')
        older, coverage = f.package_ref(head=committed)
        self.no(1, 'range package differs from its reviewed tree', action='dispatch', proposed=review(older, coverage), artifact=older, fleet=f.fleet())
        # A package from another base than the step's.
        wrong, coverage = f.package_ref(base=committed)
        self.no(1, 'package base differs from the step base', action='dispatch', proposed=review(wrong, coverage), artifact=wrong, fleet=f.fleet())

    # -- 3: cumulative authorship ----------------------------------------------------------
    def test_03a_unchanged_contract_side_keeps_its_earlier_author(self):
        """Two phases: Claude writes the C1 producer in F1; in F2 an Anthropic reviewer may not cover it as a side."""
        f = self.f; base = f.git.base; self.baseline_tracked()
        f.plan.write_text(two_phases(base, f1=base), encoding='utf-8'); f.git.git('add', 'plan.md'); f.state['plan'] = f.plan_ref()
        f.state['plan_approved'] = f.state['plan']['structure']  # the Run's approved plan
        self.worker('frontend-implementer', 'Anthropic', assigned=f.snapshot_ref(), deliver=self.writer('ui.ts', 'export const ui = 1\n'),
                    barrier='awaiting_gate')
        c1 = [dict(id='C1', producer=['ui.ts'], consumer=['plan.md'])]
        art, coverage = f.package_ref(families={'Anthropic': ['ui.ts'], 'Google': ['plan.md']}, contracts=c1)
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        self.ok(f.report_input('review-primary', 'OpenAI', artifact=art, coverage=coverage))
        self.ok(f.report_input('review-control', 'OpenAI', artifact=art, coverage=coverage, round=2), barrier='awaiting_commit')
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet())
        f1 = f.git_commit('feat(F1): ui producer')
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=f1, base=base), fleet=f.fleet(), barrier='ready_next_phase')
        self.ok(action='advance', barrier='awaiting_implementation')
        f.plan.write_text(two_phases(base, f1=base, f2=f1), encoding='utf-8'); f.git.git('add', 'plan.md')
        self.ok(plan=f.plan_ref(), barrier='awaiting_implementation')
        # F2: Gemini writes the consumer; ui.ts is unchanged in this package.
        self.worker('implementer', 'Google', assigned=f.snapshot_ref(), deliver=self.writer('api.ts', 'import { ui } from "./ui"\n'), barrier='awaiting_gate')
        c1 = [dict(id='C1', producer=['ui.ts'], consumer=['api.ts'])]
        art, coverage = f.package_ref(families={'Google': ['api.ts', 'plan.md']}, contracts=c1)
        self.assertNotIn('ui.ts', coverage['files'])
        claude = dict(self.assignment('review-primary', 'Anthropic'), coverage=dict(coverage, contracts=c1))
        self.no(1, 'same-family review: ui.ts', action='dispatch', proposed=claude, artifact=art, fleet=f.fleet())
        astra = dict(self.assignment('review-primary', 'OpenAI'), coverage=dict(coverage, contracts=c1))
        self.ok(action='dispatch', proposed=astra, artifact=art, fleet=f.fleet())

    def test_03b_package_provenance_cannot_omit_an_accepted_writer(self):
        f = self.f
        self.worker('implementer', 'OpenAI', assigned=f.snapshot_ref(), deliver=self.writer('tracked.txt', 'implemented\n'), barrier='awaiting_gate')
        # The package declares only a Google write for tracked.txt; the accepted OpenAI writer is omitted.
        art, coverage = f.package_ref(families={'Google': ['tracked.txt', 'plan.md']})
        astra = dict(self.assignment('review-control', 'OpenAI'), coverage=coverage)
        self.no(1, 'same-family review: tracked.txt', action='dispatch', proposed=astra, artifact=art, fleet=f.fleet())

    def test_03c_record_author_invalidates_an_affected_approval(self):
        f = self.f; art, _ = self.phase_ready(review_family='Anthropic', control_family='Google')
        late = f.observation(f.assignment('implementer', 'Anthropic'))
        self.ok(action='record-author', observation=late, artifact=f.snapshot_ref())
        self.no(1, 'same-family review: tracked.txt', action='prepare-commit', artifact=art, fleet=f.fleet())

    # -- 4: Git modes are part of the candidate -----------------------------------------------
    def test_04_executable_mode_change_after_acceptance_is_not_the_candidate(self):
        f = self.f; art, _ = self.phase_ready()
        os.chmod(f.git.root / 'tracked.txt', 0o755); f.git.git('update-index', '--chmod=+x', 'tracked.txt')
        self.no(1, 'stale artifact', action='prepare-commit', artifact=art, fleet=f.fleet())
        sha = f.git_commit('feat: with an executable bit nobody reviewed')
        self.no(1, 'stale artifact', action='confirm-commit', artifact=art, commit=dict(sha=sha, base=f.git.base), fleet=f.fleet())

    # -- 5: a cannot_verify check is bound to the finding's literal check and expect ----------
    def test_05_cannot_verify_needs_the_literal_check_and_its_expectation(self):
        f = self.f
        self.ok(f.report_input('implementer'))
        art, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        path, spec = f.verified_spec(code="print('ok')")
        cv = dict(id='CV1', kind='cannot_verify', issue='acceptance assertion not run', location='tracked.txt',
                  check=spec['command'], expect='exit 0; stdout exactly: ok')
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage, findings=[cv]))
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage), barrier='awaiting_resolution')
        def ledger(result):
            p = f.workspace / 'ledger.json'; p.write_text(json.dumps([dict(id='CV1', check=result)]), encoding='utf-8')
            return f.reference(p)
        unrelated = self.passing_evidence()[0]['path']  # an intact sealed result of another command
        self.ok(ledger=ledger(unrelated), barrier='awaiting_resolution')
        self.no(1, 'unresolved findings: CV1', action='prepare-commit', artifact=art, fleet=f.fleet(), ledger=ledger(unrelated))
        rc, out, err = f.start(path).finish(); literal = str(Path(spec['run_dir']) / 'result.json')
        self.assertEqual(rc, 0, (out, err))
        self.ok(ledger=ledger(literal), barrier='awaiting_commit')
        # The same literal command whose output contradicts the expectation does not close it.
        cv2 = dict(cv, id='CV2', expect='exit 0; stdout exactly: something else')
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage, findings=[cv2], round=2))
        p = f.workspace / 'ledger.json'; p.write_text(json.dumps([dict(id='CV1', check=literal), dict(id='CV2', check=literal)]), encoding='utf-8')
        self.ok(ledger=f.reference(p), barrier='awaiting_resolution')

    # -- 6: complementary review assignments ----------------------------------------------------
    def test_06a_complementary_final_reviews_complete_together(self):
        f = self.f; contracts = self.mixed_phase()
        art, coverage = self.mixed_package(contracts)
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        self.ok(f.report_input('review-primary', 'Google', artifact=art, coverage=coverage))
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage, round=2), barrier='awaiting_commit')
        sha = f.commit(art)['sha']
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=sha, base=f.git.base), fleet=f.fleet())
        self.ok(action='advance', barrier='awaiting_final_review')
        final, coverage = self.mixed_package(contracts)
        # Claude-written UI reviewed by Astra, OpenAI-written API by Opus: one round, complementary units.
        self.ok(f.report_input('review-final', 'OpenAI', artifact=final, coverage=self.cover(coverage, ['ui.tsx'])))
        self.ok(f.report_input('review-final', 'Anthropic', artifact=final, coverage=self.cover(coverage, ['api.py'])))
        self.ok(action='finish-checkpoint', artifact=final, fleet=f.fleet(), barrier='awaiting_delivery')

    def test_06b_a_partial_later_review_does_not_close_an_uncovered_finding(self):
        f = self.f; contracts = self.mixed_phase()
        art, coverage = self.mixed_package(contracts)
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        self.ok(f.report_input('review-primary', 'Google', token='REVIEW_BLOCKING', artifact=art, coverage=coverage,
                               findings=[blocking('F1-B1', location='api.py:1')]), barrier='awaiting_resolution')
        # Round 2 covers only the UI: it says nothing about api.py.
        self.ok(f.report_input('review-primary', 'OpenAI', artifact=art, coverage=self.cover(coverage, ['ui.tsx']), round=2))
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage), barrier='awaiting_resolution')
        self.no(1, 'unresolved findings: F1-B1', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.ok(f.report_input('review-primary', 'Google', artifact=art, coverage=self.cover(coverage, ['api.py']), round=2), barrier='awaiting_commit')

    # -- 7: a rejected plan-author report keeps a recovery path ---------------------------------
    def test_07_rejected_reviser_report_can_be_redispatched(self):
        f = self.f; base = f.git.base; self.plan_step()
        def plan(text):
            def deliver():
                f.plan.write_text(text, encoding='utf-8'); return f.plan_artifact()
            return deliver
        self.worker('plan-writer', 'Anthropic', deliver=plan(plan_text(base)), token='PLAN_WRITTEN', plan=f.plan_ref, barrier='awaiting_plan_review')
        accepted = f.plan_artifact()
        p1 = dict(blocking('P1-B1', location='plan.md'), criterion='scope')
        self.worker('plan-reviewer', 'OpenAI', assigned=accepted, token='CHANGES_REQUESTED', findings=[p1], barrier='awaiting_resolution')
        # The reviser edits the plan, then its report fails the worker contract.
        first = self.assignment('plan-reviser', 'Anthropic', round=2)
        self.ok(action='dispatch', proposed=first, artifact=accepted, fleet=f.fleet())
        f.plan.write_text(plan_text(base, 'Draft written before binding.\n'), encoding='utf-8')
        self.ok(action='bind-dispatch', observation=f.observation(dict(first, dispatch_id='D-reviser-1'), 'running'), barrier='awaiting_writer')
        bad = f.report_input('plan-reviser', 'Anthropic', token='DONE', artifact=f.plan_artifact(), round=2, assignment=f.state['active'])
        bad['plan'] = f.plan_ref()
        self.no(1, 'format: role verdict', bad)
        # Recovery: register the settled reviser, then a fresh reviser Task on the accepted plan; the draft is its working copy.
        self.ok(action='record-author', observation=f.observation(dict(first, dispatch_id='D-reviser-1')))
        second = self.assignment('plan-reviser', 'Anthropic', round=2)
        self.ok(action='dispatch', proposed=second, artifact=accepted, fleet=f.fleet([dict(
            dispatchId='D-reviser-1', taskId=first['task_id'], dispatchStatus='completed', terminalState='retained', resource=None,
            projection=dict(workspace=None, evidence=dict(durable=True), liveness=dict(verdict='unverifiable')))]))
        self.ok(action='bind-dispatch', observation=f.observation(dict(second, dispatch_id='D-reviser-2'), 'running'))
        # A reader still needs the accepted bytes.
        self.no(1, 'artifact hash mismatch', action='dispatch', proposed=self.assignment('plan-reviewer', 'OpenAI', round=2), artifact=accepted,
                fleet=f.fleet())
        f.plan.write_text(plan_text(base, 'Fixture plan, narrowed scope.\n'), encoding='utf-8')
        revised = f.report_input('plan-reviser', 'Anthropic', token='REVISED', artifact=f.plan_artifact(), round=2, assignment=f.state['active'])
        revised['plan'] = f.plan_ref()
        self.ok(revised, barrier='awaiting_plan_review')

    # -- 8: a failed unbound writer launch can be reconciled ----------------------------------
    def test_08_failed_unbound_launch_is_reconciled_by_positive_evidence(self):
        f = self.f; gemini = self.assignment('implementer', 'Google')
        self.ok(action='dispatch', proposed=gemini, artifact=f.snapshot_ref(), fleet=f.fleet(), barrier='awaiting_writer')
        row = dict(dispatchId='D-gemini', taskId=gemini['task_id'], dispatchStatus='failed', terminalState='released', resource=None,
                   projection=dict(workspace=dict(id='fixture-worktree'), evidence=dict(durable=True), liveness=dict(verdict='exited')))
        running = dict(row, dispatchStatus='dispatched', terminalState='retained',
                       projection=dict(row['projection'], evidence=dict(durable=False), liveness=dict(verdict='live')))
        self.no(2, 'live or unverifiable prior writer', action='reconcile-intent', fleet=f.fleet([running]), artifact=f.snapshot_ref())
        self.no(2, 'missing launch failure evidence', action='reconcile-intent', fleet=f.fleet(), artifact=f.snapshot_ref())
        self.write('tracked.txt', 'written by the failed launch\n')
        self.no(1, 'the failed launch changed the candidate', action='reconcile-intent', fleet=f.fleet([row]), artifact=f.snapshot_ref())
        self.write('tracked.txt', 'candidate\n')
        self.ok(action='reconcile-intent', fleet=f.fleet([row]), artifact=f.snapshot_ref(), barrier='awaiting_implementation')
        self.assertEqual((f.state['active'], f.state['write_ownership']), (None, []))
        luna = self.assignment('implementer', 'OpenAI')
        self.ok(action='dispatch', proposed=luna, artifact=f.snapshot_ref(), fleet=f.fleet([row]), barrier='awaiting_writer')
        # No Dispatch was ever created: the saved failed launch receipt naming the Task is the evidence.
        failure = f.save(dict(id='local', ok=False, error=dict(code='runtime_error', message='launch failed', data=dict(taskId=luna['task_id'])),
                              _meta=dict(runtimeId=None)))
        other = f.save(dict(id='local', ok=False, error=dict(code='runtime_error', message='launch failed', data=dict(taskId='another-task'))))
        self.no(2, 'missing launch failure evidence', action='reconcile-intent', fleet=f.fleet([row]), artifact=f.snapshot_ref(), launch_failure=other)
        self.ok(action='reconcile-intent', fleet=f.fleet([row]), artifact=f.snapshot_ref(), launch_failure=failure)

    # -- 9: a BLOCKED review attempt keeps its round ----------------------------------------
    def test_09_blocked_review_attempt_does_not_consume_the_substantive_round(self):
        f = self.f
        self.ok(f.report_input('implementer'))
        art, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        for cap_round in (1, 4):
            f.state['rounds']['fused_review'] = cap_round
            self.ok(f.report_input('review-primary', 'Anthropic', token='BLOCKED', artifact=art, coverage=coverage, round=cap_round))
            retry = dict(self.assignment('review-primary', 'Anthropic', round=cap_round), coverage=coverage)
            self.ok(action='dispatch', proposed=retry, artifact=art, fleet=f.fleet())
            f.state['active'] = None
        # A substantive same-family repeat still needs a new round.
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage, round=4))
        again = dict(self.assignment('review-primary', 'Anthropic', round=4), coverage=coverage)
        self.no(1, 'substantive review needs a new round', action='dispatch', proposed=again, artifact=art, fleet=f.fleet())

    # -- 10: a plan-review extension survives advance ----------------------------------------
    def test_10_plan_review_extension_does_not_poison_the_next_phase(self):
        f = self.f; base = f.git.base; self.plan_step()
        f.plan.write_text(plan_text(base), encoding='utf-8'); f.state['plan'] = f.plan_ref()
        author = f.observation(f.assignment('plan-writer', 'Anthropic'))
        f.state.update(plan_authors=[author], provenance=[author])
        f.state['rounds']['plan_review'] = 4
        art = f.plan_artifact()
        p4 = dict(blocking('P4-B1', location='plan.md'), criterion='scope', new_blocker_materiality='blocks the phase split')
        self.ok(f.report_input('plan-reviewer', 'OpenAI', token='CHANGES_REQUESTED', artifact=art, findings=[p4], round=4), barrier='awaiting_resolution')
        auth = f.save(dict(schema_version=1, run_id='fixture-run', phase=None, group='plan_review', extra_rounds=1, findings=['P4-B1'],
                           user_decision='One more plan review round.'))
        self.ok(action='extend-cap', authorization=auth)
        self.worker('plan-reviewer', 'OpenAI', assigned=art, round=5, barrier='awaiting_commit')
        f.git.git('add', 'plan.md')
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet())
        sha = f.git_commit('docs(plans): add fixture plan')
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=sha, base=base), fleet=f.fleet(), barrier='ready_next_phase')
        self.ok(action='advance')
        f.plan.write_text(plan_text(base, phase_status='in-progress', phase_base=sha), encoding='utf-8')
        self.ok(plan=f.plan_ref(), barrier='awaiting_implementation')

    # -- 11: gate-fix rounds: consecutive count and extension identity ---------------------------
    def gate_fix_round(self, text):
        """One gate-fix round: the implementer re-dispatched with gate_fix, its fix delivered and accepted."""
        f = self.f; evidence = dict(tests=['gate command'], commands=['verify-gate'], outputs=['passed'])
        p = self.assignment('implementer', 'OpenAI', round=f.state['rounds']['gate_fix'] + 1, fix=True, gate_fix=True)
        self.ok(action='dispatch', proposed=p, artifact=f.snapshot_ref(), fleet=f.fleet())
        self.ok(action='bind-dispatch', observation=f.observation(dict(p, dispatch_id=p['task_id'] + '-dispatch'), 'running'))
        self.ok(f.report_input('implementer', artifact=self.writer('tracked.txt', text)(), assignment=f.state['active'],
                               extra='FIX_EVIDENCE: ' + json.dumps(evidence)))

    def test_11a_a_green_gate_resets_the_consecutive_gate_fix_count(self):
        f = self.f
        self.ok(f.report_input('implementer'))
        for n in range(3):
            self.gate_fix_round('gate fix %d\n' % n)
            self.ok(action='record-gate', artifact=f.snapshot_ref(), evidence=self.passing_evidence(), barrier='awaiting_review')
        self.assertEqual(f.state['rounds']['gate_fix'], 0)

    def test_11b_a_failing_script_gate_registers_an_extendable_finding(self):
        f = self.f
        self.ok(f.report_input('implementer'))
        f.state['rounds']['gate_fix'] = 2
        self.ok(action='record-gate', verdict='GATE_FAIL', artifact=f.snapshot_ref(), evidence=self.gate_failure(), barrier='awaiting_resolution')
        self.assertEqual([x['id'] for x in f.state['accepted'][-1]['findings']], ['G3-B1'])
        self.no(1, 'zero failing checks', action='record-gate', verdict='GATE_FAIL', artifact=f.snapshot_ref(), evidence=self.passing_evidence())
        auth = f.save(dict(schema_version=1, run_id='fixture-run', phase='F1', group='gate_fix', extra_rounds=1, findings=['G3-B1'],
                           user_decision='Allow a third gate-fix round for G3-B1.'))
        self.ok(action='extend-cap', authorization=auth)
        self.gate_fix_round('third gate fix\n')
        self.assertEqual(f.state['rounds']['gate_fix'], 3)

    # -- 12/13: plan authorship is the plan authors only ------------------------------------------
    def test_12_code_writers_are_not_plan_authors(self):
        """Opus plans; the implementation fell back to Luna; a later plan revision is still reviewed by Astra."""
        f = self.f
        f.state['plan_authors'] = [f.observation(f.assignment('plan-writer', 'Anthropic'))]
        self.ok(f.report_input('implementer', 'OpenAI'))
        f.plan.write_text(f.plan.read_text().replace('Fixture plan.', 'Fixture plan, phase split.'), encoding='utf-8')
        revised = f.report_input('plan-reviser', 'Anthropic', token='REVISED', artifact=f.plan_artifact(), round=1)
        revised['plan'] = f.plan_ref()
        self.ok(revised)
        plan = f.plan_artifact()
        self.no(1, 'same-family plan review', f.report_input('plan-reviewer', 'Anthropic', artifact=plan))
        self.ok(f.report_input('plan-reviewer', 'OpenAI', artifact=plan))

    def test_13_astra_profile_run_keeps_its_plan_reviewer(self):
        """An Astra-written plan, a Claude-written frontend, an Astra revision: Opus still reviews the plan."""
        f = self.f
        f.state['plan_authors'] = [f.observation(f.assignment('plan-writer', 'OpenAI'))]
        self.ok(f.report_input('frontend-implementer', 'Anthropic'))
        f.plan.write_text(f.plan.read_text().replace('Fixture plan.', 'Fixture plan, revised by Astra.'), encoding='utf-8')
        revised = f.report_input('plan-reviser', 'OpenAI', token='REVISED', artifact=f.plan_artifact(), round=1)
        revised['plan'] = f.plan_ref()
        self.ok(revised)
        plan = f.plan_artifact()
        self.no(1, 'same-family plan review', f.report_input('plan-reviewer', 'OpenAI', artifact=plan))
        self.ok(f.report_input('plan-reviewer', 'Anthropic', artifact=plan))

    # -- 14: a final-fix commit needs a gate on its bytes ----------------------------------------
    def test_14_final_fix_commit_requires_a_gate_on_the_fixed_bytes(self):
        f = self.f; phase = self.to_final_review()
        self.stage('final fix\n')
        fixed, coverage = f.package_ref()
        self.ok(f.report_input('review-final', 'Google', artifact=fixed, coverage=coverage))
        self.no(2, 'required report is missing: gate', action='prepare-commit', artifact=fixed, fleet=f.fleet())
        self.ok(action='record-gate', artifact=fixed, evidence=self.passing_evidence())
        self.ok(action='prepare-commit', artifact=fixed, fleet=f.fleet())
        sha = f.git_commit('fix: address final-review findings')
        self.ok(action='confirm-commit', artifact=fixed, commit=dict(sha=sha, base=phase), fleet=f.fleet(), barrier='awaiting_final_review')

    # -- 15: delivery repair returns to the final review ------------------------------------------
    def test_15_delivery_repair_returns_to_final_review(self):
        f = self.f; phase = self.to_final_review()
        final, coverage = f.package_ref()
        self.ok(f.report_input('review-final', 'Google', artifact=final, coverage=coverage))
        f.state['rounds']['final_review'] = 1
        self.no(1, 'reopen-final outside delivery or completion', action='reopen-final', fleet=f.fleet())
        self.ok(action='finish-checkpoint', artifact=final, fleet=f.fleet(), barrier='awaiting_delivery')
        self.ok(action='record-gate', verdict='GATE_FAIL', artifact=f.snapshot_ref(), evidence=self.gate_failure())
        self.ok(action='reopen-final', fleet=f.fleet(), barrier='awaiting_final_review')
        self.assertEqual((f.state['step'], f.state['final_source'], f.state['rounds']['final_review']), ('final-review', None, 1))
        self.stage('delivery repair\n')
        repaired, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=repaired, evidence=self.passing_evidence())
        self.ok(f.report_input('review-final', 'Google', artifact=repaired, coverage=coverage, round=2))
        self.ok(action='prepare-commit', artifact=repaired, fleet=f.fleet())
        sha = f.git_commit('fix: delivery repair')
        self.ok(action='confirm-commit', artifact=repaired, commit=dict(sha=sha, base=phase), fleet=f.fleet())
        self.ok(action='finish-checkpoint', artifact=repaired, fleet=f.fleet(), barrier='awaiting_delivery')
        self.ok(action='record-gate', artifact=f.snapshot_ref(), evidence=self.passing_evidence())
        self.ok(action='finish-checkpoint', artifact=f.snapshot_ref(), fleet=f.fleet(), barrier='awaiting_completion_commit')

    # -- 16: synthesis does not invalidate the acceptance it summarises ----------------------------
    def test_16_synthesis_is_committed_with_the_phase_without_a_new_review(self):
        f = self.f; art, coverage = self.phase_ready()
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage, round=2))
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage, round=2), barrier='awaiting_commit')
        self.worker('synthesizer', 'Google', assigned=f.snapshot_ref(), deliver=self.writer('docs/reviews/fixture-F1.md', '# F1 review synthesis\n'),
                    token='SYNTHESIS_DONE', barrier='awaiting_commit')
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet())
        self.write('docs/reviews/fixture-F1.md', '# rewritten after acceptance\n')
        self.no(1, 'stale synthesis: docs/reviews/fixture-F1.md', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.write('docs/reviews/fixture-F1.md', '# F1 review synthesis\n')
        sha = f.git_commit('feat: fixture phase F1')
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=sha, base=f.git.base), fleet=f.fleet(), barrier='awaiting_final_review')
        self.assertIn('docs/reviews/fixture-F1.md', f.git.git('show', '--name-only', '--format=', sha).split())

    # -- 17: both backends share canonical identities and exact model lookup ----------------------
    def test_17_canonical_candidate_and_exact_model_ids(self):
        f = self.f; name = "docs/заметка d'Artagnan <x>.md"
        self.write(name, 'Unicode path and apostrophe\n')
        snap = f.snapshot_ref()
        self.ok(f.report_input('implementer', artifact=snap))
        files = read_json(snap['path'])['manifest']['files']
        entries = {k[5:]: x['sha256'] + ('+x' if (x.get('index') or [''])[0] == '100755' else '')
                   for k, x in files.items() if k.startswith('repo:') and x['type'] == 'file' and k[5:] != 'plan.md'}
        canonical = json.dumps(entries, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()
        self.assertIn(b'\\u0437', canonical); self.assertIn(b"d'Artagnan <x>", canonical)
        self.assertEqual(f.state['accepted'][-1]['candidate'], hashlib.sha256(canonical).hexdigest())
        # A model id differing only in case is not a known model on either backend.
        self.no(2, 'unknown actual model family: OPUS', action='dispatch', proposed=dict(self.assignment('review-control', 'Anthropic'), model='OPUS'),
                artifact=f.package_ref()[0], fleet=f.fleet())

    # -- 18: transition coverage: record-author needs a durably settled author -------------------
    def test_18_record_author_rejects_a_running_or_non_durable_author(self):
        f = self.f; a = f.assignment('implementer', 'Anthropic')
        self.no(2, 'author Dispatch is not durably settled', action='record-author', observation=f.observation(a, status='running'),
                artifact=f.snapshot_ref())
        raw = read_json(f.observation(a)['path']); raw['result']['projection']['evidence']['durable'] = False
        self.no(2, 'author Dispatch is not durably settled', action='record-author', observation=f.save(raw), artifact=f.snapshot_ref())
        self.ok(action='record-author', observation=f.observation(a), artifact=f.snapshot_ref())


    # == Round-2 review (Astra xhigh) =============================================================================
    def rebase_on(self, name, text):
        """Commit one file as an earlier phase of this Run (after plan_base) and make that commit the phase base."""
        f = self.f; self.write(name, text)
        f.git.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
                  '-c', 'core.hooksPath=', 'commit', '-qm', 'earlier phase', '--', name)
        new = f.git.git('rev-parse', 'HEAD').strip()
        f.plan.write_text(f.plan.read_text().replace('    base: ' + f.git.base, '    base: ' + new), encoding='utf-8')
        f.state.update(base=new, plan=f.plan_ref())
        return new

    def legacy(self, *keys):
        """The state shape of the live Runs, written before authors/plan_authors/attempts/plan_approved existed."""
        for key in keys or ('authors', 'plan_authors', 'authors_incomplete', 'attempts', 'plan_approved'): self.f.state.pop(key, None)

    def test_r2_10_free_text_expect_is_checked_by_its_exit_code(self):
        """p3b F3R2-CV1: `exit 0; stdout — <prose>` with a sealed result already recorded as verified-by-controller."""
        f = self.f
        self.ok(f.report_input('implementer'))
        art, coverage = f.package_ref()
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        path, spec = f.verified_spec(code="print('one JSON line')")
        prose = dict(id='F3R2-CV1', kind='cannot_verify', issue='merge result not run', location='tracked.txt', check=spec['command'],
                     expect='exit 0; stdout — одна JSON-строка из двух объектов, где x.d="conflict" (без \\n)')
        wrong = dict(prose, id='CV-exit', expect='exit 3; stdout — the command fails')
        noexit = dict(prose, id='CV-prose', expect='the merge reports a conflict')
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage, findings=[prose, wrong, noexit]))
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage), barrier='awaiting_resolution')
        rc, out, err = f.start(path).finish(); self.assertEqual(rc, 0, (out, err))
        result = str(Path(spec['run_dir']) / 'result.json')
        ledger = f.workspace / 'ledger.json'
        ledger.write_text(json.dumps([dict(id=i, check=result, status='verified-by-controller') for i in ('F3R2-CV1', 'CV-exit', 'CV-prose')]))
        self.no(1, 'unresolved findings: CV-exit, CV-prose', action='prepare-commit', artifact=art, fleet=f.fleet(), ledger=f.reference(ledger))
        ledger.write_text(json.dumps([dict(id='F3R2-CV1', check=result), dict(id='CV-exit', decision='DEFER'), dict(id='CV-prose', decision='DEFER')]))
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet(), ledger=f.reference(ledger))

    def test_r2_11_legacy_state_rebuilds_plan_authors_without_code_writers(self):
        """An astra-profile Run without plan_authors: an Anthropic frontend contribution does not bar Opus from the plan."""
        f = self.f; self.baseline_tracked()
        self.write('api.ts', 'export const api = 1\n')
        art, coverage = f.package_ref(families={'OpenAI': ['plan.md'], 'Google': ['api.ts']})
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        self.legacy()
        self.ok()
        self.assertEqual(f.state['authors'], {'api.ts': ['Google']})
        self.assertEqual(len(f.state['plan_authors']), 1)
        self.ok(f.report_input('frontend-implementer', 'Anthropic', artifact=self.writer('ui.tsx', 'export const ui = 1\n')()))
        f.plan.write_text(f.plan.read_text().replace('Fixture plan.', 'Fixture plan, revised by Astra.'), encoding='utf-8')
        revised = f.report_input('plan-reviser', 'OpenAI', token='REVISED', artifact=f.plan_artifact())
        revised['plan'] = f.plan_ref()
        self.ok(revised)
        plan = f.plan_artifact()
        self.no(1, 'same-family plan review', f.report_input('plan-reviewer', 'OpenAI', artifact=plan))
        self.ok(f.report_input('plan-reviewer', 'Anthropic', artifact=plan))

    def test_r2_03_unattributed_earlier_side_file_is_unknown_not_independent(self):
        """A contract side names a file written earlier in this Run with no recorded author (a legacy state's history)."""
        f = self.f
        self.rebase_on('lib/earlier.ts', 'export const earlier = 1\n')
        self.ok(f.report_input('implementer', 'Google'))
        sides = [dict(id='C1', producer=['lib/earlier.ts'], consumer=['tracked.txt'])]
        art, coverage = f.package_ref(families={'Google': ['tracked.txt', 'plan.md']}, contracts=sides)
        review = lambda family, cov: dict(self.assignment('review-primary', family), coverage=dict(cov, contracts=sides))
        self.no(2, 'unknown actual author: lib/earlier.ts', action='dispatch', proposed=review('Anthropic', coverage), artifact=art, fleet=f.fleet())
        # Declaring the earlier writer's receipt in the package resolves it.
        art, coverage = f.package_ref(families={'Google': ['tracked.txt', 'plan.md', 'lib/earlier.ts']}, contracts=sides)
        self.ok(action='dispatch', proposed=review('Anthropic', coverage), artifact=art, fleet=f.fleet())

    def test_r2_02_settled_writer_is_attributed_before_its_replacement(self):
        f = self.f; self.baseline_tracked()
        claude = self.assignment('frontend-implementer', 'Anthropic')
        self.ok(action='dispatch', proposed=claude, artifact=f.snapshot_ref(), fleet=f.fleet())
        self.ok(action='bind-dispatch', observation=f.observation(dict(claude, dispatch_id='D-claude'), 'running'))
        self.write('ui.tsx', 'export const ui = 1\n')
        self.no(1, 'format: role verdict', f.report_input('frontend-implementer', 'Anthropic', token='WRONG', artifact=f.snapshot_ref(),
                                                          assignment=f.state['active']))
        done = dict(dispatchId='D-claude', taskId=claude['task_id'], dispatchStatus='completed', terminalState='retained', resource=None,
                    projection=dict(workspace=dict(id='fixture-worktree'), evidence=dict(durable=True), liveness=dict(verdict='live')))
        gemini = self.assignment('implementer', 'Google')
        self.no(2, 'record-author it first', action='dispatch', proposed=gemini, artifact=f.snapshot_ref(), fleet=f.fleet([done]))
        self.ok(action='record-author', observation=f.observation(dict(claude, dispatch_id='D-claude')), artifact=f.snapshot_ref())
        self.assertEqual(f.state['authors'], {'ui.tsx': ['Anthropic']})  # exactly its own window
        self.worker('implementer', 'Google', assigned=f.snapshot_ref(), deliver=self.writer('api.py', 'API = 1\n'), barrier='awaiting_gate')
        art, coverage = f.package_ref(families={'Google': ['api.py', 'plan.md']})
        self.no(1, 'same-family review: ui.tsx', action='dispatch', proposed=dict(self.assignment('review-primary', 'Anthropic'), coverage=coverage),
                artifact=art, fleet=f.fleet())

    def test_r2_02b_record_author_with_a_plan_artifact_records_a_plan_author(self):
        f = self.f
        reviser = f.observation(f.assignment('plan-reviser', 'OpenAI'))
        self.ok(action='record-author', observation=reviser, artifact=f.plan_artifact())
        self.no(1, 'same-family plan review', f.report_input('plan-reviewer', 'OpenAI', artifact=f.plan_artifact()))

    def test_r2_09_a_launch_with_another_model_that_wrote_is_recovered_by_record_author(self):
        f = self.f; gemini = self.assignment('implementer', 'Google')
        self.ok(action='dispatch', proposed=gemini, artifact=f.snapshot_ref(), fleet=f.fleet(), barrier='awaiting_writer')
        # The terminal actually started Luna; it wrote and settled before the coordinator could bind.
        actual = f.observation(dict(gemini, dispatch_id='D-actual', model=f.model('OpenAI')))
        self.no(1, 'actual launch differs from proposal', action='bind-dispatch', observation=actual)
        self.write('tracked.txt', 'written by the actual launch\n')
        row = dict(dispatchId='D-actual', taskId=gemini['task_id'], dispatchStatus='completed', terminalState='retained', resource=None,
                   projection=dict(workspace=dict(id='fixture-worktree'), evidence=dict(durable=True), liveness=dict(verdict='live')))
        self.no(1, 'the failed launch changed the candidate', action='reconcile-intent', fleet=f.fleet([row]), artifact=f.snapshot_ref())
        self.ok(action='record-author', observation=actual, artifact=f.snapshot_ref(), barrier='awaiting_implementation')
        self.assertEqual((f.state['active'], f.state['write_ownership'], f.state['authors']), (None, [], {'tracked.txt': ['OpenAI']}))
        self.ok(action='dispatch', proposed=self.assignment('implementer', 'Google'), artifact=f.snapshot_ref(), fleet=f.fleet([row]))

    def test_r2_06_mid_phase_plan_revision_awaits_an_independent_plan_review(self):
        f = self.f; art, _ = self.phase_ready()
        f.plan.write_text(f.plan.read_text().replace('Fixture plan.', 'Fixture plan, split after review.'), encoding='utf-8')
        revised = f.report_input('plan-reviser', 'Anthropic', token='REVISED', artifact=f.plan_artifact())
        revised['plan'] = f.plan_ref()
        self.ok(revised, barrier='awaiting_plan_review')
        self.no(1, 'plan revision awaits an independent plan review', action='prepare-commit', artifact=art, fleet=f.fleet())
        self.no(1, 'plan revision awaits an independent plan review', action='dispatch', proposed=self.assignment('implementer'),
                artifact=f.snapshot_ref(), fleet=f.fleet())
        self.ok(f.report_input('plan-reviewer', 'OpenAI', artifact=f.plan_artifact()), barrier='awaiting_commit')
        f.git.git('add', 'plan.md')
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet())

    def test_r2_08_a_contract_side_finding_needs_a_review_of_that_side(self):
        f = self.f
        self.rebase_on('producer.py', 'def produce(): return 1\n')
        self.ok(f.report_input('implementer', 'OpenAI', artifact=self.writer('consumer.py', 'from producer import produce\n')()))
        sides = [dict(id='C1', producer=['producer.py'], consumer=['consumer.py'])]
        art, coverage = f.package_ref(families={'OpenAI': ['consumer.py', 'tracked.txt', 'plan.md'], 'Google': ['producer.py']}, contracts=sides)
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        full = dict(coverage, contracts=sides)
        self.ok(f.report_input('review-primary', 'Anthropic', token='REVIEW_BLOCKING', artifact=art, coverage=full,
                               findings=[blocking('F1-B1', location='producer.py:9')]))
        consumer_only = dict(coverage, contracts=[dict(id='C1', producer=[], consumer=['consumer.py'])])
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=consumer_only, round=2))
        self.ok(f.report_input('review-control', 'Anthropic', artifact=art, coverage=full), barrier='awaiting_resolution')
        self.no(1, 'unresolved findings: F1-B1', action='prepare-commit', artifact=art, fleet=f.fleet())
        producer_side = dict(files=[], parts=coverage['parts'], contracts=[dict(id='C1', producer=['producer.py'], consumer=[])])
        self.ok(f.report_input('review-primary', 'OpenAI', artifact=art, coverage=producer_side, round=2), barrier='awaiting_commit')

    def test_r2_04_synthesis_exception_is_one_markdown_document_only(self):
        f = self.f; art, coverage = self.phase_ready()
        synth = lambda name, text, extra=None: self.worker(
            'synthesizer', 'Google', assigned=f.snapshot_ref(), token='SYNTHESIS_DONE', synthesis=name,
            deliver=(lambda: (self.write(extra, 'x = 1\n') if extra else None, self.writer(name, text)())[1]))
        synth('docs/reviews/test_unreviewed.py', 'assert True\n')
        self.no(1, 'stale artifact', action='prepare-commit', artifact=art, fleet=f.fleet())
        f.git.git('rm', '-q', '-f', 'docs/reviews/test_unreviewed.py')
        synth('docs/reviews/fixture-F1.md', '# synthesis\n', extra='docs/reviews/helper.py')
        self.no(1, 'stale artifact', action='prepare-commit', artifact=art, fleet=f.fleet())
        f.git.git('rm', '-q', '-f', 'docs/reviews/helper.py', 'docs/reviews/fixture-F1.md')
        synth('docs/reviews/fixture-F1.md', '# synthesis\n')
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet())
        # A hook rewrote it: the documented recovery is a new synthesis, accepted on the unchanged reviewed candidate.
        self.write('docs/reviews/fixture-F1.md', '# rewritten by a hook\n')
        self.no(1, 'stale synthesis', action='prepare-commit', artifact=art, fleet=f.fleet())
        synth('docs/reviews/fixture-F1.md', '# synthesis, regenerated\n')
        self.ok(action='prepare-commit', artifact=art, fleet=f.fleet())

    def test_r2_12_reopen_final_at_the_cap_needs_a_new_round(self):
        f = self.f; self.to_final_review()
        final, coverage = f.package_ref()
        for n in (1, 2): self.worker('review-final', 'Google', assigned=final, coverage=coverage, round=n)
        self.ok(action='finish-checkpoint', artifact=final, fleet=f.fleet(), barrier='awaiting_delivery')
        self.ok(action='record-gate', verdict='GATE_FAIL', artifact=f.snapshot_ref(), evidence=self.gate_failure())
        self.ok(action='reopen-final', fleet=f.fleet(), barrier='awaiting_final_review')
        again = lambda n: dict(self.assignment('review-final', 'Google', round=n), coverage=coverage)
        self.no(1, 'substantive review needs a new round', action='dispatch', proposed=again(2), artifact=final, fleet=f.fleet())
        self.no(1, 'round cap/sequence: final_review', action='dispatch', proposed=again(3), artifact=final, fleet=f.fleet())
        self.ok(action='extend-cap', authorization=f.save(dict(schema_version=1, run_id='fixture-run', phase='F1', group='final_review',
                extra_rounds=1, findings=['G1-B1'], user_decision='One more final review after the delivery failure.')))
        self.ok(action='dispatch', proposed=again(3), artifact=final, fleet=f.fleet())

    def test_r2_13_canonical_json_vectors(self):
        """Golden canonical bytes both backends must emit: code-point key order (U+10000 after U+E000), -0.0, escapes."""
        f = self.f; src = f.workspace / 'canonical-in.json'; out = f.workspace / 'canonical-out.json'
        src.write_text('{"\\ue000":1,"\\ud800\\udc00":2,"a":-0.0,"b":[0.1,2.0,1e-05,1e+16,1000000000000001.0],"c":"d\'Artagnan <x> \\u0437"}', encoding='utf-8')
        rc, stdout, stderr = f.helper('canonical', src, out)
        self.assertEqual(rc, 0, (stdout, stderr))
        self.assertEqual(out.read_bytes(), b'{"a":-0.0,"b":[0.1,2.0,1e-05,1e+16,1000000000000001.0],"c":"d\'Artagnan <x> \\u0437","\\ue000":1,"\\ud800\\udc00":2}')

    # == Round-3 review (Astra xhigh) =============================================================================
    def revise(self, family, text, round=1):
        """A plan reviser's accepted REVISED report changing the plan body (a substantive mid-phase revision)."""
        f = self.f; f.plan.write_text(f.plan.read_text().replace('Fixture plan', text, 1), encoding='utf-8')
        data = f.report_input('plan-reviser', family, token='REVISED', artifact=f.plan_artifact(), round=round)
        data['plan'] = f.plan_ref()
        return data

    def test_r3_2_partial_legacy_history_keeps_a_file_unknown(self):
        """OpenAI writes the producer in F1; Google changes it in F2; only F2's package survives the upgrade."""
        f = self.f; base = f.git.base; self.baseline_tracked()
        f.plan.write_text(two_phases(base, f1=base), encoding='utf-8'); f.git.git('add', 'plan.md')
        f.state['plan'] = f.plan_ref(); f.state['plan_approved'] = f.state['plan']['structure']
        self.worker('implementer', 'OpenAI', assigned=f.snapshot_ref(), deliver=self.writer('producer.ts', 'export const p = 1\n'), barrier='awaiting_gate')
        art, coverage = f.package_ref(families={'OpenAI': ['producer.ts', 'plan.md']})
        self.ok(action='record-gate', artifact=art, evidence=self.passing_evidence())
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        self.ok(f.report_input('review-control', 'Google', artifact=art, coverage=coverage, round=2), barrier='awaiting_commit')
        f1 = f.git_commit('feat(F1): producer')
        self.ok(action='confirm-commit', artifact=art, commit=dict(sha=f1, base=base), fleet=f.fleet())
        self.ok(action='advance')
        f.plan.write_text(two_phases(base, f1=base, f2=f1), encoding='utf-8'); f.git.git('add', 'plan.md')
        self.ok(plan=f.plan_ref())
        self.worker('implementer', 'Google', assigned=f.snapshot_ref(), deliver=self.writer('producer.ts', 'export const p = 2\n'), barrier='awaiting_gate')
        art, coverage = f.package_ref(families={'Google': ['producer.ts', 'plan.md']})
        self.ok(f.report_input('review-primary', 'Anthropic', artifact=art, coverage=coverage))
        self.legacy('authors', 'plan_authors', 'authors_incomplete')
        self.ok()
        self.assertEqual((f.state['authors'], f.state['authors_incomplete']), ({'producer.ts': ['Google']}, {'producer.ts': 2}))
        astra = lambda a, c: dict(self.assignment('review-control', 'OpenAI'), coverage=c)
        self.no(2, 'unknown actual author: producer.ts', action='dispatch', proposed=astra(art, coverage), artifact=art, fleet=f.fleet())
        # Declaring the earlier phase's writer too makes the history complete, and then OpenAI is its author.
        full, coverage = f.package_ref(families={'Google': ['producer.ts', 'plan.md'], 'OpenAI': ['producer.ts']})
        self.no(1, 'same-family review: producer.ts', action='dispatch', proposed=astra(full, coverage), artifact=full, fleet=f.fleet())

    def test_r3_3_upgrade_keeps_an_unreviewed_revision_pending(self):
        f = self.f; self.phase_ready()
        self.ok(self.revise('Anthropic', 'Fixture plan, split'))
        self.legacy()
        self.ok(barrier='awaiting_plan_review')
        # With the approval in the state, the upgrade proves the revised structure approved.
        self.ok(f.report_input('plan-reviewer', 'Google', artifact=f.plan_artifact()))
        self.legacy()
        self.ok(barrier='awaiting_commit')

    def test_r3_6_legacy_checkpoint_keeps_its_consumed_rounds(self):
        f = self.f; self.to_final_review()
        final, coverage = f.package_ref()
        for n in (1, 2): self.worker('review-final', 'Google', assigned=final, coverage=coverage, round=n)
        self.ok(action='finish-checkpoint', artifact=final, fleet=f.fleet(), barrier='awaiting_delivery')
        self.legacy('attempts')
        self.ok(action='record-gate', verdict='GATE_FAIL', artifact=f.snapshot_ref(), evidence=self.gate_failure())
        self.ok(action='reopen-final', fleet=f.fleet(), artifact=f.snapshot_ref())
        self.no(1, 'substantive review needs a new round', action='dispatch', artifact=final, fleet=f.fleet(),
                proposed=dict(self.assignment('review-final', 'Google', round=2), coverage=coverage))


if __name__ == '__main__': unittest.main()

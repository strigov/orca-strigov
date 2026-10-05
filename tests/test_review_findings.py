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


if __name__ == '__main__': unittest.main()

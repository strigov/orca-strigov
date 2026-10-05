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


if __name__ == '__main__': unittest.main()

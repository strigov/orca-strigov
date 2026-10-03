"""C6 v2 rejection catalogue: one real proposal per rejection reason not exercised elsewhere.

Each case names the exact exit code and reason fragment; a rejected proposal must
leave a previous RESUME_OUT untouched. Receipts are synthetic, Git/C4/C5 real.
"""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import unittest

from support import WINDOWS, ProtocolFixture, command, read_json

TOKENS = ['VALID', 'INVALID', 'UNVERIFIABLE']


class RejectionTests(unittest.TestCase):
    def setUp(self): self.f = ProtocolFixture()
    def tearDown(self): self.f.close()

    def expect(self, cases):
        """Run (proposal, code, reason) cases in bounded native batches; rejections keep RESUME_OUT."""
        f = self.f
        for start in range(0, len(cases), 6):
            group = cases[start:start + 6]
            outputs = [Path(f.save('previous complete record')['path']) for _ in group]
            results = f.validate_many([copy.deepcopy(data) for data, _, _ in group], outputs=outputs)
            for (code, token, result), (_, want, why), output in zip(results, group, outputs):
                print(json.dumps(dict(code=code, reason=result.get('reason'))), flush=True)
                self.assertEqual((code, token), (want, TOKENS[want]), result)
                self.assertIn(why, result.get('reason', ''))
                if want: self.assertEqual(output.read_bytes(), b'previous complete record')

    def case(self, action='resume', state=None, **fields):
        return copy.deepcopy(dict(schema_version=1, action=action, state=state or self.f.state, **fields))

    def report(self, *args, **kwargs):
        return copy.deepcopy(self.f.report_input(*args, **kwargs))

    def edited(self, data, change=None, subject=None, **payload):
        """A new report file (and matching event) whose text is change(old text)."""
        f = self.f; text = Path(data['report']['path']).read_text(encoding='utf-8')
        report = f.save(change(text) if change else text, '.md')
        event = read_json(data['event']['path']); message = event['result']['message']
        body = json.loads(message['payload']); body.update(payload, reportPath=report['path'])
        message['payload'] = json.dumps(body)
        if subject is not None: message['subject'] = subject
        return dict(copy.deepcopy(data), report=report, event=f.save(event))

    def event(self, data, **changes):
        event = read_json(data['event']['path']); event['result']['message'].update(changes)
        return dict(copy.deepcopy(data), event=self.f.save(event))

    def binding(self, data, **changes):
        def change(text):
            line = re.search(r'^BINDING: (.+)$', text, re.M)
            return text.replace(line[1], json.dumps(dict(json.loads(line[1]), **changes)))
        return self.edited(data, change)

    def observed(self, data, **dispatch):
        raw = read_json(data['observation']['path'])
        raw['result']['dispatch'].update(dispatch)
        return dict(copy.deepcopy(data), observation=self.f.save(raw))

    def linked_dir(self, target):
        link = self.f.workspace / ('linked-' + str(self.f.serial)); self.f.serial += 1
        if WINDOWS:
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True, capture_output=True)
        else: link.symlink_to(target, target_is_directory=True)
        return link

    def test_report_format_rejections(self):
        f = self.f; art, cov = f.package_ref()
        impl = self.report()
        fix = dict(f.assignment(), fix=True)
        review = lambda findings, token='REVIEW_BLOCKING', role='review-primary': self.report(role, 'Google', token, art, cov, findings)
        bad = dict(id='B', kind='blocking', issue='i', location='tracked.txt', change='c', risk='none', **{'class': 'MUST_FIX_NOW'})
        self.expect([
            (self.edited(impl, lambda t: 'WRONG' + t[4:], subject='WRONG'), 1, 'format: role verdict'),
            (self.edited(impl, outcome='failed'), 1, 'format: subject/outcome conflict'),
            (self.edited(impl, lambda t: re.sub(r'^BINDING: .*\n', '', t, flags=re.M)), 1, 'format: expected one BINDING'),
            (self.binding(impl, extra=1), 1, 'format: binding schema'),
            (self.binding(impl, task_id='other-task'), 1, 'conflicting report binding: task_id'),
            (self.binding(impl, artifact_id='other-artifact'), 1, 'conflicting artifact binding')])
        self.expect([
            (self.edited(impl, lambda t: 'BLOCKED' + t[4:], subject='BLOCKED', outcome='failed'), 1, 'format: missing Reason'),
            (self.edited(self.report('review-primary', 'Google', artifact=art, coverage=cov), lambda t: t.replace('SPEC: OK', 'SPEC: FAIL')),
             1, 'format: SPEC/QUALITY verdict conflict'),
            (self.edited(review([]), lambda t: re.sub(r'^FINDINGS: .*$', 'FINDINGS: {}', t, flags=re.M)), 1, 'format: findings array'),
            (review([dict(bad, kind='other')]), 1, 'format: finding kind'),
            (review([dict(bad, risk='huge')]), 1, 'format: finding risk'),
            (review([dict(bad, **{'class': 'LATER'})]), 1, 'format: finding class')])
        self.expect([
            (review([dict(bad, simplicity=True)]), 1, 'format: simplicity finding'),
            (self.report(assignment=dict(fix, round=2), extra='FIX_EVIDENCE: {"tests":[],"commands":["c"],"outputs":["o"]}'), 1, 'format: fix evidence'),
            (self.edited(self.report('gate', token='GATE_FAIL'), lambda t: t.replace('verify: fixture=PASS', 'nonsense')), 1, 'format: gate summary'),
            (self.report('synthesizer', token='SYNTHESIS_DONE'), 1, 'format: synthesis path'),
            (self.report('diagnosis', token='IMPASSE_SUMMARY'), 1, 'format: diagnosis sections')])
        f.state.update(phase=None, step='plan')
        plan = f.plan_artifact()
        plan_review = lambda findings, round=1, token='CHANGES_REQUESTED': self.report('plan-reviewer', 'Google', token, plan, None, findings, round)
        self.expect([
            (self.edited(plan_review([], token='APPROVED'), lambda t: t.replace('SIMPLICITY: OK', 'SIMPLICITY: CHANGES_REQUESTED')), 1, 'format: simplicity verdict conflict'),
            (plan_review([bad]), 1, 'format: plan criterion'),
            (plan_review([dict(bad, criterion='scope')], round=2), 1, 'format: new blocker materiality')])

    def test_delivery_and_settlement_rejections(self):
        f = self.f; art, cov = f.package_ref()
        impl = self.report()
        failed = read_json(impl['event']['path']); failed['ok'] = False
        reader = self.report('review-primary', 'Google', artifact=art, coverage=cov); reader['state']['active']['artifact_id'] = 'other'
        unsuccessful = read_json(impl['observation']['path']); unsuccessful['ok'] = False
        elsewhere = read_json(impl['observation']['path']); elsewhere['result']['projection']['workspace']['id'] = 'other-worktree'
        self.expect([
            (dict(impl, event=f.save(failed)), 2, 'Orca did not accept event'),
            (dict(impl, message_id='no-such-message'), 2, 'missing exact delivery message'),
            (dict(impl, observation=f.observation(impl['state']['active'], 'running')), 2, 'missing durable settlement'),
            (self.event(impl, from_handle='someone-else'), 1, 'wrong report sender'),
            (reader, 1, 'assigned artifact changed'),
            (dict(impl, observation=f.save(unsuccessful)), 2, 'unsuccessful Orca observation')])
        self.expect([
            (self.observed(impl, taskId='other-task'), 1, 'Task/Run observation mismatch'),
            (self.observed(impl, id='other-dispatch'), 1, 'Dispatch observation mismatch'),
            (dict(impl, observation=f.save(elsewhere)), 2, 'observation worktree mismatch')])

    def test_dispatch_bind_and_model_proof_rejections(self):
        f = self.f; art = f.snapshot_ref()
        proposed = f.assignment(); proposed['dispatch_id'] = None
        dispatch = lambda **changed: self.case('dispatch', proposed=dict(proposed, **changed), artifact=art, fleet=f.fleet())
        self.expect([
            (dispatch(phase='F9'), 1, 'proposed binding mismatch'),
            (dispatch(round=0), 1, 'invalid proposed round'),
            (dispatch(dispatch_id='already-created'), 1, 'needs a fresh Task and null not-yet-created Dispatch'),
            (self.case('bind-dispatch', observation=f.observation(dict(proposed, dispatch_id='d'))), 1, 'no pending dispatch intent')])
        self.assertEqual(f.validate(dispatch())[0], 0)
        bound = dict(proposed, dispatch_id='bound-dispatch')
        retry = read_json(f.observation(bound, 'running')['path']); retry['result']['dispatch']['retryOfDispatchId'] = 'old'
        start = read_json(f.start_receipt(bound)['path']); start['ok'] = False
        self.expect([
            (self.case('bind-dispatch', observation=f.save(retry)), 1, 'dispatch does not bind pending fresh Task'),
            (self.case('bind-dispatch', observation=f.observation(bound, 'running', model=None, start=f.save(start))), 2, 'unsuccessful worker-start receipt')])
        # Claude Path A reuse chain and Path B transcript facts.
        f.state.update(active=None, write_ownership=[])
        claude = f.assignment(family='Anthropic'); claude['dispatch_id'] = None
        self.assertEqual(f.validate(self.case('dispatch', proposed=claude, artifact=f.snapshot_ref(), fleet=f.fleet()))[0], 0)
        task, d = claude['task_id'], 'ctx_reuse'
        observed = f.claude_observation(d, task)
        current = f.launch_receipt(task, d, 'reused')
        origin = read_json(f.launch_receipt('origin-task', 'ctx_origin', 'created', model=claude['model'])['path'])
        bind = lambda first, obs=observed: self.case('bind-dispatch', observation=dict(obs, start=current, origin_start=first))
        def variant(change):
            raw = copy.deepcopy(origin); change(raw); return f.save(raw)
        no_incarnation = read_json(f.launch_receipt('origin-task', 'ctx_origin', 'created', model=claude['model'], incarnation='')['path'])
        def transcript(rows):
            path = f.workspace / ('transcript-' + str(f.serial) + '.jsonl'); f.serial += 1
            path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            return dict(f.reference(path), kind='claude-transcript')
        good = Path(f.claude_transcript(f.workspace / 'good.jsonl', task, d)).read_text().splitlines()
        rows = [json.loads(x) for x in good]
        rows[-1]['sessionId'] = 'another-session'
        no_root = read_json(observed['path']); no_root['result']['terminal']['worktreePath'] = None
        evidence = lambda proof, obs=observed: self.case('bind-dispatch', observation=dict(obs, model_evidence=proof))
        self.expect([
            (bind(variant(lambda r: r.update(ok=False))), 2, 'unsuccessful origin worker-start receipt'),
            (bind(variant(lambda r: r['result']['launch']['effective'].update(agent='codex'))), 1, 'origin launch agent mismatch'),
            (bind(f.save(no_incarnation)), 2, 'missing terminal incarnation'),
            (evidence(transcript(rows)), 1, 'Claude transcript session changed'),
            (evidence(transcript([[1]])), 2, 'invalid session transcript record'),
            (evidence(transcript([json.loads(x) for x in good]), f.save(no_root)), 2, 'missing Dispatch worktree path')])

    def test_fleet_rejections(self):
        f = self.f; proposed = f.assignment(); proposed['dispatch_id'] = None; art = f.snapshot_ref()
        page = lambda **result: dict(f.save(dict(id='fleet-' + str(f.serial), ok=True, result=dict(dict(
            scope=dict(source='all'), workers=[], page=dict(total=0, hasMore=False, nextCursor=None)), **result))), cursor=None)
        unavailable = page(); raw = read_json(unavailable['path']); raw['ok'] = False
        first = page(page=dict(total=2, hasMore=True, nextCursor='next'), workers=[dict(dispatchId='a', dispatchStatus='completed', projection=dict(evidence=dict(durable=True)))])
        second = dict(page(page=dict(total=3, hasMore=False, nextCursor=None), workers=[]), cursor='next')
        dispatch = lambda fleet: self.case('dispatch', proposed=proposed, artifact=art, fleet=fleet)
        self.expect([
            (dispatch([]), 2, 'missing fresh fleet'),
            (dispatch([dict(page(), cursor='unexpected')]), 2, 'fleet cursor mismatch'),
            (dispatch([dict(f.save(raw), cursor=None)]), 2, 'fleet unavailable'),
            (dispatch([page(scope=dict(source='run'))]), 2, 'fleet must cover all local runs'),
            (dispatch([first, second]), 2, 'inconsistent fleet')])

    def test_artifact_plan_and_coverage_rejections(self):
        f = self.f; snap = f.snapshot_ref(); raw = read_json(snap['path'])
        real = f.base / 'real-artifacts'; real.mkdir(); (real / 'snapshot.json').write_bytes(Path(snap['path']).read_bytes())
        linked = self.linked_dir(real)
        package, cov = f.package_ref(); incomplete = read_json(package['path']); incomplete['complete'] = False
        spec = f.base / 'other-snapshot.json'; out = f.base / 'other-snapshot-out.json'
        spec.write_text(json.dumps(dict(root=str(f.git.other), inputs=[], exclusions=[])))
        self.assertEqual(f.helper('snapshot', spec, out)[0], 0)
        resume = lambda artifact: self.case('record-gate', artifact=artifact, evidence=[])
        self.expect([
            (resume(dict(snap, path='relative/snapshot.json')), 1, 'artifact path must be absolute'),
            (resume(dict(f.reference(linked / 'snapshot.json'), kind='snapshot')), 2, 'linked artifact path'),
            (resume(dict(snap, path=str(f.workspace / 'missing.json'))), 2, 'missing artifact: '),
            (resume(dict(f.save(dict(raw, valid=False)), kind='snapshot')), 2, 'invalid snapshot'),
            (resume(dict(f.save(incomplete), kind='package')), 2, 'incomplete package'),
            (resume(dict(f.reference(out), kind='snapshot')), 1, 'artifact worktree mismatch')])
        original = f.plan.read_text()
        plan = lambda old, new: dict(f.save(original.replace(old, new), '.md'), structure=None)
        self.expect([
            (self.case(state=dict(f.state, plan=plan('contracts: ["C1"]', 'contracts: ["C1", "C1"]'))), 1, 'invalid contract ids'),
            (self.case(state=dict(f.state, plan=plan('contracts: ["C1"]', 'contracts: ["C1", "1bad"]'))), 1, 'invalid contract id'),
            (self.case(state=dict(f.state, plan=plan('  - id: F1', '  - nophase: F1'))), 1, 'invalid phases'),
            (self.case(state=dict(f.state, plan=plan('consumes: []', 'consumes: {}'))), 1, 'contract references must be arrays'),
            (self.case(state=dict(f.state, plan=plan('produces: ["C1"]', 'produces: ["C9"]'))), 1, 'undeclared produced contract')])
        review = lambda coverage: self.report('review-primary', 'Google', artifact=package, coverage=dict(cov, **coverage))
        side = lambda **c: dict(contracts=[dict(dict(id='C1', producer=['tracked.txt'], consumer=['plan.md']), **c)])
        self.expect([
            (review(dict(files=['nope.txt'])), 1, 'unknown coverage file'),
            (review(dict(parts=['/nope.diff'])), 1, 'unknown coverage part'),
            (review(dict(contracts=[dict(id='C9')])), 1, 'unknown coverage contract'),
            (review(side(producer=['plan.md'])), 1, 'unknown contract side'),
            (review(dict(side(), files=['plan.md'])), 1, 'contract side lacks file review')])

    def test_gate_evidence_rejections(self):
        f = self.f
        passing = self.f.reference(Path(f.verified_run(code="print('ok')")[1]['run_dir']) / 'result.json')
        rc, failing = f.verified_run(code='raise SystemExit(4)'); self.assertEqual(rc, 4, failing)
        failing_ref = f.reference(Path(failing['run_dir']) / 'result.json')
        # A BASE baseline: the same failure on the detached base worktree.
        import sys; sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin/lib'))
        from verification import check
        path, spec = f.spec('raise SystemExit(4)', root=f.git.other)
        c = check(dict(command=spec['command'], timeout_seconds=spec['timeout_seconds'], cancel_grace_seconds=spec['cancel_grace_seconds']))
        for name in ('command', 'timeout_seconds', 'cancel_grace_seconds', 'no_progress_seconds', 'resource_key', 'progress_file'): spec[name] = c[name]
        spec['verification'] = dict(check=c, provenance=dict(kind='BASE', base_sha=f.git.base, preparation='git-worktree-add-detach', linked_dependencies=[]))
        path.write_text(json.dumps(spec)); f.start(path).finish()
        baseline = f.reference(Path(spec['run_dir']) / 'result.json')
        self.assertTrue(read_json(baseline['path'])['evidence']['valid'], read_json(baseline['path']))
        art = f.snapshot_ref()
        gate = lambda records: self.case('record-gate', artifact=art, evidence=records)
        self.expect([
            (gate([dict(failing_ref, baseline=baseline)]), 1, 'zero passing checks'),
            (gate([dict(failing_ref, baseline=passing), passing]), 1, 'unproven inherited failure'),
            (gate([dict(failing_ref, baseline=baseline), passing]), 0, '')])
        (f.git.root / 'tracked.txt').write_text('changed after the check\n')
        self.expect([(self.case('record-gate', artifact=f.snapshot_ref(), evidence=[passing]), 1, 'evidence snapshot mismatch')])

    def test_unstaged_new_source_cannot_be_committed(self):
        f = self.f; (f.git.root / 'new.txt').write_text('untracked source\n')
        files = f.git.git('diff', '--name-only', f.git.base).splitlines() + ['new.txt']
        self.assertEqual(f.validate(f.report_input('implementer'))[0], 0)
        art, cov = f.package_ref(families={'OpenAI': files})
        passing = [f.reference(Path(f.verified_run(code="print('ok')")[1]['run_dir']) / 'result.json')]
        self.assertEqual(f.validate(action='record-gate', artifact=art, evidence=passing)[0], 0)
        for role, family in (('review-primary', 'Google'), ('review-control', 'Anthropic')):
            self.assertEqual(f.validate(f.report_input(role, family, artifact=art, coverage=cov))[0], 0)
        sha = f.git_commit('feat: without the new file')
        self.expect([(self.case('confirm-commit', artifact=art, commit=dict(sha=sha, base=f.git.base), fleet=f.fleet()), 1,
                      'accepted source was not staged')])

    def test_cli_output_and_usage_rejections(self):
        f = self.f; data = self.case()
        proposal = f.save(data)['path']
        inside = f.workspace / 'inside'; inside.mkdir()
        linked = self.linked_dir(inside)
        def run(*args, code, reason):
            rc, out, err = command(f.argv('protocol-state', *args), f.git.root)
            rows = out.splitlines(); self.assertEqual(len(rows), 2, (rc, out, err))
            self.assertEqual((rc, rows[0]), (code, TOKENS[code]), out); self.assertIn(reason, json.loads(rows[1])['reason'])
        run('validate', proposal, f.base / 'outside.json', code=1, reason='resume output outside existing workspace')
        run('validate', proposal, linked / 'out.json', code=1, reason='linked resume output')
        run('validate', proposal, proposal, code=1, reason='resume must not replace an input artifact')
        run(code=1, reason='usage: protocol-state validate INPUT_JSON [RESUME_OUT]')
        run('summary', code=1, reason='usage: protocol-state summary')
        run('migrate', proposal, code=1, reason='usage: protocol-state migrate')
        run('claude-model-evidence', proposal, code=1, reason='usage: protocol-state claude-model-evidence')
        run('antigravity-model-evidence', proposal, code=1, reason='usage: protocol-state antigravity-model-evidence')
        run('migrate', proposal, f.workspace / 'migrated.json', code=2, reason='not a schema 1 state')

    def test_model_evidence_builder_rejections(self):
        f = self.f; task, d = 'builder-task', 'ctx_builder'
        home = f.workspace / 'claude-home'; (home / 'projects').mkdir(parents=True)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home))
        def run(kind, observation, out, code, reason, env=env):
            rc, text, err = command(f.argv('protocol-state', kind + '-model-evidence', observation['path'], out), f.git.root, env=env)
            rows = text.splitlines(); self.assertEqual(len(rows), 2, (rc, text, err))
            self.assertEqual(rc, code, text); self.assertIn(reason, json.loads(rows[1])['reason'])
        run('claude', f.claude_observation(d, task, model='claude-opus-5-5'), f.workspace / 'a.jsonl', 1, 'model evidence only for unreported Claude model')
        target = f.base / 'evidence-target'; target.mkdir()
        run('claude', f.claude_observation(d, task), self.linked_dir(target) / 'b.jsonl', 2, 'linked snapshot output')
        undated = read_json(f.claude_observation(d, task)['path']); undated['result']['dispatch'].pop('createdAt')
        run('claude', f.save(undated), f.workspace / 'c.jsonl', 2, 'missing Dispatch creation time')
        run('claude', f.claude_observation(d, task), f.workspace / 'd.jsonl', 2, 'no Claude transcript with this Dispatch preamble')
        agy = f.workspace / 'agy-home'; agy_env = dict(os.environ, ORCA_AGY_HOME=str(agy)); observed = f.agy_observation(d, task)
        (agy / 'brain').mkdir(parents=True); (agy / 'log').mkdir()
        run('antigravity', observed, f.workspace / 'e.jsonl', 2, 'no Antigravity transcript with this Dispatch preamble', agy_env)
        f.agy_home(agy, 'aaaa0000-0000-0000-0000-000000000001', task, d, models=())
        run('antigravity', observed, f.workspace / 'f.jsonl', 2, 'no resolved model in Antigravity log', agy_env)
        (agy / 'log' / 'cli-aaaa0000.log').unlink()
        run('antigravity', observed, f.workspace / 'g.jsonl', 2, 'expected exactly one Antigravity process log for conversation', agy_env)
        f.agy_home(agy, 'bbbb0000-0000-0000-0000-000000000002', task, d)
        run('antigravity', observed, f.workspace / 'h.jsonl', 2, 'several Antigravity conversations claim this Dispatch', agy_env)


if __name__ == '__main__': unittest.main()

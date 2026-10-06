"""Shared CLI fixtures for POSIX/native Windows; all writes are disposable.

Use ORCA_TEST_ARTIFACTS to retain isolated receipts. No Orca, real provider home,
installation, global configuration or live workspace is touched.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import unittest

from support import ProtocolFixture, ROOT, command, read_json


class AgyLogEncodingTests(unittest.TestCase):
    CONVERSATION = 'c0ffee00-1111-2222-3333-444455556666'
    MODEL = 'gemini-3.8-flash-high'
    DISPATCH = 'ctx_agyencoding'

    def setUp(self):
        self.f = ProtocolFixture()
        f = self.f
        self.proposed = f.assignment(family='Google')
        self.proposed['dispatch_id'] = None
        result = f.validate(dict(schema_version=1, action='dispatch', state=f.state,
                                 proposed=self.proposed, artifact=f.snapshot_ref(), fleet=f.fleet()))
        self.assertEqual(result[:2], (0, 'VALID'), result)
        self.pending = copy.deepcopy(f.state)
        self.task = self.proposed['task_id']
        self.observed = f.agy_observation(self.DISPATCH, self.task)

    def tearDown(self): self.f.close()

    def source(self, **kwargs):
        self.f.serial += 1
        home = self.f.workspace / ('agy-encoding-' + str(self.f.serial))
        transcript, log = self.f.agy_home(home, self.CONVERSATION, self.task, self.DISPATCH, **kwargs)
        return home, transcript, log

    def proof(self, transcript, log):
        return dict(self.f.reference(transcript), kind='antigravity-log',
                    conversation_id=self.CONVERSATION, log=self.f.reference(log))

    def bind(self, proof, observed=None):
        return self.f.validate(dict(schema_version=1, action='bind-dispatch', state=copy.deepcopy(self.pending),
                                    observation=dict(observed or self.observed, model_evidence=proof)))

    def build(self, home, observation=None):
        self.f.serial += 1
        out = self.f.workspace / ('frozen-' + str(self.f.serial) + '.jsonl')
        rc, text, err = command(self.f.argv('protocol-state', 'antigravity-model-evidence',
                                         (observation or self.observed)['path'], out), self.f.git.root,
                                env=dict(os.environ, ORCA_AGY_HOME=str(home)))
        rows = text.splitlines()
        self.assertEqual(len(rows), 2, (rc, text, err))
        if rc:
            self.assertFalse(out.exists())
            self.assertFalse(Path(str(out) + '.cli.log').exists())
        return rc, rows[0], json.loads(rows[1])

    def assert_result(self, result, code, reason=''):
        self.assertEqual(result[:2], (code, ('VALID', 'INVALID', 'UNVERIFIABLE')[code]), result)
        if code and reason: self.assertIn(reason, result[2]['reason'])
        if not code and 'state' in result[2]:
            active = result[2]['state']['active']
            self.assertEqual((active['task_id'], active['dispatch_id'], active['model']),
                             (self.task, self.DISPATCH, self.MODEL))

    def test_shared_log_cases_builder_and_validator(self):
        for spec in read_json(ROOT / 'tests/fixtures/agy-log-encoding.json'):
            with self.subTest(spec['name']):
                home, transcript, log = self.source()
                raw = spec['log'].replace('{MODEL}', self.MODEL).replace('{CONVERSATION}', self.CONVERSATION).encode()
                raw = raw.replace(b'{BAD}', b'\xd0X').replace(b'{INVALID}', b'\x80').replace(b'{TRUNCATED}', b'\xd0')
                raw = raw.replace(b'{LONG_NOISE}', b'ordinary-noise-\x80' * 30000)
                log.write_bytes(raw)
                before = {p: p.read_bytes() for p in (transcript, log, Path(self.observed['path']))}
                proof = self.proof(transcript, log)
                self.assert_result(self.bind(proof), spec['code'], spec['reason'])
                built = self.build(home)
                # The builder reports raw facts, so a clean differing model is
                # valid there; binding to the assigned model must still refuse.
                builder_code = 0 if spec['name'] == 'wrong-model-amid-noise' else spec['code']
                self.assert_result(built, builder_code)
                if builder_code == 0:
                    frozen = built[2]['model_evidence']
                    self.assertEqual(Path(frozen['path']).read_bytes(), before[transcript])
                    self.assertEqual(Path(frozen['log']['path']).read_bytes(), raw)
                    self.assertEqual(frozen['log']['sha256'], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(frozen['sha256'], hashlib.sha256(before[transcript]).hexdigest())
                    self.assert_result(self.bind(frozen), spec['code'], spec['reason'])
                self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_wrong_or_missing_preamble(self):
        for name, replacement in [('task', self.task + '-wrong'), ('dispatch', 'ctx_wrong'),
                                  ('sender', 'term_wrong'), ('missing', '')]:
            with self.subTest(name):
                home, transcript, log = self.source()
                rows = [json.loads(line) for line in transcript.read_text().splitlines()]
                if name == 'missing': rows[0]['content'] = ''
                else:
                    old = {'task': self.task, 'dispatch': self.DISPATCH, 'sender': self.f.CLAUDE_HANDLE}[name]
                    rows[0]['content'] = rows[0]['content'].replace(old, replacement)
                transcript.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
                self.assert_result(self.bind(self.proof(transcript, log)), 2, 'no Orca preamble')
                self.assert_result(self.build(home), 2, 'no Antigravity transcript')

    def test_strict_transcript_observation_and_generic_reference(self):
        home, transcript, log = self.source()
        proof = self.proof(transcript, log)
        # Inside a JSON string: replacing the bad byte would leave valid JSON.
        transcript.write_bytes(transcript.read_bytes().replace(b'"ok"', b'"noise-\x80"'))
        self.assert_result(self.bind(self.proof(transcript, log)), 2)
        self.assert_result(self.build(home), 2)
        observation = Path(self.observed['path'])
        observation.write_bytes(observation.read_bytes().replace(b'antigravity', b'antigravity\x80'))
        malformed = self.f.reference(observation)
        self.assert_result(self.bind(proof, malformed), 2)
        self.assert_result(self.build(home, malformed), 2)
        # The same malformed console log remains invalid as a generic JSON ref.
        log.write_bytes(b'{"noise":"\x80"}\n')
        self.assert_result(self.bind(proof, self.f.reference(log)), 2)

    def test_log_reference_hash_paths_and_links(self):
        _, transcript, log = self.source()
        good = self.proof(transcript, log)
        drift = copy.deepcopy(good); drift['log']['sha256'] = '0' * 64
        self.assert_result(self.bind(drift), 1, 'artifact hash mismatch')
        log.write_bytes(log.read_bytes() + b'console noise \x80\n')
        self.assert_result(self.bind(good), 1, 'artifact hash mismatch')
        good = self.proof(transcript, log)
        relative = copy.deepcopy(good); relative['log']['path'] = 'relative.cli.log'
        self.assert_result(self.bind(relative), 1, 'artifact path must be absolute')
        missing = copy.deepcopy(good); missing['log']['path'] += '.missing'
        self.assert_result(self.bind(missing), 2, 'missing artifact')
        for ancestor in (False, True):
            with self.subTest(ancestor=ancestor):
                link = self.f.workspace / ('linked-dir' if ancestor else 'linked-log')
                try: link.symlink_to(log.parent if ancestor else log, target_is_directory=ancestor)
                except OSError as error:
                    if os.name == 'nt': self.skipTest('symlink creation unavailable: ' + str(error))
                    raise
                linked = copy.deepcopy(good)
                linked['log']['path'] = str(link / log.name if ancestor else link)
                self.assert_result(self.bind(linked), 2, 'linked artifact path')


if __name__ == '__main__': unittest.main()

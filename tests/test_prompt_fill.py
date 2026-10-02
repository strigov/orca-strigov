"""prompt-fill assembles a worker spec from a bundled template without the template transiting the coordinator."""
import hashlib
import json
from pathlib import Path
import re
import unittest

from support import ROOT, RunnerFixture, command, selected_shell, write_json

BOUNDARY = "You are a dispatched worker. Do the assigned work yourself."


class PromptFillTests(unittest.TestCase):
    def setUp(self): self.fx = RunnerFixture(selected_shell())
    def tearDown(self): self.fx.close()

    def run_tool(self, *args):
        rc, out, err = command(self.fx.argv('prompt-fill', *args), self.fx.git.root)
        rows = out.splitlines()
        self.assertEqual(len(rows), 2, (rc, out, err))
        return rc, rows[0], json.loads(rows[1])

    def request(self, **changed):
        base = dict(schema_version=1, template='implementer-prompt.md', block='First-round',
                    fields={'REPORT_FILE': '/abs/ws/phase-F1-r1-a1.md', 'RUNTIME_CONTRACTS_PATH': '/abs/plugin/runtime-contracts.md',
                            'FROZEN_ASSIGNMENT': '{"role":"implementer","phase":"F1","round":1}'},
                    replacements={'<repo-root>': '/abs/repo'}, output=str(self.fx.base / 'spec.md'))
        base.update(changed)
        path = self.fx.base / ('request-%d.json' % id(base)); write_json(path, base); return str(path)

    def test_list_names_blocks_and_placeholders_of_every_template(self):
        for template in sorted(p.name for p in (ROOT / 'skills/orca-dev/prompts').glob('*.md')):
            rc, token, result = self.run_tool('list', template)
            self.assertEqual((rc, token), (0, 'VALID'), result)
            self.assertTrue(result['blocks'], template)
            for block in result['blocks']:
                self.assertEqual(block['placeholders'], sorted(block['placeholders']))
                for p in block['placeholders']: self.assertRegex(p, r'^\[[A-Z][A-Z0-9_]*\]$')
        rc, token, result = self.run_tool('list', 'implementer-prompt.md')
        self.assertEqual(result['blocks'][0]['heading'], 'First-round prompt template')
        self.assertIn('[REPORT_FILE]', result['blocks'][0]['placeholders'])
        rc, token, result = self.run_tool('list', '../roles.md')
        self.assertEqual((rc, token), (2, 'UNVERIFIABLE'), result)

    def test_fill_prepends_boundary_fills_fields_and_reports_worker_tokens(self):
        rc, token, result = self.run_tool('fill', self.request())
        self.assertEqual((rc, token), (0, 'VALID'), result)
        data = Path(result['path']).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), result['sha256']); self.assertEqual(len(data), result['bytes'])
        text = data.decode('utf-8')
        self.assertTrue(text.startswith(BOUNDARY), text[:80])
        self.assertIn('\n\nYou are implementing one phase of an approved plan.', text)
        self.assertNotIn('[REPORT_FILE]', text); self.assertIn('/abs/ws/phase-F1-r1-a1.md', text)
        self.assertNotIn('<repo-root>', text); self.assertIn('/abs/repo/docs/plans/<slug>.md', text)
        self.assertNotRegex(text, r'\[[A-Z][A-Z0-9_]*\]')
        self.assertIn('<slug>', result['worker_tokens']); self.assertIn('<copy the --from value from the Orca preamble>', result['worker_tokens'])
        rc, token, result = self.run_tool('fill', self.request())
        self.assertEqual((rc, token), (1, 'INVALID'), result); self.assertIn('new absolute file', result['reason'])

    def test_fill_rejects_missing_unknown_fields_and_bad_selectors(self):
        fields = dict(REPORT_FILE='/abs/r.md', RUNTIME_CONTRACTS_PATH='/abs/c.md', FROZEN_ASSIGNMENT='{}')
        cases = [(dict(fields={k: v for k, v in fields.items() if k != 'REPORT_FILE'}), 1, 'unfilled placeholders: [REPORT_FILE]'),
                 (dict(fields=dict(fields, EXTRA='x')), 1, 'fields not used by the template: EXTRA'),
                 (dict(fields=dict(fields, lower='x')), 1, 'UPPER_SNAKE'),
                 (dict(block=1), 1, 'unfilled placeholders: [FIX_FINDING_REFERENCES], [PREVIOUS_REPORT_FILE]'),
                 (dict(block='Fix-round'), 1, 'matches 2 blocks'),
                 (dict(block='Nope'), 1, 'matches 0 blocks'),
                 (dict(block=9), 1, 'out of range'),
                 (dict(replacements={'<nowhere>': 'x'}), 1, 'replacement text not in template'),
                 (dict(template='../roles.md'), 1, 'unknown template'),
                 (dict(output='relative.md'), 1, 'new absolute file'),
                 (dict(schema_version=2), 1, 'unsupported request schema')]
        for changed, code, reason in cases:
            with self.subTest(changed=changed):
                rc, token, result = self.run_tool('fill', self.request(**dict({'output': str(self.fx.base / ('out-%d.md' % id(changed)))}, **changed)))
                self.assertEqual(rc, code, result); self.assertIn(reason, result['reason'])
        self.assertFalse(list(self.fx.base.glob('out-*.md')))

    def test_outcome_body_appends_filled_shared_contract(self):
        contract = (ROOT / 'skills/orca-dev/prompts/outcome-worker-contract.md').read_text(encoding='utf-8')
        names = sorted(set(re.findall(r'\[([A-Z][A-Z0-9_]*)\]', contract)) |
                       set(re.findall(r'\[([A-Z][A-Z0-9_]*)\]', (ROOT / 'skills/orca-dev/prompts/outcome-implementer.md').read_text(encoding='utf-8'))))
        fields = {n: 'value of ' + n for n in names}
        rc, token, result = self.run_tool('fill', self.request(template='outcome-implementer.md', block=None, fields=fields, replacements={},
                                                               outcome_contract=True, prepend='Re-brief: the previous worker is gone.', append='Budget: 2 checks.'))
        self.assertEqual((rc, token), (0, 'VALID'), result)
        text = Path(result['path']).read_text(encoding='utf-8')
        self.assertTrue(text.startswith(BOUNDARY))
        self.assertLess(text.index('Re-brief: the previous worker is gone.'), text.index('Deliver the assigned phase'))
        self.assertLess(text.index('Deliver the assigned phase'), text.index('## Assignment and environment'))
        self.assertTrue(text.rstrip().endswith('Budget: 2 checks.'))
        self.assertIn('value of REPORT_FILE', text); self.assertNotIn('# Shared worker contract', text)
        self.assertNotRegex(text, r'\[[A-Z][A-Z0-9_]*\]')


if __name__ == '__main__': unittest.main()

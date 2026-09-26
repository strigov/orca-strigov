"""sdd-workspace keeps the transient plan ledger out of C4 snapshots and C5 packages."""
from pathlib import Path
import unittest

from support import VerificationFixture, command


class SddWorkspaceTests(unittest.TestCase):
    def setUp(self): self.fx = VerificationFixture()
    def tearDown(self): self.fx.close()

    def workspace(self, plan, root=None):
        root = root or self.fx.git.root
        rc, out, err = command(self.fx.argv('sdd-workspace', plan), root)
        self.assertEqual(rc, 0, (out, err))
        return Path(out.strip())

    def ignored(self, root, path):
        return command(['git', '-C', str(root), 'check-ignore', '-q', '--', path], root)[0] == 0

    def exclude(self):
        return (self.fx.git.root / '.git/info/exclude').read_text(encoding='utf-8').splitlines()

    def test_plan_ledger_is_ignored_once_and_left_out_of_snapshots(self):
        f = self.fx; root = f.git.root; plans = root / 'docs/plans'; plans.mkdir(parents=True)
        (plans / 'demo.md').write_text('---\nstatus: implementing\n---\n', encoding='utf-8')
        ledger = plans / 'demo.ledger.json'; ledger.write_text('[]\n', encoding='utf-8')
        (plans / 'other.ledger.json').write_text('[]\n', encoding='utf-8')
        path = self.workspace(plans / 'demo.md')
        self.assertEqual(path.name, 'demo'); self.assertEqual(path.parent.name, 'sdd')
        self.workspace(plans / 'demo.md')
        self.assertEqual(self.exclude().count('/docs/plans/demo.ledger.json'), 1)
        self.assertTrue(self.ignored(root, 'docs/plans/demo.ledger.json'))
        self.assertFalse(self.ignored(root, 'docs/plans/other.ledger.json'))
        files = f.snapshot()['manifest']['files']
        self.assertNotIn('repo:docs/plans/demo.ledger.json', files)
        self.assertIn('repo:docs/plans/other.ledger.json', files)
        self.assertEqual(ledger.read_text(encoding='utf-8'), '[]\n')

    def test_special_characters_are_escaped_and_worktrees_share_the_exclude(self):
        f = self.fx; other = f.git.other; plans = other / 'docs/pl ans'; plans.mkdir(parents=True)
        (plans / 'odd[1]*.md').write_text('plan\n', encoding='utf-8')
        (plans / 'odd[1]*.ledger.json').write_text('[]\n', encoding='utf-8')
        (plans / 'odd1x.ledger.json').write_text('[]\n', encoding='utf-8')
        self.workspace(plans / 'odd[1]*.md', root=other)
        self.assertIn('/docs/pl ans/odd\\[1\\]\\*.ledger.json', self.exclude())
        self.assertTrue(self.ignored(other, 'docs/pl ans/odd[1]*.ledger.json'))
        self.assertFalse(self.ignored(other, 'docs/pl ans/odd1x.ledger.json'))


if __name__ == '__main__': unittest.main()

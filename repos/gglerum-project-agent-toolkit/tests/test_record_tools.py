import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
DECISIONS = TOOLS / 'decision-records' / 'decisions.py'
FINDINGS = TOOLS / 'finding-records' / 'findings.py'
REGISTER = TOOLS / 'design-register' / 'register.py'


def run(script, cwd, *args, env=None):
    return subprocess.run([sys.executable, '-B', '-I', str(script), *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


class DecisionRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'decisions.config.json').write_text(json.dumps({'history_files': ['docs/log.md']}))
        (self.root / 'text.md').write_text('Use optimistic locking.\n')
        (self.root / 'docs').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def d(self, *args, env=None):
        return run(DECISIONS, self.root, '--config', 'decisions.config.json', *args, env=env)

    def add(self, title='Locking', status='decided', extra=()):
        return self.d('add', '--title', title, '--status', status, '--text-file', 'text.md',
                      '--on', '2026-01-15', '--by', 'team', '--sources', 'https://example.test/t', *extra)

    def test_add_index_check_cycle(self):
        self.assertEqual(0, self.add().returncode)
        self.assertTrue((self.root / 'docs/decisions/DEC-001.md').exists())
        stale = self.d('check')
        self.assertEqual(1, stale.returncode)
        self.assertIn('not up to date', stale.stderr)
        self.assertEqual(0, self.d('index').returncode)
        self.assertEqual(0, self.d('check').returncode)
        self.assertIn('1 decisions: 1 decided', (self.root / 'docs/decisions.md').read_text())

    def test_ids_are_never_reused_and_supersede_archives(self):
        self.add('First')
        self.add('Second')
        result = self.d('supersede', 'DEC-001', 'DEC-002')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse((self.root / 'docs/decisions/DEC-001.md').exists())
        self.assertTrue((self.root / 'docs/decisions/archive/DEC-001.md').exists())
        self.assertIn('IS SUPERSEDED', self.d('show', 'DEC-001').stdout)
        self.assertNotIn('DEC-001', self.d('list').stdout)
        self.assertIn('DEC-001', self.d('list', '--all').stdout)
        self.add('Third')
        self.assertTrue((self.root / 'docs/decisions/DEC-003.md').exists())
        self.d('index')
        self.assertEqual(0, self.d('check').returncode)

    def test_reference_to_unknown_or_superseded_decision_fails(self):
        self.add('First')
        self.add('Second')
        self.d('supersede', 'DEC-001', 'DEC-002')
        self.d('index')
        (self.root / 'docs/guide.md').write_text('See DEC-009 and DEC-001.\n')
        (self.root / 'docs/log.md').write_text('Earlier DEC-001 was used.\n')
        result = self.d('check')
        self.assertEqual(1, result.returncode)
        self.assertIn('DEC-009 is referenced in docs/guide.md but has no record', result.stderr)
        self.assertIn('DEC-001 is superseded by DEC-002 but still referenced in docs/guide.md', result.stderr)
        self.assertNotIn('docs/log.md', result.stderr)

    def test_decided_record_needs_date_author_and_origin(self):
        (self.root / 'docs/decisions').mkdir(parents=True)
        result = self.d('add', '--title', 'Bare', '--status', 'decided', '--text-file', 'text.md')
        self.assertEqual(0, result.returncode)
        self.d('index')
        checked = self.d('check')
        self.assertEqual(1, checked.returncode)
        self.assertIn('needs decided_on and decided_by', checked.stderr)

    def test_for_lists_current_decisions_of_an_issue(self):
        self.add(extra=('--issue', '42', '--related', 'F10'))
        self.assertIn('DEC-001', self.d('for', '42').stdout)
        self.assertIn('DEC-001', self.d('for', 'F10').stdout)
        self.assertIn('none', self.d('for', '7').stdout)

    def test_mirror_needs_tracker_and_writes_section_with_links(self):
        self.add(extra=('--issue', '42'))
        self.assertIn('tracker_repo', self.d('mirror', 'DEC-001').stderr)
        (self.root / 'decisions.config.json').write_text(json.dumps({'tracker_repo': 'owner/repo'}))
        fake = self.root / 'fakegh.py'
        fake.write_text(
            'import sys\nargs = sys.argv[1:]\n'
            'if args[:2] == ["issue", "view"]:\n    print("Body text")\n'
            'elif args[:2] == ["issue", "edit"]:\n    open("edited.txt", "w").write(sys.stdin.read())\n')
        env = {'DECISIONS_GH': f'{sys.executable} fakegh.py'}
        result = self.d('mirror', 'DEC-001', env=env)
        self.assertEqual(0, result.returncode, result.stderr)
        edited = (self.root / 'edited.txt').read_text()
        self.assertIn('## Decisions\n<!-- decisions -->', edited)
        self.assertIn('https://github.com/owner/repo/blob/main/docs/decisions/DEC-001.md', edited)
        self.assertNotIn('optimistic', edited)
        self.assertIn('"https://github.com/owner/repo/issues/42"', (self.root / 'docs/decisions/DEC-001.md').read_text())


class FindingRecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'findings.config.json').write_text('{}')
        groups = self.root / 'docs/findings/_groups'
        groups.mkdir(parents=True)
        (groups / '01-security.md').write_text(
            '---\ntitle: "Security"\n---\n## Security\n\n| ID | Severity | Finding | Found by | Status |\n| --- | --- | --- | --- | --- |\n<!-- findings-table -->\n')
        (self.root / 'text.txt').write_text('Tokens are logged.\n')

    def tearDown(self):
        self.tmp.cleanup()

    def f(self, *args):
        return run(FINDINGS, self.root, '--config', 'findings.config.json', *args)

    def test_add_status_index_check(self):
        added = self.f('add', 'S1', '--group', 'Security', '--severity', 'Blocker', '--found-by', 'review', '--text-file', 'text.txt')
        self.assertEqual(0, added.returncode, added.stderr)
        self.f('index')
        self.assertEqual(0, self.f('check').returncode)
        overview = (self.root / 'docs/findings.md').read_text()
        self.assertIn('| S1 | **Blocker** | Tokens are logged. | review | Open |', overview)
        self.assertIn('1 findings: 0 fixed', overview)
        self.f('status', 'S1', 'fixed', 'in 1.4')
        self.assertEqual(1, self.f('check').returncode)
        self.f('index')
        self.assertIn('Fixed: in 1.4', (self.root / 'docs/findings.md').read_text())
        self.assertEqual('1 fixed' in self.f('counts').stdout, True)

    def test_rejects_unknown_group_severity_and_multiline_text(self):
        base = ('add', 'S2', '--found-by', 'x', '--text-file', 'text.txt')
        self.assertIn('unknown group', self.f(*base, '--group', 'Nope', '--severity', 'Low').stderr)
        self.assertIn('severity must be', self.f(*base, '--group', 'Security', '--severity', 'Huge').stderr)
        (self.root / 'text.txt').write_text('one\ntwo\n')
        self.assertIn('one line', self.f(*base, '--group', 'Security', '--severity', 'Low').stderr)

    def test_feedback_item_roundtrip(self):
        fb = self.root / 'docs/feedback'
        fb.mkdir(parents=True)
        (fb / 'FB-001.md').write_text(
            '---\nid: "FB-001"\narea: "Login"\nsummary: "Button hidden"\npriority: "High"\nstatus: "new"\nrelated: "S1"\n---\n### FB-001 Button hidden\n\nDetails.\n')
        self.f('index')
        self.assertEqual(0, self.f('check').returncode)
        self.f('fb', 'status', 'FB-001', 'triaged')
        self.assertIn('triaged', self.f('fb', 'show', 'FB-001').stdout)
        (fb / 'FB-002.md').write_text(
            '---\nid: "FB-002"\narea: "x"\nsummary: "y"\npriority: "Low"\nstatus: "new"\nrelated: ""\n---\nno heading\n')
        self.assertIn("must start with '### FB-002 title'", self.f('check').stderr)


class DesignRegisterTest(unittest.TestCase):
    PAGE = ('<html><head><title>Checkout</title></head><body>'
            '<figure id="f1"><figcaption><b>1. Cart</b></figcaption><p>Your cart is empty</p></figure>'
            '<figure><figcaption>2. Done</figcaption><p>Order confirmed</p></figure></body></html>')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'register.config.json').write_text(json.dumps({'decisions_dir': 'docs/decisions', 'visible_code_pattern': r'\bDEC-\d+\b'}))
        (self.root / 'design/prototypes').mkdir(parents=True)
        (self.root / 'docs/decisions').mkdir(parents=True)
        (self.root / 'docs/decisions/DEC-001.md').write_text('x')
        (self.root / 'design/prototypes/checkout.html').write_text(self.PAGE)

    def tearDown(self):
        self.tmp.cleanup()

    def r(self, *args):
        return run(REGISTER, self.root, '--config', 'register.config.json', *args)

    def record(self):
        return json.loads((self.root / 'design/register/checkout.json').read_text())

    def test_add_writes_ids_and_records_frames(self):
        self.assertEqual(0, self.r('add', 'checkout', '--write-ids').returncode)
        self.assertIn('<figure id="f2">', (self.root / 'design/prototypes/checkout.html').read_text())
        self.assertEqual(['f1', 'f2'], [f['id'] for f in self.record()['frames']])

    def test_check_requires_issue_then_passes_after_index(self):
        self.r('add', 'checkout', '--write-ids')
        self.r('index')
        failed = self.r('check')
        self.assertEqual(1, failed.returncode)
        self.assertIn('must name the issue', failed.stderr)
        rec = self.record()
        rec['issues'] = [42]
        rec['decisions'] = ['DEC-001']
        (self.root / 'design/register/checkout.json').write_text(json.dumps(rec))
        self.r('index')
        self.assertEqual(0, self.r('check').returncode, self.r('check').stderr)

    def test_unknown_decision_and_unreplaced_frame_fail(self):
        self.r('add', 'checkout', '--write-ids')
        rec = self.record()
        rec['issues'] = [1]
        rec['decisions'] = ['DEC-404']
        rec['frames'][0]['status'] = 'superseded'
        (self.root / 'design/register/checkout.json').write_text(json.dumps(rec))
        self.r('index')
        err = self.r('check').stderr
        self.assertIn('unknown decision DEC-404', err)
        self.assertIn('a superseded frame must name replaced_by', err)
        rec['frames'][0]['replaced_by'] = ['checkout#f9']
        (self.root / 'design/register/checkout.json').write_text(json.dumps(rec))
        self.assertIn('replaced_by checkout#f9 does not exist', self.r('check').stderr)

    def test_find_reports_frame_or_not_found_with_what_was_searched(self):
        self.r('add', 'checkout', '--write-ids')
        found = self.r('find', 'order confirmed')
        self.assertIn('checkout#f2', found.stdout)
        missing = self.r('find', 'refund')
        self.assertIn('NOT FOUND', missing.stdout)
        self.assertIn('Searched: register', missing.stdout)

    def test_visible_codes_fail_but_comments_do_not(self):
        self.r('add', 'checkout', '--write-ids')
        (self.root / 'design/prototypes/checkout.html').write_text(self.PAGE.replace('Order confirmed', 'Order confirmed DEC-001') + '<!-- DEC-001 -->')
        err = self.r('check').stderr
        self.assertEqual(1, err.count("code 'DEC-001'"))

    def test_for_lists_artifact_by_issue(self):
        self.r('add', 'checkout', '--write-ids')
        rec = self.record()
        rec['frames'][1]['issues'] = [77]
        (self.root / 'design/register/checkout.json').write_text(json.dumps(rec))
        self.assertIn('checkout#f2', self.r('for', '77').stdout)
        self.assertIn('none registered', self.r('for', '5').stdout)


if __name__ == '__main__':
    unittest.main()

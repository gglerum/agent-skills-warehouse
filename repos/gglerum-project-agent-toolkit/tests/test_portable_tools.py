"""Regression checks with synthetic input and disposable consumer checkouts."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(tool, file):
    path = ROOT / 'tools' / tool / file
    spec = importlib.util.spec_from_file_location('fixture_' + tool.replace('-', '_') + '_' + path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, name, data):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
        return p

    def cli(self, tool, script, *args):
        return subprocess.run([sys.executable, '-B', '-I', str(ROOT / 'tools' / tool / script), *map(str, args)],
                              cwd=self.root, capture_output=True, text=True, timeout=20)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True)


class Converters(Scratch):
    CASES = [
        ('composer_audit_to_sarif.py', [], {'advisories': {}, 'abandoned': {}}),
        ('security_to_sarif.py', ['gitleaks'], []),
        ('security_to_sarif.py', ['trivy'], {'Results': []}),
        ('convert_reports.py', ['rector'], {'file_diffs': []}),
        ('convert_reports.py', ['deptrac'], {'files': {}}),
        ('convert_reports.py', ['infection'], []),
        ('convert_reports.py', ['cspell'], {'issues': []}),
        ('convert_reports.py', ['zap'], {'site': []}),
        ('convert_reports.py', ['composer-audit'], {'advisories': {}}),
        ('eslint_json_to_sarif.py', [], []),
    ]

    def test_every_converter_rejects_missing_malformed_and_wrong_shape_without_output_change(self):
        for script, prefix, valid in self.CASES:
            for payload in (None, '{broken', 'null', '"wrong"', '{}'):
                if payload == '{}' and valid == {}:
                    continue
                with self.subTest(script=script, prefix=prefix, payload=payload):
                    source = self.root / 'input.json'
                    source.unlink(missing_ok=True)
                    if payload is not None:
                        source.write_text(payload)
                    output = self.put('out.json', 'prior valid output')
                    result = self.cli('report-converters', script, *prefix, source, output)
                    self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual('prior valid output', output.read_text())

    def test_every_converter_accepts_valid_empty_report(self):
        for script, prefix, payload in self.CASES:
            with self.subTest(script=script, prefix=prefix):
                source = self.put('input.json', json.dumps(payload))
                out = self.root / 'out.json'
                result = self.cli('report-converters', script, *prefix, source, out)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIsInstance(json.loads(out.read_text()), dict)

    def test_composer_findings_are_not_lost(self):
        source = self.put('in.json', json.dumps({'advisories': {'pkg/name': [{'advisoryId': 'ID-1', 'title': 'test', 'cve': 'CVE-EXAMPLE', 'affectedVersions': '<2', 'link': 'https://example.test/advisory'}]}}))
        out = self.root / 'out.json'
        self.assertEqual(0, self.cli('report-converters', 'composer_audit_to_sarif.py', source, out).returncode)
        self.assertEqual('ID-1', json.loads(out.read_text())['runs'][0]['results'][0]['ruleId'])

    def test_pint_xml_requires_actual_checkstyle(self):
        out = self.put('out.json', 'keep')
        for xml in ('<broken', '<coverage/>'):
            source = self.put('report.xml', xml)
            self.assertNotEqual(0, self.cli('report-converters', 'convert_reports.py', 'pint', source, out).returncode)
            self.assertEqual('keep', out.read_text())
        source = self.put('report.xml', '<checkstyle><file name="src/a.php"><error line="1" message="fix" severity="error" source="rule"/></file></checkstyle>')
        self.assertEqual(0, self.cli('report-converters', 'convert_reports.py', 'pint', source, out).returncode)
        self.assertEqual(1, len(json.loads(out.read_text())['issues']))

    def test_merge_never_skips_requested_input(self):
        valid = self.put('one.json', json.dumps({'version': '2.1.0', 'runs': [{'tool': {'driver': {'name': 'fixture'}}, 'results': []}]}))
        out = self.put('out.json', 'keep')
        self.assertEqual(2, self.cli('report-converters', 'merge_sarif.py', out, valid, 'absent').returncode)
        self.assertEqual('keep', out.read_text())
        self.assertEqual(0, self.cli('report-converters', 'merge_sarif.py', out, valid).returncode)
        self.assertEqual(1, len(json.loads(out.read_text())['runs']))


class EditingNavigation(Scratch):
    def test_staged_checks_never_run_fixer_on_partial_file(self):
        self.git('init', '-q')
        source = self.put('example.py', 'staged\n')
        self.git('add', 'example.py')
        source.write_text('unstaged\n')
        marker = self.root / 'ran'
        config = self.put('checks.json', json.dumps({'steps': [{'args': [sys.executable, '-c', 'from pathlib import Path;Path("ran").touch()'], 'globs': ['*.py']}]}))
        result = self.cli('git-checks', 'checks.py', '--root', self.root, '--config', config)
        self.assertEqual(2, result.returncode)
        self.assertFalse(marker.exists())
        self.assertEqual('unstaged\n', source.read_text())

    def test_deletion_still_selects_configured_check(self):
        m = load('git-checks', 'select_changes.py')
        self.assertEqual({'TEST_PY': True, 'TEST_JS': False}, m.select([('D', 'src/old.py')], {'TEST_PY': ['*.py'], 'TEST_JS': ['*.js']}))
        with self.assertRaises(ValueError):
            m.select([], {})

    def test_patch_prevalidation_and_mode_preservation(self):
        a, b = self.put('a', 'one'), self.put('b', 'two')
        a.chmod(0o751)
        edits = self.put('edits.json', json.dumps([{'file': str(a), 'old': 'one', 'new': 'ONE'}, {'file': str(b), 'old': 'missing', 'new': 'TWO'}]))
        self.assertEqual(1, self.cli('exact-patch', 'patch.py', edits).returncode)
        self.assertEqual('one', a.read_text())
        edits.write_text(json.dumps([{'file': str(a), 'old': 'one', 'new': 'ONE'}]))
        self.assertEqual(0, self.cli('exact-patch', 'patch.py', edits).returncode)
        self.assertEqual('ONE', a.read_text())
        self.assertEqual(0o751, a.stat().st_mode & 0o777)

    def test_markdown_fences_and_ambiguous_headings(self):
        source = self.put('doc.md', '# Top\n## Desired\nkeep\n```\n## Fake\n```\n## Other\nnot selected\n')
        r = self.cli('code-navigation', 'sect.py', source, 'Desired')
        self.assertEqual(0, r.returncode)
        self.assertIn('keep', r.stdout)
        self.assertNotIn('not selected', r.stdout)
        source.write_text('# Top\n## Same one\na\n## Same two\nb\n')
        self.assertEqual(2, self.cli('code-navigation', 'sect.py', source, 'Same').returncode)

    def test_relocated_code_map_and_symbol_reader(self):
        target = self.root / 'copied'
        shutil.copytree(ROOT / 'tools/code-navigation', target)
        source = self.put('src/example.py', 'def first():\n    return 42\n\ndef second():\n    return 0\n')
        for args in (['src', '--root', str(self.root), '--output', str(self.root / 'MAP.md')],):
            r = subprocess.run([sys.executable, '-I', str(target / 'code_map.py'), *args], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(0, r.returncode, r.stderr)
        r = subprocess.run([sys.executable, '-I', str(target / 'sect.py'), str(source), 'first'], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn('return 42', r.stdout)


class ProjectState(Scratch):
    def state(self):
        return {'gates': [{'id': 'a', 'class': 'AUTO', 'status': 'active'},
                          {'id': 'b', 'class': 'HUMAN', 'status': 'queued', 'depends_on': ['a']}]}

    def test_missing_evidence_prerequisites_cycles_and_human_approval(self):
        m = load('project-state', 'state.py')
        state = self.state()
        state['gates'][1]['status'] = 'passed'
        self.put('proof', 'fixture')
        state['gates'][1]['evidence'] = ['proof']
        with self.assertRaises(ValueError):
            m.validate(state, self.root)
        state['gates'][0].update(status='passed', evidence=['proof'])
        with self.assertRaises(ValueError):
            m.validate(state, self.root)
        state['gates'][1]['approval'] = {'by': 'owner', 'gate': 'b', 'record': 'explicit approval in session'}
        self.assertEqual(2, len(m.validate(state, self.root)))
        state['gates'][0]['depends_on'] = ['b']
        with self.assertRaises(ValueError):
            m.validate(state, self.root)

    def test_record_preview_does_not_write(self):
        p = self.put('PROJECT_STATE.json', json.dumps(self.state()))
        self.put('proof', 'evidence')
        original = p.read_bytes()
        r = self.cli('project-state', 'state.py', '--root', self.root, 'record', 'a', '--evidence', 'proof')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(original, p.read_bytes())

    def test_evidence_cannot_escape_root(self):
        m = load('project-state', 'state.py')
        state = self.state()
        state['gates'][0].update(status='passed', evidence=['../outside'])
        with self.assertRaises(ValueError):
            m.validate(state, self.root)


class EvidenceAndChecks(Scratch):
    def test_origin_drift_is_scoped_and_content_sensitive(self):
        import hashlib
        m = load('origin-drift', 'check.py')
        source = self.put('source.py', 'original')
        record = {'origins': [{'project': 'fixture', 'path': 'source.py', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]}
        self.assertEqual(([], []), m.compare(record, {'fixture': self.root}))
        source.write_text('changed')
        self.assertEqual(['fixture/source.py'], m.compare(record, {'fixture': self.root})[0])
        self.assertTrue(m.compare(record, {})[1])

    def test_clover_configured_language_and_invalid_threshold(self):
        report = self.put('clover.xml', '<coverage><project><file name="/container/src/a.py"><metrics coveredstatements="9" statements="10"/></file></project></coverage>')
        r = self.cli('test-reports', 'coverage_for_files.py', report, 'src/a.py', '--required-suffix=.py', '--report-prefix=/container', '--min=90')
        self.assertEqual(0, r.returncode, r.stderr)
        r = self.cli('test-reports', 'coverage_for_files.py', report, 'src/missing.py', '--required-suffix=.py')
        self.assertEqual(1, r.returncode)
        self.assertEqual(2, self.cli('test-reports', 'coverage_for_files.py', report, 'src/a.py', '--min=nan').returncode)

    def test_receipt_identity_health_and_timezone(self):
        m = load('deployment-receipt', 'receipt.py')
        record = {'sha': 'a'*40, 'host': 'staging.example.test', 'deploy_id': 'run-1',
                  'deployed_at': '2026-11-11T10:00:00Z', 'health': {'passed': True, 'deploy_id': 'run-1', 'checked_at': '2026-11-11T10:01:00Z'}}
        self.assertTrue(m.validate(record, 'a'*40, 'staging.example.test'))
        for mutation in ({'sha': 'b'*40}, {'deployed_at': '2026-11-11T10:00:00'}, {'health': {'passed': True, 'deploy_id': 'other'}}):
            with self.assertRaises((ValueError, TypeError)):
                m.validate({**record, **mutation}, 'a'*40, 'staging.example.test')

    def test_fixture_control_and_fresh_run(self):
        m = load('fixture-evidence', 'evidence.py')
        record = {'id': 'case-1', 'property': 'bounded', 'oracle': 'independent rule', 'preconditions': 'control ready',
                  'expected': {}, 'actual': {}, 'outcome': 'PASS', 'control_passed': False, 'evidence': ['count=1']}
        with self.assertRaises(ValueError):
            m.validate(record)
        record['control_passed'] = True
        m.write_run(self.root, 'run-1', [record])
        with self.assertRaises(FileExistsError):
            m.write_run(self.root, 'run-1', [record])

    def test_hash_and_link_drift(self):
        m = load('project-checks', 'check.py')
        self.put('README.md', '[missing](missing.md)')
        cfg = {'required': ['README.md'], 'hashes': {'README.md': '0'*64}, 'link_files': ['README.md']}
        self.assertEqual(2, len(m.check(self.root, cfg)))

    def test_workspace_requires_acceptance_tests_and_shared_consistency(self):
        m = load('ux-workspace', 'check.py')
        self.put('lab.html', 'BEGIN\nshared\nEND')
        self.put('acceptance.md', 'waiting on owner')
        self.put('tests.js', '// explicit tests')
        self.put('shared.txt', 'shared\n')
        cfg = {'labs': [{'file': 'lab.html', 'acceptance': 'acceptance.md', 'tests': 'tests.js'}],
               'shared': [{'source': 'shared.txt', 'begin': 'BEGIN', 'end': 'END'}]}
        self.assertEqual([], m.check(self.root, cfg))
        self.put('shared.txt', 'changed')
        self.assertEqual(1, len(m.check(self.root, cfg)))

    def test_workspace_sync_prevalidates_entire_batch_and_feedback_previews(self):
        self.put('one.html', 'BEGIN\nold\nEND')
        self.put('two.html', 'no markers')
        self.put('shared.txt', 'new')
        manifest = self.put('labs.json', json.dumps({'labs': [{'file': 'one.html'}, {'file': 'two.html'}],
                                                   'shared': [{'source': 'shared.txt', 'begin': 'BEGIN', 'end': 'END'}]}))
        self.assertEqual(2, self.cli('ux-workspace', 'sync.py', manifest, '--root', self.root, '--write').returncode)
        self.assertEqual('BEGIN\nold\nEND', (self.root / 'one.html').read_text())
        acceptance = self.put('acceptance.md', 'pending')
        observations = self.put('observations.txt', 'participant hesitated')
        self.assertEqual(0, self.cli('ux-workspace', 'feedback.py', acceptance, '--from-file', observations).returncode)
        self.assertEqual('pending', acceptance.read_text())

    def test_container_running_and_missing_memory_are_not_blanket_health(self):
        m = load('container-status', 'status.py')
        c = {'Name': 'fixture', 'HostConfig': {'RestartPolicy': {'Name': 'always'}}, 'State': {'Running': True, 'Health': {'Status': 'unhealthy'}}}
        result = m.evaluate([c], {'available_mb': 3000, 'swap_used_pct': 0}, 1500, 75)
        self.assertFalse(result['healthy'])
        self.assertFalse(m.evaluate([c], None, 1500, 75)['complete'])


class ConversationsAndReferences(Scratch):
    def test_byte_exact_chunks_and_tamper_detection(self):
        m = load('conversation-index', 'index.py')
        source = self.put('chat.md', 'preamble\n## You (2026-11-11 10:00 UTC)\nhello\n## ChatGPT (2026-11-11 10:01 UTC)\nanswer\n## You (2026-11-11 10:02 UTC)\nmore')
        out = self.root / 'chunks'
        record = m.build(source, out, 2)
        self.assertEqual(record, m.verify(source, out))
        with self.assertRaises(ValueError):
            m.build(source, out, 2)
        (out / record['chunks'][0]['file']).write_text('modified')
        with self.assertRaises(ValueError):
            m.verify(source, out)

    def test_segment_quotes_and_gaps(self):
        m = load('conversation-index', 'index.py')
        source = self.put('chat.md', '## You (2026-11-11 10:00 UTC)\nkeep this decision\n')
        m.check_segments(source, [{'start': 1, 'end': 2, 'decisions': [{'line': 2, 'quote': 'keep this decision'}]}])
        with self.assertRaises(ValueError):
            m.check_segments(source, [{'start': 1, 'end': 2, 'decisions': [{'line': 2, 'quote': 'invented decision'}]}])

    def test_reference_query_is_scoped_and_bounded(self):
        m = load('reference-library', 'query.py')
        self.put('docs/page.md', '# Focus\n' + 'focus '*1000)
        rows = m.search(self.root / 'docs', 'focus', limit=1, chars=50)
        self.assertEqual(1, len(rows))
        self.assertLessEqual(len(rows[0][3]), 50)


class Services(Scratch):
    def test_sonar_complete_pages_and_repeated_identity(self):
        m = load('service-readers', 'http_reader.py')
        r = m.Reader('https://service.example.test', {})
        pages = [{'issues': [{'key': 'a'}], 'paging': {'total': 2}}, {'issues': [{'key': 'b'}], 'paging': {'total': 2}}]
        with mock.patch.object(r, 'get', side_effect=pages):
            self.assertEqual(2, len(r.sonar_pages('/issues', {}, 'issues')))
        with mock.patch.object(r, 'get', side_effect=[pages[0], pages[0]]), self.assertRaises(m.Unavailable):
            r.sonar_pages('/issues', {}, 'issues')

    def test_untrusted_pagination_url_rejected_before_request(self):
        m = load('service-readers', 'http_reader.py')
        opener = mock.Mock()
        r = m.Reader('https://service.example.test/api', {}, opener=opener)
        with self.assertRaises(m.Unavailable):
            r.get('https://other.example.test/steal')
        opener.open.assert_not_called()

    def test_sonar_pagination_cannot_silently_stop_without_total(self):
        m = load('service-readers', 'http_reader.py')
        r = m.Reader('https://service.example.test', {})
        with mock.patch.object(r, 'get', return_value={'issues': []}), self.assertRaises(m.Unavailable):
            r.sonar_pages('/api/issues', {}, 'issues')

    def test_dojo_pagination_count_mismatch(self):
        m = load('service-readers', 'http_reader.py')
        r = m.Reader('https://service.example.test', {})
        with mock.patch.object(r, 'get', return_value={'results': [], 'count': 3, 'next': None}), self.assertRaises(m.Unavailable):
            r.dojo_pages('findings', {})

    def test_pr_required_stages_and_trusted_job(self):
        m = load('service-readers', 'pr_review.py')
        head = 'a'*40
        pr = {'number': 5, 'headRefOid': head}
        url = 'https://ci.example.test/jenkins/job/fixture/job/PR-5/12'
        status = {'statuses': [{'context': m.CONTEXT, 'state': 'success', 'target_url': url}]}
        build = {'number': 12, 'building': False, 'result': 'SUCCESS', 'actions': [{'lastBuiltRevision': {'SHA1': head}}]}
        flow = {'id': '12', 'status': 'SUCCESS', 'stages': [{'name': 'Tests', 'status': 'SUCCESS'}]}
        env = {'JENKINS_URL': 'https://ci.example.test/jenkins', 'JENKINS_JOB_PATH': 'job/fixture', 'REQUIRED_STAGES': 'Tests,Security'}
        with mock.patch.dict(os.environ, env), mock.patch.object(m, 'jenkins_get', side_effect=[build, flow]):
            self.assertFalse(m.jenkins_evidence(pr, status)['success'])
        env['REQUIRED_STAGES'] = 'Tests'
        with mock.patch.dict(os.environ, env), mock.patch.object(m, 'jenkins_get', side_effect=[build, flow]):
            self.assertTrue(m.jenkins_evidence(pr, status)['success'])
        status['statuses'][0]['target_url'] = url.replace('fixture', 'other')
        with mock.patch.dict(os.environ, env), mock.patch.object(m, 'jenkins_get') as transport, self.assertRaises(ValueError):
            m.jenkins_evidence(pr, status)
        transport.assert_not_called()


class PhpAndLexical(Scratch):
    @unittest.skipUnless(shutil.which('php'), 'PHP CLI required')
    def test_php_render_list_overrides_and_no_mutation(self):
        self.put('composer.json', '{"require":{"php":"^8.2"}}')
        (self.root / 'app').mkdir()
        (self.root / 'src').mkdir()
        self.put('.quality-tools.json', '{"paths":{"source":["src"]}}')
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        r = subprocess.run(['php', str(ROOT / 'tools/php-quality-config/generate.php'), str(self.root)], capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        rendered = json.loads(r.stdout)
        self.assertEqual(['src'], rendered['detected']['paths']['source'])
        self.assertIn('src', rendered['files']['phpstan.neon'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_lexical_build_query_and_refresh(self):
        self.git('init', '-q')
        self.put('alpha.py', 'def handle_invoice():\n    return "invoice"\n')
        self.put('.env', 'DO_NOT_INDEX=1')
        self.git('add', '.')
        db = self.root / 'index.db'
        r = self.cli('lexical-search', 'search.py', 'build', '--root', self.root, '--db', db)
        self.assertEqual(0, r.returncode, r.stderr)
        r = self.cli('lexical-search', 'search.py', 'query', '--root', self.root, '--db', db, '--query', 'handle_invoice')
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(['alpha.py'], json.loads(r.stdout)['paths'])
        self.assertEqual(2, self.cli('lexical-search', 'search.py', 'build', '--root', self.root, '--db', db).returncode)
        self.git('rm', '-f', 'alpha.py')
        self.assertEqual(0, self.cli('lexical-search', 'search.py', 'refresh', '--root', self.root, '--db', db).returncode)
        r = self.cli('lexical-search', 'search.py', 'query', '--root', self.root, '--db', db, '--query', 'handle_invoice')
        self.assertEqual([], json.loads(r.stdout)['paths'])


if __name__ == '__main__':
    unittest.main()

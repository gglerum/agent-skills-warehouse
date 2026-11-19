"""CLI regressions using disposable consumer checkouts and real linked worktrees."""
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

SCRIPTS = Path(__file__).resolve().parents[1] / 'tools' / 'test-reports'


class ReportHelpersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'consumer'
        self.root.mkdir()
        self.git('init', '-q')
        self.helpers = self.root / 'utils/shared/scripts'
        self.helpers.mkdir(parents=True)
        for name in ('failed_tests.py', 'coverage_for_files.py'):
            shutil.copy(SCRIPTS / name, self.helpers / name)
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True)

    def run_helper(self, name, *args, cwd=None, helpers=None):
        return subprocess.run([sys.executable, str((helpers or self.helpers) / name),
                               *map(str, args)], cwd=cwd or self.root,
                              capture_output=True, text=True)

    def junit(self, path, name=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        suite = ET.Element('testsuite')
        if name:
            case = ET.SubElement(suite, 'testcase', {'class': r'Tests\Feature\LoginTest',
                                                   'name': name, 'file': 'LoginTest.php'})
            ET.SubElement(case, 'failure', {'message': 'Oops & broken'})
        ET.ElementTree(suite).write(path)

    def test_default_junit_main_checkout_and_subdirectory(self):
        self.junit(self.root / 'reports/junit-local.xml', 'testMain')
        self.junit(self.helpers.parent / 'reports/junit-local.xml')
        for cwd in (self.root, self.helpers):
            with self.subTest(cwd=cwd):
                result = self.run_helper('failed_tests.py', cwd=cwd)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn('testMain', result.stdout)

    def test_default_junit_linked_worktree_and_arbitrary_directory(self):
        worktree = Path(self.tmp.name) / 'worktree'
        self.git('worktree', 'add', '-qb', 'fixture-worktree', str(worktree))
        self.junit(self.root / 'reports/junit-local.xml')
        self.junit(worktree / 'reports/junit-local.xml', 'testWorktree')
        helpers = worktree / 'utils/shared/scripts'
        for cwd in (worktree, helpers, Path(self.tmp.name)):
            with self.subTest(cwd=cwd):
                result = self.run_helper('failed_tests.py', cwd=cwd, helpers=helpers)
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn('testWorktree', result.stdout)

    def test_explicit_junit_and_escaped_test_names(self):
        name = "testOdd[1]/it's+$"
        self.junit(self.root / 'custom.xml', name + ' with data set #0')
        result = self.run_helper('failed_tests.py', 'custom.xml')
        self.assertEqual(1, result.returncode)
        self.assertIn('Oops & broken', result.stdout)
        command = shlex.split(result.stdout.splitlines()[-1])
        pattern = command[-1].removeprefix('--filter=')[1:-1].replace(r'\/', '/')
        self.assertIsNotNone(re.search(pattern, '\\LoginTest::' + name + ' with data set #0'))
        for wrong in ('\\WrongLoginTest::' + name, '\\LoginTest::testOdd1/its',
                      '\\LoginTest::' + name + 'Longer'):
            self.assertIsNone(re.search(pattern, wrong))

    def test_junit_success_missing_and_malformed(self):
        for contents, code in ((None, 2), ('<broken', 2), ('<testsuite/>', 0)):
            with self.subTest(contents=contents):
                report = self.root / 'reports/junit-local.xml'
                if contents is not None:
                    report.parent.mkdir(exist_ok=True)
                    report.write_text(contents)
                result = self.run_helper('failed_tests.py')
                self.assertEqual(code, result.returncode)
                self.assertNotIn('Traceback', result.stderr)

    def clover(self, entries):
        project = ET.Element('project')
        for name, covered, total in entries:
            node = ET.SubElement(project, 'file', {'name': str(self.root / name)})
            ET.SubElement(node, 'metrics', {'coveredstatements': str(covered),
                                           'statements': str(total)})
        report = self.root / 'clover.xml'
        ET.ElementTree(project).write(report)
        return report

    def test_missing_executable_source_fails_even_with_other_valid_coverage(self):
        (self.root / 'Missing.php').write_text('<?php function missing() { return 1; }')
        report = self.clover([('Covered.php', 10, 10)])
        result = self.run_helper('coverage_for_files.py', report, 'Missing.php', 'Covered.php')
        self.assertEqual(1, result.returncode)
        self.assertIn('coverage unknown', result.stdout)
        self.assertIn('100.0%', result.stdout)

    def test_zero_statement_records_and_absent_non_php_files(self):
        (self.root / 'Contract.php').write_text('<?php interface Contract {}')
        result = self.run_helper('coverage_for_files.py',
                                 self.clover([('Contract.php', 0, 0)]), 'Contract.php', 'README.md')
        self.assertEqual(0, result.returncode)
        self.assertIn('no statements', result.stdout)
        self.assertIn('not in report', result.stdout)

    def test_coverage_threshold(self):
        report = self.clover([('Good.php', 8, 10), ('Low.php', 7, 10)])
        for files, code in ((('Good.php',), 0), (('Good.php', 'Low.php'), 1),
                            (('Low.php', '--min=70'), 0)):
            with self.subTest(files=files):
                result = self.run_helper('coverage_for_files.py', report, *files)
                self.assertEqual(code, result.returncode, result.stderr)

    def test_missing_malformed_and_invalid_clover(self):
        report = self.root / 'clover.xml'
        for contents in (None, '<broken',
                         '<project><file name="bad.php"><metrics statements="bad"/></file></project>'):
            with self.subTest(contents=contents):
                if contents is not None:
                    report.write_text(contents)
                result = self.run_helper('coverage_for_files.py', report, 'Source.php')
                self.assertEqual(2, result.returncode)
                self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()

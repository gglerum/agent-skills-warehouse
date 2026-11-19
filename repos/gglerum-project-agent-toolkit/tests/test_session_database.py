"""Local DB adapter contract; real PHP evaluates SQL selection over fake inventory."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/laravel-tests/session_database.py'


@unittest.skipUnless(shutil.which('php'), 'PHP CLI required for fake artisan fixture')
class SessionDatabase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.test')
        self.git('config', 'user.name', 'Fixture')
        (self.root / 'tracked').touch()
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.worktree = self.root / '.worktrees/demo'
        self.git('worktree', 'add', '-qb', 'demo', str(self.worktree))
        self.receipt = self.root / '.git/session-databases/demo.json'
        identity = str(self.root / '.git') + '\0demo'
        self.database = 'testing_wt_' + hashlib.sha256(identity.encode()).hexdigest()[:24] + '_base'
        self.inventory = Path(self.temp.name) / 'inventory.json'
        self.inventory.write_text('[]')
        self.env = dict(os.environ, FAKE_INVENTORY=str(self.inventory))
        (self.worktree / 'artisan').write_text('''<?php
class DB {
    public static function select($sql) {
        return array_map(fn($name) => (object)['Database' => $name], json_decode(file_get_contents(getenv('FAKE_INVENTORY')), true));
    }
    public static function statement($sql) {
        if (getenv('FAIL_SQL')) { throw new Exception('Injected SQL failure'); }
        $file = getenv('FAKE_INVENTORY');
        $names = json_decode(file_get_contents($file), true);
        preg_match('/`([^`]+)`/', $sql, $matches);
        $name = $matches[1];
        if (str_starts_with($sql, 'CREATE')) {
            if (in_array($name, $names)) { throw new Exception('Database exists'); }
            $names[] = $name;
        } else { $names = array_values(array_diff($names, [$name])); }
        file_put_contents($file, json_encode($names));
    }
}
if (!getenv('SILENT_SQL')) { eval(substr($argv[2], strlen('--execute='))); }
''')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.STDOUT, text=True)

    def run_adapter(self, action, success=True, topic='demo', directory=None):
        command = [sys.executable, '-B']
        result = subprocess.run(command + [str(SCRIPT), action, str(directory or self.worktree), topic],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def names(self):
        return json.loads(self.inventory.read_text())

    def test_ready_resume_exact_workers_and_idempotent_cleanup(self):
        self.run_adapter('setup')
        self.run_adapter('setup')
        owned = [self.database, self.database + '_test_1', self.database + '_test_20']
        unrelated = ['testing', 'testing_test_1', self.database + '_test_other',
                     self.database + '_test_1_extra', self.database + '_test_', 'testing_other']
        self.inventory.write_text(json.dumps(owned + unrelated))
        self.run_adapter('teardown')
        self.assertEqual(self.names(), unrelated)
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'removed')
        self.assertFalse((self.worktree / '.testing-database').exists())
        self.run_adapter('teardown')
        self.run_adapter('setup', success=False)

    def test_failed_creation_never_adopts_existing_database(self):
        self.inventory.write_text(json.dumps([self.database]))
        self.run_adapter('setup', success=False)
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'creating')
        self.run_adapter('setup', success=False)
        self.run_adapter('teardown', success=False)
        self.assertEqual(self.names(), [self.database])

    def test_drop_failure_receipt_survives_worktree_loss_and_retries(self):
        self.run_adapter('setup')
        self.env['FAIL_SQL'] = '1'
        self.run_adapter('teardown', success=False)
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'dropping')
        self.assertTrue((self.worktree / '.testing-database').exists())
        del self.env['FAIL_SQL']
        self.run_adapter('teardown')
        self.assertEqual(self.names(), [])
        self.git('worktree', 'remove', '--force', str(self.worktree))
        self.assertTrue(self.receipt.exists())

    def test_marker_and_receipt_tampering_block(self):
        marker = self.worktree / '.testing-database'
        marker.write_text('testing_unrelated\n')
        self.run_adapter('setup', success=False)
        self.run_adapter('teardown', success=False)
        self.assertTrue((self.receipt.parent / 'demo.unowned.json').exists())
        marker.unlink()
        self.run_adapter('setup')
        record = json.loads(self.receipt.read_text())
        record['path'] = str(self.root)
        self.receipt.write_text(json.dumps(record))
        self.run_adapter('teardown', success=False)
        self.assertEqual(self.names(), [self.database])

    def test_invalid_topics_roots_and_unowned_cleanup(self):
        for topic in ['demo-', 'a', '../demo', 'demo_test_1']:
            self.run_adapter('setup', success=False, topic=topic)
        self.run_adapter('setup', success=False, directory=self.root, topic='repo')
        self.run_adapter('setup', success=False, directory=self.worktree / 'missing')
        self.run_adapter('teardown')
        self.assertEqual(self.names(), [])

    def test_worker_like_topic_uses_disjoint_fixed_namespace(self):
        self.run_adapter('setup')
        other_tree = self.root / '.worktrees/demo-test-1'
        self.git('worktree', 'add', '-qb', 'other', str(other_tree))
        shutil.copyfile(self.worktree / 'artisan', other_tree / 'artisan')
        self.run_adapter('setup', topic='demo-test-1', directory=other_tree)
        other = json.loads((self.receipt.parent / 'demo-test-1.json').read_text())['database']
        self.assertNotEqual(other, self.database + '_test_1')
        self.assertLessEqual(len(other + '_test_1234567890'), 64)
        self.run_adapter('teardown')
        self.assertEqual(self.names(), [other])

    def test_lock_and_malformed_receipt_block(self):
        import fcntl
        self.receipt.parent.mkdir(parents=True)
        with self.receipt.with_suffix('.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.run_adapter('setup', success=False)
        self.receipt.write_text('{')
        self.run_adapter('setup', success=False)
        self.assertEqual(self.names(), [])

    def test_dependency_failures_preserve_env_then_resume(self):
        (self.root / '.env').write_text('APP_KEY=fixture-only\n')
        (self.worktree / 'tests').mkdir()
        (self.worktree / 'tests/bootstrap.php').write_text('# .testing-database')
        (self.root / '.claude').mkdir()
        (self.root / 'tools/laravel-tests').mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.root / 'tools/laravel-tests/session_database.py')
        shutil.copyfile(ROOT / 'tools/laravel-tests/setup.sh', self.root / 'tools/laravel-tests/setup.sh')
        binaries = Path(self.temp.name) / 'bin'
        binaries.mkdir()
        for name in ('composer', 'npm'):
            stub = binaries / name
            stub.write_text('#!/bin/sh\n[ "$FAIL_TOOL" != "' + name + '" ]\n')
            stub.chmod(0o755)
        env = dict(self.env, MAIN_ROOT=str(self.root), PATH=str(binaries) + ':' + os.environ['PATH'])
        for tool in ('composer', 'npm', ''):
            env['FAIL_TOOL'] = tool
            result = subprocess.run(['bash', str(self.root / 'tools/laravel-tests/setup.sh'),
                                     str(self.worktree), 'demo'], env=env, capture_output=True)
            self.assertEqual(result.returncode == 0, tool == '', result.stderr)
            self.assertEqual((self.worktree / '.env').read_text(), 'APP_KEY=fixture-only\n')
            (self.root / '.env').write_text('APP_KEY=changed-main-fixture\n')
        self.assertEqual(self.names(), [self.database])

    def test_zero_exit_without_sql_completion_blocks(self):
        self.env['SILENT_SQL'] = '1'
        self.run_adapter('setup', success=False)
        self.assertEqual(json.loads(self.receipt.read_text())['state'], 'creating')
        self.assertEqual(self.names(), [])

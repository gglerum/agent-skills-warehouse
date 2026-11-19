"""Exercise actual session shell against disposable local Git repositories."""
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/worktrees/new_session.sh'


class Sessions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.env = dict(os.environ, HOME=str(Path(self.temp.name) / 'home'))
        self.memory = Path(self.env['HOME']) / '.claude/projects' / re.sub('[^A-Za-z0-9]', '-', str(self.root)) / 'memory'
        self.memory.mkdir(parents=True)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.test')
        self.git('config', 'user.name', 'Fixture')
        (self.root / '.agent-toolkit').mkdir()
        (self.root / '.gitignore').write_text('.worktrees/\n')
        (self.root / '.agent-toolkit/workflow.conf').write_text('BASE_BRANCH=main\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        self.git('remote', 'add', 'origin', str(self.root))
        self.journal = self.root / '.git/session-recovery/demo'
        self.worktree = self.root / '.worktrees/demo'
        self.setup = self.root / '.agent-toolkit/session-setup.sh'
        self.teardown = self.root / '.agent-toolkit/session-teardown.sh'
        self.adapter(self.setup, 'echo setup >> "$MAIN_ROOT/calls"\n')
        self.adapter(self.teardown, 'echo teardown >> "$MAIN_ROOT/calls"\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'adapters')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], env=self.env, stderr=subprocess.STDOUT, text=True)

    def adapter(self, path, body):
        path.write_text('#!/bin/bash\nset -eu\n' + body)
        path.chmod(0o755)

    def run_session(self, *args, success=True):
        result = subprocess.run(['bash', str(SCRIPT), *args], cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def test_setup_failure_resume_teardown_failure_and_retry(self):
        self.adapter(self.setup, 'exit 7\n')
        result = self.run_session('demo', success=False)
        self.assertIn('--resume demo', result.stderr)
        self.assertEqual((self.journal / 'phase').read_text().strip(), 'setup')
        self.assertTrue(self.worktree.exists())
        self.adapter(self.setup, 'echo recovered > "$1/recovered"\n')
        self.run_session('--resume', 'demo')
        self.assertEqual((self.journal / 'phase').read_text().strip(), 'ready')
        (self.worktree / 'recovered').unlink()
        self.adapter(self.teardown, 'exit 9\n')
        self.run_session('--remove', 'demo', success=False)
        self.assertTrue(self.worktree.exists())
        self.assertEqual((self.journal / 'phase').read_text().strip(), 'teardown')
        self.adapter(self.teardown, ':\n')
        self.run_session('--remove', 'demo')
        self.assertFalse(self.worktree.exists())
        self.assertTrue(self.memory.exists())
        self.assertEqual((self.journal / 'phase').read_text().strip(), 'removed')
        self.assertIn('demo', self.git('branch', '--list'))

    def test_dirty_and_changed_branch_never_teardown(self):
        self.run_session('demo')
        (self.worktree / 'dirty').write_text('keep')
        self.run_session('--remove', 'demo', success=False)
        (self.worktree / 'dirty').unlink()
        subprocess.run(['git', '-C', str(self.worktree), 'switch', '-qc', 'other'], check=True, capture_output=True)
        self.run_session('--remove', 'demo', success=False)
        self.assertNotIn('teardown', (self.root / 'calls').read_text())

    def test_collisions_and_trailing_dash(self):
        self.run_session('demo-', success=False)
        self.run_session('demo')
        self.run_session('demo', success=False)
        self.assertTrue(self.worktree.exists())
        self.run_session('--resume', 'missing', success=False)
        self.run_session('--remove', 'missing', success=False)

    def test_missing_teardown_keeps_worktree(self):
        self.run_session('demo')
        self.teardown.unlink()
        self.run_session('--remove', 'demo', success=False)
        self.assertTrue(self.worktree.exists())

    def test_fetch_failure_keeps_creation_journal(self):
        self.git('remote', 'set-url', 'origin', str(self.root / 'missing'))
        self.run_session('demo', success=False)
        self.assertEqual((self.journal / 'phase').read_text().strip(), 'creating')
        self.assertFalse(self.worktree.exists())

    def test_existing_branch_or_folder_not_adopted(self):
        self.run_session('demo')
        self.run_session('--remove', 'demo')
        import shutil
        shutil.rmtree(self.journal)
        self.run_session('demo', success=False)
        self.assertFalse(self.journal.exists())
        self.worktree.mkdir()
        self.run_session('demo', success=False)
        self.assertTrue(self.worktree.exists())

    def test_lock_blocks_concurrent_operation(self):
        lock = self.root / '.git/session-recovery/demo.lock'
        lock.mkdir(parents=True)
        self.run_session('demo', success=False)
        self.assertFalse(self.worktree.exists())

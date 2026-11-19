import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOKS = os.path.join(os.path.dirname(__file__), '..', 'tools', 'hooks')
GUARD = os.path.join(HOOKS, 'destructive_guard.py')
POINTER = os.path.join(HOOKS, 'session_review_pointer.py')


def run(script, payload, env=None):
    return subprocess.run([sys.executable, '-I', script], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def bash(command):
    return run(GUARD, {'tool_name': 'Bash', 'tool_input': {'command': command}})


class DestructiveGuardTest(unittest.TestCase):
    def assertBlocked(self, command):
        result = bash(command)
        self.assertEqual(2, result.returncode, command)
        self.assertIn('Blocked destructive command', result.stderr)

    def assertAllowed(self, command):
        self.assertEqual(0, bash(command).returncode, command)

    def test_blocks_destructive_commands(self):
        for command in [
            'sudo apt install x', 'FOO=1 sudo ls', 'ls && sudo ls', 'git reset --hard', 'git reset --hard HEAD~1',
            'git -C /x reset --hard', 'git clean -fd', 'git clean -xdf', 'git clean --force', 'rm -rf /', 'rm -rf .',
            'rm -fr ~', 'rm -r -f $HOME', 'rm --recursive --force *', 'git status\nsudo ls',
            'docker run --privileged x', 'docker run -v /var/run/docker.sock:/s x', '/usr/bin/sudo ls',
        ]:
            with self.subTest(command=command):
                self.assertBlocked(command)

    def test_allows_normal_commands(self):
        for command in [
            'git status', 'git reset --soft HEAD~1', 'git reset HEAD file', 'git clean -n', 'git clean -nd',
            'rm -rf vendor/cache', 'rm file.txt', 'rm -r build', 'docker ps', 'grep sudo README.md',
            "git commit -m 'document git reset --hard and sudo; rm -rf /'", 'echo "sudo; git reset --hard"',
            "gh pr create --body-file - <<'EOF'\nnever run git reset --hard\nEOF",
        ]:
            with self.subTest(command=command):
                self.assertAllowed(command)

    def test_ignores_other_tools(self):
        self.assertEqual(0, run(GUARD, {'tool_name': 'Read', 'tool_input': {'file_path': 'x'}}).returncode)

    def test_blocks_malformed_json(self):
        for raw in ('not json', '', '{', '{"tool_name": "Bash"'):
            with self.subTest(raw=raw):
                result = subprocess.run([sys.executable, '-I', GUARD], input=raw, capture_output=True, text=True)
                self.assertEqual(2, result.returncode)
                self.assertIn('blocked (fail closed)', result.stderr)
                self.assertEqual('', result.stdout)

    def test_blocks_invalid_tool_call_shapes(self):
        for payload in (None, [], 'Bash', 1, {}, {'tool_name': None}, {'tool_name': ''},
                        {'tool_name': 'Bash'}, {'tool_name': 'Bash', 'tool_input': None},
                        {'tool_name': 'Bash', 'tool_input': []}, {'tool_name': 'Bash', 'tool_input': {}},
                        {'tool_name': 'Bash', 'tool_input': {'command': None}},
                        {'tool_name': 'Bash', 'tool_input': {'command': ['git', 'status']}}):
            with self.subTest(payload=payload):
                result = run(GUARD, payload)
                self.assertEqual(2, result.returncode)
                self.assertIn('blocked (fail closed)', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual('', result.stdout)


class SessionReviewPointerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {'CLAUDE_CONFIG_DIR': self.tmp.name, 'PATH': os.environ.get('PATH', '')}

    def tearDown(self):
        self.tmp.cleanup()

    def folder(self):
        path = os.path.join(self.tmp.name, 'session-reviews', '-work-app')
        os.makedirs(path)
        return path

    def test_silent_without_reviews(self):
        result = run(POINTER, {'cwd': '/work/app'}, self.env)
        self.assertEqual((0, ''), (result.returncode, result.stdout))

    def test_points_at_newest_recent_review(self):
        folder = self.folder()
        for name in ('a.md', 'b.md'):
            open(os.path.join(folder, name), 'w').close()
        os.utime(os.path.join(folder, 'a.md'), (1, 1))
        os.utime(os.path.join(folder, 'b.md'), None)
        result = run(POINTER, {'cwd': '/work/app'}, self.env)
        context = json.loads(result.stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn(os.path.join(folder, 'b.md'), context)

    def test_ignores_old_review(self):
        folder = self.folder()
        old = os.path.join(folder, 'old.md')
        open(old, 'w').close()
        os.utime(old, (1, 1))
        self.assertEqual('', run(POINTER, {'cwd': '/work/app'}, self.env).stdout)


if __name__ == '__main__':
    unittest.main()

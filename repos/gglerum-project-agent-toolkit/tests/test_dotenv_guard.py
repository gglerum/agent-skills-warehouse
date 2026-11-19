import json
import os
import subprocess
import sys
import unittest

GUARD = os.path.join(os.path.dirname(__file__), '..', 'tools', 'hooks', 'dotenv_guard.py')


def run(payload):
    return subprocess.run([sys.executable, '-I', GUARD], input=json.dumps(payload), capture_output=True, text=True)


def bash(command):
    return run({'tool_name': 'Bash', 'tool_input': {'command': command}})


def tool(name, **inp):
    return run({'tool_name': name, 'tool_input': inp})


class GuardTest(unittest.TestCase):
    def assertBlocked(self, result, label):
        self.assertEqual(2, result.returncode, label)
        self.assertNotEqual('', result.stderr, label)

    def assertAllowed(self, result, label):
        self.assertEqual(0, result.returncode, label)

    def test_blocks_dotenv_in_bash(self):
        for command in ['cat .env', 'cat ./.env', 'grep KEY .env.local', 'head -5 /var/www/html/.env', 'cat .env*',
                        'cat .en*', 'cat "$(pwd)/.env"', 'cp .env /tmp/x', 'git status && cat .env.production']:
            with self.subTest(command=command):
                self.assertBlocked(bash(command), command)

    def test_allows_env_example_and_text_mentions(self):
        for command in ['cat .env.example', 'diff .env.example .env.example', 'git status',
                        "git commit -m 'never read .env or print APP_KEY'",
                        'git commit -m "mention .env in docs"',
                        "gh pr create --body-file - <<'EOF'\nDo not cat .env\nEOF",
                        "git commit -F - <<EOF\nfix: stop reading .env\n\nbody\nEOF",
                        'grep -rn environment app/']:
            with self.subTest(command=command):
                self.assertAllowed(bash(command), command)

    def test_blocks_indirect_dotenv_forms(self):
        for command in ['bash -c "cat .env"', "sh -c 'grep KEY .env.local'", 'cat<.env', 'cat < .env', 'grep --file=.env x',
                        'cat .e*', 'cat .?nv']:
            with self.subTest(command=command):
                self.assertBlocked(bash(command), command)

    def test_allows_lookalikes(self):
        for command in ['git commit -m ".env is now ignored"', 'cat .envrc', 'ls .eslintrc.js', 'bash -c "echo hi"']:
            with self.subTest(command=command):
                self.assertAllowed(bash(command), command)
        self.assertAllowed(tool('Grep', pattern='.env(', path='app'), 'grep pattern')
        self.assertBlocked(tool('Glob', pattern='.env*'), 'glob')
        self.assertBlocked(tool('NotebookEdit', notebook_path='.env'), 'notebook')

    def test_fails_closed_on_bad_input(self):
        result = subprocess.run([sys.executable, '-I', GUARD], input='garbage', capture_output=True, text=True)
        self.assertEqual(2, result.returncode)

    def test_blocks_dotenv_for_file_tools(self):
        for name, key, value in [('Read', 'file_path', '/var/www/html/.env'), ('Read', 'file_path', '.env.local'),
                                 ('Edit', 'file_path', '.env'), ('Write', 'file_path', 'x/.env.testing'),
                                 ('Grep', 'path', '.env'), ('Glob', 'pattern', '.env*')]:
            with self.subTest(tool=name, value=value):
                self.assertBlocked(tool(name, **{key: value}), value)

    def test_allows_other_files_for_file_tools(self):
        for name, key, value in [('Read', 'file_path', '/var/www/html/.env.example'), ('Read', 'file_path', 'app/Models/User.php'),
                                 ('Grep', 'path', 'app'), ('Glob', 'pattern', '**/*.php'), ('Write', 'file_path', 'docs/env.md')]:
            with self.subTest(tool=name, value=value):
                self.assertAllowed(tool(name, **{key: value}), value)

    def test_blocks_sleep_but_not_until_loops(self):
        self.assertBlocked(bash('sleep 30'), 'sleep 30')
        self.assertBlocked(bash('make && sleep 5'), 'make && sleep 5')
        self.assertAllowed(bash('until curl -s x; do sleep 2; done'), 'until loop')
        self.assertAllowed(bash('echo sleepy'), 'echo sleepy')
        self.assertBlocked(bash('echo hi\nsleep 5'), 'newline sleep')
        self.assertBlocked(bash('(sleep 5)'), 'subshell sleep')
        self.assertBlocked(bash('timeout 9 sleep 5'), 'timeout sleep')
        self.assertAllowed(bash('git commit -m "a; sleep 3"'), 'sleep in quotes')

    def test_unbalanced_quotes_fall_back_to_whitespace_split(self):
        self.assertBlocked(bash("cat .env 'unterminated"), 'unterminated quote')
        self.assertAllowed(bash("echo 'unterminated"), 'unterminated quote, harmless')

    def test_ignores_other_tools(self):
        self.assertAllowed(tool('WebFetch', url='https://x/.env'), 'WebFetch')


if __name__ == '__main__':
    unittest.main()

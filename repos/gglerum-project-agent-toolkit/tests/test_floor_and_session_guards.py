import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
FLOOR = TOOLS / 'floor-guard' / 'floor_guard.py'
WORKFLOW = TOOLS / 'session-guards' / 'workflow_guard.py'
CONTEXT = TOOLS / 'session-guards' / 'context_guard.py'

GIT_ENV = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.test', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.test'}


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True, env={**os.environ, **GIT_ENV})


class FloorGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        git(self.root, 'init', '-q', '-b', 'main')
        (self.root / 'tests').mkdir()
        (self.root / 'src').mkdir()
        (self.root / 'tests/test_math.py').write_text('def test_a():\n    assert 1 == 1\n    assert 2 == 2\n')
        (self.root / 'src/app.py').write_text('def f():\n    return 1\n')
        (self.root / 'CONSTRAINTS.md').write_text(
            '# Constraints\n\n## Floor\n\n- Coverage: at least 80 percent\n- Complexity: at most 10\n\n## Exceptions\n\n'
            '| Id | Rule | Reason | Owner | Expires |\n| --- | --- | --- | --- | --- |\n')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-q', '-m', 'base')

    def tearDown(self):
        self.tmp.cleanup()

    def guard(self, *args):
        return subprocess.run([sys.executable, '-B', '-I', str(FLOOR), '--base', 'main', *args], cwd=self.root, capture_output=True, text=True)

    def test_clean_tree_passes(self):
        result = self.guard()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('clean', result.stdout)

    def test_new_suppression_stub_and_skip_are_reported_without_the_code_line(self):
        (self.root / 'src/app.py').write_text('def f():\n    x = secret_token_123  # noqa\n    # TODO later\n    return 1\n')
        (self.root / 'tests/test_math.py').write_text('import pytest\n\n@pytest.mark.skip\ndef test_a():\n    pass\n')
        result = self.guard()
        self.assertEqual(1, result.returncode)
        for rule in ('silenced-checker', 'unfinished-work', 'test-made-easier', 'assertions-lost'):
            self.assertIn(rule, result.stderr)
        self.assertNotIn('secret_token_123', result.stderr)

    def test_deleted_test_and_untracked_suppression(self):
        (self.root / 'tests/test_math.py').unlink()
        (self.root / 'src/new.py').write_text('x = 1  # type: ignore\n')
        result = self.guard()
        self.assertEqual(1, result.returncode)
        self.assertIn('test-deleted', result.stderr)
        self.assertIn('src/new.py:1', result.stderr)

    def test_weakened_rule_and_removed_rule(self):
        text = (self.root / 'CONSTRAINTS.md').read_text()
        text = text.replace('at least 80 percent', 'at least 60 percent').replace('- Complexity: at most 10\n', '')
        (self.root / 'CONSTRAINTS.md').write_text(text)
        result = self.guard()
        self.assertEqual(1, result.returncode)
        self.assertIn('threshold-loosened', result.stderr)
        self.assertIn('rule-removed', result.stderr)

    def test_tightening_is_silent(self):
        text = (self.root / 'CONSTRAINTS.md').read_text().replace('at least 80 percent', 'at least 90 percent')
        (self.root / 'CONSTRAINTS.md').write_text(text)
        self.assertEqual(0, self.guard().returncode)

    def test_exception_rows_need_owner_and_future_expiry(self):
        path = self.root / 'CONSTRAINTS.md'
        base = path.read_text()
        path.write_text(base + '| U1 | Coverage | legacy | | 2999-01-01 |\n')
        self.assertIn('exception-without-owner', self.guard().stderr)
        path.write_text(base + '| U1 | Coverage | legacy | alice | soon |\n')
        self.assertIn('exception-without-expiry', self.guard().stderr)
        path.write_text(base + '| U1 | Coverage | legacy | alice | 2000-01-01 |\n')
        self.assertIn('exception-already-expired', self.guard().stderr)
        path.write_text(base + '| U1 | Coverage | legacy | alice | 2999-01-01 |\n')
        result = self.guard()
        self.assertEqual(0, result.returncode)
        self.assertIn('warning: new exception', result.stderr)

    def test_baseline_growth(self):
        (self.root / 'lint-baseline.json').write_text('{}\n')
        self.assertIn('baseline-grown', self.guard().stderr)

    def test_named_suppression_allow_list_from_configuration(self):
        (self.root / 'src/app.php').write_text('<?php\n/** @psalm-suppress TaintedInput */\n/** @psalm-suppress MixedAssignment */\n')
        config = self.root / 'guard.json'
        config.write_text(json.dumps({'named_suppressions': [{'pattern': r'@psalm-suppress\s+([^*\n]*)', 'allowed': ['TaintedInput']}]}))
        result = self.guard('--config', str(config))
        self.assertEqual(1, result.returncode)
        self.assertEqual(1, result.stderr.count('silenced-checker'))
        self.assertIn('MixedAssignment', result.stderr)

    def test_could_not_run_is_exit_2(self):
        result = subprocess.run([sys.executable, '-B', '-I', str(FLOOR), '--base', 'no-such-ref'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(2, result.returncode)
        outside = tempfile.TemporaryDirectory()
        try:
            result = subprocess.run([sys.executable, '-B', '-I', str(FLOOR)], cwd=outside.name, capture_output=True, text=True)
            self.assertEqual(2, result.returncode)
        finally:
            outside.cleanup()
        bad = self.root / 'bad.json'
        bad.write_text('{not json')
        result = subprocess.run([sys.executable, '-B', '-I', str(FLOOR), '--config', str(bad)], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(2, result.returncode)


def hook(script, payload, **env):
    return subprocess.run([sys.executable, '-B', '-I', str(script)], input=json.dumps(payload), capture_output=True, text=True,
                          env={**os.environ, **env})


class WorkflowGuardTest(unittest.TestCase):
    def bash(self, command, cwd='/nonexistent-cwd', session='s1', **env):
        return hook(WORKFLOW, {'tool_name': 'Bash', 'cwd': cwd, 'session_id': session, 'tool_input': {'command': command}}, **env)

    def test_redundant_cd_blocked_but_other_directory_passes(self):
        with tempfile.TemporaryDirectory() as here, tempfile.TemporaryDirectory() as there:
            blocked = self.bash(f'cd {here} && ls', cwd=here)
            self.assertEqual(2, blocked.returncode)
            self.assertIn('already starts there', blocked.stderr)
            self.assertEqual(0, self.bash(f'cd {there} && ls', cwd=here).returncode)
            self.assertEqual(0, self.bash(f'cd {here} && ls', cwd=here, WORKFLOW_GUARD_DISABLE='redundant_cd').returncode)

    def test_sleep_blocked_unless_in_until_loop(self):
        self.assertEqual(2, self.bash('sleep 30').returncode)
        self.assertEqual(0, self.bash('until test -f x; do sleep 1; done').returncode)

    def test_dump_nudge_never_blocks_and_ignores_pipes_to_nothing(self):
        result = self.bash('cat README.md')
        self.assertEqual(0, result.returncode)
        self.assertIn('Token discipline', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
        self.assertEqual('', self.bash('git log | head -5').stdout)
        self.assertEqual('', self.bash('cat > out.txt <<EOF\nmentions cat file\nEOF').stdout)

    def test_second_inline_rewrite_blocked_per_session(self):
        command = "python3 -c \"open('src/app.py','w').write('x')\""
        env = {'WORKFLOW_GUARD_STATE_PREFIX': 'toolkit-test-guard'}
        session = 'rewrite-test-%d' % os.getpid()
        try:
            self.assertEqual(0, self.bash(command, session=session, **env).returncode)
            second = self.bash(command, session=session, **env)
            self.assertEqual(2, second.returncode)
            self.assertIn('Second inline rewrite of src/app.py', second.stderr)
            self.assertEqual(0, self.bash(command, session=session + 'other', **env).returncode)
        finally:
            for name in os.listdir(tempfile.gettempdir()):
                if name.startswith('toolkit-test-guard-'):
                    os.unlink(os.path.join(tempfile.gettempdir(), name))

    def test_other_tools_and_bad_input_pass(self):
        self.assertEqual(0, hook(WORKFLOW, {'tool_name': 'Read', 'tool_input': {'file_path': 'x'}}).returncode)
        self.assertEqual(0, subprocess.run([sys.executable, '-I', str(WORKFLOW)], input='not json', capture_output=True, text=True).returncode)


class ContextGuardTest(unittest.TestCase):
    def transcript(self, directory, tokens):
        path = Path(directory) / 't.jsonl'
        path.write_text(json.dumps({'message': {'usage': {'input_tokens': tokens, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}}}) + '\n')
        return path

    def test_warns_once_per_band_and_stays_quiet_below_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {'CONTEXT_GUARD_STATE_PREFIX': 'toolkit-test-context', 'CONTEXT_GUARD_TOKENS': '1000', 'CONTEXT_GUARD_STEP': '500'}
            session = 'ctx-%d' % os.getpid()
            try:
                low = hook(CONTEXT, {'transcript_path': str(self.transcript(directory, 900)), 'session_id': session}, **env)
                self.assertEqual('', low.stdout)
                high = hook(CONTEXT, {'transcript_path': str(self.transcript(directory, 1200)), 'session_id': session}, **env)
                self.assertIn('past the 1k split point', json.loads(high.stdout)['hookSpecificOutput']['additionalContext'])
                again = hook(CONTEXT, {'transcript_path': str(self.transcript(directory, 1300)), 'session_id': session}, **env)
                self.assertEqual('', again.stdout)
                next_band = hook(CONTEXT, {'transcript_path': str(self.transcript(directory, 1700)), 'session_id': session}, **env)
                self.assertIn('additionalContext', next_band.stdout)
            finally:
                for name in os.listdir(tempfile.gettempdir()):
                    if name.startswith('toolkit-test-context-'):
                        os.unlink(os.path.join(tempfile.gettempdir(), name))

    def test_fails_open(self):
        result = hook(CONTEXT, {'transcript_path': '/no/such/file', 'session_id': 's'})
        self.assertEqual((0, ''), (result.returncode, result.stdout))


if __name__ == '__main__':
    unittest.main()

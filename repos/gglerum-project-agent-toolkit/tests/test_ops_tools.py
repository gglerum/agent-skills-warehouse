import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
BOARD = TOOLS / 'roadmap-board' / 'board.sh'
PREFLIGHT = TOOLS / 'roadmap-board' / 'preflight.sh'
SESSION_END = TOOLS / 'session-closeout' / 'session_end.sh'
LOG_STEP = TOOLS / 'session-closeout' / 'log_step.sh'
STATUS = TOOLS / 'session-closeout' / 'project_status.sh'
CONTAINER = TOOLS / 'throwaway-container' / 'run_in_container.sh'
WORKFLOW = TOOLS / 'pr-conventions' / 'no-closing-keywords.yml'

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
state = json.load(open(os.environ["FAKE_GH_STATE"]))
log = open(os.environ["FAKE_GH_LOG"], "a")
log.write(json.dumps(args) + "\n")
joined = " ".join(args)
if args[:2] == ["issue", "list"] and "--state all" in joined:
    print("\n".join(f"{n}\t{s}" for n, s in state["issue_states"].items()))
elif args[:2] == ["project", "item-list"]:
    if "--jq" in args:
        print("\n".join(f"{n}\t{s}" for n, s in state["statuses"].items()))
    else:
        print(json.dumps({"items": state["items"]}))
elif args[:2] == ["api", "graphql"]:
    print("\n".join("\t".join(str(c) for c in row) for row in state["graphql"]))
elif args[:2] == ["issue", "list"] and "--label" in args and "--jq" in args:
    print(state.get("waiting_numbers", ""))
elif args[:2] == ["issue", "list"] and "--label" in args:
    print(json.dumps(state.get("waiting", [])))
elif args[:2] == ["issue", "view"] and "--comments" in args:
    print("ISSUE %s with comments" % args[2])
elif args[:2] == ["issue", "view"] and "body" in joined:
    print(state["body"])
elif args[:2] == ["issue", "view"] and "assignees" in joined:
    print("\n".join(state.get("assignees", [])))
elif args[:2] == ["issue", "view"]:
    print("#%s %s\tTitle" % (args[2], state["issue_states"].get(args[2], "OPEN")))
elif args[:2] == ["issue", "edit"]:
    body_file = args[args.index("--body-file") + 1] if "--body-file" in args else None
    if body_file:
        open(os.environ["FAKE_GH_EDIT"], "w").write(open(body_file).read())
elif args[:1] == ["api"] and "blocked_by" in joined:
    print("\n".join(state.get("blockers", [])))
elif args[:2] == ["pr", "view"]:
    print("#7 OPEN mergeable=MERGEABLE https://example.test/pr/7")
'''


class FakeGhCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.state_file = self.root / 'state.json'
        self.log = self.root / 'gh.log'
        self.edit = self.root / 'edit.txt'
        (self.root / 'roadmap.conf').write_text('BOARD_REPO="acme/shop"\nBOARD_OWNER="acme"\nBOARD_PROJECT=3\nBOARD_DEFAULT_WAIT_ASSIGNEE="reviewer"\n')
        self.env = {**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}', 'ROADMAP_CONF': str(self.root / 'roadmap.conf'),
                    'FAKE_GH_STATE': str(self.state_file), 'FAKE_GH_LOG': str(self.log), 'FAKE_GH_EDIT': str(self.edit)}

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, **values):
        self.state_file.write_text(json.dumps(values))

    def run_script(self, script, *args, cwd=None):
        return subprocess.run(['bash', str(script), *args], cwd=cwd or self.root, env=self.env, capture_output=True, text=True)


class BoardTest(FakeGhCase):
    def test_next_offers_only_unblocked_ready_issues_that_are_not_waiting(self):
        self.state(issue_states={'1': 'OPEN', '2': 'OPEN', '3': 'OPEN', '4': 'OPEN', '5': 'CLOSED', '6': 'OPEN'},
                   statuses={'1': 'Ready', '2': 'Ready', '3': 'Backlog', '4': 'In progress', '6': 'Ready'},
                   graphql=[[1, 'Open and ready', 0, ''], [2, 'Blocked by open', 0, '3'], [3, 'Backlog with closed blocker', 0, '5'],
                            [4, 'Already in progress', 0, ''], [6, 'Waiting on someone', 1, '']])
        result = self.run_script(BOARD, 'next')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['#1\tReady\tOpen and ready', '#3\tBacklog\tBacklog with closed blocker'], result.stdout.strip().split('\n'))

    def test_next_explains_when_nothing_is_ready(self):
        self.state(issue_states={'1': 'OPEN'}, statuses={'1': 'In progress'}, graphql=[[1, 'x', 0, '']])
        self.assertIn('Nothing is ready', self.run_script(BOARD, 'next').stdout)

    def test_waitingon_puts_line_on_top_labels_and_assigns_default_reviewer(self):
        self.state(body='Original body text', issue_states={})
        result = self.run_script(BOARD, 'waitingon', '12', 'needs a legal answer')
        self.assertEqual(0, result.returncode, result.stderr)
        body = self.edit.read_text()
        self.assertRegex(body, r'^\*\*Waiting on reviewer \(\d{4}-\d{2}-\d{2}\):\*\* needs a legal answer\n\nOriginal body text')
        edit_call = [json.loads(l) for l in self.log.read_text().splitlines() if '"edit"' in l][-1]
        self.assertIn('--add-label', edit_call)
        self.assertEqual('reviewer', edit_call[edit_call.index('--add-assignee') + 1])

    def test_waitingon_done_removes_the_line_and_label(self):
        self.state(body='**Waiting on reviewer (2026-01-01):** question\n\nOriginal body text', assignees=['reviewer', 'acme'])
        result = self.run_script(BOARD, 'waitingon', '12', '--done')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('Original body text', self.edit.read_text().strip())
        calls = [json.loads(l) for l in self.log.read_text().splitlines() if '"edit"' in l]
        self.assertTrue(any('--remove-label' in c for c in calls))
        removed = [c[c.index('--remove-assignee') + 1] for c in calls if '--remove-assignee' in c]
        self.assertEqual(['reviewer'], removed)

    def test_handoff_writes_file_with_issue_branch_header(self):
        repo = self.root / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'feature'], cwd=repo, check=True)
        note = self.root / 'note.md'
        note.write_text('What changed.\n')
        result = self.run_script(BOARD, 'handoff', '42', str(note), cwd=repo)
        self.assertEqual(0, result.returncode, result.stderr)
        written = next((repo / 'docs/handoffs').glob('*-issue-42.md')).read_text()
        self.assertTrue(written.startswith('# Handoff issue #42'))
        self.assertIn('branch feature', written)
        self.assertIn('What changed.', written)

    def test_session_prompt_names_skill_preflight_issue_titles_and_refs_rule(self):
        self.state(items=[{'content': {'number': 42, 'title': '[AB-12] Add checkout'}, 'kind': 'Story', 'size': 'M', 'source': 'F10'}])
        result = self.run_script(BOARD, 'session-prompt', '42', 'show', 'wireframes')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('Use the roadmap-session skill', result.stdout)
        self.assertIn('- #42 AB-12 Add checkout (Story, size M), source F10', result.stdout)
        self.assertIn('never `Closes`', result.stdout)
        self.assertIn('Extra: show wireframes', result.stdout)

    def test_missing_configuration_and_usage_are_reported(self):
        env = {k: v for k, v in self.env.items() if k != 'ROADMAP_CONF'}
        env['ROADMAP_CONF'] = str(self.root / 'absent.conf')
        result = subprocess.run(['bash', str(BOARD), 'next'], env=env, capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('BOARD_REPO', result.stderr)
        self.assertNotEqual(0, self.run_script(BOARD).returncode)


class PreflightTest(FakeGhCase):
    def test_warns_for_gate_issue_without_blocker_and_prints_sections(self):
        (self.root / 'roadmap.conf').write_text(
            'BOARD_REPO="acme/shop"\nBOARD_OWNER="acme"\nBOARD_PROJECT=3\nPREFLIGHT_GATE_ISSUES="19 20"\n'
            'PREFLIGHT_DECISIONS_CMD="echo decisions-for"\nPREFLIGHT_FINDINGS_CMD="echo findings"\nPREFLIGHT_DESIGN_CMD="echo design-for"\n')
        self.state(body='Depends on design #19 and #20.', blockers=['20'], issue_states={'20': 'CLOSED'},
                   items=[{'content': {'number': 42}, 'source': 'F10 FB-003'}])
        result = self.run_script(PREFLIGHT, '42')
        self.assertEqual(0, result.returncode, result.stderr)
        out = result.stdout
        self.assertIn('WARNING: this issue names gate issue #19 but is not blocked by it', out)
        self.assertNotIn('gate issue #20', out)
        self.assertIn('--- finding F10 ---', out)
        self.assertIn('findings show F10', out)
        self.assertIn('feedback item FB-003', out)
        self.assertIn('decisions-for for 42 20 F10 FB-003', out)
        self.assertIn('design-for for 42 20', out)

    def test_rejects_non_numeric_issue(self):
        self.state()
        self.assertNotEqual(0, self.run_script(PREFLIGHT, 'abc').returncode)


class SessionCloseoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        self.work = self.root / 'work'
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.test', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.test'}
        self.git_env = env
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.remote)], check=True)
        subprocess.run(['git', 'clone', '-q', str(self.remote), str(self.work)], check=True, capture_output=True)
        (self.work / 'README.md').write_text('x')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'init')
        self.git('push', '-q', '-u', 'origin', 'main')
        self.conf = self.root / 'closeout.conf'

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.work, env=self.git_env, check=True, capture_output=True, text=True)

    def end(self, *args):
        env = {**os.environ, 'CLOSEOUT_CONF': str(self.conf)}
        return subprocess.run(['bash', str(SESSION_END), '--offline', *args], cwd=self.work, env=env, capture_output=True, text=True)

    def test_passes_when_checks_pass_tree_clean_and_pushed(self):
        self.conf.write_text('CLOSEOUT_CHECKS=("records ok|true")\nCLOSEOUT_BASE="origin/main"\nCLOSEOUT_DOC_PATHS=("docs/decisions/|decision records")\n')
        result = self.end()
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn('ok    records ok', result.stdout)
        self.assertIn('ok    working tree clean', result.stdout)
        self.assertIn('ok    pushed (origin/main)', result.stdout)
        self.assertIn('no    decision records', result.stdout)

    def test_fails_on_failing_check_dirty_tree_and_unpushed_commit(self):
        self.conf.write_text('CLOSEOUT_CHECKS=("stale overview|echo stale index >&2; exit 1")\n')
        (self.work / 'new.txt').write_text('x')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'local')
        (self.work / 'dirty.txt').write_text('x')
        result = self.end()
        self.assertEqual(1, result.returncode)
        self.assertIn('FAIL  stale overview', result.stdout)
        self.assertIn('stale index', result.stdout)
        self.assertIn('FAIL  uncommitted or untracked files', result.stdout)
        self.assertIn('FAIL  1 commit(s) not pushed to origin/main', result.stdout)

    def test_no_upstream_fails_and_docs_touched_are_reported(self):
        self.git('switch', '-q', '-c', 'feature')
        (self.work / 'docs/decisions').mkdir(parents=True)
        (self.work / 'docs/decisions/DEC-001.md').write_text('x')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'decision')
        self.conf.write_text('CLOSEOUT_DOC_PATHS=("docs/decisions/|decision records" "design/register/|design register")\n')
        result = self.end()
        self.assertEqual(1, result.returncode)
        self.assertIn('FAIL  no upstream', result.stdout)
        self.assertIn('yes   decision records', result.stdout)
        self.assertIn('no    design register', result.stdout)

    def test_outside_a_work_tree_exits_2(self):
        with tempfile.TemporaryDirectory() as outside:
            result = subprocess.run(['bash', str(SESSION_END), '--offline'], cwd=outside, capture_output=True, text=True,
                                    env={**os.environ, 'CLOSEOUT_CONF': str(self.conf), 'GIT_CEILING_DIRECTORIES': str(Path(outside).parent)})
            self.assertEqual(2, result.returncode)

    def test_project_status_short_prints_newest_handoff(self):
        (self.work / 'docs/handoffs').mkdir(parents=True)
        (self.work / 'docs/handoffs/2026-01-01-issue-1.md').write_text('old handoff')
        (self.work / 'docs/handoffs/2026-02-01-issue-2.md').write_text('newest handoff')
        result = subprocess.run(['bash', str(STATUS), '--short'], cwd=self.work, env={**os.environ, 'CLOSEOUT_CONF': str(self.conf)}, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('Branch: main', result.stdout)
        self.assertIn('newest handoff', result.stdout)
        self.assertNotIn('old handoff', result.stdout)


class LogStepTest(unittest.TestCase):
    def test_inserts_numbered_step_before_next_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log.md'
            log.write_text('# Log\n\n## Step 1: First\n\n- done\n\n## Step 2: Second\n\n- done\n\n## Next steps\n\n- more\n')
            body = Path(tmp) / 'body.md'
            body.write_text('- bullet\n**Lesson:** learn\n')
            result = subprocess.run(['bash', str(LOG_STEP), 'Third thing', str(body)], env={**os.environ, 'LOG_FILE': str(log)}, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('added Step 3', result.stdout)
            text = log.read_text()
            self.assertLess(text.index('## Step 3: Third thing'), text.index('## Next steps'))
            self.assertIn('**Lesson:** learn', text)

    def test_requires_next_steps_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log.md'
            log.write_text('# Log\n')
            body = Path(tmp) / 'body.md'
            body.write_text('x')
            result = subprocess.run(['bash', str(LOG_STEP), 'T', str(body)], env={**os.environ, 'LOG_FILE': str(log)}, capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertIn("no '## Next steps' heading", result.stderr)


class ContainerTest(unittest.TestCase):
    def test_dry_run_prints_mounts_identity_and_image_without_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            env = {**os.environ, 'CONTAINER_IMAGE': 'dev-image', 'CONTAINER_DRY_RUN': '1', 'CONTAINER_EXTRA_ARGS': '-p 127.0.0.1:9000:9000'}
            result = subprocess.run(['bash', str(CONTAINER), 'npm', 'test'], cwd=tmp, env=env, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            out = result.stdout
            self.assertIn('docker run --rm -u', out)
            self.assertIn('/workspace', out)
            self.assertIn('dev-image', out)
            self.assertIn('127.0.0.1:9000:9000', out)
            self.assertRegex(out, r'npm test\s*$')

    def test_requires_image_and_command(self):
        env = {k: v for k, v in os.environ.items() if k != 'CONTAINER_IMAGE'}
        self.assertNotEqual(0, subprocess.run(['bash', str(CONTAINER), 'ls'], env=env, capture_output=True).returncode)
        self.assertNotEqual(0, subprocess.run(['bash', str(CONTAINER)], env={**env, 'CONTAINER_IMAGE': 'x'}, capture_output=True).returncode)


class ClosingKeywordTest(unittest.TestCase):
    def pattern(self):
        return re.search(r"pattern='([^']+)'", WORKFLOW.read_text()).group(1)

    def matches(self, text):
        return subprocess.run(['grep', '-Eiq', self.pattern()], input=text, text=True).returncode == 0

    def test_closing_keywords_are_caught(self):
        for text in ('Closes #12', 'fixes #3', 'Resolved: #9', 'this FIXED owner/repo#44', 'close #1'):
            self.assertTrue(self.matches(text), text)

    def test_refs_and_other_words_pass(self):
        for text in ('Refs #12', 'Related to #12', 'closest to #5', 'prefix #7', 'fixture #8'):
            self.assertFalse(self.matches(text), text)


if __name__ == '__main__':
    unittest.main()

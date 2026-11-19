import os
import sys
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools', 'service-readers'))
import ci_status  # noqa: E402

def setUpModule():
    global fixture_env
    fixture_env = mock.patch.dict(os.environ, {'JENKINS_URL': 'https://ci.example.test/jenkins'})
    fixture_env.start()

def tearDownModule():
    fixture_env.stop()

LOG = """Waiting for next available executor on ‘Fixture’
Running on Fixture in /workspace
[Pipeline] { (Setup)
[Pipeline] // stage
[Pipeline] { (Static Analysis & Tests)
[Pipeline] { (Branch: Unit Tests)
[Pipeline] { (Branch: Frontend Tests)
[Pipeline] { (Unit Tests)
[Pipeline] { (Frontend Tests)
[Pipeline] // stage
Stage "Heavy" skipped due to when conditional
"""


class ParseStagesTest(unittest.TestCase):
    def test_sequential_and_parallel_stages(self):
        stages, skipped, waiting = ci_status.parse_stages(LOG)
        self.assertEqual(
            [(s['name'], s['state'], s['depth']) for s in stages],
            [('Setup', 'done', 0), ('Static Analysis & Tests', 'running', 0),
             ('Unit Tests', 'done', 1), ('Frontend Tests', 'running', 1)],
        )
        self.assertEqual(skipped, ['Heavy'])
        self.assertFalse(waiting)

    def test_waiting_for_executor(self):
        _, _, waiting = ci_status.parse_stages("Waiting for next available executor on ‘Fixture’\n")
        self.assertTrue(waiting)

    def test_strips_ansi(self):
        stages, _, _ = ci_status.parse_stages("\x1b[0m[Pipeline] { (Setup)\x1b[0m\n")
        self.assertEqual(stages[0]['name'], 'Setup')


class ClassifyTest(unittest.TestCase):
    def test_states(self):
        self.assertEqual(ci_status.classify('pending', None), 'running')
        self.assertEqual(ci_status.classify('error', None), 'failed')
        self.assertEqual(ci_status.classify('pending', {'building': True, 'result': None}), 'running')
        self.assertEqual(ci_status.classify('success', {'building': False, 'result': 'SUCCESS'}), 'green')
        self.assertEqual(ci_status.classify('failure', {'building': False, 'result': 'UNSTABLE'}), 'failed')


class ParseBuildTest(unittest.TestCase):
    def test_queued_build_without_timestamp_is_not_started(self):
        self.assertIsNone(ci_status.parse_build('{"_class": "WorkflowRun"}'))
        self.assertIsNone(ci_status.parse_build(''))

    def test_started_build_is_returned(self):
        build = ci_status.parse_build('{"number": 1, "timestamp": 5, "building": true, "result": null}')
        self.assertEqual(1, build['number'])


class FormatTest(unittest.TestCase):
    def test_format_age(self):
        self.assertEqual(ci_status.format_age(5), '5s')
        self.assertEqual(ci_status.format_age(125), '2m05s')
        self.assertEqual(ci_status.format_age(3700), '1h01m')

    def test_render_marks_parallel(self):
        stages, skipped, _ = ci_status.parse_stages(LOG)
        text = '\n'.join(ci_status.render_stages(stages, skipped))
        self.assertIn('    ✓ Unit Tests', text)
        self.assertIn('parallel ones close unnamed', text)
        self.assertIn('skipped by the Jenkinsfile: Heavy', text)


class ParseWfapiTest(unittest.TestCase):
    def test_maps_statuses(self):
        raw = ('{"stages": [{"name": "Setup", "status": "SUCCESS"}, {"name": "Tests", "status": "IN_PROGRESS"},'
               ' {"name": "Lint", "status": "FAILED"}, {"name": "Heavy", "status": "NOT_EXECUTED"}]}')
        stages, skipped = ci_status.parse_wfapi(raw)
        self.assertEqual([(s['name'], s['state']) for s in stages], [('Setup', 'done'), ('Tests', 'running'), ('Lint', 'failed')])
        self.assertEqual(skipped, ['Heavy'])
        self.assertIn('✗ Lint', '\n'.join(ci_status.render_stages(stages, skipped)))

    def test_unusable_responses_fall_back(self):
        for raw in (None, '', 'not json', '[]', '{"status": "SUCCESS"}', '{"stages": [{"status": "SUCCESS"}]}'):
            self.assertIsNone(ci_status.parse_wfapi(raw), raw)


SHA = 'a' * 40
URL = 'https://ci.example.test/jenkins/job/example-pr/job/PR-5/7'
BUILD = {'number': 7, 'timestamp': 1, 'building': False, 'result': 'SUCCESS',
         'actions': [{'lastBuiltRevision': {'SHA1': SHA}}]}
FLOW = {'id': '7', 'status': 'SUCCESS', 'stages': [{'name': 'Tests', 'status': 'SUCCESS'}]}
STATUS = {'context': ci_status.JENKINS_CONTEXT, 'state': 'success', 'target_url': URL}


class EvidenceTest(unittest.TestCase):
    def snapshot(self, statuses=None, build=None, flow=None):
        import json
        with mock.patch.object(ci_status, 'gh_json', return_value=statuses or [STATUS]), \
                mock.patch.object(ci_status, 'jenkins_get', side_effect=[json.dumps(build or BUILD), json.dumps(flow or FLOW)]):
            result = ci_status.fetch_state('o/r', SHA)
            ci_status.read_stages(result)
        return result

    def test_complete_green_requires_matching_revision_and_stages(self):
        result = self.snapshot()
        self.assertEqual('green', result['outcome'])
        self.assertTrue(result['report_complete'])
        self.assertEqual(SHA, result['build_sha'])

    def test_conflicting_github_status_cannot_be_green(self):
        for state, expected in [('failure', 'failed'), ('pending', 'incomplete')]:
            result = self.snapshot([STATUS, {'context': 'other', 'state': state}])
            self.assertEqual(expected, result['outcome'])

    def test_mismatched_or_missing_revision_is_incomplete(self):
        for actions in ([], [{'lastBuiltRevision': {'SHA1': 'b' * 40}}]):
            result = self.snapshot(build={**BUILD, 'actions': actions})
            self.assertEqual('incomplete', result['outcome'])
            self.assertFalse(result['report_complete'])

    def test_stage_state_contradictions_are_incomplete(self):
        for flow in ({**FLOW, 'status': 'IN_PROGRESS'},
                     {**FLOW, 'stages': [{'name': 'Tests', 'status': 'FAILED'}]},
                     {**FLOW, 'stages': [{'name': 'Tests', 'status': 'NOT_EXECUTED'}]},
                     {**FLOW, 'stages': FLOW['stages'] * 2}):
            result = self.snapshot(flow=flow)
            self.assertEqual('incomplete', result['outcome'])
            self.assertFalse(result['report_complete'])

    def test_stage_build_identity_mismatch_uses_partial_fallback(self):
        import json
        with mock.patch.object(ci_status, 'gh_json', return_value=[STATUS]), \
                mock.patch.object(ci_status, 'jenkins_get', side_effect=[json.dumps(BUILD), json.dumps({**FLOW, 'id': '8'}), LOG]):
            result = ci_status.fetch_state('o/r', SHA)
            ci_status.read_stages(result)
        self.assertEqual('incomplete', result['outcome'])
        self.assertFalse(result['report_complete'])

    def test_context_on_second_page_and_latest_context_wins(self):
        first = [{'context': f'other-{i}', 'state': 'success'} for i in range(100)]
        with mock.patch.object(ci_status, 'gh_json', side_effect=[first, [STATUS, {**STATUS, 'state': 'failure'}]]) as gh:
            status, state = ci_status.status_pages('o/r', SHA)
        self.assertEqual(STATUS, status)
        self.assertEqual('success', state)
        self.assertEqual(2, gh.call_count)
        self.assertIn('page=2', gh.call_args.args[-1])

    def test_repeated_page_and_page_limit_fail_incomplete(self):
        first = [{'context': f'x-{i}', 'state': 'success'} for i in range(100)]
        with mock.patch.object(ci_status, 'gh_json', return_value=first) as gh:
            with self.assertRaisesRegex(ci_status.ReaderError, 'Repeated'):
                ci_status.status_pages('o/r', SHA)
        self.assertEqual(2, gh.call_count)
        with mock.patch.object(ci_status, 'MAX_PAGES', 1), mock.patch.object(ci_status, 'gh_json', return_value=first):
            with self.assertRaisesRegex(ci_status.ReaderError, 'page limit'):
                ci_status.status_pages('o/r', SHA)

    def test_missing_wfapi_fetches_bounded_log_and_stays_incomplete(self):
        import json
        with mock.patch.object(ci_status, 'gh_json', return_value=[STATUS]), \
                mock.patch.object(ci_status, 'jenkins_get', side_effect=[json.dumps(BUILD), None, LOG]) as get:
            result = ci_status.fetch_state('o/r', SHA)
            ci_status.read_stages(result)
        self.assertEqual('incomplete', result['outcome'])
        self.assertFalse(result['stages_complete'])
        self.assertIn('progressiveText', get.call_args.args[0])
        self.assertEqual(ci_status.MAX_LOG, get.call_args.kwargs['limit'])
        self.assertNotIn('log', result)

    def test_wfapi_success_does_not_fetch_any_log(self):
        import json
        with mock.patch.object(ci_status, 'gh_json', return_value=[STATUS]), \
                mock.patch.object(ci_status, 'jenkins_get', side_effect=[json.dumps(BUILD), json.dumps(FLOW)]) as get:
            result = ci_status.fetch_state('o/r', SHA)
            ci_status.read_stages(result)
        self.assertEqual(2, get.call_count)
        self.assertFalse(any('console' in call.args[0] or 'progressiveText' in call.args[0] for call in get.call_args_list))

    def test_untrusted_build_url_never_receives_credentials(self):
        for url in ('https://evil.example/job/a/1', URL + '?secret=x', URL.replace('https:', 'http:')):
            with mock.patch.object(ci_status, 'gh_json', return_value=[{**STATUS, 'target_url': url}]), \
                    mock.patch.object(ci_status, 'jenkins_get') as get:
                with self.assertRaises(ci_status.ReaderError):
                    ci_status.fetch_state('o/r', SHA)
            get.assert_not_called()


class NotStartedBuildTest(unittest.TestCase):
    BASE = 'https://ci.example.test/jenkins'

    def fetch(self, url, state='pending'):
        with mock.patch.object(ci_status, 'gh_json', return_value=[{**STATUS, 'state': state, 'target_url': url}]), \
                mock.patch.object(ci_status, 'jenkins_get') as get:
            try:
                return ci_status.fetch_state('o/r', SHA), get
            finally:
                get.assert_not_called()

    def test_pending_without_build_number_is_missing_not_an_error(self):
        for url in (None, '', self.BASE + '/job/example-pr/job/PR-5/', self.BASE + '/job/example-pr/job/PR-5',
                    self.BASE + '/queue/item/12/'):
            result, _ = self.fetch(url)
            self.assertEqual('missing', result['outcome'], url)
            self.assertFalse(result['report_complete'])
            ci_status.read_stages(result)  # no build: must not call Jenkins

    def test_finished_status_without_build_number_stays_a_stable_error(self):
        for state in ('success', 'failure', 'error'):
            with self.assertRaises(ci_status.ReaderError) as caught:
                self.fetch(self.BASE + '/job/example-pr/job/PR-5/', state)
            self.assertTrue(caught.exception.stable)

    def test_untrusted_pending_url_stays_a_stable_error(self):
        for url in ('https://evil.example/job/a/', self.BASE + '/job/a/?x=1', (self.BASE + '/job/a/').replace('https:', 'http:'),
                    'https://u@ci.example.test/jenkins/job/a/', 'https://ci.example.test/other/job/a/'):
            with self.assertRaises(ci_status.ReaderError, msg=url):
                self.fetch(url)


class WaitForBuildTest(unittest.TestCase):
    def run_wait(self, outcomes, heads=None, timeout=9000, errors=None):
        now, sleeps = [0], []
        results = [{'outcome': o, 'head_sha': SHA, 'report_complete': o == 'green', 'reasons': []} for o in outcomes]

        def sleep(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        with mock.patch.object(ci_status, 'fetch_state', side_effect=errors or results) as fetch, \
                mock.patch.object(ci_status, 'read_stages'), \
                mock.patch.object(ci_status, 'head_unchanged', side_effect=heads or [True] * 20), \
                redirect_stdout(io.StringIO()), mock.patch('sys.stderr', new=io.StringIO()) as err:
            result = ci_status.wait_for_build('o/r', 5, SHA, timeout, sleep=sleep, clock=lambda: now[0])
        return result, sleeps, fetch.call_count, err.getvalue()

    def test_polls_running_then_reuses_final_snapshot(self):
        result, sleeps, calls, _ = self.run_wait(['running', 'running', 'green'])
        self.assertEqual('green', result['outcome'])
        self.assertEqual([60, 60], sleeps)
        self.assertEqual(3, calls)

    def test_not_started_polls_until_the_build_appears(self):
        result, sleeps, calls, _ = self.run_wait(['missing', 'missing', 'running', 'green'])
        self.assertEqual('green', result['outcome'])
        self.assertEqual([60, 60, 60], sleeps)
        self.assertEqual(4, calls)

    def test_failed_build_stops(self):
        self.assertEqual('failed', self.run_wait(['running', 'failed'])[0]['outcome'])

    def test_missing_grace_then_stops(self):
        result, sleeps, _, _ = self.run_wait(['missing'] * 10)
        self.assertEqual('missing', result['outcome'])
        self.assertEqual([60, 60, 60], sleeps)

    def test_head_move_immediately_before_success_blocks_green(self):
        result, sleeps, _, _ = self.run_wait(['green'], heads=[False])
        self.assertEqual('moved', result['outcome'])
        self.assertFalse(result['report_complete'])
        self.assertEqual([], sleeps)

    def test_timeout_cannot_trigger_final_refetch(self):
        result, sleeps, calls, _ = self.run_wait(['running'] * 10, timeout=150)
        self.assertEqual('running', result['outcome'])
        self.assertFalse(result['report_complete'])
        self.assertEqual([60, 60], sleeps)
        self.assertEqual(3, calls)

    def test_stable_auth_error_stops_once(self):
        result, sleeps, calls, _ = self.run_wait([], errors=ci_status.ReaderError('Jenkins HTTP 401', stable=True))
        self.assertEqual('error', result['outcome'])
        self.assertEqual([], sleeps)
        self.assertEqual(1, calls)

    def test_transient_errors_retry_but_not_forever(self):
        result, sleeps, calls, err = self.run_wait([], errors=ci_status.ReaderError('Jenkins HTTP 530', retryable=True))
        self.assertEqual('incomplete', result['outcome'])
        self.assertEqual(ci_status.MAX_POLL_FAILURES, calls)
        self.assertEqual(ci_status.MAX_POLL_FAILURES - 1, len(sleeps))
        self.assertEqual(ci_status.MAX_POLL_FAILURES - 1, err.count('poll failed'))


class TransportTest(unittest.TestCase):
    def test_auth_and_redirect_are_not_softened_or_retried(self):
        import urllib.error
        env = dict.fromkeys(('JENKINS_USER', 'JENKINS_TOKEN', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET'), 'SECRET')
        for code in (301, 302, 401, 403):
            opener = mock.Mock()
            opener.open.side_effect = urllib.error.HTTPError(URL, code, 'SECRET', {}, None)
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(ci_status.urllib.request, 'build_opener', return_value=opener):
                with self.assertRaises(ci_status.ReaderError) as error:
                    ci_status.jenkins_get(URL, soft=True)
            self.assertTrue(error.exception.stable)
            self.assertNotIn('SECRET', str(error.exception))
            self.assertEqual(1, opener.open.call_count)

    def test_truncated_http_response_has_safe_retryable_error(self):
        env = dict.fromkeys(('JENKINS_USER', 'JENKINS_TOKEN', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET'), 'x')
        opener = mock.Mock()
        opener.open.side_effect = ci_status.http.client.BadStatusLine('SECRET')
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ci_status.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(ci_status.ReaderError) as error:
                ci_status.jenkins_get(URL)
        self.assertTrue(error.exception.retryable)
        self.assertNotIn('SECRET', str(error.exception))

    def test_gh_auth_error_has_bounded_safe_message(self):
        error = ci_status.subprocess.CalledProcessError(1, 'gh', stderr='HTTP 401 SECRET' * 1000)
        with mock.patch.object(ci_status.subprocess, 'check_output', side_effect=error):
            with self.assertRaises(ci_status.ReaderError) as caught:
                ci_status.gh_json('api', 'x')
        self.assertTrue(caught.exception.stable)
        self.assertLess(len(str(caught.exception)), 100)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_request_budget_shrinks_and_exhaustion_blocks_calls(self):
        now = [0]
        token = ci_status.BUDGET.set(ci_status.Deadline(5, clock=lambda: now[0]))
        try:
            with mock.patch.object(ci_status.subprocess, 'check_output', return_value='{}') as call:
                ci_status.gh_json('api', 'x')
                self.assertEqual(5, call.call_args.kwargs['timeout'])
                now[0] = 5
                with self.assertRaises(ci_status.ReaderError):
                    ci_status.gh_json('api', 'x')
                self.assertEqual(1, call.call_count)
        finally:
            ci_status.BUDGET.reset(token)

    def test_configuration_resolution_uses_remaining_budget(self):
        with mock.patch.object(ci_status.toolchain_config, 'get', side_effect=ci_status.subprocess.TimeoutExpired('git', 3)) as get, \
                mock.patch.object(ci_status, 'remaining', return_value=3):
            with self.assertRaisesRegex(ci_status.ReaderError, 'lookup timed out'):
                ci_status.config_value('GITHUB_REPO')
        self.assertEqual(3, get.call_args.kwargs['timeout'])

    def test_log_limit_clips_without_exposing_raw_data(self):
        env = dict.fromkeys(('JENKINS_USER', 'JENKINS_TOKEN', 'CF_ACCESS_CLIENT_ID', 'CF_ACCESS_CLIENT_SECRET'), 'x')
        opener, response = mock.Mock(), mock.MagicMock()
        opener.open.return_value = response
        response.__enter__.return_value.read1.return_value = b'SECRET'
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(ci_status.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual('SECR', ci_status.jenkins_get(URL, accept='text/plain', limit=4))
            with self.assertRaisesRegex(ci_status.ReaderError, 'byte limit'):
                ci_status.jenkins_get(URL, limit=4)
        self.assertEqual(2, response.__enter__.return_value.read1.call_count)


class ReportContractTest(unittest.TestCase):
    def test_failed_sibling_makes_green_report_incomplete(self):
        snapshot = {'outcome': 'green', 'head_sha': SHA, 'report_complete': True, 'reasons': []}
        out = io.StringIO()
        with mock.patch.object(ci_status.toolchain_config, 'get', return_value='o/r'), \
                mock.patch.object(ci_status, 'resolve_pull_request', return_value=(5, SHA, 'branch')), \
                mock.patch.object(ci_status, 'wait_for_build', return_value=snapshot), \
                mock.patch.object(ci_status, 'run_sibling', side_effect=[1, 0]) as sibling, \
                redirect_stdout(out):
            self.assertEqual(5, ci_status.main(['5', '--all', '--json']))
        import json
        result = json.loads(out.getvalue())
        self.assertEqual('incomplete', result['outcome'])
        self.assertFalse(result['report_complete'])
        self.assertEqual(2, sibling.call_count)

    def test_sibling_timeout_and_output_are_bounded(self):
        with mock.patch.object(ci_status.subprocess, 'run', side_effect=ci_status.subprocess.TimeoutExpired('x', 30)) as run:
            self.assertEqual(-1, ci_status.run_sibling('sonar_status.py', '5'))
        self.assertEqual(30, run.call_args.kwargs['timeout'])
        self.assertEqual(ci_status.subprocess.DEVNULL, run.call_args.kwargs['stdout'])

    def test_final_head_move_is_explicit(self):
        with mock.patch.object(ci_status.toolchain_config, 'get', return_value='o/r'), \
                mock.patch.object(ci_status, 'resolve_pull_request', side_effect=[(5, SHA, 'branch'), (5, 'b' * 40, 'branch')]), \
                mock.patch.object(ci_status, 'wait_for_build', return_value={'outcome': 'green', 'report_complete': True, 'reasons': []}), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(4, ci_status.main(['5', '--json']))
        self.assertIn('"outcome": "moved"', out.getvalue())

    def test_public_json_never_contains_raw_build_or_description(self):
        snapshot = {'outcome': 'green', 'report_complete': True, 'reasons': [],
                    'build': {'SECRET': 'SECRET'}, 'description': 'SECRET'}
        with redirect_stdout(io.StringIO()) as out:
            ci_status.publish(snapshot, True)
        self.assertNotIn('SECRET', out.getvalue())


if __name__ == '__main__':
    unittest.main()

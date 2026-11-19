"""Compact, read-only PR CI evidence; not a merge authorization gate.

Usage: ci_status.py [PR | branch] [--wait] [--timeout=MIN] [--all] [--json]

Exit: 0 complete green, 1 failed, 2 running/deadline while waiting, 3 missing,
4 moved head, 5 incomplete evidence/report, 6 stable auth/configuration error.
--timeout (default 150 minutes waiting, 2 minutes otherwise) covers resolution,
polling, final evidence and extras. Each request/subprocess is capped at 30 seconds.
Socket operations may consume their current request bound after the deadline.
--log-lines is retained for compatibility; raw console output is never published.
JENKINS_URL optionally selects the trusted Jenkins base (required, no organization default).
"""
import argparse
import base64
import contextvars
import json
import http.client
import math
import os
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import time
import urllib.error
import urllib.parse
import urllib.request

import toolchain_config

USER_AGENT = 'project-agent-toolkit/1.0'
JENKINS_CONTEXT = toolchain_config.get('JENKINS_CONTEXT', 'continuous-integration/jenkins/pr-head')
DEFAULT_LOG_LINES = 25
STAGE_OPEN = re.compile(r'^\[Pipeline\] \{ \((.+)\)$')
STAGE_CLOSE = '[Pipeline] // stage'
SKIPPED = re.compile(r'^Stage "(.+)" skipped due to')
ANSI = re.compile(r'\x1b\[[0-9;]*m')
EXIT_CODES = {'green': 0, 'failed': 1, 'running': 2, 'missing': 3, 'moved': 4,
              'incomplete': 5, 'error': 6}
POLL_SECONDS = 60
MISSING_GRACE_SECONDS = 180
DEFAULT_TIMEOUT_MINUTES = 150
MAX_POLL_FAILURES = 5
MAX_PAGES = 100
MAX_BODY = 4 * 1024 * 1024
MAX_LOG = 64 * 1024
WFAPI_STATES = {'SUCCESS': 'done', 'IN_PROGRESS': 'running', 'PAUSED_PENDING_INPUT': 'running',
                'FAILED': 'failed', 'UNSTABLE': 'failed', 'ABORTED': 'failed'}
BUDGET = contextvars.ContextVar('ci_budget', default=None)


class ReaderError(Exception):
    def __init__(self, message, retryable=False, stable=False):
        super().__init__(message)
        self.retryable = retryable
        self.stable = stable


class Deadline:
    def __init__(self, seconds, clock=time.monotonic):
        self.clock = clock
        self.end = clock() + seconds

    def remaining(self, cap=30):
        seconds = self.end - self.clock()
        if seconds <= 0:
            raise ReaderError('operation deadline exceeded')
        return min(seconds, cap)


def remaining():
    budget = BUDGET.get()
    return budget.remaining() if budget else 30


def config_value(key):
    try:
        value = toolchain_config.get(key, timeout=remaining())
        remaining()
        return value
    except subprocess.TimeoutExpired:
        raise ReaderError('Configuration lookup timed out') from None
    except OSError:
        raise ReaderError('Cannot read workflow configuration', stable=True) from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise ReaderError(f'Missing environment variable {name}', stable=True)
    return value


def jenkins_get(url, accept='application/json', soft=False, limit=MAX_BODY):
    """Bound response size; only missing optional endpoints are soft failures."""
    credentials = f"{require_env('JENKINS_USER')}:{require_env('JENKINS_TOKEN')}".encode()
    request = urllib.request.Request(url, headers={
        'Authorization': 'Basic ' + base64.b64encode(credentials).decode(),
        'CF-Access-Client-Id': os.environ.get('CF_ACCESS_CLIENT_ID', ''),
        'CF-Access-Client-Secret': os.environ.get('CF_ACCESS_CLIENT_SECRET', ''),
        'Accept': accept, 'User-Agent': USER_AGENT,
    })
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=remaining()) as response:
            chunks, size = [], 0
            while size <= limit:
                remaining()
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b''.join(chunks)
        remaining()
        if len(raw) > limit:
            if accept == 'text/plain':
                return raw[:limit].decode(errors='replace')
            raise ReaderError('Jenkins response exceeds byte limit')
        return raw.decode(errors='replace')
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        stable = error.code in (301, 302, 303, 307, 308, 400, 401, 403)
        raise ReaderError(f'Jenkins HTTP {error.code}; check access/configuration',
                          retryable=error.code == 429 or error.code >= 500, stable=stable) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        raise ReaderError('Jenkins request failed or timed out', retryable=True) from None


def gh_json(*args):
    try:
        output = subprocess.check_output(['gh', *args], text=True, stderr=subprocess.PIPE,
                                         timeout=remaining())
        remaining()
        return json.loads(output)
    except FileNotFoundError:
        raise ReaderError('GitHub CLI (gh) is required', stable=True) from None
    except subprocess.TimeoutExpired:
        raise ReaderError('GitHub request timed out', retryable=True) from None
    except subprocess.CalledProcessError as error:
        # Inspect only status codes; never publish arbitrary stderr or response bodies.
        codes = re.findall(r'HTTP ([0-9]{3})', error.stderr or '')
        code = int(codes[-1]) if codes else None
        transient = any(text in (error.stderr or '').lower() for text in
                        ('error connecting', 'connection reset', 'connection refused', 'tls handshake timeout'))
        raise ReaderError(f'GitHub request failed (HTTP {code or "unknown"})',
                          retryable=transient or code == 429 or (code is not None and code >= 500),
                          stable=code in (400, 401, 403, 404, 422) or (code is None and not transient)) from None
    except ValueError:
        raise ReaderError('GitHub returned invalid JSON') from None


def resolve_pull_request(repo, target):
    if not target:
        try:
            target = subprocess.check_output(['git', 'branch', '--show-current'], text=True,
                                             timeout=remaining()).strip()
        except (OSError, subprocess.SubprocessError):
            raise ReaderError('Cannot resolve current branch; pass PR number', stable=True) from None
    if target.isdigit():
        pr = gh_json('api', f'repos/{repo}/pulls/{target}')
    else:
        query = urllib.parse.urlencode({'head': f'{repo.split("/")[0]}:{target}', 'state': 'open'})
        pulls = gh_json('api', f'repos/{repo}/pulls?{query}')
        if not isinstance(pulls, list) or len(pulls) != 1:
            raise ReaderError('Expected exactly one open PR for branch', stable=True)
        pr = pulls[0]
    try:
        number, sha, branch = pr['number'], pr['head']['sha'], pr['head']['ref']
        if not isinstance(number, int) or not re.fullmatch(r'[0-9a-f]{40}', sha) or not branch:
            raise ValueError
        return number, sha, branch
    except (KeyError, TypeError, ValueError):
        raise ReaderError('Invalid PR identity') from None


def parse_stages(log):
    """Walk the console log; return (stages, skipped, waiting_for_executor).

    stages is a list of dicts {name, state, depth}; state is done or running. Stages that
    open right after a "Branch:" line run in parallel (depth 1); their close marker is
    unnamed, so the first one still open is marked done (the count is right, the name is not).
    """
    sequential = []
    parallel = []
    group = False
    stages = []
    skipped = []
    waiting = False
    for raw in log.splitlines():
        line = ANSI.sub('', raw).rstrip()
        if 'Waiting for next available executor' in line:
            waiting = True
        elif line.startswith('Running on '):
            waiting = False
        opened = STAGE_OPEN.match(line)
        skip = SKIPPED.match(line)
        if skip:
            skipped.append(skip.group(1))
        elif opened and opened.group(1).startswith('Branch: '):
            group = True
        elif opened:
            stage = {'name': opened.group(1), 'state': 'running', 'depth': len(sequential)}
            (parallel if group else sequential).append(stage)
            stages.append(stage)
        elif line == STAGE_CLOSE:
            closing = parallel[0] if parallel else (sequential[-1] if sequential else None)
            if closing is not None:
                closing['state'] = 'done'
                (parallel if parallel else sequential).remove(closing)
                group = group and bool(parallel)
    return stages, skipped, waiting


def parse_wfapi(raw):
    """Stages from <build>/wfapi/describe as (stages, skipped), or None when the response is unusable.

    Parallel branches come back as ordinary entries of the same list, so they are all depth 0.
    """
    try:
        described = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(described, dict) or not isinstance(described.get('stages'), list):
        return None
    stages = []
    skipped = []
    for entry in described['stages']:
        if not isinstance(entry, dict) or not entry.get('name'):
            return None
        if entry.get('status') == 'NOT_EXECUTED':
            skipped.append(entry['name'])
        else:
            stages.append({'name': entry['name'], 'state': WFAPI_STATES.get(entry.get('status'), 'running'), 'depth': 0})
    return stages, skipped


def format_age(seconds):
    seconds = max(int(seconds), 0)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def parse_build(raw):
    """Return the build JSON, or None while Jenkins has not started it (queued: the JSON lacks timestamp and number)."""
    build = json.loads(raw) if raw else None
    return build if build and 'timestamp' in build and 'number' in build else None


def classify(github_state, build):
    """Classify observed build state; evidence completeness is checked separately."""
    if github_state in ('failure', 'error'):
        return 'failed'
    if build is None:
        return 'running' if github_state == 'pending' else 'missing'
    if build.get('building') or build.get('result') is None:
        return 'running'
    if build['result'] != 'SUCCESS':
        return 'failed'
    return 'green' if github_state == 'success' else 'incomplete'


def render_stages(stages, skipped):
    lines = []
    parallel = len([s for s in stages if s['depth'] > 0]) > 1
    for stage in stages:
        mark = {'done': '✓', 'failed': '✗'}.get(stage['state'], '…')
        lines.append(f"  {'  ' * stage['depth']}{mark} {stage['name']}")
    if parallel:
        lines.append("  (indented = nested stages; parallel ones close unnamed, so which finished first is not in the log)")
    if skipped:
        lines.append(f"  skipped by the Jenkinsfile: {', '.join(skipped)}")
    return lines


def status_pages(repo, sha):
    """Page all decision data, retaining the newest status for every context."""
    latest, fingerprints = {}, set()
    for page in range(1, MAX_PAGES + 1):
        statuses = gh_json('api', f'repos/{repo}/commits/{sha}/statuses?per_page=100&page={page}')
        if not isinstance(statuses, list) or any(not isinstance(s, dict) for s in statuses):
            raise ReaderError('Invalid GitHub status page')
        fingerprint = json.dumps(statuses, sort_keys=True)
        if statuses and fingerprint in fingerprints:
            raise ReaderError('Repeated GitHub status page')
        fingerprints.add(fingerprint)
        for status in statuses:
            context, state = status.get('context'), status.get('state')
            if not isinstance(context, str) or not context or state not in ('success', 'pending', 'failure', 'error'):
                raise ReaderError('Invalid GitHub status fields')
            latest.setdefault(context, status)
        if len(statuses) < 100:
            states = [s['state'] for s in latest.values()]
            state = ('failure' if any(s in ('failure', 'error') for s in states) else
                     'pending' if 'pending' in states else 'success' if states else None)
            return latest.get(JENKINS_CONTEXT), state
    raise ReaderError('GitHub status page limit exceeded')


def not_started_url(url, base):
    """A job or queue link on the trusted Jenkins host without a build number (https, no userinfo/query/fragment)."""
    parts, trusted = urllib.parse.urlsplit(url), urllib.parse.urlsplit(base)
    return (parts.scheme == 'https' and parts.netloc == trusted.netloc and not parts.username
            and not parts.query and not parts.fragment
            and (parts.path.rstrip('/') + '/').startswith(trusted.path.rstrip('/') + '/'))


def trusted_build_url(url, pending=False):
    """Return (build_url, number); None while a pending status has no numbered build yet (empty or job/queue link under the trusted base)."""
    base = os.environ.get('JENKINS_URL') or config_value('JENKINS_URL') or ''
    # Validate before sending Jenkins/Cloudflare credentials to a status-supplied URL.
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
        raise ReaderError('Invalid trusted JENKINS_URL', stable=True)
    pattern = re.escape(base.rstrip('/')) + r'/(?:job/[A-Za-z0-9_.%~-]+/)+([1-9][0-9]*)(?:/display/redirect)?/?'
    match = re.fullmatch(pattern, url or '')
    if match is None:
        if pending and (not url or not_started_url(url, base)):
            return None
        raise ReaderError('Unexpected Jenkins build URL', stable=True)
    return re.sub(r'/display/redirect/?$', '', url).rstrip('/'), int(match[1])


def fetch_state(repo, sha):
    jenkins, github_state = status_pages(repo, sha)
    if jenkins is None:
        return {'outcome': 'missing', 'github_state': github_state, 'build': None,
                'build_url': None, 'build_sha': None, 'head_sha': sha, 'stages': [],
                'skipped': [], 'stages_complete': False, 'report_complete': False,
                'reasons': ['No Jenkins context on captured head']}
    trusted = trusted_build_url(jenkins.get('target_url'), pending=jenkins.get('state') == 'pending')
    if trusted is None:
        return {'outcome': 'missing', 'github_state': github_state, 'jenkins_state': 'pending', 'build': None,
                'build_url': None, 'build_sha': None, 'head_sha': sha, 'stages': [],
                'skipped': [], 'stages_complete': False, 'report_complete': False,
                'reasons': ['Jenkins build not started yet (status has no build URL)']}
    build_url, number = trusted
    raw = jenkins_get(build_url + '/api/json?tree=building,result,timestamp,duration,estimatedDuration,number,actions[lastBuiltRevision[SHA1]]')
    try:
        build = parse_build(raw)
    except (ValueError, TypeError):
        raise ReaderError('Invalid Jenkins build JSON') from None
    result = {'outcome': classify(github_state, build), 'github_state': github_state,
              'jenkins_state': jenkins['state'], 'build': build, 'build_url': build_url,
              'head_sha': sha, 'build_sha': None, 'stages': [], 'skipped': [],
              'stages_complete': False, 'report_complete': False, 'reasons': []}
    if build is None:
        result['reasons'].append('Jenkins build not created yet')
        return result
    if build.get('number') != number or type(build.get('building')) is not bool:
        raise ReaderError('Jenkins build identity/state mismatch')
    actions = build.get('actions')
    revisions = [a['lastBuiltRevision'].get('SHA1') for a in actions
                 if isinstance(a, dict) and isinstance(a.get('lastBuiltRevision'), dict)] if isinstance(actions, list) else []
    if revisions and all(s == sha for s in revisions):
        result['build_sha'] = sha
    else:
        result['reasons'].append('Jenkins revision missing or mismatched')
    result['report_complete'] = result['build_sha'] == sha and result['outcome'] != 'incomplete'
    if result['outcome'] == 'incomplete':
        result['reasons'].append('Successful Jenkins build contradicts GitHub state')
    if result['outcome'] == 'green' and not result['report_complete']:
        result['outcome'] = 'incomplete'
    return result


def read_stages(snapshot):
    """wfapi is decision evidence; bounded log fallback is display-only."""
    build = snapshot['build']
    if build is None:
        return
    url = snapshot['build_url']
    raw = jenkins_get(url + '/wfapi/describe', soft=True)
    parsed = parse_wfapi(raw)
    try:
        flow = json.loads(raw) if raw else {}
    except ValueError:
        flow = {}
    valid = (parsed is not None and bool(flow.get('stages'))
             and str(flow.get('id')) == str(build['number'])
             and flow.get('status') in (*WFAPI_STATES, 'NOT_EXECUTED')
             and all(s.get('status') in (*WFAPI_STATES, 'NOT_EXECUTED') for s in flow['stages']))
    if valid:
        snapshot['stages'], snapshot['skipped'] = parsed
        snapshot['stages_complete'] = True
        if len({s['name'] for s in flow['stages']}) != len(flow['stages']):
            snapshot['stages_complete'] = False
            snapshot['reasons'].append('Duplicate stage names')
        if snapshot['outcome'] == 'green' and (not snapshot['stages'] or flow['status'] != 'SUCCESS' or
                any(s['state'] != 'done' for s in snapshot['stages'])):
            snapshot['outcome'] = 'incomplete'
            snapshot['report_complete'] = False
            snapshot['reasons'].append('Stage/build states contradict')
    else:
        log = jenkins_get(url + '/logText/progressiveText?start=0', accept='text/plain', limit=MAX_LOG)
        stages, skipped, waiting = parse_stages(log or '')
        snapshot.update(stages=stages, skipped=skipped, waiting=waiting,
                        log_display='bounded fallback; raw log withheld', stages_complete=False)
        snapshot['reasons'].append('Stage evidence unavailable; log fallback is partial display only')
    snapshot['report_complete'] = snapshot['report_complete'] and snapshot['stages_complete']
    if snapshot['outcome'] == 'green' and not snapshot['report_complete']:
        snapshot['outcome'] = 'incomplete'


def run_sibling(script, target):
    """Suppress unbounded/raw sibling output; failures must affect report completeness."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
    try:
        result = subprocess.run([sys.executable, path, target], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=remaining(), check=False)
        remaining()
        return result.returncode
    except (OSError, subprocess.TimeoutExpired):
        return -1


def head_unchanged(repo, number, sha):
    return resolve_pull_request(repo, str(number))[1] == sha


def wait_for_build(repo, number, sha, timeout_seconds, poll=POLL_SECONDS, grace=MISSING_GRACE_SECONDS,
                   sleep=time.sleep, clock=time.monotonic, wait=True):
    """Return the final snapshot; no second report fetch can replace the waited result."""
    started = clock()
    token = None
    if BUDGET.get() is None:
        token = BUDGET.set(Deadline(timeout_seconds, clock))
    failures = 0
    last = {'outcome': 'incomplete', 'head_sha': sha, 'report_complete': False, 'reasons': []}
    try:
        while True:
            try:
                remaining()
                current = fetch_state(repo, sha)
                read_stages(current)
                if not head_unchanged(repo, number, sha):
                    current.update(outcome='moved', report_complete=False)
                    current['reasons'].append('PR head moved; rerun for new head')
                    return current
                remaining()
                failures = 0
                last = current
                outcome = current['outcome']
            except ReaderError as error:
                failures += 1
                outcome = 'error' if error.stable else 'incomplete'
                last.update(outcome=outcome, report_complete=False, reasons=[str(error)])
                if not wait or not error.retryable or failures >= MAX_POLL_FAILURES:
                    return last
                print(f'poll failed ({failures}/{MAX_POLL_FAILURES}): {error}', file=sys.stderr, flush=True)
            elapsed = clock() - started
            if not wait or outcome in ('green', 'failed', 'incomplete', 'error') and failures == 0:
                return last
            if outcome == 'missing' and elapsed >= grace:
                return last
            if BUDGET.get().end - clock() <= poll:
                last.update(outcome='running', report_complete=False)
                last['reasons'].append('Operation budget exhausted before next poll')
                return last
            print(f'[{format_age(elapsed)}] {sha[:8]} {outcome}', file=sys.stderr, flush=True)
            sleep(poll)
    finally:
        if token is not None:
            BUDGET.reset(token)


def publish(result, as_json=False):
    # Never serialize raw build actions, GitHub descriptions or console text.
    allowed = ('outcome', 'head_sha', 'build_sha', 'build_url', 'github_state', 'jenkins_state',
               'report_complete', 'stages_complete', 'stages', 'skipped', 'reasons', 'extras', 'pr', 'branch')
    public = {k: result[k] for k in allowed if k in result}
    if as_json:
        print(json.dumps(public, sort_keys=True))
    else:
        print(f"{result['outcome'].upper()} PR #{result.get('pr', '?')} @ {result.get('head_sha', '?')}")
        print(f"  report_complete={result['report_complete']} stages_complete={result.get('stages_complete', False)}")
        if result.get('build_url'):
            print(f"  {result['build_url']}")
        print('\n'.join(render_stages(result.get('stages', []), result.get('skipped', []))))
        for reason in result['reasons']:
            print(f'  {reason}')
    return EXIT_CODES[result['outcome']]


def positive_minutes(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError('must be finite and > 0')
    return value


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', nargs='?')
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--timeout', type=positive_minutes)
    parser.add_argument('--log-lines', type=int, default=DEFAULT_LOG_LINES)
    args = parser.parse_args(argv)
    minutes = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT_MINUTES if args.wait else 2
    token = BUDGET.set(Deadline(minutes * 60))
    result = {'outcome': 'incomplete', 'report_complete': False, 'reasons': []}
    try:
        repo = config_value('GITHUB_REPO')
        if not repo:
            raise ReaderError('GITHUB_REPO is not set in .agent-toolkit/workflow.conf', stable=True)
        number, sha, branch = resolve_pull_request(repo, args.target)
        result.update(pr=number, head_sha=sha, branch=branch)
        result.update(wait_for_build(repo, number, sha, minutes * 60, wait=args.wait))
        if args.all and result['outcome'] in ('green', 'failed'):
            result['extras'] = {}
            for script, target in (('sonar_status.py', str(number)), ('dojo_findings.py', branch)):
                code = run_sibling(script, target)
                result['extras'][script] = code
                if code != 0:
                    result['report_complete'] = False
                    result['reasons'].append(f'{script} failed (exit {code}); consult service directly')
                    if result['outcome'] == 'green':
                        result['outcome'] = 'incomplete'
        if result['outcome'] in ('green', 'failed'):
            if not head_unchanged(repo, number, sha):
                result.update(outcome='moved', report_complete=False)
                result['reasons'].append('PR head moved during final report')
        remaining()
    except ReaderError as error:
        result.update(outcome='error' if error.stable else 'incomplete', report_complete=False)
        result['reasons'].append(str(error))
    except (ValueError, KeyError, TypeError, AttributeError):
        result.update(outcome='incomplete', report_complete=False)
        result['reasons'].append('Malformed decision evidence')
    finally:
        BUDGET.reset(token)
    return publish(result, args.json)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

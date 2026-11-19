"""Read a GitHub issue and explicitly referenced blockers; no board/status/comment writes."""
import argparse
import json
import re
import subprocess
import sys


def brief(repo, number):
    def get(n):
        raw = subprocess.check_output(['gh', 'issue', 'view', str(n), '--repo', repo,
                                       '--json', 'number,title,state,body,url'], timeout=30, stderr=subprocess.DEVNULL)
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('number') != int(n) or data.get('state') not in ('OPEN', 'CLOSED'):
            raise ValueError('invalid issue identity/state')
        return data
    issue = get(number)
    # Explicit marker avoids interpreting every casual #number as a dependency.
    blockers = list(dict.fromkeys(re.findall(r'(?im)^blocked by:\s*#([0-9]+)\s*$', issue.get('body') or '')))
    if len(blockers) > 20:
        raise ValueError('blocker limit exceeded')
    return {'issue': issue, 'blockers': [get(n) for n in blockers]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('number', type=int)
    ap.add_argument('--repo', required=True)
    a = ap.parse_args()
    try:
        if a.number <= 0 or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', a.repo):
            raise ValueError('invalid repository/issue')
        print(json.dumps(brief(a.repo, a.number)))
        return 0
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        print('Issue evidence unavailable; no tracker changes made', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

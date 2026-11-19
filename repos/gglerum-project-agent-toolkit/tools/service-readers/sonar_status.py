"""Compact read-only Sonar evidence. Exit 0=OK gate, 1=failed gate, 5=unavailable."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_reader import Reader, Unavailable
import toolchain_config as config


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('target')
    ap.add_argument('--timeout', type=float, default=120)
    a = ap.parse_args(argv)
    try:
        token, base, project = (config.get(k) for k in ('SONAR_TOKEN', 'SONAR_URL', 'SONAR_PROJECT_KEY'))
        if not all((token, base, project)):
            raise Unavailable('set SONAR_URL, SONAR_PROJECT_KEY and SONAR_TOKEN')
        headers = {'Authorization': 'Bearer ' + token}
        for key, header in [('CF_ACCESS_CLIENT_ID', 'CF-Access-Client-Id'), ('CF_ACCESS_CLIENT_SECRET', 'CF-Access-Client-Secret')]:
            if os.environ.get(key):
                headers[header] = os.environ[key]
        reader = Reader(base, headers, a.timeout)
        scope = {'pullRequest' if a.target.isdigit() else 'branch': a.target}
        gate = reader.get('/api/qualitygates/project_status', {'projectKey': project, **scope}).get('projectStatus')
        if not isinstance(gate, dict) or gate.get('status') not in ('OK', 'ERROR'):
            raise Unavailable('missing/unknown quality gate')
        issues = reader.sonar_pages('/api/issues/search', {'components': project, 'resolved': 'false', **scope}, 'issues')
        hotspots = reader.sonar_pages('/api/hotspots/search', {'project': project, 'status': 'TO_REVIEW', **scope}, 'hotspots')
        print(json.dumps({'complete': True, 'gate': gate, 'issue_count': len(issues),
                          'issues': [{k: i.get(k) for k in ('key', 'rule', 'severity', 'component', 'line')} for i in issues],
                          'hotspots_to_review': len(hotspots)}))
        return 1 if gate['status'] == 'ERROR' else 0
    except (Unavailable, TypeError, KeyError) as e:
        print('INCOMPLETE: ' + str(e), file=sys.stderr)
        return 5


if __name__ == '__main__':
    sys.exit(main())

"""Compact DefectDojo evidence. Exit 0=no selected findings, 1=findings, 5=incomplete."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_reader import Reader, Unavailable
import toolchain_config as config

SEVERITIES = ['Info', 'Low', 'Medium', 'High', 'Critical']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('branch', nargs='?')
    ap.add_argument('--min-severity', choices=SEVERITIES, default='Info')
    ap.add_argument('--timeout', type=float, default=120)
    a = ap.parse_args(argv)
    try:
        token, base, product = (config.get(k) for k in ('DEFECTDOJO_TOKEN', 'DEFECTDOJO_URL', 'DEFECTDOJO_PRODUCT'))
        if not all((token, base, product)):
            raise Unavailable('set DEFECTDOJO_URL, DEFECTDOJO_PRODUCT and DEFECTDOJO_TOKEN')
        headers = {'Authorization': 'Token ' + token}
        for key, header in [('CF_ACCESS_CLIENT_ID', 'CF-Access-Client-Id'), ('CF_ACCESS_CLIENT_SECRET', 'CF-Access-Client-Secret')]:
            if os.environ.get(key):
                headers[header] = os.environ[key]
        reader = Reader(base, headers, a.timeout)
        products = [p for p in reader.dojo_pages('products', {'name': product}) if p.get('name') == product]
        if len(products) != 1 or type(products[0].get('id')) is not int:
            raise Unavailable('expected exactly one matching product')
        pid = products[0]['id']
        tests = reader.dojo_pages('tests', {'engagement__product': pid})
        engagements = {e['id']: e for e in reader.dojo_pages('engagements', {'product': pid})} if a.branch else {}
        branches = {t['id']: t.get('branch_tag') or engagements.get(t.get('engagement'), {}).get('branch_tag') for t in tests}
        if a.branch and any(not isinstance(b, str) or not b for b in branches.values()):
            raise Unavailable('branch applicability is incomplete; inspect unlabelled tests or query all branches')
        test_ids = {t['id'] for t in tests if not a.branch or branches[t['id']] == a.branch}
        findings = reader.dojo_pages('findings', {'test__engagement__product': pid, 'active': 'true', 'duplicate': 'false'})
        if any(f.get('test') not in branches for f in findings):
            raise Unavailable('finding refers to an unavailable test')
        if any(f.get('severity') not in SEVERITIES for f in findings):
            raise Unavailable('unknown finding severity')
        chosen = [f for f in findings if f.get('test') in test_ids and SEVERITIES.index(f['severity']) >= SEVERITIES.index(a.min_severity)]
        print(json.dumps({'complete': True, 'count': len(chosen), 'findings': [
            {k: f.get(k) for k in ('id', 'severity', 'file_path', 'line', 'date')} for f in chosen]}))
        return 1 if chosen else 0
    except (Unavailable, TypeError, KeyError) as e:
        print('INCOMPLETE: ' + str(e), file=sys.stderr)
        return 5


if __name__ == '__main__':
    sys.exit(main())

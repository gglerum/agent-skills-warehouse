"""Compare a component's recorded origins with explicitly supplied local source folders."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def compare(record, roots):
    drift, unavailable = [], []
    for item in record['origins']:
        key = item['project']
        if key not in roots:
            unavailable.append(key + ': no source folder supplied')
            continue
        root = roots[key].resolve()
        p = (root / item['path']).resolve()
        if not p.is_relative_to(root) or not p.is_file():
            unavailable.append(key + '/' + item['path'] + ': unavailable')
        elif hashlib.sha256(p.read_bytes()).hexdigest() != item['sha256']:
            drift.append(key + '/' + item['path'])
    return drift, unavailable


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('origin', type=Path, help='copied component ORIGIN.json')
    ap.add_argument('--source', action='append', required=True, metavar='NAME=FOLDER')
    a = ap.parse_args()
    try:
        roots = {}
        for pair in a.source:
            name, sep, value = pair.partition('=')
            if not sep or not name or not value or name in roots:
                raise ValueError('invalid/duplicate source mapping')
            roots[name] = Path(value)
        drift, unavailable = compare(json.loads(a.origin.read_text()), roots)
        print(json.dumps({'changed': drift, 'unavailable': unavailable}))
        return 2 if unavailable else 1 if drift else 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Origin comparison unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

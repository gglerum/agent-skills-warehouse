"""Validate explicit fixture outcomes and write fresh evidence runs; no test execution."""
import argparse
import json
from pathlib import Path
import re
import sys

OUTCOMES = {'PASS', 'FAIL', 'BLOCKED_BY_SETUP', 'INCONCLUSIVE', 'BROKEN_TEST'}


def validate(record):
    if not isinstance(record, dict) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', record.get('id', '')):
        raise ValueError('invalid fixture identity')
    for key in ('property', 'oracle', 'preconditions'):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError('missing property/oracle/preconditions')
    if record.get('outcome') not in OUTCOMES:
        raise ValueError('unknown outcome')
    if not isinstance(record.get('expected'), dict) or not isinstance(record.get('actual'), dict):
        raise ValueError('expected/actual must be separate observations')
    if record['outcome'] in ('PASS', 'FAIL'):
        if record.get('control_passed') is not True or not record.get('evidence'):
            raise ValueError('decisive outcome needs healthy control and evidence')
    return record


def write_run(parent, run_id, records):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', run_id):
        raise ValueError('unsafe run identity')
    ids = set()
    for record in records:
        validate(record)
        if record['id'] in ids:
            raise ValueError('duplicate fixture')
        ids.add(record['id'])
    if not records:
        raise ValueError('no fixture observations')
    path = parent / run_id
    path.mkdir(parents=True, exist_ok=False)
    for record in records:
        (path / (record['id'] + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    (path / 'summary.json').write_text(json.dumps({k: sum(r['outcome'] == k for r in records) for k in sorted(OUTCOMES)}, indent=2) + '\n')
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('records')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--run-id', required=True)
    a = ap.parse_args()
    try:
        records = json.loads(Path(a.records).read_text())
        if not isinstance(records, list):
            raise ValueError('expected records list')
        print(write_run(a.out, a.run_id, records))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Evidence invalid or run already exists', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

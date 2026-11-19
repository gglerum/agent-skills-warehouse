"""Validate a deployment-specific receipt; never infer deployment from CI or merge."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys


def validate(receipt, sha, host):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('expected full Git SHA')
    if not isinstance(receipt, dict) or receipt.get('sha') != sha or receipt.get('host') != host:
        raise ValueError('receipt identity mismatch')
    if not isinstance(receipt.get('deploy_id'), str) or not receipt['deploy_id'].strip():
        raise ValueError('missing deployment identity')
    stamp = datetime.fromisoformat(receipt.get('deployed_at', '').replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('deployment timestamp needs a timezone')
    health = receipt.get('health')
    if not isinstance(health, dict) or health.get('passed') is not True or health.get('deploy_id') != receipt['deploy_id']:
        raise ValueError('health must pass for this deployment identity')
    checked = datetime.fromisoformat(health.get('checked_at', '').replace('Z', '+00:00'))
    if checked.tzinfo is None or checked < stamp:
        raise ValueError('health timestamp predates deployment or lacks timezone')
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('receipt')
    ap.add_argument('--sha', required=True)
    ap.add_argument('--host', required=True)
    a = ap.parse_args()
    try:
        validate(json.loads(Path(a.receipt).read_text()), a.sha, a.host)
        print('Deployment receipt matches; producer authenticity still requires project verification.')
        return 0
    except (OSError, ValueError, TypeError, AttributeError):
        print('Deployment unconfirmed: missing, malformed or mismatched receipt', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

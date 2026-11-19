"""Compact local Git state; no fetch, service calls, tracking changes or writes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def snapshot(root, base=None):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, timeout=10).decode().strip()
    result = {'head': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
              'changes': git('status', '--porcelain=v1').splitlines()}
    for key, ref in [('ahead_of_base', base), ('unpushed', '@{upstream}')]:
        if ref:
            try:
                result[key] = int(git('rev-list', '--count', ref + '..HEAD'))
            except subprocess.CalledProcessError:
                result[key] = None
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default='.')
    ap.add_argument('--base')
    a = ap.parse_args()
    try:
        print(json.dumps(snapshot(Path(a.root), a.base)))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Git state unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

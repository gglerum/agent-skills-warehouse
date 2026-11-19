"""Run explicit staged-file checks after index/worktree validation; never install hooks."""
import argparse
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_staging


def execute(config):
    steps = config.get('steps')
    if not isinstance(steps, list) or not steps:
        raise ValueError('configure at least one real check')
    check_staging.check()
    paths = [os.fsdecode(p) for p in check_staging.git('diff', '--cached', '--name-only', '--diff-filter=ACM', '-z').split(b'\0') if p]
    executed = 0
    for step in steps:
        command, globs = step.get('args'), step.get('globs')
        if (not isinstance(command, list) or not command or any(not isinstance(a, str) for a in command)
                or not isinstance(globs, list) or not globs or any(not isinstance(g, str) for g in globs)
                or type(step.get('timeout', 300)) not in (int, float) or not 0 < step.get('timeout', 300) <= 3600):
            raise ValueError('invalid command/globs/timeout')
        chosen = [p for p in paths if any(fnmatch.fnmatchcase(p, g) for g in globs)]
        if not chosen:
            continue
        args = [value for part in command for value in (chosen if part == '{files}' else [part])]
        result = subprocess.run(args, timeout=step.get('timeout', 300), check=False)
        if result.returncode:
            return result.returncode
        if step.get('restage') is True:
            check_staging.git('add', '--', *chosen)
        executed += 1
    print(f'Executed {executed} configured check(s)' if executed else 'No configured checks apply to the staged paths')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True)
    ap.add_argument('--root', required=True)
    a = ap.parse_args()
    try:
        config = json.loads(Path(a.config).read_text())
        os.chdir(a.root)
        return execute(config)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        print('Configured checks did not complete; commit must remain blocked', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

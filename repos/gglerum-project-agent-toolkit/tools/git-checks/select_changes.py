"""Select PR checks from a verified Git diff. Uncertain input is an error."""
import argparse
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys


def git(*args):
    return subprocess.run(['git', *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


def changed_files(*revisions):
    # Disable rename detection so both old and new paths affect selection.
    fields = git('diff', '--name-status', '-z', '--no-renames', *revisions).split(b'\0')
    if fields.pop() != b'' or len(fields) % 2:
        raise ValueError('Malformed Git diff output')
    changes = []
    for status, path in zip(fields[::2], fields[1::2]):
        if status not in (b'A', b'C', b'M', b'D', b'T', b'U', b'X', b'B') or not path:
            raise ValueError('Malformed Git change')
        if status in (b'U', b'X', b'B'):
            raise ValueError('Unresolved Git change')
        changes.append((status.decode(), os.fsdecode(path)))
    return changes




def select(changes, rules):
    if not isinstance(rules, dict) or not rules or any(not isinstance(k, str) or not k.isidentifier() or not isinstance(v, list) or any(not isinstance(p, str) for p in v) for k, v in rules.items()):
        raise ValueError('Expected nonempty map of check names to glob lists')
    return {key: any(fnmatch.fnmatchcase(path, pattern) for _, path in changes for pattern in patterns)
            for key, patterns in rules.items()}


def pr_changes(target, fetch=False):
    git('check-ref-format', 'refs/heads/' + target)
    ref = 'refs/remotes/origin/' + target
    # Do not silently use an old ref when the fetch fails.
    if fetch:
        git('fetch', '--no-tags', 'origin', '+refs/heads/' + target + ':' + ref)
    base = git('rev-parse', '--verify', ref + '^{commit}').decode().strip()
    head = git('rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
    git('merge-base', base, head)
    return changed_files(base + '...' + head)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--target')
    mode.add_argument('--staged', action='store_true')
    parser.add_argument('--fetch', action='store_true', help='explicitly refresh origin target before diffing')
    parser.add_argument('--rules', required=True, help='JSON map of check flags to affected path globs')
    parser.add_argument('--output-dir', help='Existing disposable directory for Jenkins environment files')
    args = parser.parse_args()
    try:
        if args.fetch and not args.target:
            raise ValueError('--fetch requires --target')
        changes = changed_files('--cached') if args.staged else pr_changes(args.target, args.fetch)
        result = select(changes, json.loads(Path(args.rules).read_text()))
        if args.output_dir:
            for key, value in result.items():
                text = str(value).lower() if isinstance(value, bool) else value
                (Path(args.output_dir) / key).write_text(text, encoding='utf-8')
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f'Change selection failed; required checks cannot be skipped: {exc}', file=sys.stderr)
        return 1
    if not args.output_dir:
        print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""Reject ambiguous staged inputs before any project check or auto-fixer runs."""
import os
from pathlib import Path
import subprocess
import sys


def git(*args):
    return subprocess.check_output(['git', '--literal-pathspecs', *args])


def check():
    paths = git('diff', '--cached', '--name-only', '--no-renames', '-z').split(b'\0')
    for raw in filter(None, paths):
        path = os.fsdecode(raw)
        # checks.sh still consumes newline-delimited paths and invokes xargs.
        if (path.startswith(('-', ':')) or not path.isascii()
                or any(ord(c) < 32 or ord(c) == 127 or c in '\\"' for c in path)):
            raise ValueError(f'Unsupported hook path: {path!r}; rename it before committing.')
        entries = git('ls-files', '--stage', '-z', '--', path).split(b'\0')
        entries = [entry for entry in entries if entry]
        if not entries:
            if os.path.lexists(path):
                raise ValueError(f'Staged deletion has an unstaged replacement: {path!r}.')
            continue
        if len(entries) != 1:
            raise ValueError(f'Unresolved index entries: {path!r}; resolve conflicts first.')
        mode, oid, stage = entries[0].split(b'\t', 1)[0].split()
        if stage != b'0' or mode not in (b'100644', b'100755') or not Path(path).is_file() or Path(path).is_symlink():
            raise ValueError(f'Unsupported or missing staged regular file: {path!r}.')
        # Hash the actual file too: assume-unchanged/skip-worktree can hide edits from diff.
        actual = git('hash-object', '--path=' + path, '--', path).strip()
        differs = subprocess.run(['git', '--literal-pathspecs', 'diff', '--no-ext-diff', '--no-textconv',
                                  '--quiet', '--', path]).returncode
        if differs not in (0, 1):
            raise ValueError(f'Cannot compare staged input: {path!r}.')
        if actual != oid or differs:
            raise ValueError(f'Partial staging: {path!r}. Stage the complete intended file, '
                             'or move its unstaged edits aside yourself, then retry. '
                             'No formatter or restaging has run.')


def main():
    try:
        os.chdir(os.fsdecode(git('rev-parse', '--show-toplevel')).strip())
        check()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Staging check blocked: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

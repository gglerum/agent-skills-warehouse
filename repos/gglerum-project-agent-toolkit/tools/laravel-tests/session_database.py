#!/usr/bin/env python3
"""Own one worktree database; retain receipts outside removable worktrees."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


def git(directory, *args):
    return subprocess.check_output(['git', '-C', str(directory), *args], text=True).strip()


def save(path, record):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(path)


def main():
    if sys.argv[1:] in (['-h'], ['--help']):
        print('Usage: session_database.py setup|teardown WORKTREE TOPIC. Mutates explicitly owned MySQL/Laravel test resources only.')
        return
    action, directory, topic = sys.argv[1:]
    if action not in ('setup', 'teardown') or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,39}[a-z0-9]', topic):
        raise ValueError('Expected setup/teardown and 2-41 character topic ending in a letter or digit')
    directory = Path(directory).resolve()
    if directory.name != topic:
        raise ValueError('Topic does not match worktree folder')
    if Path(git(directory, 'rev-parse', '--show-toplevel')).resolve() != directory:
        raise ValueError('Not a worktree root')
    common = Path(git(directory, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    if directory == common.parent.resolve():
        raise ValueError('Refusing main checkout database operations')
    receipts = common / 'session-databases'
    receipts.mkdir(exist_ok=True)
    with (receipts / f'{topic}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        operate(action, directory, topic, common, receipts)


def operate(action, directory, topic, common, receipts):
    receipt = receipts / f'{topic}.json'
    database = 'testing_wt_' + hashlib.sha256(
        (str(common.resolve()) + '\0' + topic).encode()).hexdigest()[:24] + '_base'
    identity = {'path': str(directory), 'topic': topic, 'database': database,
                'branch': git(directory, 'branch', '--show-current')}
    record = json.loads(receipt.read_text()) if receipt.exists() else None
    marker = directory / '.testing-database'
    if record and any(record.get(key) != value for key, value in identity.items()):
        raise ValueError(f'Ownership mismatch; inspect {receipt}')
    if marker.exists() and (not record or marker.read_text().strip() != database):
        save(receipts / f'{topic}.unowned.json',
             dict(identity, state='unowned', observed_marker=marker.read_text()))
        raise ValueError(f'Unowned database marker; inspect {marker}. No database changed')
    env = dict(os.environ, XDEBUG_MODE='off')

    def execute(code):
        sentinel = 'SESSION_DB_OK_' + uuid.uuid4().hex
        result = subprocess.run(
            ['php', 'artisan', 'tinker', '--execute=' + code + f" echo '{sentinel}' . PHP_EOL;"],
            cwd=directory, env=env, check=True, capture_output=True, text=True)
        if sentinel not in result.stdout.splitlines():
            raise ValueError('Database command did not confirm completion; ownership remains uncertain')

    if action == 'setup':
        if record and record['state'] != 'ready':
            raise ValueError(f'Uncertain database creation; inspect {receipt} before retry. No database changed')
        if not record:
            record = dict(identity, state='creating')
            save(receipt, record)
            # No IF NOT EXISTS: an existing database is never adopted as ours.
            execute(f"DB::statement('CREATE DATABASE `{database}`');")
            record['state'] = 'ready'
            save(receipt, record)
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(database + '\n')
        temporary.replace(marker)
    else:
        if not record:
            return
        if record['state'] == 'removed':
            return
        if record['state'] not in ('ready', 'dropping'):
            raise ValueError(f'Uncertain ownership; inspect {receipt}. No database dropped')
        record['state'] = 'dropping'
        save(receipt, record)
        # Exact base or numeric Laravel worker suffix only; never broad prefix matching.
        execute("foreach (DB::select('SHOW DATABASES') as $row) { "
                f"if ($row->Database === '{database}' || "
                f"preg_match('/\\A{database}_test_[0-9]+\\z/', $row->Database) === 1) {{ "
                "DB::statement('DROP DATABASE `' . $row->Database . '`'); } }")
        record['state'] = 'removed'
        save(receipt, record)
        marker.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f'Session database blocked: {error}', file=sys.stderr)
        sys.exit(1)

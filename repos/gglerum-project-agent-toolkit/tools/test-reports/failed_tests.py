"""List the failed tests of the last PHPUnit run.

Usage:
    python3 utils/failed_tests.py [junit.xml]

phpunit.xml makes every run (also `php artisan test --parallel`) write a JUnit
log to reports/junit-local.xml, so after a failing full suite this prints each
failed or erroring test with its message and location, and a --filter that
reruns only those tests. The default report belongs to the current Git checkout
(or the checkout containing this script when invoked outside Git). An explicit
report path is relative to the working directory. Exits 1 when tests failed,
2 when the report cannot be read.
"""

import argparse
import os
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ElementTree

MESSAGE_LINES = 12


def default_log():
    # Prefer the invoking checkout (including linked worktrees). An absolute
    # invocation from outside Git can still locate the checkout containing us.
    for directory in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        try:
            root = subprocess.check_output(
                ['git', '-C', directory, 'rev-parse', '--show-toplevel'],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            return os.path.join(root, 'reports', 'junit-local.xml')
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
    return os.path.join(os.getcwd(), 'reports', 'junit-local.xml')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', nargs='?')
    parser.add_argument('--no-rerun', action='store_true', help='omit the PHPUnit-specific rerun hint')
    options = parser.parse_args()
    log_file = options.report or default_log()

    if not os.path.exists(log_file):
        print(f'No JUnit log at {log_file}; run the tests first.')
        return 2

    try:
        report = ElementTree.parse(log_file)
        if report.getroot().tag not in ('testsuites', 'testsuite'):
            raise ValueError('expected JUnit testsuite envelope')
    except (OSError, ElementTree.ParseError, ValueError) as error:
        print(f'Cannot read JUnit log at {log_file}: {error}', file=sys.stderr)
        return 2

    failed = []

    for testcase in report.iter('testcase'):
        problem = testcase.find('failure')
        if problem is None:
            problem = testcase.find('error')
        if problem is None:
            continue

        failed.append((testcase.get('class') or testcase.get('classname', ''), testcase.get('name', ''), testcase.get('file', ''), problem))

    if not failed:
        print('No failed tests.')
        return 0

    for class_name, name, file, problem in failed:
        print(f'✗ {class_name}::{name}  ({file})')
        lines = (problem.text or problem.get('message', '')).strip().splitlines()
        if lines and lines[0] == f'{class_name}::{name}':
            lines = lines[1:]
        for line in lines[:MESSAGE_LINES]:
            print(f'    {line}')
        if len(lines) > MESSAGE_LINES:
            print('    …')
        print()

    if options.no_rerun:
        return 1

    # \Class::method, anchored on both sides, so the filter doesn't also match longer names, classes ending in the
    # same name (LoginTest vs. WrongPanelLoginTest) or same-named methods elsewhere.
    names = sorted({re.escape(f"{class_name.rsplit(chr(92), 1)[-1]}::{name.split(' ')[0]}")
                    .replace('/', r'\/') for class_name, name, _, _ in failed})
    pattern = r'/\\(' + '|'.join(names) + r')( |$)/'
    print(f'{len(failed)} failed. Rerun only these:')
    print(f"    php artisan test --compact --filter={shlex.quote(pattern)}")

    return 1


if __name__ == '__main__':
    sys.exit(main())

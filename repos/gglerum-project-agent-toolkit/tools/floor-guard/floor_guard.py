#!/usr/bin/env python3
"""Floor guard: diff-scoped check that a change does not lower the bar written in CONSTRAINTS.md.

Usage: python3 floor_guard.py [--config FILE] [--base <ref>]   (default base: origin/main, then main)

It reads the diff between the merge base and the working tree (added and removed lines, plus untracked files) and
reports moves that make a check easier: a new suppression comment, a skipped or deleted test, a net loss of
assertions in a test file, unfinished work, a growing baseline file, a weakened rule in CONSTRAINTS.md, a new exception
row without an owner and expiry date. Tightening is silent, loosening is loud.

Exit codes: 0 clean, 1 at least one violation (block the change), 2 the guard could not run (not a git work tree,
no merge base). A 2 must never be read as a 0. It reports the rule and the place, never a line of code that could
hold a secret: only the matched token is printed (CONSTRAINTS.md lines are printed whole).
Python 3.10+ standard library and Git. It does not change files, Git configuration or hooks.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULTS = {
    "code_extensions": [".php", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".css", ".py", ".rb", ".go", ".java", ".kt", ".cs"],
    "ignored_prefixes": ["vendor/", "node_modules/", "dist/", "build/", "public/build/", "storage/", "bootstrap/cache/", ".venv/"],
    # Files that hold the patterns below as fixture text (the guard's own tests); they are not scanned.
    "self_exempt": [],
    "suppression_pattern": r"@phpstan-ignore|@codeCoverageIgnore|phpcs:ignore|NOSONAR|eslint-disable|cspell:disable|@ts-ignore|@ts-nocheck|@ts-expect-error|#\s*noqa|type:\s*ignore|pragma:\s*no cover|pylint:\s*disable|#\s*nosec|//\s*nolint",
    # Suppressions that name what they silence: group 1 holds the names; only the allowed names pass.
    "named_suppressions": [{"pattern": r"@psalm-suppress\s+([^*\n]*)", "allowed": []}],
    "stub_pattern": r"\bTODO\b|catch\s*\([^)]*\)\s*\{\s*\}|(?i:throw new\s+\\?[\w\\]*(Exception|Error)\s*\(\s*['\"][^'\"]*not implemented)|raise NotImplementedError|except[^:\n]*:\s*pass\b",
    "skip_pattern": r"markTest(Skipped|Incomplete)|(->|\.)(skip|todo)\(|\bx(it|describe)\(|@pytest\.mark\.skip|@unittest\.skip|pytest\.skip\(|\bt\.Skip\(",
    "assertion_pattern": r"\bassert[A-Z_]\w*\(|\bexpect\w*\(|^\s*assert\s",
    "test_file_pattern": r"(^|/)tests?/.*(Test\.php|_test\.py|\.test\.[jt]sx?)$|(^|/)tests?/js/|(^|/)test_[^/]*\.py$|\.(test|spec)\.(js|jsx|ts|tsx)$",
    "baseline_extensions": [".xml", ".neon", ".json", ".dist", ".txt"],
    "constraints_file": "CONSTRAINTS.md",
    "exception_row_pattern": r"^\|\s*U\d+\s*\|",
    "default_bases": ["origin/main", "main"],
}

MIN_BEFORE = re.compile(r"(>=|>|≥|at least|minimum|\bmin\b|no less than|not fall|not drop)\s*$")
MAX_BEFORE = re.compile(r"(<=|<|≤|at most|maximum|\bmax\b|no more than|under|below|not grow|not exceed)\s*$")
MIN_AFTER = re.compile(r"^\s*\S*\s*(?:\|\s*)?(or more|or higher|must not fall|must not drop)")
MAX_AFTER = re.compile(r"^\s*\S*\s*(?:\|\s*)?(or less|or lower|must not grow|must not exceed)")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

CFG: dict = {}


class GuardError(Exception):
    """The guard could not run; this ends in exit code 2."""


@dataclass
class FileChange:
    path: str
    deleted: bool = False
    added: list[tuple[int, str]] = field(default_factory=list)
    removed: list[tuple[int, str]] = field(default_factory=list)


def configure(config_path: str | None) -> None:
    global CFG
    CFG = dict(DEFAULTS)
    if config_path:
        try:
            CFG.update(json.loads(Path(config_path).read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise GuardError(f"unreadable configuration {config_path}: {error}") from error
    try:
        CFG["_suppressions"] = re.compile(CFG["suppression_pattern"])
        CFG["_named"] = [(re.compile(item["pattern"]), set(item.get("allowed", []))) for item in CFG["named_suppressions"]]
        CFG["_stubs"] = re.compile(CFG["stub_pattern"])
        CFG["_skips"] = re.compile(CFG["skip_pattern"])
        CFG["_assertion"] = re.compile(CFG["assertion_pattern"], re.M)
        CFG["_tests"] = re.compile(CFG["test_file_pattern"])
        CFG["_exception"] = re.compile(CFG["exception_row_pattern"])
    except (re.error, KeyError, TypeError) as error:
        raise GuardError(f"invalid pattern in the configuration: {error}") from error


def git(args: list[str], diff_exit: bool = False) -> str:
    """Run git; `git diff --no-index` exits 1 for a new file, which is the normal case and keeps its output."""
    process = subprocess.run(['git', *args], capture_output=True, text=True, errors='replace')
    if process.returncode == 0 or (diff_exit and process.returncode == 1):
        return process.stdout
    raise GuardError(f"git {' '.join(args[:2])} failed: {process.stderr.strip()[:200]}")


def resolve_base(requested: str | None) -> str:
    candidates = [requested] if requested else CFG['default_bases']
    for ref in candidates:
        if subprocess.run(['git', 'rev-parse', '--verify', '--quiet', ref + '^{commit}'], capture_output=True).returncode == 0:
            return ref
    raise GuardError('base ref not found: ' + ' / '.join(c for c in candidates if c))


def read_diff(base: str) -> str:
    merge_base = git(['merge-base', base, 'HEAD']).strip()
    if not merge_base:
        raise GuardError('no merge base against ' + base)
    tracked = git(['diff', '--find-renames', '--unified=0', merge_base, '--'])
    untracked_names = [name for name in git(['ls-files', '--others', '--exclude-standard']).split('\n') if name]
    untracked = ''.join(
        git(['diff', '--no-index', '--unified=0', '/dev/null', name], diff_exit=True) for name in untracked_names
    )
    return tracked + '\n' + untracked


def strip_prefix(path: str) -> str:
    return path[2:] if path[:2] in ('a/', 'b/') else path


def parse_diff(diff: str) -> list[FileChange]:
    """Headers (---, +++) only count between a `diff` line and its first hunk; inside a hunk every line is content."""
    changes: list[FileChange] = []
    current: FileChange | None = None
    in_header = False
    old_path = ''
    old_line = new_line = 0
    for line in diff.split('\n'):
        if line.startswith('diff '):
            in_header = True
            current = None
            old_path = ''
        elif line.startswith('@@'):
            in_header = False
            match = HUNK.match(line)
            if match:
                old_line, new_line = int(match.group(1)), int(match.group(2))
        elif in_header:
            if line.startswith('--- '):
                old_path = strip_prefix(line[4:])
            elif line.startswith('+++ '):
                new_path = strip_prefix(line[4:])
                deleted = new_path == '/dev/null'
                current = FileChange(path=old_path if deleted else new_path, deleted=deleted)
                changes.append(current)
        elif current is not None and line.startswith('+'):
            current.added.append((new_line, line[1:]))
            new_line += 1
        elif current is not None and line.startswith('-'):
            current.removed.append((old_line, line[1:]))
            old_line += 1
    return changes


def is_code(path: str) -> bool:
    return (path.endswith(tuple(CFG['code_extensions'])) and not path.startswith(tuple(CFG['ignored_prefixes']))
            and path not in CFG['self_exempt'])


def is_test(path: str) -> bool:
    return bool(CFG['_tests'].search(path))


def is_baseline(path: str) -> bool:
    return 'baseline' in path.rsplit('/', 1)[-1].lower() and path.endswith(tuple(CFG['baseline_extensions']))


Finding = tuple[str, str, str]  # rule, place, what


def scan_code(change: FileChange, findings: list[Finding]) -> None:
    for number, text in change.added:
        place = f'{change.path}:{number}'
        suppression = CFG['_suppressions'].search(text)
        if suppression:
            findings.append(('silenced-checker', place, suppression.group(0)))
        for pattern, allowed in CFG['_named']:
            for named in pattern.finditer(text):
                names = [n for n in re.split(r'[\s,]+', named.group(1).strip()) if n]
                loud = [n for n in names if n not in allowed]
                if loud or not names:
                    findings.append(('silenced-checker', place, named.group(0).split()[0] + ' ' + ' '.join(loud or ['(nothing named)'])))
        stub = CFG['_stubs'].search(text)
        if stub:
            findings.append(('unfinished-work', place, stub.group(0)))
        if is_test(change.path):
            skip = CFG['_skips'].search(text)
            if skip:
                findings.append(('test-made-easier', place, skip.group(0)))


def scan_tests(change: FileChange, findings: list[Finding]) -> None:
    if change.deleted:
        findings.append(('test-deleted', change.path, 'file deleted'))
        return
    count = CFG['_assertion']
    lost = sum(len(count.findall(t)) for _, t in change.removed) - sum(len(count.findall(t)) for _, t in change.added)
    if lost > 0:
        findings.append(('assertions-lost', change.path, f'net {lost} assertion(s) fewer than before'))


def scan_baseline(change: FileChange, findings: list[Finding]) -> None:
    grown = len(change.added) - len(change.removed)
    if grown > 0:
        findings.append(('baseline-grown', change.path, f'{grown} line(s) more in the baseline'))


def rule_key(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith('|'):
        cells = [c.strip() for c in stripped.split('|') if c.strip()]
        return cells[0] if cells else ''
    if re.match(r'^[-*] ', stripped):
        return stripped[2:].split(':')[0].strip()
    return None  # prose, headings, dates: not a rule


def thresholds(text: str) -> list[tuple[float, str | None]]:
    found: list[tuple[float, str | None]] = []
    for match in re.finditer(r'\d+(?:\.\d+)?', text):
        before = text[max(0, match.start() - 24):match.start()].lower()
        after = text[match.end():match.end() + 40].lower()
        if MIN_BEFORE.search(before) or MIN_AFTER.match(after):
            direction = 'min'
        elif MAX_BEFORE.search(before) or MAX_AFTER.match(after):
            direction = 'max'
        else:
            direction = None
        found.append((float(match.group(0)), direction))
    return found


def check_exception_row(path: str, number: int, text: str, findings: list[Finding], warnings: list[str]) -> None:
    cells = [c.strip() for c in text.strip().strip('|').split('|')]
    # id | rule | reason | owner | expires
    owner = cells[3] if len(cells) > 3 else ''
    expires = cells[4] if len(cells) > 4 else ''
    place = f'{path}:{number}'
    if not owner:
        findings.append(('exception-without-owner', place, text.strip()[:120]))
    elif not DATE.fullmatch(expires):
        findings.append(('exception-without-expiry', place, text.strip()[:120]))
    elif datetime.date.fromisoformat(expires) < datetime.date.today():
        findings.append(('exception-already-expired', place, text.strip()[:120]))
    else:
        warnings.append(f'new exception in {place} (owner {owner}, expires {expires}): the reviewer must agree')


def scan_constraints(change: FileChange, findings: list[Finding], warnings: list[str]) -> None:
    exception = CFG['_exception']
    for number, text in change.added:
        if exception.match(text.strip()):
            check_exception_row(change.path, number, text, findings, warnings)
    added_rules = [(n, t) for n, t in change.added if rule_key(t) is not None]
    for number, text in [(n, t) for n, t in change.removed if rule_key(t) is not None]:
        place = f'{change.path}:{number}'
        key = rule_key(text)
        counterpart = next((t for _, t in added_rules if rule_key(t) == key), None)
        if counterpart is None:
            if not exception.match(text.strip()):  # dropping an exception tightens: silent
                findings.append(('rule-removed', place, text.strip()[:120]))
            continue
        before, after = thresholds(text), thresholds(counterpart)
        verdict = None
        for direction in ('min', 'max', None):
            was = [n for n, d in before if d == direction]
            now = [n for n, d in after if d == direction]
            for index, value in enumerate(was):
                if verdict:
                    break
                if index >= len(now):
                    verdict = 'threshold-removed'
                elif now[index] == value:
                    continue
                elif direction == 'min' and now[index] < value or direction == 'max' and now[index] > value or direction is None:
                    verdict = 'threshold-loosened' if direction else 'threshold-changed'
        if verdict:
            findings.append((verdict, place, f'{text.strip()[:100]}  ->  {counterpart.strip()[:100]}'))


def run(base_arg: str | None) -> int:
    top = git(['rev-parse', '--show-toplevel']).strip()
    if not top:
        raise GuardError('not inside a git work tree')
    base = resolve_base(base_arg)
    # Paths in the diff are relative to the top of the work tree, so run from there.
    os.chdir(top)
    changes = parse_diff(read_diff(base))

    findings: list[Finding] = []
    warnings: list[str] = []
    for change in changes:
        if change.path.endswith(CFG['constraints_file']):
            scan_constraints(change, findings, warnings)
        if is_baseline(change.path):
            scan_baseline(change, findings)
        if is_test(change.path) and change.path not in CFG['self_exempt']:
            scan_tests(change, findings)
        if is_code(change.path):
            scan_code(change, findings)

    for warning in warnings:
        print('floor-guard: warning: ' + warning, file=sys.stderr)
    if not findings:
        print('floor-guard: clean')
        return 0
    print(f'floor-guard: {len(findings)} floor violation(s):', file=sys.stderr)
    for rule, place, what in findings:
        print(f'  [{rule}] {place}: {what}', file=sys.stderr)
    if any(rule == 'rule-removed' for rule, _, _ in findings):
        print("\nA rule-removed finding can also mean the rule's label changed: rename a rule in one commit and change its thresholds in another.", file=sys.stderr)
    print(f'\nEach is a move that lowers the bar. Fix the code, or add a row to the exception table in {CFG["constraints_file"]} with an owner and an expiry date.', file=sys.stderr)
    return 1


def argument(argv: list[str], name: str) -> str | None:
    if name in argv and argv.index(name) + 1 < len(argv):
        return argv[argv.index(name) + 1]
    return None


def main(argv: list[str]) -> int:
    if '-h' in argv or '--help' in argv:
        print(__doc__)
        return 0
    try:
        configure(argument(argv, '--config'))
        return run(argument(argv, '--base'))
    except GuardError as error:
        print('floor-guard: could not run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

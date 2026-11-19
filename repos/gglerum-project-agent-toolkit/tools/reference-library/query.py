"""Search an explicitly selected local Markdown library and return bounded excerpts."""
import argparse
from pathlib import Path
import re
import sys


def search(root, query, limit=8, chars=500):
    words = set(re.findall(r'\w+', query.lower()))
    if not words:
        raise ValueError('empty query')
    found = []
    for p in sorted(root.rglob('*.md')):
        if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or p.stat().st_size > 2_000_000:
            continue
        text = p.read_text(encoding='utf-8', errors='replace')
        score = sum(w in text.lower() for w in words)
        if score:
            lines = text.splitlines()
            hit = next((i for i, line in enumerate(lines) if any(w in line.lower() for w in words)), 0)
            found.append((score, p.relative_to(root).as_posix(), hit + 1, '\n'.join(lines[hit:hit + 12])[:chars]))
    return sorted(found, key=lambda row: (-row[0], row[1]))[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('query')
    ap.add_argument('--limit', type=int, default=8)
    ap.add_argument('--chars', type=int, default=500)
    a = ap.parse_args()
    try:
        if not a.root.is_dir() or not 1 <= a.limit <= 100 or not 1 <= a.chars <= 10000:
            raise ValueError('invalid root/bounds')
        for score, name, line, excerpt in search(a.root, a.query, a.limit, a.chars):
            print(f'-- {name}:{line} matches={score}\n{excerpt}')
        return 0
    except (OSError, ValueError):
        print('Reference query unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

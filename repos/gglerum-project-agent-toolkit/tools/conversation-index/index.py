"""Byte-exact Markdown conversation chunks and checked segment plans; no model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

TURN = re.compile(rb'^## (?:You|ChatGPT) \(\d{4}-\d\d-\d\d \d\d:\d\d UTC\)\s*$')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build(source, out, max_lines):
    if max_lines < 1:
        raise ValueError('max-lines must be positive')
    if out.exists() and any(out.iterdir()):
        raise ValueError('output must be new or empty; existing annotations are never replaced')
    raw = source.read_bytes()
    lines = raw.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if TURN.fullmatch(line.rstrip(b'\r\n'))]
    if not starts:
        raise ValueError('no supported turn headings found')
    cuts, start = [], 0
    for pos in starts[1:]:
        if pos - start >= max_lines:
            cuts.append((start, pos))
            start = pos
    cuts.append((start, len(lines)))
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for n, (a, b) in enumerate(cuts, 1):
        content = b''.join(lines[a:b])
        name = f'chunk-{n:04d}.md'
        (out / name).write_bytes(content)
        records.append({'file': name, 'start': a + 1, 'end': b, 'sha256': digest(content)})
    record = {'source_name': source.name, 'source_sha256': digest(raw), 'line_count': len(lines), 'chunks': records}
    (out / 'index.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def verify(source, out):
    raw = source.read_bytes()
    record = json.loads((out / 'index.json').read_text())
    if digest(raw) != record['source_sha256']:
        raise ValueError('source changed')
    rebuilt, expected = [], 1
    for chunk in record['chunks']:
        p = (out / chunk['file']).resolve()
        p.relative_to(out.resolve())
        content = p.read_bytes()
        if chunk['start'] != expected or chunk['end'] < chunk['start'] or digest(content) != chunk['sha256']:
            raise ValueError('chunk gap/overlap or hash mismatch')
        expected = chunk['end'] + 1
        rebuilt.append(content)
    if b''.join(rebuilt) != raw or expected != len(raw.splitlines()) + 1:
        raise ValueError('reassembly differs from source')
    return record


def check_segments(source, plan):
    lines = source.read_bytes().splitlines(keepends=True)
    starts = {i + 1 for i, line in enumerate(lines) if TURN.fullmatch(line.rstrip(b'\r\n'))}
    expected = 1
    for seg in plan:
        if type(seg['start']) is not int or type(seg['end']) is not int or seg['start'] != expected or seg['end'] < seg['start'] or seg['end'] > len(lines):
            raise ValueError('segments must cover source exactly without overlaps')
        if seg['start'] != 1 and seg['start'] not in starts:
            raise ValueError('segment must begin at a turn boundary')
        for dec in seg.get('decisions', []):
            line = dec['line']
            if type(line) is not int or not seg['start'] <= line <= seg['end']:
                raise ValueError('decision line outside segment')
            window = b''.join(lines[max(seg['start'] - 1, line - 13):min(seg['end'], line + 12)]).decode('utf-8')
            if not isinstance(dec['quote'], str) or not dec['quote'].strip() or ' '.join(dec['quote'].split()) not in ' '.join(window.split()):
                raise ValueError('decision quote not present near cited line')
        expected = seg['end'] + 1
    if expected != len(lines) + 1:
        raise ValueError('segments do not cover all source lines')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['build', 'check', 'segments-check'])
    ap.add_argument('source', type=Path)
    ap.add_argument('output', type=Path, help='chunk directory or segment-plan JSON')
    ap.add_argument('--max-lines', type=int, default=2400)
    a = ap.parse_args()
    try:
        if a.action == 'build':
            build(a.source, a.output, a.max_lines)
        elif a.action == 'check':
            verify(a.source, a.output)
        else:
            check_segments(a.source, json.loads(a.output.read_text()))
        print('Conversation evidence checked')
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        print('Conversation evidence invalid/unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

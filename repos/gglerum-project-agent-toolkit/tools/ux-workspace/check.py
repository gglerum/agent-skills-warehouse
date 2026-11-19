"""Check an explicit lab registry and shared marked blocks; no synthetic acceptance."""
import argparse
import json
from pathlib import Path
import sys


def block(text, begin, end):
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError('shared markers must occur exactly once')
    a, b = text.index(begin) + len(begin), text.index(end)
    if a > b:
        raise ValueError('shared marker order')
    return text[a:b].strip('\n')


def check(root, manifest):
    def local(name):
        p = (root / name).resolve()
        p.relative_to(root.resolve())
        if not p.is_file():
            raise ValueError('missing lab/acceptance/test/shared file')
        return p
    errors, seen = [], set()
    for lab in manifest['labs']:
        if lab['file'] in seen:
            errors.append('duplicate lab: ' + lab['file'])
        seen.add(lab['file'])
        text = local(lab['file']).read_text()
        local(lab['acceptance'])
        local(lab['tests'])
        for shared in manifest.get('shared', []):
            if block(text, shared['begin'], shared['end']) != local(shared['source']).read_text().strip('\n'):
                errors.append(lab['file'] + ': stale shared block')
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('manifest')
    ap.add_argument('--root', required=True, type=Path)
    a = ap.parse_args()
    try:
        errors = check(a.root, json.loads(Path(a.manifest).read_text()))
        print('\n'.join(errors) if errors else 'Workspace consistent; human acceptance is a separate decision.')
        return 1 if errors else 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Workspace evidence incomplete', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

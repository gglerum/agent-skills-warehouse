"""Preview or refresh shared marked blocks in every explicitly registered lab."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import block


def plan(root, manifest):
    def local(name):
        p = (root / name).resolve()
        p.relative_to(root.resolve())
        if not p.is_file():
            raise ValueError('missing target/source')
        return p
    planned = {}
    for lab in manifest['labs']:
        p = local(lab['file'])
        text = p.read_text()
        for shared in manifest['shared']:
            begin, end = shared['begin'], shared['end']
            block(text, begin, end)  # validates unique and ordered markers before any write
            content = local(shared['source']).read_text().strip('\n')
            a, b = text.index(begin) + len(begin), text.index(end)
            text = text[:a] + '\n' + content + '\n' + text[b:]
        planned[p] = text
    return planned


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('manifest')
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    try:
        planned = plan(a.root, json.loads(Path(a.manifest).read_text()))
        changed = {p: text for p, text in planned.items() if text != p.read_text()}
        if a.write:
            # Prevalidated as a batch, but replacements are atomic per file, not a transaction.
            for p, text in changed.items():
                fd, tmp = tempfile.mkstemp(dir=p.parent, prefix='.shared-')
                try:
                    with os.fdopen(fd, 'w') as out:
                        out.write(text)
                    os.chmod(tmp, p.stat().st_mode & 0o777)
                    os.replace(tmp, p)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
        print(f'{len(changed)} lab(s) ' + ('updated; run behavior checks separately' if a.write else 'would change; no file written'))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Shared block update incomplete; inspect files before retry', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

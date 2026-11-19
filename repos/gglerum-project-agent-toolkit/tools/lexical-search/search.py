"""Explicit-root tracked-file lexical index; no model, service or global indexing."""
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fts


def selected(root):
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', '--cached'], timeout=30)
    files = []
    for name in sorted(set(x.decode() for x in raw.split(b'\0') if x)):
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root) or not p.is_file() or p.stat().st_size > 1_000_000:
            continue
        if p.name.startswith('.env') or p.suffix.lower() in ('.pem', '.key', '.p12', '.lock', '.png', '.jpg', '.pdf', '.sqlite', '.db'):
            continue
        sample = p.read_bytes()
        if b'\0' not in sample:
            files.append(name)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['build', 'refresh', 'query'])
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('--db', required=True, type=Path)
    ap.add_argument('--query')
    ap.add_argument('--limit', type=int, default=10)
    a = ap.parse_args()
    try:
        root = a.root.resolve()
        if not root.is_dir() or not 1 <= a.limit <= 100:
            raise ValueError('invalid root/limit')
        if a.action == 'build':
            if a.db.exists():
                raise ValueError('index already exists; use refresh or choose a new path')
            # Build in a fresh named path only. An interrupted build is not a complete index.
            c = fts.build(str(root), selected(root), str(a.db), contentless=False)
            c.execute('create table identity(root text)')
            c.execute('insert into identity values(?)', (str(root),))
            c.commit()
            c.close()
            print('Built explicit-root index')
        else:
            c = sqlite3.connect(a.db.resolve().as_uri() + '?mode=rw', uri=True)
            try:
                if c.execute('select root from identity').fetchone() != (str(root),):
                    raise ValueError('index belongs to another root')
                if a.action == 'refresh':
                    print(json.dumps({'changed': fts.refresh_hash(c, str(root), selected(root))}))
                else:
                    if not a.query:
                        raise ValueError('query required')
                    paths, candidates = fts.search(c, a.query, a.limit)
                    print(json.dumps({'paths': paths, 'candidates': candidates}))
            finally:
                c.close()
        return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
        print('Lexical index unavailable; no model or service fallback invoked', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

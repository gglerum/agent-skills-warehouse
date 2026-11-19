"""Check configured required files, hashes, local links, spec IDs and forbidden strings."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


def local(root, name):
    path = (root / name).resolve()
    path.relative_to(root.resolve())
    return path


def check(root, config):
    errors = []
    for name in config.get('required', []):
        if not local(root, name).is_file():
            errors.append('missing file: ' + name)
    for name, expected in config.get('hashes', {}).items():
        p = local(root, name)
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            errors.append('hash mismatch: ' + name)
    for name in config.get('link_files', []):
        p = local(root, name)
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text()):
            u = urlsplit(target.strip('<>'))
            if u.scheme or u.netloc or not u.path:
                continue
            rel = unquote(u.path)
            q = (p.parent / rel).resolve()
            q.relative_to(root.resolve())
            if not q.exists():
                errors.append(f'{name}: missing link {target}')
    for rule in config.get('forbid', []):
        for pattern in rule['globs']:
            for p in root.glob(pattern):
                if p.is_file() and re.search(rule['pattern'], p.read_text(errors='replace')):
                    errors.append(f'{p.relative_to(root)}: {rule["reason"]}')
    for spec in config.get('id_sets', []):
        canonical = set(re.findall(spec['pattern'], local(root, spec['canonical']).read_text()))
        data = json.loads(local(root, spec['machine']).read_text())
        machine = {row[spec['id_field']] for row in data[spec['json_key']]}
        if not canonical or canonical != machine:
            errors.append('spec/machine ID mismatch: ' + spec['canonical'])
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('config', help='JSON check configuration')
    ap.add_argument('--root', required=True)
    ap.add_argument('--record-hashes', action='store_true', help='explicitly write hashes for configured hash_globs; this records a review, not performs it')
    a = ap.parse_args()
    try:
        root = Path(a.root).resolve()
        cfgpath = Path(a.config)
        cfg = json.loads(cfgpath.read_text())
        if a.record_hashes:
            cfg['hashes'] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for glob in cfg['hash_globs'] for p in root.glob(glob) if p.is_file() and p.resolve().is_relative_to(root)}
            cfgpath.write_text(json.dumps(cfg, indent=2) + '\n')
            print('Recorded reviewed hashes; review content separately.')
        errors = check(root, cfg)
        print('\n'.join(errors) if errors else 'Configured checks passed')
        return 1 if errors else 0
    except (OSError, ValueError, TypeError, KeyError, re.error):
        print('Check unavailable: invalid configuration/input', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

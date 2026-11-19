"""Append a dated participant observation without promoting it to acceptance."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('acceptance', type=Path)
    ap.add_argument('--from-file', required=True, type=Path)
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    try:
        if a.acceptance.is_symlink() or not a.acceptance.is_file():
            raise ValueError('select an existing regular observation record')
        text = a.from_file.read_text().strip()
        if not text:
            raise ValueError('no observations')
        if a.write:
            with a.acceptance.open('a') as out:
                out.write('\n\n## Participant observation ' + datetime.now(timezone.utc).isoformat() + '\n\n' + text + '\n')
        print('Observation appended; acceptance unchanged' if a.write else 'Observation ready; no file written')
        return 0
    except (OSError, ValueError):
        print('Observation unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

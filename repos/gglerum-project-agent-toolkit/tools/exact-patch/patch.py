#!/usr/bin/env python3
"""Apply exact-text edits across files atomically.

Usage: python3 -I scripts/patch.py EDITS.json|- [--dry-run] [--then "CMD"]

EDITS is a JSON list of {"file": ..., "old": ..., "new": ..., "count": 1}. Every edit is checked
first (the old text must occur exactly `count` times in the file as it stands after earlier edits to
that file); if any check fails nothing is written. Writes use a temp file plus os.replace.
Prints one line per edit. --then runs CMD (shell) afterwards, prints the last 30 lines of its output
and exits with its exit code. Matching follows docs/implementation/ux01/design/templates/lab-patch.py.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile


def plan(edits, read=None):
    """Return (new_contents{path: text}, report_lines, ok). Pure apart from reading files."""
    read = read or (lambda p: open(p, encoding="utf-8").read())
    texts, lines, ok = {}, [], True
    for i, e in enumerate(edits, 1):
        f, old, new, count = e["file"], e["old"], e["new"], e.get("count", 1)
        label = f"edit {i} {f}"
        try:
            s = texts[f] if f in texts else read(f)
        except OSError as exc:
            lines.append(f"{label}: FAIL cannot read ({exc.strerror})")
            ok = False
            continue
        if not old:
            lines.append(f"{label}: FAIL empty old text")
            ok = False
            continue
        n = s.count(old)
        if n != count:
            lines.append(f"{label}: FAIL matches {n} times (need {count}): {old.splitlines()[0][:60]!r}")
            ok = False
            continue
        texts[f] = s.replace(old, new)
        lines.append(f"{label}: ok ({n} replaced)")
    return texts, lines, ok


def write_atomic(path, text):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".patch-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edits", help="JSON file, or - for stdin")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--then", metavar="CMD")
    a = ap.parse_args(argv)
    raw = sys.stdin.read() if a.edits == "-" else open(a.edits, encoding="utf-8").read()
    edits = json.loads(raw)
    if not isinstance(edits, list) or not edits:
        sys.exit("patch: expected a non-empty JSON list of edits")
    texts, lines, ok = plan(edits)
    print("\n".join(lines))
    if not ok:
        print("patch: NOT applied, no file written")
        return 1
    if a.dry_run:
        print(f"patch dry-run: {len(edits)} edit(s) apply cleanly to {len(texts)} file(s)")
        return 0
    for f, t in texts.items():
        write_atomic(f, t)
    print(f"patch: {len(edits)} edit(s) applied to {len(texts)} file(s)")
    if a.then:
        r = subprocess.run(a.then, shell=True, text=True, capture_output=True)
        print("\n".join((r.stdout + r.stderr).strip().splitlines()[-30:]))
        print(f"patch: --then exit {r.returncode}")
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())

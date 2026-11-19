#!/usr/bin/env python3
"""Print one section or one symbol of a file instead of dumping the whole file.

Usage: python3 -I scripts/sect.py <file> <heading|number|symbol> [--list]
  Markdown: heading text (exact, then substring, case-insensitive) or its
            leading number ("8.1"). A section runs to the next heading of the
            same or higher level. Headings inside code fences are ignored.
  .cs/.py : symbol name (a method name, or Class.Method); ranges come from
            scripts/code_map.py so they match CODE_MAP.md.
  --list  : list headings/symbols with line ranges instead of printing a body.
Exit 0 found, 1 not found, 2 ambiguous (candidates are listed).
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def load_code_map():
    spec = importlib.util.spec_from_file_location("code_map", HERE / "code_map.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def md_sections(lines):
    """[(level, title, start, end)] with 1-based inclusive lines."""
    heads, fence = [], False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence:
            m = HEAD.match(ln)
            if m:
                heads.append((len(m.group(1)), m.group(2), i + 1))
    out = []
    for k, (lvl, title, a) in enumerate(heads):
        end = len(lines)
        for lvl2, _, a2 in heads[k + 1:]:
            if lvl2 <= lvl:
                end = a2 - 1
                break
        out.append((lvl, title, a, end))
    return out


def pick_md(secs, query):
    q = query.strip().lstrip("#").strip().lower()
    num = lambda t: t.split()[0].lower() if t.split() else ""
    for test in (lambda t: t.lower() == q, lambda t: num(t) == q, lambda t: q in t.lower()):
        hits = [s for s in secs if test(s[1])]
        if hits:
            return hits
    return []


def code_rows(path):
    cm = load_code_map()
    _, rows = cm.scan(path)
    out, cls = [], ""
    for sym, a, b, _ in rows:
        name = sym.strip()
        if not sym.startswith("  "):
            cls = name
        out.append((f"{cls}.{name}" if sym.startswith("  ") else name, name, a, b))
    return out


def pick_code(rows, query):
    exact = [r for r in rows if query in (r[0], r[1])]
    return exact or [r for r in rows if query.lower() in r[0].lower()]


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    listing = "--list" in argv
    if not args or (len(args) < 2 and not listing):
        print(__doc__)
        return 1
    path, query = Path(args[0]), (args[1] if len(args) > 1 else "")
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        print(f"no such file: {args[0]}", file=sys.stderr)
        return 1
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if path.suffix.lower() == ".md":
        secs = md_sections(lines)
        if listing:
            for lvl, t, a, b in secs:
                print(f"{a}-{b}\t{'  ' * (lvl - 1)}{t}")
            return 0
        hits = [(t, a, b) for _, t, a, b in pick_md(secs, query)]
    elif path.suffix.lower() in (".cs", ".py"):
        rows = code_rows(path)
        if listing:
            for full, _, a, b in rows:
                print(f"{a}-{b}\t{full}")
            return 0
        hits = [(f, a, b) for f, _, a, b in pick_code(rows, query)]
    else:
        print("unsupported file type (use .md, .cs, .py)", file=sys.stderr)
        return 1
    if not hits:
        print(f"not found: {query!r} (try --list)", file=sys.stderr)
        return 1
    if len(hits) > 1 and not (len({h[0] for h in hits}) == 1):
        print(f"ambiguous: {query!r} matches:", file=sys.stderr)
        for t, a, b in hits:
            print(f"  {a}-{b}\t{t}", file=sys.stderr)
        return 2
    for t, a, b in hits:  # same-name overloads: print every one
        print(f"-- {args[0]}:{a}-{b} {t}")
        print("\n".join(lines[a - 1:b]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

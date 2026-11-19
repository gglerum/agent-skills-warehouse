#!/usr/bin/env python3
"""Register of design artifacts: one record per prototype or wireframe file, one entry per frame inside it.

Records live in <register_dir>/<file stem>.json (hand-owned, one file per artifact so parallel branches do not
collide). A frame is a <figure id="fN"> in the HTML file; its reference is `<stem>#fN`, for example
`checkout_flow#f16`. The overview document is generated; never edit it by hand.

Usage: python3 register.py [--config FILE] <find|for|show|add|index|check> ...

Record fields: file, title, kind (wireframe|prototype), status (proposed|approved|superseded|existing),
design_ref (page of an external design export, or null), implementation (the view or component that builds it, or
null), issues [n], decisions [ids], note, frames [{id, title, status, issues, decisions, replaced_by [ref], removed_because}].
A frame's own issues and decisions add to the record's. A frame with status `superseded` must name `replaced_by`, or
`removed_because` (a sentence) when no frame takes its place. Python 3.10+ standard library only.
"""
import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

DEFAULTS = {
    "artifacts_dir": "design/prototypes",
    "register_dir": "design/register",
    "index_file": "docs/design-register.md",
    "decisions_dir": None,  # directory with decision records; a decision id is the file stem (e.g. docs/decisions)
    "decisions_glob": "*.md",
    "skip_files": ["index.html"],
    # Regex for tracker or decision codes that must not appear in the visible text of an artifact (readers who do not use
    # the tracker would have to look every code up); null disables the check. Example: "\\b(?:DEC|ISSUE)-?\\d+\\b"
    "visible_code_pattern": None,
    "command": "python3 register.py",
}
STATUSES = {"proposed", "approved", "superseded", "existing"}
KINDS = {"wireframe", "prototype"}
FIGURE = re.compile(r"<figure\b([^>]*)>(.*?)</figure>", re.S)
CAPTION = re.compile(r"<figcaption>\s*(?:<b>)?\s*(.*?)\s*(?:</b>|<)", re.S)
REF = re.compile(r"^([\w.-]+)#(f\d+)$")

CFG = {}
ROOT = Path.cwd()
REG = PROTO = INDEX = Path()


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def configure(config_path):
    global CFG, ROOT, REG, PROTO, INDEX
    CFG = dict(DEFAULTS)
    ROOT = Path.cwd()
    if config_path:
        path = Path(config_path).resolve()
        CFG.update(json.loads(path.read_text(encoding="utf-8")))
        ROOT = path.parent
    ROOT = Path(os.environ.get("DESIGN_REGISTER_ROOT") or ROOT)
    REG, PROTO, INDEX = ROOT / CFG["register_dir"], ROOT / CFG["artifacts_dir"], ROOT / CFG["index_file"]


def load():
    out = {}
    for p in sorted(REG.glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def save(stem, rec):
    REG.mkdir(parents=True, exist_ok=True)
    (REG / f"{stem}.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def text_of(fragment):
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def figures(path):
    """[(id or None, caption title, visible text)] of the <figure> elements of an HTML file."""
    src = path.read_text(encoding="utf-8", errors="replace")
    found = []
    for attrs, body in FIGURE.findall(src):
        m = re.search(r'\bid="([^"]+)"', attrs)
        c = CAPTION.search(body)
        found.append((m.group(1) if m else None, text_of(c.group(1)) if c else "", text_of(body)))
    return found


def artifact_files():
    return {p.stem: p for p in sorted(PROTO.glob("*.html")) if p.name not in CFG["skip_files"]}


def decision_ids():
    if not CFG["decisions_dir"]:
        return None  # no decision records configured: ids are not validated
    return {p.stem for p in (ROOT / CFG["decisions_dir"]).glob(CFG["decisions_glob"]) if not p.name.startswith("_")}


def frame_refs(stem, rec):
    return {f"{stem}#{f['id']}" for f in rec.get("frames", [])}


def issues_of(rec, frame=None):
    got = set(rec.get("issues", []))
    if frame:
        got |= set(frame.get("issues", []))
    return got


def decisions_of(rec, frame=None):
    got = set(rec.get("decisions", []))
    if frame:
        got |= set(frame.get("decisions", []))
    return got


def line(stem, rec, frame=None):
    status = (frame or rec).get("status", rec.get("status", ""))
    ref = f"{stem}#{frame['id']}" if frame else stem
    title = (frame or rec).get("title", "")
    iss = " ".join(f"#{n}" for n in sorted(issues_of(rec, frame)))
    dec = " ".join(sorted(decisions_of(rec, frame)))
    extra = f"  design-ref {rec['design_ref']}" if rec.get("design_ref") and not frame else ""
    rep = f"  superseded by {', '.join(frame['replaced_by'])}" if frame and frame.get("replaced_by") else ""
    return f"{ref:<38} {status:<11} {title}  [{iss}] [{dec}]{extra}{rep}"


# ---------------------------------------------------------------- commands

def cmd_find(a):
    """Search the register, then the visible text of every artifact; map text hits to their frame."""
    reg = load()
    needle = a.text.lower()
    hits, seen = [], set()
    for stem, rec in reg.items():
        if needle in json.dumps(rec, ensure_ascii=False).lower() and not rec.get("frames"):
            hits.append((stem, None))
            seen.add(stem)
        for f in rec.get("frames", []):
            if needle in json.dumps(f, ensure_ascii=False).lower():
                hits.append((stem, f))
                seen.add(f"{stem}#{f['id']}")
    for stem, path in artifact_files().items():
        rec = reg.get(stem, {"status": "unregistered", "issues": [], "decisions": []})
        figs = figures(path)
        if figs:
            for fid, title, text in figs:
                if needle in text.lower() and f"{stem}#{fid}" not in seen:
                    f = next((x for x in rec.get("frames", []) if x["id"] == fid), {"id": fid or "?", "title": title})
                    hits.append((stem, f))
                    seen.add(f"{stem}#{fid}")
        elif stem not in seen and needle in text_of(path.read_text(encoding="utf-8", errors="replace")).lower():
            hits.append((stem, None))
            seen.add(stem)
    print(f"Searched: register ({CFG['register_dir']}/*.json) and the visible text of {CFG['artifacts_dir']}/*.html for {a.text!r}; external design exports are not searched.")
    if not hits:
        print("NOT FOUND. No wireframe or prototype names or shows this text. Only now say that no design exists.")
        return 0
    for stem, f in hits:
        print(line(stem, reg.get(stem, {"status": "unregistered"}), f))
    return 0


def cmd_for(a):
    """Artifacts that belong to one or more issue numbers or decision ids."""
    for key in a.keys:
        cmd_for_one(key)
    return 0


def cmd_for_one(key):
    reg = load()
    n = int(key.lstrip("#")) if re.fullmatch(r"#?\d+", key) else None
    rows = []
    for stem, rec in reg.items():
        record_decisions, record_issues = decisions_of(rec), issues_of(rec)
        if (n is not None and n in record_issues) or (n is None and key in record_decisions):
            rows.append(line(stem, rec))
        for f in rec.get("frames", []):
            if (n is not None and n in issues_of(rec, f) and n not in record_issues) or (n is None and key in decisions_of(rec, f) and key not in record_decisions):
                rows.append("  " + line(stem, rec, f))
    print("\n".join(rows) if rows else f"none registered for {key} (`{CFG['command']} find <text>` searches the artifacts themselves)")


def cmd_show(a):
    reg = load()
    stem, _, fid = a.ref.partition("#")
    rec = reg.get(stem) or die(f"no record {stem} in {CFG['register_dir']}/")
    if not fid:
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        return 0
    f = next((x for x in rec.get("frames", []) if x["id"] == fid), None) or die(f"no frame {a.ref}")
    print(json.dumps({"file": rec["file"], "frame": f, "inherits": {k: rec.get(k) for k in ("kind", "design_ref", "implementation", "issues", "decisions")}}, indent=2, ensure_ascii=False))
    return 0


def number_of(caption, position):
    m = re.match(r"(\d+)\.", caption)
    return int(m.group(1)) if m else position


def cmd_add(a):
    """Create missing records from the HTML files; give figures without an id one (f<caption number>) with --write-ids."""
    reg = load()
    added = []
    for stem, path in artifact_files().items():
        if a.files and path.name not in a.files and stem not in a.files:
            continue
        figs = figures(path)
        if a.write_ids and figs and any(fid is None for fid, _, _ in figs):
            src = path.read_text(encoding="utf-8")
            count = [0]

            def put(m):
                count[0] += 1
                attrs, body = m.group(1), m.group(2)
                if re.search(r'\bid="', attrs):
                    return m.group(0)
                c = CAPTION.search(body)
                num = number_of(text_of(c.group(1)) if c else "", count[0])
                return f'<figure id="f{num}"{attrs}>{body}</figure>'

            path.write_text(FIGURE.sub(put, src), encoding="utf-8")
            figs = figures(path)
        if stem in reg:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        title_match = re.search(r"<title>(.*?)</title>", source, re.S)
        rec = {
            "file": f"{CFG['artifacts_dir']}/{path.name}",
            "title": text_of(title_match.group(1)) if title_match else stem,
            "kind": "wireframe",
            "status": "proposed",
            "design_ref": None,
            "implementation": None,
            "issues": [],
            "decisions": [],
            "note": "",
            "frames": [{"id": fid, "title": re.sub(r"^\d+\.\s*", "", title), "status": "proposed"} for fid, title, _ in figs if fid],
        }
        save(stem, rec)
        added.append(stem)
    print("added: " + (", ".join(added) if added else "nothing (every file has a record)"))
    return 0


def code_problems(path):
    """Codes (matching `visible_code_pattern`) in the visible text of an artifact. Comments, ids and attributes are not checked."""
    if not CFG["visible_code_pattern"]:
        return []
    codes = re.compile(CFG["visible_code_pattern"])
    visible = text_of(re.sub(r"<!--.*?-->", " ", path.read_text(encoding="utf-8", errors="replace"), flags=re.S))
    return [f"{path.name}: code {m.group(0)!r} in the visible text ({visible[max(0, m.start() - 25):m.end() + 15]!r}): write it in words; the register links the issue and the decision" for m in codes.finditer(visible)]


def problems():
    reg = load()
    out = []
    known = decision_ids()
    files = artifact_files()
    index_page = PROTO / "index.html"
    if index_page.exists():
        out += code_problems(index_page)
    for stem in sorted(files):
        out += code_problems(files[stem])
        if stem not in reg:
            out.append(f"{stem}.html has no record: run `{CFG['command']} add {stem} --write-ids`, then fill in issues and decisions")
    for stem, rec in sorted(reg.items()):
        where = f"{CFG['register_dir']}/{stem}.json"
        if stem not in files:
            out.append(f"{where}: {CFG['artifacts_dir']}/{stem}.html does not exist")
            continue
        if rec.get("kind") not in KINDS:
            out.append(f"{where}: kind must be one of {sorted(KINDS)}")
        if rec.get("status") not in STATUSES:
            out.append(f"{where}: status must be one of {sorted(STATUSES)}")
        if rec.get("file") != f"{CFG['artifacts_dir']}/{stem}.html":
            out.append(f"{where}: file must be {CFG['artifacts_dir']}/{stem}.html")
        for d in rec.get("decisions", []):
            if known is not None and d not in known:
                out.append(f"{where}: unknown decision {d}")
        if rec.get("status") in ("proposed", "approved") and rec.get("kind") == "wireframe" and not rec.get("issues"):
            out.append(f"{where}: a {rec['status']} wireframe must name the issue(s) it belongs to")
        figs = figures(files[stem])
        html_ids = [fid for fid, _, _ in figs]
        if any(i is None for i in html_ids):
            out.append(f"{stem}.html: a <figure> has no id (`{CFG['command']} add {stem} --write-ids`)")
        if len({i for i in html_ids if i}) != len([i for i in html_ids if i]):
            out.append(f"{stem}.html: duplicate figure ids")
        rec_ids = [f["id"] for f in rec.get("frames", [])]
        for fid in sorted(set(i for i in html_ids if i) - set(rec_ids)):
            out.append(f"{where}: frame {fid} is in the HTML but not in the record")
        for fid in sorted(set(rec_ids) - set(html_ids)):
            out.append(f"{where}: frame {fid} is in the record but not in the HTML")
        for f in rec.get("frames", []):
            ref = f"{stem}#{f['id']}"
            if f.get("status") not in STATUSES:
                out.append(f"{ref}: status must be one of {sorted(STATUSES)}")
            for d in f.get("decisions", []):
                if known is not None and d not in known:
                    out.append(f"{ref}: unknown decision {d}")
            if f.get("status") == "superseded" and not f.get("replaced_by") and not f.get("removed_because"):
                out.append(f"{ref}: a superseded frame must name replaced_by (or removed_because when no frame takes its place)")
            for r in f.get("replaced_by", []):
                m = REF.match(r)
                other = reg.get(m.group(1)) if m else None
                if not other or r not in frame_refs(m.group(1), other):
                    out.append(f"{ref}: replaced_by {r} does not exist")
    return out, reg


def render(reg):
    cmd = CFG["command"]
    lines = ["# Design register", "",
             f"*Generated by `{cmd} index` from `{CFG['register_dir']}/*.json`. Never edit by hand; change the record and run the command.*", "",
             f"A frame is one `<figure id=\"fN\">` in a wireframe file; its reference is `file#fN`. Look up with `{cmd} find <text>`, `{cmd} for <issue>`, `{cmd} show <ref>`.", "",
             "| Artifact | Kind | Status | Design ref | Implementation | Issues | Decisions |", "|---|---|---|---|---|---|---|"]
    for stem, rec in reg.items():
        iss = " ".join(f"#{n}" for n in sorted(rec.get("issues", [])))
        lines.append(f"| `{stem}` | {rec['kind']} | {rec['status']} | {rec.get('design_ref') or ''} | {rec.get('implementation') or ''} | {iss} | {' '.join(sorted(rec.get('decisions', [])))} |")
    for stem, rec in reg.items():
        if not rec.get("frames"):
            continue
        lines += ["", f"## {stem}: frames", "", "| Frame | Title | Status | Issues | Decisions | Replaced by |", "|---|---|---|---|---|---|"]
        for f in rec["frames"]:
            iss = " ".join(f"#{n}" for n in sorted(f.get("issues", [])))
            lines.append(f"| `{stem}#{f['id']}` | {f['title']} | {f['status']} | {iss} | {' '.join(sorted(f.get('decisions', [])))} | {', '.join(f.get('replaced_by', []))} |")
    return "\n".join(lines) + "\n"


def cmd_index(a):
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(render(load()), encoding="utf-8")
    print(f"wrote {CFG['index_file']}")
    return 0


def cmd_check(a):
    out, reg = problems()
    if not INDEX.exists() or INDEX.read_text(encoding="utf-8") != render(reg):
        out.append(f"{CFG['index_file']} is out of date: run `{CFG['command']} index`")
    for p in out:
        print(p, file=sys.stderr)
    if not out:
        print(f"design register ok: {len(reg)} records, {sum(len(r.get('frames', [])) for r in reg.values())} frames")
    return 1 if out else 0


def main():
    ap = argparse.ArgumentParser(prog="register.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="configuration file (JSON); paths are relative to it")
    sp = ap.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("find")
    f.add_argument("text")
    f.set_defaults(fn=cmd_find)
    f = sp.add_parser("for")
    f.add_argument("keys", nargs="+")
    f.set_defaults(fn=cmd_for)
    f = sp.add_parser("show")
    f.add_argument("ref")
    f.set_defaults(fn=cmd_show)
    f = sp.add_parser("add")
    f.add_argument("files", nargs="*")
    f.add_argument("--write-ids", action="store_true")
    f.set_defaults(fn=cmd_add)
    f = sp.add_parser("index")
    f.set_defaults(fn=cmd_index)
    f = sp.add_parser("check")
    f.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    configure(a.config)
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()

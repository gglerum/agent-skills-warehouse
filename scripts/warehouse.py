#!/usr/bin/env python3
"""Local inventory, search, and explicit review recording. Standard library only."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
GROUPS = [
    "Discover and configure", "Requirements and planning", "Architecture and APIs",
    "Build and simplify", "Test and verify", "Debug and performance",
    "Review and security", "Ship and maintain", "Context, learning and handoff",
    "Integrations", "Source maintenance and evaluations",
]
MATURITY = re.compile(
    r"\b(experimental|beta|alpha|deprecated|archived|retired|unmaintained)\b"
    r"|\bin[- ]progress\b|\b(?:public|private|technical|early.access) preview\b",
    re.I,
)
EXCLUDED_PARTS = {"experimental", "in-progress", "archived", "deprecated", "retired", "alpha", "beta", "draft"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inside(path, parent):
    return path == parent or parent in path.parents


def local(root, value):
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Expected warehouse-relative path: {value}")
    target = root / path
    if not inside(target.resolve(), root.resolve()):
        raise ValueError(f"Path escapes warehouse: {value}")
    return target


def load(root):
    return json.loads((root / "warehouse.json").read_text())


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.PIPE
    )


def source_files(root, source):
    base = local(root, source["path"])
    if source.get("kind") == "warehouse-owned":
        # Local packages have no independent Git history. Fingerprint the whole
        # copy bundle; do not pretend the warehouse is an upstream repository.
        files = {}
        def walk(directory):
            for path in sorted(directory.iterdir()):
                if path.name in {".git", "__pycache__"} or path.suffix in {".pyc", ".pyo"}:
                    continue
                if path.is_symlink():
                    raise ValueError(f"Local package symlink: {path}")
                if path.is_dir():
                    walk(path)
                elif path.is_file():
                    data = (b"executable:" if path.stat().st_mode & 0o111 else b"file:") + path.read_bytes()
                    files[path.relative_to(root).as_posix()] = digest(data)
                else:
                    raise ValueError(f"Unsupported local package entry: {path}")
        walk(base)
        return files
    # Both tracked and untracked, honoring upstream ignore rules; never traverse .git.
    names = git(base, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    files = {}
    for name in sorted(set(os.fsdecode(n) for n in names.split(b"\0") if n)):
        path = base / name
        if not inside(path.resolve(), base.resolve()):
            raise ValueError(f"Source symlink escapes repository: {path}")
        if path.is_symlink():
            data = b"symlink:" + os.fsencode(os.readlink(path))
        elif path.is_file():
            data = (b"executable:" if path.stat().st_mode & 0o111 else b"file:") + path.read_bytes()
        elif not path.exists():
            continue  # A working-tree deletion changes the fingerprint and discovery.
        else:
            raise ValueError(f"Unsupported source entry: {path}")
        files[f"{source['path']}/{name}"] = digest(data)
    return files


def tree_digest(files):
    return digest(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())


def matches(path, prefix):
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def discover(root, sources, all_files):
    """Entry points, not every helper inside a bundle. Coverage is explicit."""
    candidates = set()
    for source in sources:
        sp = source["path"]
        for name in all_files[source["id"]]:
            rel = Path(name).relative_to(sp)
            parts = rel.parts
            if rel.name == "SKILL.md" or rel.suffix == ".mdc":
                candidates.add(name)
            if rel.name == "mcp.json" or ("agents" in parts and rel.suffix == ".md" and parts[0] != "docs"):
                candidates.add(name)
            if ".claude" in parts and "commands" in parts and rel.suffix == ".md":
                candidates.add(name)
            if parts[0] in {"references", "commands"} and rel.suffix in {".md", ".toml"}:
                candidates.add(name)
            if len(parts) >= 2 and parts[0] in {"scripts", "hooks", "evals", "docs"}:
                candidates.add(f"{sp}/{parts[0]}")
            if "hooks" in parts and rel.suffix == ".json":
                candidates.add(name)
            if "automations" in parts and rel.name == "README.md":
                candidates.add(str(Path(name).parent))
            if rel.name in {"plugin.json", "marketplace.json"}:
                candidates.add(name)
        for name in all_files[source["id"]]:
            if name.endswith("/marketplace.json"):
                data = json.loads(local(root, name).read_text())
                for plugin in data.get("plugins", []):
                    location = plugin.get("source")
                    if isinstance(location, str) and not re.match(r"https?:|git@", location):
                        # Marketplace paths are relative to source repository root.
                        path = local(root, f"{sp}/{location.removeprefix('./')}")
                        if path != local(root, sp):
                            candidates.add(path.relative_to(root).as_posix())
    return sorted(candidates)


def maturity_signals(root, files):
    signals = {}
    for name in files:
        path = Path(name)
        relevant = (path.name in {"README.md", "AGENTS.md", "CLAUDE.md", "SCOPE.md", "SKILL.md"}
                    or path.name in {"plugin.json", "marketplace.json"})
        if not relevant:
            continue
        text = local(root, name).read_text(errors="replace")
        hits = [f"{i}:{line.strip()}" for i, line in enumerate(text.splitlines(), 1) if MATURITY.search(line)]
        if EXCLUDED_PARTS.intersection(path.parts):
            hits.insert(0, "Path carries an excluded maturity label")
        if hits:
            signals[name] = {"sha256": digest("\n".join(hits).encode()), "lines": hits}
    return signals


def capture(root, cfg):
    file_maps = {s["id"]: source_files(root, s) for s in cfg["sources"]}
    sources = {}
    for s in cfg["sources"]:
        files = file_maps[s["id"]]
        sources[s["id"]] = {
            "revision": ("warehouse-owned" if s.get("kind") == "warehouse-owned" else
                         git(local(root, s["path"]), "rev-parse", "HEAD").decode().strip()),
            "tree_sha256": tree_digest(files), "files": len(files),
        }
    fingerprints = {}
    for a in cfg["assets"]:
        selected = {}
        for prefix in a["copy"] + a.get("related", []) + cfg["profiles"][a["profile"]].get("related", []):
            for files in file_maps.values():
                selected.update({n: h for n, h in files.items() if matches(n, prefix)})
        fingerprints[a["id"]] = tree_digest(selected)
    signals = maturity_signals(root, {n: h for files in file_maps.values() for n, h in files.items()})
    return {"sources": sources, "assets": fingerprints,
            "maturity": {n: v["sha256"] for n, v in signals.items()}}, discover(root, cfg["sources"], file_maps), signals


def validate(root, cfg, candidates, signals):
    errors = []
    if cfg.get("schema") != 1:
        errors.append("Unsupported warehouse schema")
    sources = {s["id"]: s for s in cfg["sources"]}
    if len(sources) != len(cfg["sources"]):
        errors.append("Duplicate source IDs")
    for s in sources.values():
        if s.get("kind", "git") not in {"git", "warehouse-owned"}:
            errors.append(f"Invalid source kind: {s['id']}")
        base = local(root, s["path"])
        if not base.is_dir() or base.resolve() == root.resolve():
            errors.append(f"Invalid source directory: {s['path']}")
        for other in sources.values():
            if other["id"] != s["id"] and matches(s["path"], other["path"]):
                errors.append(f"Overlapping source paths: {s['path']}, {other['path']}")
    ids = set()
    coverage = []
    for a in cfg["assets"]:
        if a["id"] in ids:
            errors.append(f"Duplicate asset ID: {a['id']}")
        ids.add(a["id"])
        if a["source"] not in sources or a["profile"] not in cfg["profiles"] or a["group"] not in GROUPS:
            errors.append(f"Invalid source, profile, or group: {a['id']}")
            continue
        coverage += a["copy"]
        paths = [a["path"], *a["copy"], *a.get("related", [])]
        for name in paths:
            if not local(root, name).exists():
                errors.append(f"Missing asset target: {a['id']}: {name}")
            if not matches(name, sources[a["source"]]["path"]):
                errors.append(f"Asset path outside its source: {a['id']}: {name}")
        if EXCLUDED_PARTS.intersection(Path(a["path"]).parts):
            errors.append(f"Eligible asset has excluded maturity label: {a['id']}")
    for a in cfg["assets"]:
        for alt in a.get("alternatives", []):
            if alt not in ids:
                errors.append(f"Unknown alternative: {a['id']}: {alt}")
    for p in cfg["profiles"].values():
        for name in p.get("related", []):
            if not local(root, name).exists():
                errors.append(f"Missing profile target: {name}")
    excluded = [e["path"] for e in cfg["exclusions"]]
    for name in excluded:
        if not local(root, name).exists():
            errors.append(f"Missing exclusion target: {name}")
        if any(matches(name, p) or matches(p, name) for p in coverage):
            errors.append(f"Eligible bundle overlaps exclusion: {name}")
    for variant in cfg["variants"]:
        for field in ["path", "canonical", "adapter"]:
            if not local(root, variant[field]).exists():
                errors.append(f"Missing variant {field}: {variant[field]}")
        if not any(matches(variant["canonical"], p) for p in coverage):
            errors.append(f"Variant has no canonical coverage: {variant['path']}")
    accounted = coverage + excluded + [v["path"] for v in cfg["variants"]]
    entry_paths = {a["path"] for a in cfg["assets"]}
    for name in candidates:
        if name not in entry_paths and not any(matches(name, p) for p in accounted):
            errors.append(f"Uncataloged entry point: {name}")
    old = cfg.get("review", {}).get("maturity", {})
    for name, value in signals.items():
        if old.get(name) != value["sha256"]:
            judgment = cfg.get("maturity_judgments", {}).get(name, {})
            if judgment.get("sha256") != value["sha256"] or not judgment.get("reason"):
                errors.append(f"Maturity signal needs contextual judgment: {name}")
    for route in cfg["routes"]:
        if not route["assets"] or any(a not in ids for a in route["assets"]):
            errors.append(f"Invalid task route: {route['task']}")
    return errors


def link(label, path):
    return f"[{label}]({path})"


def cell(value):
    return re.sub(r"\s+", " ", value).replace("|", "\\|")


def render(cfg):
    assets = {a["id"]: a for a in cfg["assets"]}
    out = ["# Warehouse catalog", "", "<!-- Generated by scripts/warehouse.py record-review. Edit warehouse.json. -->", "",
           f"Reviewed {cfg['reviewed_on']}. {len(assets)} entries; bundled helpers are not counted separately.", "",
           "Start with a task route, then read its entries and source. Eligible means no known disqualifying maturity marker at the recorded review, not certified stable. The catalog is a selection aid; follow [AGENTS.md](AGENTS.md) before copying.", "",
           "## Find by task", "", "| Task | Candidates | Choice |", "| --- | --- | --- |"]
    for r in cfg["routes"]:
        refs = ", ".join(link(assets[i]["name"], "#" + i) for i in r["assets"])
        out.append(f"| {cell(r['task'])} | {refs} | {cell(r['choice'])} |")
    out += ["", "## Sources and reviewed revisions", "", "| Source | Revision | Indexed files |", "| --- | --- | --- |"]
    for s in cfg["sources"]:
        snap = cfg["review"]["sources"][s["id"]]
        out.append(f"| {link(s['name'], s['url'])} (`{s['path']}/`) | `{snap['revision']}` | {snap['files']} |")
    out += ["", "## Dependency and compatibility profiles", "",
            "Each entry names a profile. Apply that profile along with the entry's notes. Related source paths are inspection pointers, not a promise that all dependencies have been resolved. Copy the listed bundle, inspect its links and invoked skills recursively, then adapt to the consuming project.", ""]
    for key, p in cfg["profiles"].items():
        out += [f"### {key}", "", p["text"], ""]
        if p.get("related"):
            out += ["Inspect: " + ", ".join(link(n, n) for n in p["related"]) + ".", ""]
    out += ["## Generated variants", ""]
    for v in cfg["variants"]:
        out += [f"- {link(v['path'], v['path'])} derives from {link(v['canonical'], v['canonical'])}. {v['notes']} Read the {link('adapter', v['adapter'])}."]
    out += ["", "## Eligible assets", "", "Descriptions summarize upstream metadata and reviewed notes. Tool availability and service access must be checked in the consuming environment. Full copied material retains its upstream license."]
    for group in GROUPS:
        rows = [a for a in cfg["assets"] if a["group"] == group]
        if not rows:
            continue
        out += ["", f"### {group}", "", "| Asset and when to consider it | Copy, inspect, and alternatives |", "| --- | --- |"]
        for a in sorted(rows, key=lambda a: (a["source"], a["name"], a["id"])):
            left = f"<a id=\"{a['id']}\"></a>{link(a['name'], a['path'])} ({a['source']}; {a['kind']}). {cell(a['description'])}"
            right = ("Copy: " + ", ".join(link(n, n) for n in a["copy"]) + "."
                     if a["copy"] else "Navigation only; select a leaf copy bundle.")
            right += f" Profile: [{a['profile']}](#{a['profile']})."
            if a.get("notes"):
                right += " " + cell(a["notes"])
            if a.get("related"):
                right += " Inspect: " + ", ".join(link(n, n) for n in a["related"]) + "."
            if a.get("alternatives"):
                right += " Compare: " + ", ".join(link(assets[n]["name"], "#" + n) for n in a["alternatives"]) + "."
            out.append(f"| {left} | {right} |")
    out += ["", "## Excluded material", "", "These paths are not candidates for adoption. Entries here document the boundary and its evidence.", "", "| Path | Reason |", "| --- | --- |"]
    out += [f"| {link(e['path'], e['path'])} | {cell(e['reason'])} |" for e in cfg["exclusions"]]
    out += ["", "## Validation", "", "Run `python3 scripts/warehouse.py check` for source drift and structural integrity. See [README.md](README.md#maintenance) for the review process and [validation/SMOKE.md](validation/SMOKE.md) for representative discovery/copy checks. No upstream agent workflow or live integration is certified by these checks.", ""]
    return "\n".join(out)


def catalog_links(root, text):
    errors = []
    anchors = set(re.findall(r'<a id="([^"]+)"', text))
    anchors.update(re.sub(r"[^\w -]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^#+ (.+)$", text, re.M))
    for target in re.findall(r"\]\(([^)]+)\)", text):
        url = urlsplit(target)
        if url.scheme or url.netloc:
            continue
        if not url.path:
            if url.fragment and unquote(url.fragment) not in anchors:
                errors.append(f"Missing catalog anchor: {target}")
        elif not local(root, unquote(url.path)).exists():
            errors.append(f"Missing catalog link: {target}")
    return errors


def run(root, args):
    cfg = load(root)
    if args.command == "search":
        words = re.findall(r"[\w-]+", args.query.lower())
        if not words:
            raise ValueError("Supply at least one search word")
        results = []
        for a in cfg["assets"]:
            text = json.dumps(a) + " " + cfg["profiles"][a["profile"]]["text"]
            if all(w in text.lower() for w in words):
                results.append(a)
        for a in results:
            print(f"{a['id']}: {a['name']} [{a['group']}]\n  {a['path']}\n  {a['description']}")
        print(f"{len(results)} matches. Read catalog profiles and source before copying.")
        return 0
    current, candidates, signals = capture(root, cfg)
    if args.command == "scan":
        print(json.dumps({"candidates": candidates, "maturity_signals": signals}, indent=2))
        return 0
    errors = validate(root, cfg, candidates, signals)
    if args.command == "record-review":
        datetime.date.fromisoformat(args.date)
        # Validate links before either output is changed.
        cfg["review"] = current
        cfg["reviewed_on"] = args.date
        text = render(cfg)
        errors += catalog_links(root, text)
        if not errors:
            (root / "warehouse.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
            (root / "CATALOG.md").write_text(text)
            print(f"Recorded explicit review: {len(cfg['assets'])} assets, {len(candidates)} entry points.")
            return 0
    else:
        reviewed = cfg.get("review", {})
        for sid, snap in current["sources"].items():
            if snap != reviewed.get("sources", {}).get(sid):
                errors.append(f"Source revision or content needs review: {sid}")
        for aid, sha in current["assets"].items():
            if sha != reviewed.get("assets", {}).get(aid):
                errors.append(f"Asset bundle needs review: {aid}")
        if current["maturity"] != reviewed.get("maturity", {}):
            errors.append("Maturity evidence changed; review scan output in context")
        text = render(cfg)
        if not (root / "CATALOG.md").exists() or (root / "CATALOG.md").read_text() != text:
            errors.append("CATALOG.md differs from reviewed metadata; review then record-review")
        errors += catalog_links(root, text)
    if errors:
        for error in errors:
            print("REVIEW: " + error)
        return 1
    print(f"OK: {len(cfg['sources'])} sources, {len(cfg['assets'])} assets, {len(candidates)} discovered entry points; no drift.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command")
    subs.add_parser("check", help="Read-only checks (default)")
    subs.add_parser("scan", help="Read-only JSON inventory and contextual maturity signals")
    search = subs.add_parser("search", help="Search eligible entries using all query words")
    search.add_argument("query")
    review = subs.add_parser("record-review", help="Explicitly record completed review and render catalog")
    review.add_argument("--date", required=True, help="Review date, YYYY-MM-DD")
    args = parser.parse_args()
    args.command = args.command or "check"
    try:
        return run(ROOT, args)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

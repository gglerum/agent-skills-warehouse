#!/usr/bin/env python3
"""Download the Apple Human Interface Guidelines (all pages) for offline use.

Developer tooling only; not part of the product. Uses the same public JSON
(DocC) endpoints that the HIG website itself loads, so no HTML scraping or
headless browser is needed. Standard library only.

Output (default ./hig-download, which is gitignored):
  json/<slug>.json   raw page payload (lossless)
  md/<slug>.md       Markdown rendering of each page
  images/...         only with --images
  index.json         navigation tree from Apple's index
  README.md          table of contents linking every page

Usage:
  python3 tools/hig_download.py [--out DIR] [--images] [--workers N] [--delay S]

Re-running skips pages already in json/ (use --refresh to refetch).
Content is (c) Apple Inc.; keep it for personal reference.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://developer.apple.com"
INDEX_URL = f"{BASE}/tutorials/data/index/design--human-interface-guidelines"
PAGE_URL = BASE + "/tutorials/data{path}.json"
HIG_PREFIX = "/design/human-interface-guidelines"
UA = "hig-offline-downloader/1.0 (personal reference copy)"


def fetch(url: str, retries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"failed after {retries} tries: {url}: {last}")


def walk(node: dict):
    yield node
    for c in node.get("children", []):
        yield from walk(c)


def slug_of(path: str) -> str:
    # "/design/human-interface-guidelines/buttons" -> "buttons"
    rest = path[len(HIG_PREFIX):].strip("/")
    return rest or "index"


# ---------------------------------------------------------------- rendering

class Renderer:
    def __init__(self, page: dict):
        self.refs = page.get("references", {})

    def link_for(self, ident: str) -> str | None:
        low = ident.lower()
        marker = "/design/human-interface-guidelines/"
        if "com.apple.hig" in low and marker in low:
            slug = low.split(marker, 1)[1].strip("/")
            return f"{slug}.md"
        ref = self.refs.get(ident, {})
        url = ref.get("url")
        if url and url.startswith("/"):
            return BASE + url
        return url

    def inline(self, items: list) -> str:
        out = []
        for it in items or []:
            t = it.get("type")
            if t == "text":
                out.append(it.get("text", ""))
            elif t == "strong":
                out.append(f"**{self.inline(it.get('inlineContent'))}**")
            elif t in ("emphasis", "newTerm"):
                out.append(f"*{self.inline(it.get('inlineContent'))}*")
            elif t == "codeVoice":
                out.append(f"`{it.get('code', '')}`")
            elif t == "reference":
                ident = it.get("identifier", "")
                title = (self.inline(it.get("overridingTitleInlineContent"))
                         or it.get("overridingTitle")
                         or self.refs.get(ident, {}).get("title", ident))
                href = self.link_for(ident)
                out.append(f"[{title}]({href})" if href else title)
            elif t == "image":
                ref = self.refs.get(it.get("identifier", ""), {})
                out.append(f"![{ref.get('alt', '')}]({self.image_path(ref)})")
            elif t == "superscript":
                out.append(f"<sup>{self.inline(it.get('inlineContent'))}</sup>")
            elif t == "subscript":
                out.append(f"<sub>{self.inline(it.get('inlineContent'))}</sub>")
            elif t == "strikethrough":
                out.append(f"~~{self.inline(it.get('inlineContent'))}~~")
            else:
                out.append(self.inline(it.get("inlineContent")) or it.get("text", ""))
        return "".join(out)

    @staticmethod
    def image_path(ref: dict) -> str:
        variants = ref.get("variants") or []
        pick = next((v for v in variants
                     if "light" in v.get("traits", []) and "2x" in v.get("traits", [])),
                    variants[0] if variants else None)
        if not pick:
            return ""
        return "../images" + pick["url"].split("/images/com.apple.HIG", 1)[-1]

    def blocks(self, blocks: list, indent: str = "") -> str:
        parts = []
        for b in blocks or []:
            r = self.block(b)
            if r:
                parts.append(r)
        text = "\n\n".join(parts)
        if indent:
            text = "\n".join(indent + l if l else l for l in text.split("\n"))
        return text

    def block(self, b: dict) -> str:
        t = b.get("type")
        if t == "paragraph":
            return self.inline(b.get("inlineContent"))
        if t == "heading":
            return f"{'#' * min(6, b.get('level', 2))} {b.get('text', '')}"
        if t in ("unorderedList", "orderedList"):
            lines = []
            for i, item in enumerate(b.get("items", []), 1):
                marker = "-" if t == "unorderedList" else f"{i}."
                body = self.blocks(item.get("content"), " " * (len(marker) + 1))
                lines.append(f"{marker} {body.lstrip()}")
            return "\n".join(lines)
        if t == "aside":
            name = b.get("name") or b.get("style", "Note").title()
            body = self.blocks(b.get("content"), "> ")
            return f"> **{name}**\n>\n{body}"
        if t == "codeListing":
            return f"```{b.get('syntax') or ''}\n" + "\n".join(b.get("code", [])) + "\n```"
        if t == "table":
            rows = b.get("rows", [])
            if not rows:
                return ""
            cells = [[self.blocks(c).replace("\n", " ") for c in row] for row in rows]
            head, *rest = cells
            lines = ["| " + " | ".join(head) + " |",
                     "|" + "---|" * len(head)]
            lines += ["| " + " | ".join(r) + " |" for r in rest]
            return "\n".join(lines)
        if t == "links":
            return "\n".join(f"- [{self.refs.get(i, {}).get('title', i)}]({self.link_for(i)})"
                             for i in b.get("items", []))
        if t == "thematicBreak":
            return "---"
        if t == "small":
            return self.inline(b.get("inlineContent"))
        if t == "row":
            return "\n\n".join(self.blocks(c.get("content")) for c in b.get("columns", []))
        # Unknown block: keep any text so nothing is silently lost.
        return self.blocks(b.get("content")) or self.inline(b.get("inlineContent"))

    def page(self, p: dict) -> str:
        title = p.get("metadata", {}).get("title", "")
        out = [f"# {title}"]
        abstract = self.inline(p.get("abstract"))
        if abstract:
            out.append(f"_{abstract}_" if abstract else "")
        for sec in p.get("primaryContentSections", []):
            out.append(self.blocks(sec.get("content")))
        for sec in p.get("topicSections", []):
            out.append(f"## {sec.get('title', 'Topics')}\n\n" + "\n".join(
                f"- [{self.refs.get(i, {}).get('title', i)}]({self.link_for(i)})"
                for i in sec.get("identifiers", [])))
        for sec in p.get("relatedSections", []) + p.get("seeAlsoSections", []):
            out.append(f"## {sec.get('title', 'Related')}\n\n" + "\n".join(
                f"- [{self.refs.get(i, {}).get('title', i)}]({self.link_for(i)})"
                for i in sec.get("identifiers", [])))
        return "\n\n".join(s for s in out if s).rstrip() + "\n"


# ------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--images", action="store_true", help="also download referenced images")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.1, help="seconds between requests per worker")
    ap.add_argument("--refresh", action="store_true", help="refetch pages already downloaded")
    args = ap.parse_args()

    out: Path = args.out
    (out / "json").mkdir(parents=True, exist_ok=True)
    (out / "md").mkdir(exist_ok=True)

    index = json.loads(fetch(INDEX_URL))
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")

    nodes = {}
    for root in index["interfaceLanguages"]["swift"]:
        for n in walk(root):
            if n.get("path", "").startswith(HIG_PREFIX):
                nodes[n["path"]] = n
    print(f"{len(nodes)} pages in index", file=sys.stderr)

    def get_page(path: str) -> tuple[str, dict]:
        f = out / "json" / f"{slug_of(path)}.json"
        if f.exists() and not args.refresh:
            return path, json.loads(f.read_text(encoding="utf-8"))
        time.sleep(args.delay)
        raw = fetch(PAGE_URL.format(path=path))
        f.write_bytes(raw)
        return path, json.loads(raw)

    pages: dict[str, dict] = {}
    failures: list[str] = []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(get_page, p): p for p in nodes}
        for i, fut in enumerate(as_completed(futs), 1):
            p = futs[fut]
            try:
                _, data = fut.result()
                pages[p] = data
            except Exception as e:  # report, keep going
                failures.append(f"{p}: {e}")
            if i % 20 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)}", file=sys.stderr)

    image_urls: set[str] = set()
    for path, data in pages.items():
        r = Renderer(data)
        (out / "md" / f"{slug_of(path)}.md").write_text(r.page(data), encoding="utf-8")
        for ref in data.get("references", {}).values():
            if ref.get("type") == "image":
                for v in ref.get("variants", []):
                    image_urls.add(v["url"])

    toc = ["# Apple Human Interface Guidelines (offline copy)\n",
           f"Downloaded {time.strftime('%Y-%m-%d')} from {BASE}{HIG_PREFIX}/\n"]

    def toc_walk(n: dict, depth: int):
        p = n.get("path", "")
        if p.startswith(HIG_PREFIX) and p in pages:
            toc.append(f"{'  ' * depth}- [{n.get('title', slug_of(p))}](md/{slug_of(p)}.md)")
        for c in n.get("children", []):
            toc_walk(c, depth + (1 if p.startswith(HIG_PREFIX) else 0))

    for root in index["interfaceLanguages"]["swift"]:
        toc_walk(root, 0)
    (out / "README.md").write_text("\n".join(toc) + "\n", encoding="utf-8")

    if args.images:
        print(f"downloading {len(image_urls)} images", file=sys.stderr)

        def get_img(url: str):
            dest = out / "images" / url.split("/images/com.apple.HIG/", 1)[-1]
            if dest.exists():
                return
            dest.parent.mkdir(parents=True, exist_ok=True)
            time.sleep(args.delay)
            dest.write_bytes(fetch(BASE + url))

        with ThreadPoolExecutor(args.workers) as ex:
            for url, fut in [(u, ex.submit(get_img, u)) for u in sorted(image_urls)]:
                try:
                    fut.result()
                except Exception as e:
                    failures.append(f"{url}: {e}")

    print(f"done: {len(pages)}/{len(nodes)} pages -> {out}", file=sys.stderr)
    if failures:
        print("FAILURES:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

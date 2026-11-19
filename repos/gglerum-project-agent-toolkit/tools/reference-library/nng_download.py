#!/usr/bin/env python3
"""Download a CURATED list of NN/g articles for private offline reference (not the whole site).

Developer tooling only; not part of the product. Standard library only.
Polite by construction: reads robots.txt and refuses disallowed URLs, honours its Crawl-Delay (60 s at the time of writing;
--delay can only raise it), identifies itself honestly, one request at a time, skips pages already downloaded, stops on
HTTP 403/429. NN/g content is (c) Nielsen Norman Group, all rights reserved; their policy forbids republishing articles
without a licence. The copy is gitignored and for personal reference only; never commit it, and paraphrase + link in repo
files you maintain.

Usage:
  python3 tools/nng_download.py [--list tools/nng-articles.txt] [--out DIR] [--delay S] [--limit N] [--refresh] [--dry-run]
Both --list and --out are explicit. Output:
  html/<slug>.html   raw page (so extraction can be re-run without refetching)
  md/<slug>.md       title, author/date, URL, retrieved date, body as Markdown
  index.md           table of contents
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as htmllib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path

UA = "ProjectAgentToolkit/1.0 (personal offline reference; honours robots.txt and Crawl-Delay)"
BASE = "https://www.nngroup.com"
STOP_H2 = ("related topics", "learn more", "related articles", "never miss an update", "follow us", "references", "related courses", "free downloads")
SKIP_TAGS = {"script", "style", "svg", "nav", "aside", "button", "form", "figure", "img", "video", "iframe", "noscript"}
SKIP_CLASS = ("table-of-contents", "article-toc", "article-share", "related-content", "article-sidebar")


class Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta = ""
        self.out: list[str] = []
        self.in_h1 = False
        self.in_header = False
        self.in_body = False
        self.stopped = False
        self.skip = 0            # nesting depth of a skipped subtree
        self.stack: list[tuple[str, bool]] = []
        self.buf = ""
        self.mode = ""           # current block kind
        self.header_text = []

    def _cls(self, attrs):
        return dict(attrs).get("class", "") or ""

    def handle_starttag(self, tag, attrs):
        cls = self._cls(attrs)
        skipping = tag in SKIP_TAGS or any(c in cls for c in SKIP_CLASS)
        self.stack.append((tag, skipping))
        if skipping or self.skip:
            self.skip += 1
            return
        if tag == "div" and "article-header" in cls:
            self.in_header = True
        if tag == "div" and "article-body" in cls:
            self.in_body = True
        if tag == "h1" and "article-h1" in cls:
            self.in_h1 = True
        if self.in_body and not self.stopped:
            if tag in ("h2", "h3", "h4", "p", "li", "blockquote"):
                self.flush()
                self.mode = tag
            elif tag in ("strong", "b"):
                self.buf += "**"
            elif tag in ("em", "i"):
                self.buf += "*"
            elif tag == "br":
                self.buf += " "

    def handle_endtag(self, tag):
        if not self.stack:
            return
        while self.stack:
            t, sk = self.stack.pop()
            if sk or self.skip:
                self.skip = max(0, self.skip - 1) if (sk or self.skip) else 0
            if t == tag:
                break
        if self.skip:
            return
        if tag == "h1":
            self.in_h1 = False
        if self.in_body and not self.stopped:
            if tag in ("strong", "b"):
                self.buf += "**"
            elif tag in ("em", "i"):
                self.buf += "*"
            elif tag in ("h2", "h3", "h4", "p", "li", "blockquote"):
                self.flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_h1:
            self.title += data
        elif self.in_header and not self.in_body:
            self.header_text.append(data.strip())
        elif self.in_body and not self.stopped:
            self.buf += data

    def flush(self):
        text = re.sub(r"\s+", " ", self.buf).strip().replace("** **", " ").replace("****", "")
        self.buf = ""
        mode, self.mode = self.mode, ""
        if not text:
            return
        if mode in ("h2", "h3", "h4"):
            if mode == "h2" and text.lower().rstrip(":") in STOP_H2 or text.lower().startswith("in this article"):
                if text.lower().startswith("in this article"):
                    return
                self.stopped = True
                return
            self.out.append("\n" + "#" * int(mode[1]) + " " + text.strip("*") + "\n")
        elif mode == "li":
            self.out.append("- " + text)
        elif mode == "blockquote":
            self.out.append("> " + text)
        else:
            self.out.append(text + "\n")


def to_markdown(raw: str, url: str, retrieved: str) -> tuple[str, str]:
    p = Extract()
    p.feed(raw)
    p.flush()
    title = re.sub(r"\s+", " ", htmllib.unescape(p.title)).strip() or url.rstrip("/").rsplit("/", 1)[-1]
    head = " ".join(t for t in p.header_text if t)
    iso = re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", head)
    byline = next((t for t in p.header_text if t and not re.match(r"(Summary|Share|Email)", t) and not re.search(r"\d{4}", t)), "")[:80]
    md = f"# {title}\n\n_Source: {url}  |  published {iso[0] if iso else 'n/a'}  |  {byline}  |  retrieved {retrieved}_\n_(c) Nielsen Norman Group, all rights reserved. Private offline reference; do not republish._\n\n" + "\n".join(p.out).strip() + "\n"
    return title, md


def read_list(path: Path):
    items = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        url, _, keys = [x.strip() for x in ln.partition("|")]
        if not url.startswith(BASE + "/articles/"):
            print(f"skip (not an nngroup.com article URL): {url}", file=sys.stderr)
            continue
        items.append((url, keys))
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests; never below robots.txt Crawl-Delay")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    items = read_list(Path(a.list))
    rp = urllib.robotparser.RobotFileParser(BASE + "/robots.txt")
    rp.read()
    delay = max(float(rp.crawl_delay(UA) or 0), a.delay)
    todo = [(u, k) for u, k in items if a.refresh or not (out / "html" / (u.rstrip("/").rsplit("/", 1)[-1] + ".html")).exists()]
    if a.limit:
        todo = todo[: a.limit]
    blocked = [u for u, _ in todo if not rp.can_fetch(UA, u)]
    print(f"listed {len(items)}, to fetch {len(todo)}, crawl delay {delay:.0f}s (about {len(todo) * delay / 60:.0f} min), out {out}")
    if blocked:
        print("robots.txt disallows: " + ", ".join(blocked), file=sys.stderr)
        todo = [(u, k) for u, k in todo if u not in blocked]
    if a.dry_run:
        for u, k in todo:
            print("  would fetch", u)
        return 0
    (out / "html").mkdir(parents=True, exist_ok=True)
    (out / "md").mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    failed = bool(blocked)
    first = True
    for u, _ in todo:
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        if not first:
            time.sleep(delay)
        first = False
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html"})
            raw = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            failed = True
            print(f"{slug}: HTTP {e.code}", file=sys.stderr)
            if e.code in (403, 429):
                print("stopping: the site asked us to back off", file=sys.stderr)
                break
            continue
        except Exception as e:                      # network error: skip, keep going
            failed = True
            print(f"{slug}: {e}", file=sys.stderr)
            continue
        (out / "html" / f"{slug}.html").write_text(raw, encoding="utf-8")
        title, md = to_markdown(raw, u, today)
        (out / "md" / f"{slug}.md").write_text(md, encoding="utf-8")
        print(f"ok {slug}: {title[:70]} ({len(md)} chars)", flush=True)
    # index from whatever is on disk
    rows = []
    for u, k in items:
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        f = out / "md" / f"{slug}.md"
        if f.exists():
            rows.append(f"- [{f.read_text(encoding='utf-8').splitlines()[0][2:]}](md/{slug}.md)  keys: {k}")
    (out / "index.md").write_text("# NN/g offline copy (curated)\n\nPrivate reference; (c) Nielsen Norman Group.\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

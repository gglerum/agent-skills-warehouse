#!/usr/bin/env python3
"""Compact read-only Asana views for Claude, so the model ingests only what it needs.

Reads the REST API directly and prints a bounded subset of task fields.
No performance or token-saving guarantee is made for other workloads.

Needs ASANA_TOKEN (personal access token) in the environment. GET only; writes stay on the MCP.

  asana.py [--project GID] open [--section NAME] [--ours]
                                                     open tasks: gid | section | assignee | name
                                                     --ours: only configured ownership items (name prefix or Epic/Featured field),
                                                     without Voorstel:/On hold:; unmarked bugs are counted on stderr
  asana.py [--project GID] find TEXT [--all]                       tasks whose name contains TEXT (--all includes completed)
  asana.py task GID [--notes N] [--comments N]       one task; notes cut at N chars (default 1500), last N comments (default 0)
  asana.py stories GID [--last N]                    last N comments of a task (default 5), cut at 400 chars
"""
import argparse
import contextlib
import contextvars
import io
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None

def open_request(req, timeout):
    return urllib.request.build_opener(NoRedirect).open(req, timeout=timeout)


BASE = "https://app.asana.com/api/1.0"
DEFAULT_PROJECT = os.environ.get("ASANA_PROJECT_ID", "")
DEFAULT_TIMEOUT = 120
REQUEST_TIMEOUT = 30
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
DEADLINE = contextvars.ContextVar("asana_deadline", default=None)


class ReaderError(Exception):
    """A safe, bounded diagnostic; remote bodies and credentials never enter output."""

    def __init__(self, message, state="INCOMPLETE"):
        super().__init__(message)
        self.state = state


def remaining() -> float:
    deadline = DEADLINE.get()
    seconds = deadline - time.monotonic() if deadline is not None else REQUEST_TIMEOUT
    if seconds <= 0:
        raise ReaderError("operation deadline exceeded")
    return min(seconds, REQUEST_TIMEOUT)


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be finite and > 0")
    return seconds


def count(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError('must be >= 0')
    return n


def get(path: str, params: dict | None = None) -> dict:
    token = os.environ.get("ASANA_TOKEN")
    if not token:
        raise ReaderError("ASANA_TOKEN is not set", "ERROR")
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with open_request(req, timeout=remaining()) as response:
            chunks, size = [], 0
            while True:
                remaining()
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ReaderError("response exceeds byte limit")
            raw = b"".join(chunks)
        remaining()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ReaderError("response exceeds byte limit")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ReaderError("invalid response object")
        return data
    except urllib.error.HTTPError as error:
        state = "ERROR" if error.code in (400, 401, 403, 404) else "INCOMPLETE"
        raise ReaderError(f"Asana HTTP {error.code}; no retry performed", state) from None
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        raise ReaderError("Asana request failed or timed out; no retry performed") from None
    except (ValueError, UnicodeError):
        raise ReaderError("invalid JSON response") from None


def paged(path: str, params: dict) -> list:
    # Direct callers get the same operation budget as the CLI.
    if DEADLINE.get() is None:
        token = DEADLINE.set(time.monotonic() + DEFAULT_TIMEOUT)
        try:
            return paged(path, params)
        finally:
            DEADLINE.reset(token)
    items: list = []
    identities = set()
    params = {**params, "limit": 100}
    seen = {params.get("offset")}
    for _ in range(MAX_PAGES):
        remaining()
        data = get(path, params)
        remaining()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ReaderError("invalid page data")
        if any(not isinstance(item, dict) for item in data["data"]):
            raise ReaderError("invalid page item")
        gids = [item.get('gid') for item in data['data']]
        if any(not isinstance(gid, str) or not gid for gid in gids) or len(set(gids)) != len(gids) or identities.intersection(gids):
            raise ReaderError('missing or repeated item identity')
        identities.update(gids)
        items += data["data"]
        page = data.get("next_page")
        if page is None:
            return items
        offset = page.get("offset") if isinstance(page, dict) else None
        if not isinstance(offset, str) or not offset or offset in seen:
            raise ReaderError("invalid or repeated pagination offset")
        seen.add(offset)
        params["offset"] = offset
    raise ReaderError("pagination page limit exceeded")


def clip(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + f"… [+{len(text) - limit} chars]"


def section_of(task: dict, project: str) -> str:
    for m in task.get("memberships") or []:
        if (m.get("project") or {}).get("gid") == project:
            return (m.get("section") or {}).get("name", "-")
    return "-"


OURS = re.compile(os.environ.get("ASANA_OWNERSHIP_PATTERN", r"(?!)"), re.IGNORECASE)
BUGS_SECTION = os.environ.get("ASANA_BUGS_SECTION", "Bugs")


def is_ours(task: dict) -> bool:
    """configured ownership item per CLAUDE.md: name prefix, or custom field Epic/Featured mentions it."""
    if OURS.match(task["name"]):
        return True
    for f in task.get("custom_fields") or []:
        if f.get("name") in tuple(os.environ.get("ASANA_OWNERSHIP_FIELDS", "Epic,Featured").split(",")) and OURS.search(f.get("display_value") or ""):
            return True
    return False


def is_skipped(task: dict) -> bool:
    return task["name"].strip().lower().startswith(tuple(x.strip().lower() for x in os.environ.get("ASANA_SKIP_PREFIXES", "proposal:,on hold:").split(",") if x.strip()))


def task_rows(project: str, include_completed: bool, custom_fields: bool = False) -> list:
    fields = "name,completed,assignee.name,memberships.project.gid,memberships.section.name"
    if custom_fields:
        fields += ",custom_fields.name,custom_fields.display_value"
    params = {"project": project, "opt_fields": fields}
    if not include_completed:
        params["completed_since"] = "now"
    return paged("/tasks", params)


def cmd_open(a) -> None:
    rows = task_rows(a.project, False, a.ours)
    shown = 0
    unmarked_bugs = 0
    for t in sorted(rows, key=lambda t: section_of(t, a.project)):
        if a.ours and (not is_ours(t) or is_skipped(t)):
            if BUGS_SECTION in section_of(t, a.project) and not is_skipped(t):
                unmarked_bugs += 1
            continue
        section = section_of(t, a.project)
        if a.section and a.section.lower() not in section.lower():
            continue
        who = (t.get("assignee") or {}).get("name", "-")
        print(f"{t['gid']} | {section} | {who} | {clip(t['name'], 110)}")
        shown += 1
    print(f"# {shown} of {len(rows)} open tasks", file=sys.stderr)
    if unmarked_bugs:
        print(f"# {unmarked_bugs} unmarked in '{BUGS_SECTION}…' hidden (ask when unsure: `open --section {BUGS_SECTION}`)", file=sys.stderr)


def cmd_find(a) -> None:
    needle = a.text.lower()
    for t in task_rows(a.project, a.all):
        if needle in t["name"].lower():
            state = "done" if t.get("completed") else section_of(t, a.project)
            print(f"{t['gid']} | {state} | {clip(t['name'], 140)}")


def comments(gid: str, last: int) -> list:
    if not last:
        return []
    stories = paged(f"/tasks/{gid}/stories", {"opt_fields": "type,created_at,created_by.name,text"})
    return [s for s in stories if s.get("type") == "comment"][-last:] if last else []


def cmd_task(a) -> None:
    t = get(f"/tasks/{a.gid}", {"opt_fields": "name,completed,due_on,permalink_url,assignee.name,notes,memberships.project.gid,memberships.section.name"})["data"]
    print(f"{t['gid']} | {section_of(t, a.project)} | {(t.get('assignee') or {}).get('name', '-')} | due {t.get('due_on') or '-'} | {'done' if t['completed'] else 'open'}")
    print(t["name"])
    print(t.get("permalink_url", ""))
    print(clip(t.get("notes"), a.notes))
    for s in comments(a.gid, a.comments):
        print(f"--- {s['created_at'][:10]} {(s.get('created_by') or {}).get('name', '?')}: {clip(s.get('text'), 400)}")


def cmd_stories(a) -> None:
    for s in comments(a.gid, a.last):
        print(f"{s['created_at'][:10]} {(s.get('created_by') or {}).get('name', '?')}: {clip(s.get('text'), 400)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default=DEFAULT_PROJECT)
    p.add_argument("--timeout", type=positive_seconds, default=DEFAULT_TIMEOUT,
                   help="whole-operation budget in seconds (default 120); each request <=30 seconds")
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open"); o.add_argument("--section"); o.add_argument("--ours", action="store_true"); o.set_defaults(fn=cmd_open)
    f = sub.add_parser("find"); f.add_argument("text"); f.add_argument("--all", action="store_true"); f.set_defaults(fn=cmd_find)
    t = sub.add_parser("task"); t.add_argument("gid"); t.add_argument("--notes", type=count, default=1500); t.add_argument("--comments", type=count, default=0); t.set_defaults(fn=cmd_task)
    s = sub.add_parser("stories"); s.add_argument("gid"); s.add_argument("--last", type=count, default=5); s.set_defaults(fn=cmd_stories)
    a = p.parse_args(argv)
    if a.cmd in ('open', 'find') and not a.project.isdigit():
        p.error('provide numeric --project or ASANA_PROJECT_ID')
    if getattr(a, 'ours', False) and not os.environ.get('ASANA_OWNERSHIP_PATTERN'):
        p.error('--ours requires ASANA_OWNERSHIP_PATTERN; no ownership inferred')
    token = DEADLINE.set(time.monotonic() + a.timeout)
    out, err = io.StringIO(), io.StringIO()
    try:
        # Publish only after every decision page and requested comment has arrived.
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            a.fn(a)
        remaining()
    except ReaderError as error:
        print(f"# {error.state}: {error}. Check https://app.asana.com/0/{a.project}/list", file=sys.stderr)
        return 6 if error.state == "ERROR" else 5
    except (KeyError, TypeError, ValueError, AttributeError):
        print(f"# INCOMPLETE: invalid response fields. Check https://app.asana.com/0/{a.project}/list", file=sys.stderr)
        return 5
    finally:
        DEADLINE.reset(token)
    print(out.getvalue(), end="")
    print(err.getvalue(), end="", file=sys.stderr)
    print("# COMPLETE: requested data fetched; display filters and marked text clipping may apply", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

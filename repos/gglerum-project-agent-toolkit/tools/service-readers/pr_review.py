#!/usr/bin/env python3
"""Read-only, fail-closed merge gate. Usage: pr_review.py [<pr-number>].

Exit 0: complete readiness evidence; 1: not ready; 2: failed/malformed evidence.
Requires exact Jenkins context, same-head successful build and executed stages,
current SHA-bound approval, no later ambiguous conversation, and stable snapshots.
GET only; never merges. Same-login approval cannot prove human provenance.
"""
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import urllib.error
import urllib.request
from datetime import datetime
import toolchain_config
import ci_status

REPO = toolchain_config.get("GITHUB_REPO", "")
BASE = toolchain_config.get("BASE_BRANCH", "main")
CONTEXT = toolchain_config.get("JENKINS_CONTEXT", "continuous-integration/jenkins/pr-head")
SHA = re.compile(r"[0-9a-f]{40}")
APPROVAL = re.compile(r"(approved?|merge( it)?|approved?,? *merge)[.! ]*", re.IGNORECASE)
GENERATED = re.compile(r"generated with.*claude code", re.IGNORECASE | re.DOTALL)
FIELDS = "number,state,isDraft,mergeable,author,baseRefName,headRefOid,headRefName"


def fail(message: str) -> None:
    print(message[:400], file=sys.stderr)
    sys.exit(2)


def gh(*args: str) -> str:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              check=True, timeout=60).stdout
    except FileNotFoundError:
        fail("gh is not installed")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        fail("gh request failed or timed out; evidence incomplete")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def obj(value):
    require(isinstance(value, dict), "expected an object")
    return value


def text_field(item, key):
    value = obj(item).get(key)
    require(isinstance(value, str) and bool(value), f"missing/invalid {key}")
    return value


def timestamp(value):
    require(isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value)),
            "missing/invalid UTC timestamp")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value


def api(path: str) -> list:
    """All array pages; never treat an error object as a comment page."""
    pages = json.loads(gh("api", "--paginate", "--slurp", path + "?per_page=100"))
    require(isinstance(pages, list) and bool(pages), "missing API pages")
    require(all(isinstance(page, list) for page in pages), "invalid API array page")
    items = [item for page in pages for item in page]
    ids = [obj(item).get("id") for item in items]
    require(all(type(i) is int and i > 0 for i in ids) and len(ids) == len(set(ids)),
            "invalid or repeated API item IDs")
    return items


def status_for(head):
    pages = json.loads(gh("api", "--paginate", "--slurp",
                          f"repos/{REPO}/commits/{head}/status?per_page=100"))
    require(isinstance(pages, list) and bool(pages), "missing status pages")
    first = obj(pages[0])
    statuses = []
    for page in pages:
        page = obj(page)
        require(page.get("sha") == head, "status SHA mismatch")
        require(page.get("state") in ("success", "pending", "failure", "error"), "invalid combined status")
        require(type(page.get("total_count")) is int and page["total_count"] >= 0,
                "invalid status count")
        require(page["state"] == first["state"] and page["total_count"] == first["total_count"],
                "status changed during pagination")
        require(isinstance(page.get("statuses"), list), "invalid statuses")
        statuses.extend(page["statuses"])
    require(len(statuses) == first["total_count"], "incomplete status pagination")
    contexts = [text_field(s, "context") for s in statuses]
    require(len(contexts) == len(set(contexts)), "duplicate status contexts")
    for status in statuses:
        require(status.get("state") in ("success", "pending", "failure", "error"), "invalid context state")
    return {"sha": head, "state": first["state"], "statuses": statuses}


def login(item: dict) -> str:
    user = item.get("user")
    if user is None:
        return "ghost"
    return text_field(user, "login")


def when(item: dict) -> str:
    return item.get("updated_at") or item.get("submitted_at") or item.get("created_at") or ""


def is_approval(body: str | None, head: str | None = None) -> bool:
    if not isinstance(body, str) or GENERATED.search(body):
        return False
    body = body.strip()
    if head and body.endswith(" " + head):
        body = body[:-len(head)].strip()
    return bool(APPROVAL.fullmatch(body))


def validate(pr, status, reviews, comments, inline):
    for key in ("state", "baseRefName", "headRefOid"):
        text_field(pr, key)
    text_field(obj(pr).get("author"), "login")
    require(bool(SHA.fullmatch(pr["headRefOid"])), "invalid head SHA")
    require(type(pr.get("isDraft")) is bool, "invalid draft state")
    require(status.get("sha") == pr["headRefOid"], "status SHA mismatch")
    require(status.get("state") in ("success", "pending", "failure", "error"), "invalid status state")
    require(isinstance(status.get("statuses"), list), "invalid statuses")
    for s in status["statuses"]:
        text_field(s, "context")
        require(s.get("state") in ("success", "pending", "failure", "error"), "invalid context state")
    for items in (reviews, comments, inline):
        require(isinstance(items, list), "invalid review/comment array")
        for item in items:
            obj(item)
            require("user" in item, "missing review/comment user")
            login(item)
            require(type(item.get("id")) is int and item["id"] > 0, "invalid comment/review ID")
            require("body" in item and (item["body"] is None or isinstance(item["body"], str)), "invalid body")
            if "updated_at" in item:
                timestamp(item["updated_at"])
            timestamp(when(item))
            original = timestamp(item.get("submitted_at") or item.get("created_at"))
            require(when(item) >= original, "updated timestamp precedes creation/submission")
    for r in reviews:
        require(r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING"),
                "invalid review state")
        require(isinstance(r.get("commit_id"), str) and bool(SHA.fullmatch(r["commit_id"])),
                "invalid review commit")
    roots = {c["id"] for c in inline if not c.get("in_reply_to_id")}
    for c in inline:
        require(not c.get("in_reply_to_id") or c["in_reply_to_id"] in roots, "orphan inline reply")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def jenkins_get(url, json_body=True):
    try:
        raw = ci_status.jenkins_get(url)
        require(raw is not None, "missing Jenkins endpoint")
        return json.loads(raw) if json_body else raw
    except ci_status.ReaderError:
        raise ValueError("Jenkins evidence unavailable") from None


def jenkins_evidence(pr, status):
    context = next((s for s in status["statuses"] if s["context"] == CONTEXT), None)
    if not context or context["state"] != "success":
        return None
    trusted = toolchain_config.get("JENKINS_URL", "").rstrip("/")
    job = toolchain_config.get("JENKINS_JOB_PATH", "")
    required = [s.strip() for s in toolchain_config.get("REQUIRED_STAGES", "").split(",") if s.strip()]
    require(bool(job) and bool(re.fullmatch(r"(?:job/[A-Za-z0-9_.%~-]+/)*job/[A-Za-z0-9_.%~-]+", job)), "configure JENKINS_JOB_PATH")
    require(bool(required) and len(required) == len(set(required)), "configure distinct REQUIRED_STAGES")
    url = text_field(context, "target_url")
    base, number = ci_status.trusted_build_url(url)
    prefix = f"{trusted}/{job}/job/PR-{pr['number']}/"
    require(base == prefix + str(number), "unexpected Jenkins PR/job/build URL")
    build = obj(jenkins_get(base + "/api/json"))
    flow = obj(jenkins_get(base + "/wfapi/describe"))
    require(type(build.get("building")) is bool, "missing Jenkins building state")
    require(build.get("number") == number and str(flow.get("id")) == str(number), "Jenkins build mismatch")
    require(isinstance(build.get("actions"), list), "missing Jenkins revision actions")
    revisions = [a["lastBuiltRevision"].get("SHA1") for a in build["actions"]
                 if isinstance(a, dict) and isinstance(a.get("lastBuiltRevision"), dict)]
    require(bool(revisions) and all(s == pr["headRefOid"] for s in revisions), "Jenkins revision mismatch")
    require(isinstance(flow.get("stages"), list) and bool(flow["stages"]), "missing Jenkins stages")
    stages = {}
    for stage in flow['stages']:
        name = text_field(stage, 'name')
        require(name not in stages, 'duplicate Jenkins stage')
        stages[name] = text_field(stage, 'status')
    return {"sha": pr['headRefOid'], "url": base,
            "success": build.get('result') == 'SUCCESS' and build['building'] is False
            and flow.get('status') == 'SUCCESS'
            and all(stages.get(s) == 'SUCCESS' for s in required)}


def evaluate(pr: dict, status: dict, reviews: list, issue_comments: list,
             inline: list, evidence=None) -> tuple:
    """Return readiness, blockers, approval. Invalid evidence raises ValueError (exit 2)."""
    validate(pr, status, reviews, issue_comments, inline)
    author, head = pr["author"]["login"], pr["headRefOid"]
    reasons = []
    if pr["state"] != "OPEN":
        reasons.append(f"PR is {pr['state']}")
    if pr["isDraft"]:
        reasons.append("PR is a draft")
    if pr.get("mergeable") != "MERGEABLE":
        reasons.append(f"mergeable is {pr.get('mergeable')}")
    if pr["baseRefName"] != BASE:
        reasons.append(f"targets {pr['baseRefName']}, not {BASE}")
    if status["state"] != "success":
        reasons.append(f"head status is {status['state']}")
    expected = [s for s in status["statuses"] if s["context"] == CONTEXT]
    if len(expected) != 1 or expected[0]["state"] != "success":
        reasons.append(f"missing successful {CONTEXT} on checked head")
    if not evidence or evidence.get("sha") != head or evidence.get("success") is not True:
        reasons.append("missing successful same-head Jenkins build/stage evidence")

    latest = {}
    for r in sorted(reviews, key=lambda r: (when(r), r["id"])):
        if r["state"] not in ("COMMENTED", "PENDING"):
            latest[login(r)] = r
    approvals = []
    for r in reviews:
        body = r.get("body") or ""
        if r["state"] in ("DISMISSED", "PENDING", "CHANGES_REQUESTED") or GENERATED.search(body):
            continue
        approving = ((login(r) == author and is_approval(body, head)) or
                     (login(r) not in (author, "ghost") and r["state"] == "APPROVED" and latest.get(login(r)) == r))
        if approving and r["commit_id"] == head:
            approvals.append((when(r), login(r), f"review {r['id']}"))
    for c in issue_comments:
        body = c.get("body") or ""
        if login(c) == author and body.strip().endswith(" " + head) and is_approval(body, head):
            approvals.append((when(c), author, f"comment {c['id']}"))
    approval = max(approvals) if approvals else None
    if not approval:
        reasons.append("no approval on the current head (stale/unbound approvals ignored)")
    requesters = {login(r) for r in reviews if r["state"] == "CHANGES_REQUESTED"}
    for who in sorted(requesters):
        r = latest[who]
        if (r["state"] != "APPROVED" or r["commit_id"] != head
                or GENERATED.search(r.get("body") or "")):
            reasons.append(f"{who} requested changes")
    # Do not interpret arbitrary language as resolution. A human must read it and
    # record a fresh SHA-bound approval; equal timestamps are ambiguous too.
    if approval:
        for c in reviews + issue_comments:
            body = c.get("body") or ""
            if c.get("state") == "DISMISSED":
                continue
            selected_formal = c.get("state") == "APPROVED" and approval[2] == f"review {c['id']}"
            if when(c) >= approval[0] and not selected_formal and not is_approval(body, head):
                reasons.append(f"ambiguous/later message {c['id']} by {login(c)}: human review required")
    roots = {c["id"]: c for c in inline if not c.get("in_reply_to_id")}
    replied = {c["in_reply_to_id"] for c in inline if c.get("in_reply_to_id")
               and login(c) != "ghost" and login(c) != login(roots[c["in_reply_to_id"]])}
    for cid, c in roots.items():
        if login(c) != author and cid not in replied:
            reasons.append(f"unanswered inline comment {cid} by {login(c)} on {c.get('path')}")
    return not reasons, reasons, approval


def current_branch() -> str:
    """Resolve locally: gh pr view with --repo requires an explicit selector."""
    try:
        branch = subprocess.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                                capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        fail("cannot resolve current Git branch; pass an explicit PR number")
    require(bool(branch), "empty current Git branch; pass an explicit PR number")
    return branch

def snapshot(number):
    selector = number or current_branch()
    pr = obj(json.loads(gh("pr", "view", selector, "--repo", REPO, "--json", FIELDS)))
    require(type(pr.get("number")) is int and pr["number"] > 0, "invalid PR number")
    require(not number or pr["number"] == int(number), "PR number mismatch")
    require(bool(number) or pr.get("headRefName") == selector, "PR branch mismatch")
    require(bool(SHA.fullmatch(text_field(pr, "headRefOid"))), "invalid head SHA")
    n = pr["number"]
    status = status_for(pr["headRefOid"])
    reviews = api(f"repos/{REPO}/pulls/{n}/reviews")
    comments = api(f"repos/{REPO}/issues/{n}/comments")
    inline = api(f"repos/{REPO}/pulls/{n}/comments")
    validate(pr, status, reviews, comments, inline)
    return pr, status, reviews, comments, inline


def main() -> None:
    if sys.argv[1:] in (['-h'], ['--help']):
        print(__doc__)
        return
    number = sys.argv[1] if len(sys.argv) == 2 else ""
    if len(sys.argv) > 2 or (number and not number.isdigit()):
        fail("usage: pr_review.py [<pr-number>]")
    try:
        require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", REPO)), "configure GITHUB_REPO")
        first = snapshot(number)
        pr, status, reviews, comments, inline = first
        evidence = jenkins_evidence(pr, status)
        second = snapshot(str(pr["number"]))
        if first != second:
            print("NOT ready: PR head/status/review evidence changed; rerun gate")
            sys.exit(1)
        ready, reasons, approval = evaluate(*first, evidence)
        print(f"PR #{pr['number']} -> {pr['baseRefName']} | checked SHA {pr['headRefOid']}")
        for label, items in (("review", reviews), ("comment", comments), ("inline", inline)):
            for c in items:
                print(f"  {label} {c['id']} {when(c)} {login(c)} {c.get('state', '')}")
        if ready:
            print(f"READY: {pr['headRefOid']} | {approval[2]} | {evidence['url']}")
            print("Same-login approval provenance requires human verification. Rerun immediately before authorized merge.")
        else:
            print("NOT ready: " + "; ".join(reasons))
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, ci_status.ReaderError) as e:
        fail(f"incomplete/unexpected evidence: {e}")
    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()

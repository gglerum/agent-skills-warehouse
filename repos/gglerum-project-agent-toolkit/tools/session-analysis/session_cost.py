#!/usr/bin/env python3
"""Relative cost and flow metrics per Claude Code session (read-only; reads local transcripts).

Usage: python3 -I scripts/session_cost.py [--since YYYY-MM-DD] [--match SUBSTR] [--project-glob GLOB]
                                          [--prompts | --commands | --files | --patterns]
Default is the cost table. --prompts lists real user prompts per session (tool results, hook/system text and
slash-command wrappers excluded). --commands counts Bash commands per category (a command counts once in every
category it matches) plus the first word of uncategorised ones. --files counts Read/Edit/Write touches per path.
--patterns shows top normalised commands, inline-Python purposes, dump targets and a per-category output-token tally
(tokens of the assistant turn that issued the command, split evenly across its tool calls; compare runs with --since).
Cost units are relative: input 1, cache write 1.25, cache read 0.1, output 5 (typical price ratios). They rank
sessions; they are not currency. Subagent transcripts are added to their parent session.
Columns: turns, first-write turn and context size then (orientation cost), final context, dump calls
(Bash sed -n/cat/head/tail), docker/dev calls, Agent calls.
"""
import argparse, collections, glob, json, os, re, sys

CATEGORIES = [
    ("dev verify", r"\./dev verify\b"),
    ("dev check", r"\./dev (check|scaffold-check|spec-check|phase-check)\b"),
    ("dev pytest", r"\./dev pytest\b"),
    ("dev closeout", r"\./dev closeout\b"),
    ("dev other", r"\./dev (?!verify|check|scaffold-check|spec-check|phase-check|pytest|closeout)\w+"),
    ("docker compose", r"\bdocker compose\b"),
    ("git commit", r"\bgit commit\b"),
    ("git status/diff/log", r"\bgit (status|diff|log|show)\b"),
    ("git merge/worktree", r"\bgit (merge|worktree|rebase|branch|checkout|switch)\b"),
    ("git push", r"\bgit push\b"),
    ("gh", r"\bgh \w+"),
    ("file dump", r"\b(sed -n|cat |head -|tail -)"),
    ("grep/find", r"\b(grep|rg|find)\b"),
    ("python", r"\bpython3?\b"),
    ("lab-check/patch", r"lab-(check|patch)"),
]

def user_prompt(e):
    """Text of a real user prompt, or None for tool results, meta, hook and command wrappers."""
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"): return None
    c = e.get("message", {}).get("content")
    if isinstance(c, list):
        if any(b.get("type") == "tool_result" for b in c): return None
        c = " ".join(b.get("text", "") for b in c if b.get("type") == "text")
    if not isinstance(c, str): return None
    c = re.sub(r"<(system-reminder|local-command-caveat|local-command-stdout)>.*?</\1>", "", c, flags=re.S).strip()
    if not c or c.startswith(("<command-name>", "<command-message>", "<task-notification", "[Request interrupted")): return None
    return c

def normalise(c):
    """Collapse a command to its shape: quoted strings, paths, numbers and hashes removed."""
    c = " ".join(c.split("\n")[0].split())
    c = re.sub(r"(\"[^\"]*\"|'[^']*')", "S", c)
    c = re.sub(r"[\w./~-]*/[\w./~-]+", "P", c)
    c = re.sub(r"\b[0-9a-f]{7,}\b|\b\d+\b", "N", c)
    return c[:80]

def inline_python(c):
    """Purpose of an inline python call: first meaningful line of a heredoc or -c script, else None."""
    if not re.search(r"\bpython3?\b[^\n]*(<<|\s-c\b)", c): return None
    body = c.split("\n", 1)[1] if "\n" in c else c
    for ln in body.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith(("import ", "from ", "EOF", "PY")): return ln[:70]
    return "(empty)"

def dump_target(c):
    """File read by a leading cat / sed -n / head / tail (not pipes, redirects or heredoc writers)."""
    m = re.search(r"(?:^|&&|;)\s*(?:cat|sed -n '[^']*'|head(?: -\w+)?|tail(?: -\w+)?)\s+(?:-\S+\s+)*([^\s|<>&;]+)", c)
    return m.group(1) if m else None

def tool_category(b):
    n = b["name"]
    if n != "Bash": return n
    c = b["input"].get("command", "")
    for name, rx in CATEGORIES:
        if re.search(rx, c): return name
    return "bash other"

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--prompts", action="store_true")
    g.add_argument("--commands", action="store_true")
    g.add_argument("--files", action="store_true")
    g.add_argument("--patterns", action="store_true")
    ap.add_argument("--since", default="")
    ap.add_argument("--match", default="")
    ap.add_argument("--project-glob", required=True, help="explicit project key/glob under config/projects")
    ap.add_argument("--config-dir", default=os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"))
    a = ap.parse_args()
    root = os.path.join(a.config_dir, "projects")
    rows = {}
    prompts = collections.defaultdict(list); cats = collections.Counter(); firsts = collections.Counter(); files = collections.Counter()
    def wanted(sid):
        return not ((a.since and rows[sid]["start"] < a.since) or (a.match and a.match not in sid))
    for p in glob.glob(os.path.join(root, a.project_glob, "**", "*.jsonl"), recursive=True):
        if "corpus" in p: continue
        parts = p.split(os.sep)
        sub = "subagents" in parts
        sid = parts[parts.index("subagents") - 1][:8] if sub else os.path.basename(p)[:8]
        r = rows.setdefault(sid, dict(cost=0.0, turns=0, fw=None, fwctx=0, last=0, dumps=0, dock=0, agents=0, start="", tools=collections.Counter()))
        for line in open(p, encoding="utf-8", errors="replace"):
            try: e = json.loads(line)
            except ValueError: continue
            if not sub and e.get("timestamp") and not r["start"]: r["start"] = e["timestamp"][:10]
            if not sub and (t := user_prompt(e)): prompts[sid].append((e.get("timestamp", "")[:16], t))
            if e.get("type") != "assistant": continue
            u = e["message"].get("usage", {})
            ctx = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            r["cost"] += u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0) + 0.1 * u.get("cache_read_input_tokens", 0) + 5 * u.get("output_tokens", 0)
            if sub: continue
            r["turns"] += 1; r["last"] = ctx
            uses = [b for b in e["message"].get("content", []) if b.get("type") == "tool_use"]
            for b in uses: r.setdefault("tok", collections.Counter())[tool_category(b)] += u.get("output_tokens", 0) / len(uses)
            for b in e["message"].get("content", []):
                if b.get("type") != "tool_use": continue
                n, c = b["name"], b["input"].get("command", "")
                r["tools"][n] += 1
                fp = b["input"].get("file_path") or b["input"].get("notebook_path")
                if fp and n in ("Read", "Edit", "Write"): r.setdefault("files", collections.Counter())[(n, fp)] += 1
                if n == "Bash" and c: r.setdefault("cmds", []).append(c)
                if n in ("Edit", "Write") and r["fw"] is None: r["fw"], r["fwctx"] = r["turns"], ctx
                if n == "Bash" and re.search(r"\b(sed -n|cat |head -|tail -)", c): r["dumps"] += 1
                if n == "Bash" and ("docker compose" in c or "./dev" in c): r["dock"] += 1
                if n == "Agent": r["agents"] += 1
    if a.prompts or a.commands or a.files or a.patterns:
        sel = [sid for sid in rows if wanted(sid)]
        if a.prompts:
            n = 0
            for sid in sorted(sel, key=lambda k: rows[k]["start"]):
                if not prompts[sid]: continue
                print("== %s %s (%d prompts)" % (sid, rows[sid]["start"], len(prompts[sid])))
                for ts, t in prompts[sid]: print("  %s  %s" % (ts, " ".join(t.split())[:160]))
                n += len(prompts[sid])
            print("total: %d prompts in %d sessions" % (n, sum(1 for k in sel if prompts[k])))
        elif a.commands:
            for sid in sel:
                for c in rows[sid].get("cmds", []):
                    hit = [name for name, rx in CATEGORIES if re.search(rx, c)]
                    for h in hit: cats[h] += 1
                    if not hit: firsts[(c.split() or ["?"])[0]] += 1
            print("category counts (commands matching, %d sessions)" % len(sel))
            for k, v in cats.most_common(): print("%6d  %s" % (v, k))
            print("uncategorised, by first word")
            for k, v in firsts.most_common(15): print("%6d  %s" % (v, k))
        elif a.patterns:
            norm = collections.Counter(); py = collections.Counter(); dumps = collections.Counter(); tok = collections.Counter()
            for sid in sel:
                for c in rows[sid].get("cmds", []):
                    norm[normalise(c)] += 1
                    if (x := inline_python(c)): py[x] += 1
                    if (t := dump_target(c)): dumps[t] += 1
                tok.update(rows[sid].get("tok", {}))
            for title, ctr, n in (("top normalised commands", norm, 15), ("inline-python purposes (total %d)" % sum(py.values()), py, 10), ("dump targets (total %d)" % sum(dumps.values()), dumps, 10)):
                print(title)
                for k, v in ctr.most_common(n): print("%6d  %s" % (v, k))
            print("output tokens by tool category")
            for k, v in tok.most_common(): print("%8d  %s" % (v, k))
        else:
            for sid in sel: files.update(rows[sid].get("files", {}))
            for (n, fp), v in files.most_common(40): print("%5d  %-5s %s" % (v, n, fp))
        return 0
    total = sum(r["cost"] for r in rows.values()) or 1
    print("session  start       cost(M)  share  turns  1stWrite  ctx@1st  finalCtx  dumps  dev  agent")
    for sid, r in sorted(rows.items(), key=lambda x: -x[1]["cost"]):
        if (a.since and r["start"] < a.since) or (a.match and a.match not in sid): continue
        print("%-8s %-10s %7.1f %5.1f%% %6d %9s %7dk %8dk %6d %4d %6d" % (sid, r["start"], r["cost"] / 1e6, 100 * r["cost"] / total, r["turns"], r["fw"] or "-", r["fwctx"] // 1000, r["last"] // 1000, r["dumps"], r["dock"], r["agents"]))

if __name__ == "__main__":
    sys.exit(main())

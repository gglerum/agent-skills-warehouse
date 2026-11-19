#!/usr/bin/env python3
"""PreToolUse workflow guard for a Claude-style hook runtime (exit 2 = block, stderr goes to the model).

Stops Bash calls that waste tokens or break allowlist prefix rules, and nudges away from habits that bloat the context:

  redundant_cd      `cd <the directory the shell already starts in> && ...` is blocked (it also defeats allowlist prefix
                    rules); a cd to another directory, such as a worktree, passes.
  sleep             a bare `sleep N` is blocked (use a background run or a monitor with an until-loop).
  repeated_rewrite  the second inline rewrite of the same file in one session (`python -c` writing it, `cat > file <<EOF`,
                    `tee file <<EOF`) is blocked: use the editor tool's exact replacement.
  dump_nudge        a command that dumps part of a file (cat/head/tail FILE, sed -n .. FILE, grep -n .. FILE) adds a
                    context note to read with offset/limit or search instead. It never blocks.

Checks command arguments (tokens), not free text, so a commit message that mentions a command passes. The nudge and the
rewrite counter fail open; only the redundant_cd and sleep rules can stop a call. Dotenv protection is deliberately not
here: use the dotenv guard in ../hooks.

Environment: WORKFLOW_GUARD_DISABLE=redundant_cd,sleep,repeated_rewrite,dump_nudge (comma list) turns rules off;
WORKFLOW_GUARD_STATE_PREFIX names the per-session state file in the temporary directory (default `workflow-guard`).
Python 3.10+ standard library. Heuristic, not a shell parser or a sandbox: the user's runtime permissions stay authoritative.
"""
import json
import os
import re
import shlex
import sys
import tempfile

HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?:\n|$)", re.DOTALL)
SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")
VALUE_FLAGS = {"-n", "-c", "-s", "-q"}  # head/tail flags whose next token is a number, not a file
SCRATCH = ("/tmp/", "/var/tmp/")
PY_WRITE = re.compile(r"""\.write_(?:text|bytes)\(|\bopen\([^)]*['"][wax][+bt]*['"]""")  # opens a file for writing; print/str.replace alone is a read
PY_PATH = re.compile(r"""['"]([\w./-]+\.\w+)['"]""")
HEREDOC_WRITE = re.compile(r"(?:\bcat\s*>>?\s*|\btee\s+(?:-a\s+)?)(\S+)\s*<<")
CD_PREFIX = re.compile(r"^\s*cd\s+(\S+)\s*(?:&&|;)")


def enabled(rule: str) -> bool:
    return rule not in {r.strip() for r in os.environ.get("WORKFLOW_GUARD_DISABLE", "").split(",")}


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def tokens(cmd: str) -> list:
    cmd = HEREDOC.sub("\n", cmd)  # heredoc bodies are text (commit messages, PR bodies), not arguments
    try:
        return shlex.split(cmd, posix=True)
    except ValueError:
        return cmd.split()


def dumped_file(segment: str) -> bool:
    """True when one command (no pipes) prints part of a named file: cat/head/tail FILE, sed -n .. FILE, grep -n .. FILE."""
    parts = tokens(segment)
    if not parts or any(t.startswith(">") or t in (">", ">>") for t in parts):
        return False
    cmd, args = os.path.basename(parts[0]), parts[1:]
    if cmd in ("cat", "head", "tail"):
        files, skip = [], False
        for a in args:
            if skip:
                skip = False
            elif cmd != "cat" and a in VALUE_FLAGS:
                skip = True
            elif not a.startswith("-"):
                files.append(a)
        return bool(files)
    if cmd == "sed":
        positional = [a for a in args if not a.startswith("-")]
        return "-n" in args and len(positional) >= 2
    if cmd == "grep":
        numbered = any(re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", a) for a in args)
        positional = [a for a in args if not a.startswith("-")]
        return numbered and len(positional) >= 2
    return False


def dump_nudge(cmd: str) -> str:
    if any(dumped_file(seg) for seg in SEGMENT_SPLIT.split(HEREDOC.sub("\n", cmd)) if seg):
        return ("Token discipline: use the read tool (offset/limit) or a search tool instead of cat/head/tail/sed -n/grep -n on a file; "
                "shell dumps stay in context for the rest of the session.")
    return ""


def rewrite_targets(cmd: str) -> list:
    """Files a command rewrites inline: `python -c` code that writes/replaces, or `cat > FILE <<EOF` / `tee FILE <<EOF`."""
    targets = [m.group(1).strip("'\"") for m in HEREDOC_WRITE.finditer(cmd)]
    if re.search(r"\bpython3?\s+(?:-\w+\s+)*-c\b", cmd) and PY_WRITE.search(cmd):
        targets += PY_PATH.findall(cmd)
    return [t for t in dict.fromkeys(targets) if not t.startswith(SCRATCH) and "scratchpad" not in t]


def state_path(session_id: str) -> str:
    prefix = re.sub(r"[^\w-]", "", os.environ.get("WORKFLOW_GUARD_STATE_PREFIX", "workflow-guard")) or "workflow-guard"
    return os.path.join(tempfile.gettempdir(), "%s-%s.json" % (prefix, re.sub(r"\W", "", session_id or "none")))


def repeated_rewrite(cmd: str, session_id: str) -> str:
    """Counts inline rewrites per file for this session; returns the file whose second rewrite this is, else ''."""
    targets = rewrite_targets(cmd)
    if not targets:
        return ""
    path, seen = state_path(session_id), {}
    try:
        with open(path) as handle:
            seen = json.load(handle)
    except (OSError, ValueError):
        pass
    repeated = next((t for t in targets if seen.get(t, 0) >= 1), "")
    for t in targets:
        seen[t] = seen.get(t, 0) + 1
    with open(path, "w") as handle:
        json.dump(seen, handle)
    return repeated


def redundant_cd(cmd: str, cwd: str) -> str:
    match = CD_PREFIX.match(cmd)
    if not match or not cwd:
        return ""
    target = os.path.realpath(os.path.expanduser(match.group(1).strip("'\"")))
    if target == os.path.realpath(cwd):
        return "Do not prefix commands with `cd %s`: the shell already starts there. Run the command as it is (a cd to another directory, such as a worktree, is fine)." % match.group(1)
    return ""


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command", "")
    if enabled("redundant_cd"):
        why = redundant_cd(cmd, str(data.get("cwd", "")))
        if why:
            block(why)
    if enabled("sleep") and re.search(r"(^|[;&|]\s*)sleep\s+\d+", cmd) and "until" not in cmd:
        block("Blocked sleep. Use a background run, or a monitor with an until-loop.")
    repeated, nudge = "", ""
    try:
        if enabled("repeated_rewrite"):
            repeated = repeated_rewrite(cmd, str(data.get("session_id", "")))
        if enabled("dump_nudge"):
            nudge = dump_nudge(cmd)
    except Exception:  # the nudges never stop a call
        repeated, nudge = "", ""
    if repeated:
        block("Second inline rewrite of %s this session. Use the editor tool (exact replacement), not python -c or a heredoc." % repeated)
    if nudge:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": nudge}}))
    sys.exit(0)


if __name__ == "__main__":
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)
    main()

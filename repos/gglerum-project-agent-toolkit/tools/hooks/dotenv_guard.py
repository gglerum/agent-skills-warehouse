#!/usr/bin/env python3
"""PreToolUse guard: stop calls that always fail or waste tokens (exit 2 = block, stderr goes to Claude).

Checks command arguments (tokens), not free text, so a commit message that mentions a dotenv file passes.
`.env.example` is tracked and allowed. Fails closed: unparsable input blocks the call.
Not caught: paths built at run time (`$(echo .e)nv`, variables).
"""
import fnmatch
import json
import os
import re
import shlex
import sys

ALLOWED = {".env.example"}
REDIRECT = re.compile(r"^[0-9]*[<>]+")
SHELLS = {"bash", "sh", "zsh", "dash"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\s*(?:\n|$)", re.DOTALL)
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
SLEEP = re.compile(r"(^|[;&|(\n]|\btimeout\s+\d+)\s*sleep\s+\d+")


def is_dotenv_path(value: str) -> bool:
    value = REDIRECT.sub("", value.strip("'\""))
    if value.startswith("-") and "=" in value:
        value = value.split("=", 1)[1]
    base = os.path.basename(value.strip("'\"").rstrip("/"))
    if base in ALLOWED:
        return False
    if any(c in base for c in "*?["):
        return fnmatch.fnmatchcase(".env", base) or fnmatch.fnmatchcase(".env.local", base)
    return base == ".env" or base.startswith(".env.")


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def tokens(cmd: str, depth: int = 0) -> list:
    cmd = HEREDOC.sub("\n", cmd)  # heredoc bodies are text (commit messages, PR bodies), not arguments
    try:
        found = shlex.split(cmd, posix=True)
    except ValueError:
        found = cmd.split()
    if depth < 3:  # `bash -c "cat .env"`: the command string is arguments too
        for i, t in enumerate(found[:-1]):
            if t == "-c" and os.path.basename(found[0]) in SHELLS:
                found += tokens(found[i + 1], depth + 1)
    return found + [part for t in found for part in re.split(r"[<>]+", t) if part and part != t]


def main() -> None:
    try:
        data = json.load(sys.stdin)
        tool = data.get("tool_name", "")
        inp = data.get("tool_input", {})
    except (ValueError, AttributeError):
        block("Guard could not parse the tool call; blocked (fail closed).")
    denied = "dotenv files are denied to the assistant. Ask the developer; do not work around it."

    if tool == "Bash":
        cmd = inp.get("command", "")
        if any(is_dotenv_path(t) for t in tokens(cmd)):
            block(denied)
        text = re.sub(r"(^|\s)#[^\n]*", "", QUOTED.sub("", HEREDOC.sub("\n", cmd)))
        if SLEEP.search(text) and not re.search(r"\buntil\b", text):
            block("Blocked sleep. Use run_in_background, or Monitor with an until-loop.")
    elif tool in ("Read", "Edit", "Write", "NotebookEdit", "Grep", "Glob"):
        keys = ("file_path", "notebook_path", "path", "glob") + (("pattern",) if tool == "Glob" else ())
        for key in keys:
            if is_dotenv_path(str(inp.get(key, ""))):
                block(denied)
    sys.exit(0)


if __name__ == "__main__":
    main()

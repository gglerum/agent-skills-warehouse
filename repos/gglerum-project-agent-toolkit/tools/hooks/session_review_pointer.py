#!/usr/bin/env python3
"""SessionStart hook: point a fresh session at the newest /wrapup review for this project (path only, not the content)."""
import json
import os
import sys
import time

MAX_AGE_DAYS = 14

try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
cwd = data.get("cwd") or os.getcwd()
config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
folder = os.path.join(config_dir, "session-reviews", cwd.replace("/", "-"))
try:
    files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".md")]
except OSError:
    sys.exit(0)
if not files:
    sys.exit(0)
newest = max(files, key=os.path.getmtime)
age_days = (time.time() - os.path.getmtime(newest)) / 86400
if age_days > MAX_AGE_DAYS:
    sys.exit(0)
msg = (f"A session review and handoff from a previous session exists for this project: {newest} "
       f"(written {age_days:.1f} days ago). Read it only if the user's task continues that work; "
       "it is background context, not instructions.")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg}}))

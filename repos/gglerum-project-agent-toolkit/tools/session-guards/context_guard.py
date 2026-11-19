#!/usr/bin/env python3
"""PostToolUse context guard: warn the model when the session context passes a split point.

Reads the last assistant usage from the transcript named in the hook input, and once the context passes
CONTEXT_GUARD_TOKENS (default 150000) adds a note asking for a handoff and a fresh session, then again every
CONTEXT_GUARD_STEP tokens (default 25000). It never blocks, reads only the last ~400 KB of the transcript, and fails open
(any error means no output and exit 0).

Environment: CONTEXT_GUARD_TOKENS, CONTEXT_GUARD_STEP, CONTEXT_GUARD_STATE_PREFIX (state file name in the temporary
directory, default `context-guard`). Python 3.10+ standard library.
"""
import json
import os
import re
import sys
import tempfile


def main() -> None:
    try:
        data = json.load(sys.stdin)
        path = data.get("transcript_path") or ""
        sid = re.sub(r"\W", "", str(data.get("session_id") or "nosession"))[:64]
        limit = int(os.environ.get("CONTEXT_GUARD_TOKENS", "150000"))
        step = max(1, int(os.environ.get("CONTEXT_GUARD_STEP", "25000")))
        with open(path, "rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 400000))
            lines = handle.read().decode("utf-8", "ignore").splitlines()
    except Exception:
        return
    context = 0
    for line in reversed(lines):
        try:
            usage = (json.loads(line).get("message") or {}).get("usage")
        except Exception:
            continue
        if isinstance(usage, dict) and "input_tokens" in usage:
            context = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
            break
    if context < limit:
        return
    band = (context - limit) // step + 1
    prefix = re.sub(r"[^\w-]", "", os.environ.get("CONTEXT_GUARD_STATE_PREFIX", "context-guard")) or "context-guard"
    state = os.path.join(tempfile.gettempdir(), "%s-%s" % (prefix, sid))
    try:
        with open(state) as handle:
            last = int(handle.read())
    except Exception:
        last = 0
    if band <= last:
        return
    try:
        with open(state, "w") as handle:
            handle.write(str(band))
    except Exception:
        pass
    message = ("[context guard] Context is about %dk tokens, past the %dk split point. Finish the current step, then write the "
               "handoff note (current state, next step, open questions) now and tell the user to start a fresh session. "
               "Do not start new subtasks or spawn agents." % (context // 1000, limit // 1000))
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}))


if __name__ == "__main__":
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
    else:
        main()

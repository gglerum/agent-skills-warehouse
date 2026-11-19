# Session guards

Two optional hook scripts that keep long agent sessions cheap and inside the project's permission rules.

Python 3.10+ standard library and a compatible Claude command-hook runtime. No hook is activated by copying.

```sh
printf '%s' '{"tool_name":"Bash","cwd":"/work/app","tool_input":{"command":"cd /work/app && ls"}}' | python3 workflow_guard.py
printf '%s' '{"transcript_path":"/path/to/session.jsonl","session_id":"abc"}' | python3 context_guard.py
```

- `workflow_guard.py` (PreToolUse, matcher `Bash`): blocks `cd <current directory> && ...` (it defeats allowlist prefix rules; a cd into another directory such as a worktree passes), blocks a bare `sleep N`, blocks the second inline rewrite of the same file in one session (`python -c` writing it, `cat > file <<EOF`) and adds a context note when a command dumps part of a file with `cat`, `head`, `tail`, `sed -n` or `grep -n`. Exit 2 blocks; the nudge and the rewrite counter fail open. Disable rules with `WORKFLOW_GUARD_DISABLE`. Dotenv protection is a separate concern: combine with `dotenv_guard.py` and `destructive_guard.py` from [hooks](../hooks/README.md) as separate hook entries.
- `context_guard.py` (PostToolUse): once the last assistant turn's context passes `CONTEXT_GUARD_TOKENS` (default 150000), asks the model to finish the step, write a handoff and suggest a fresh session; it repeats every `CONTEXT_GUARD_STEP` (default 25000) tokens. It reads only the tail of the transcript and never blocks.

Both are heuristics. They are not a shell parser, a sandbox or a credential boundary. Check hook failure semantics, duplicate execution and the transcript format in the actual runtime, and test with a fixture before installing. State files live in the temporary directory and are named by session id; set the `*_STATE_PREFIX` variables to keep several projects apart.

Example hook entries (adapt matcher and path to the consumer):

```json
{"hooks": {
  "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 -I \"$CLAUDE_PROJECT_DIR/tools/workflow_guard.py\"", "timeout": 10}]}],
  "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 -I \"$CLAUDE_PROJECT_DIR/tools/context_guard.py\"", "timeout": 10}]}]
}}
```

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

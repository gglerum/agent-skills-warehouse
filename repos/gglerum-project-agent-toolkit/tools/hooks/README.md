# Hooks

Optional Claude command/dotenv guards and a latest-review path pointer.

Python 3.10+ standard library; a compatible Claude hook runtime. No hook is activated by copying.

```sh
printf "%s" '{"tool_name":"Bash","tool_input":{"command":"git status"}}' | python3 destructive_guard.py
printf "%s" '{"tool_name":"Read","tool_input":{"file_path":".env"}}' | python3 dotenv_guard.py
```

Guard exit 2 means block; exit 0 means the heuristic did not block. It is not a complete shell parser, sandbox or credential boundary. User runtime permissions remain authoritative. The dotenv guard permits `.env.example` and rejects protected dotenv access/command forms; inspect its conservative patterns against the consumer.

`session_review_pointer.py` reads the current hook input and configured Claude review directory, emits only the newest review path and does not load transcript bodies. Test with an explicit `CLAUDE_CONFIG_DIR` fixture before installing. Hook failure semantics, loaded source and duplicate execution must be checked in the actual runtime. Translating these to Codex requires that client's supported permission/hook mechanisms; source availability alone does not establish runtime support.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

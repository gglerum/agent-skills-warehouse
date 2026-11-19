# Session analysis

Measure scoped Claude transcript overhead and track when review is due.

Python 3.10+ standard library; compatible Claude JSONL transcripts.

```sh
python3 session_cost.py --config-dir /path/to/claude-config --project-glob "selected-project-key" --since 2026-01-01
python3 session_cost.py --config-dir /path/to/claude-config --project-glob "selected-project-key" --patterns
python3 review_due.py --root /path/to/project --config-dir /path/to/claude-config --threshold 20
```

Scope transcript access in the consuming task before running. `session_cost.py` requires a project key/glob and otherwise reads only that selected scope. `--prompts`, `--commands` and `--files` can reveal private text/paths; choose output deliberately and keep it local. Relative weights are not billing rates. Subagent metrics are added to their parent; abbreviated session IDs and heuristic command categories are approximate. `review_due.py` is read-only unless `--mark` explicitly writes the review marker. Neither command invokes a model. Test fixtures contain no real transcripts.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

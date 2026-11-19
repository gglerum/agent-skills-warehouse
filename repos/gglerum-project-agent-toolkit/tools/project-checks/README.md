# Project checks

Validate configured scaffold/spec consistency without importing a complete project scaffold.

Python 3.10+ standard library and a consumer-authored JSON configuration.

```sh
python3 check.py checks.example.json --root .
python3 check.py checks.example.json --root . --record-hashes
```

Configuration supports `required` file names, `hashes` map, `hash_globs` for explicit recording, `link_files` for local Markdown target checks, `forbid` regex/glob/reason rules, and `id_sets` comparing canonical regex IDs to JSON records (`canonical`, `machine`, `pattern`, `json_key`, `id_field`). Paths must stay inside the selected root.

Default checking is read-only: exit 0 complete configured checks, 1 detected drift, 2 invalid/unavailable input. Link checking verifies targets, not Markdown anchor resolution or remote URLs. `--record-hashes` writes a reviewed baseline and cannot certify the changed content. Run it only after reviewing the actual drift. Rules are consumer policy; no universal Docker, framework or manifest list is imposed.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

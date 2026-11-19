# Git checks

Protect the index before fixers, select checks from verified Git changes, and collect compact local state.

Python 3.10+ standard library and Git. Copy the entire folder.

```sh
python3 status.py --root . --base origin/main
python3 check_staging.py
python3 select_changes.py --staged --rules rules.example.json
python3 select_changes.py --target main --fetch --rules rules.example.json
python3 checks.py --root . --config checks.example.json
```

`status.py` performs only local reads; unknown upstream/base evidence is null. `check_staging.py` rejects partial staging, unresolved/nonregular index entries and paths unsupported by the conservative original hook contract. It hashes actual content to detect assume-unchanged/skip-worktree concealment. It never auto-stashes or discards edits.

Selection uses NUL-delimited status records with rename detection disabled, so deleted/old paths still affect test routing. Supply a JSON map of check flag names to path globs; examples are editable routing inputs, not complete project policy. Target refs are local until explicit `--fetch`. Fetch changes remote-tracking refs; `--output-dir` writes disposable CI flag files. Missing Git evidence fails rather than silently selecting no checks.

`checks.py` runs configured argument arrays without a shell after staged-input validation. `{files}` expands into individually passed selected filenames. Explicit `restage: true` is for authorized fixers; each step's nonzero exit blocks the run. Empty configuration fails. No matching step is reported as no applicable checks, not as executed validation. Install a hook only when the consumer requests it; this folder does not change Git configuration.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

# Floor guard

Fail a change that lowers the project's quality bar instead of meeting it: tightening is silent, loosening is loud.

Python 3.10+ standard library and Git. Copy the entire folder. No hook is installed by copying.

```sh
python3 floor_guard.py                       # base: origin/main, then main
python3 floor_guard.py --base main --config floor_guard.config.example.json
```

## What it reports

It diffs the merge base with the base ref against the working tree (staged, unstaged and untracked files) and reports:

- `silenced-checker`: a new suppression comment (`eslint-disable`, `@ts-ignore`, `noqa`, `type: ignore`, `NOSONAR`, `pragma: no cover`, ...), or a named suppression such as `@psalm-suppress X` whose names are not on the allow list.
- `unfinished-work`: `TODO`, an empty `catch`, `except: pass`, `raise NotImplementedError`, a "not implemented" exception.
- `test-made-easier`, `test-deleted`, `assertions-lost`: a skip marker added in a test file, a deleted test file, or a net loss of assertions in a changed test file.
- `baseline-grown`: more lines in a file whose name contains `baseline`.
- In `CONSTRAINTS.md`: `rule-removed`, `threshold-loosened`, `threshold-removed`, `threshold-changed` (a number next to words such as "at least", "at most", `>=`, "must not fall"), and exception rows without an owner, without a date, or already expired. A new valid exception row is a warning for the reviewer.

Exit 0 is clean, 1 a violation, 2 the guard could not run (no work tree, no merge base, invalid configuration). Treat 2 as a block, never as 0. Only the matched token of a code line is printed, never the line, so a secret on a flagged line is not echoed.

## Configuration

Every pattern and list can be overridden in a JSON file (see `floor_guard.config.example.json` and the defaults at the top of `floor_guard.py`): code extensions, ignored prefixes, suppression, stub, skip and assertion regular expressions, the test-file pattern, baseline extensions, the exception-row pattern and the default bases. When the guard is copied into the project it contains its own patterns as text: add its path to `self_exempt`, or the guard flags itself.

`CONSTRAINTS.example.md` is a starting template in the format the guard parses: rules are `- name: ...` bullets or table rows keyed by their first cell; exceptions are table rows beginning with `U<number>` and carrying `id | rule | reason | owner | expires`. Fill in only numbers that were measured. The accompanying idea is described in the warehouse's constraint-driven-development material; this folder is a runnable, language-neutral implementation of its floor check.

A hook that calls the guard should fail on any nonzero exit. The guard has heuristic limits: it does not parse code, a renamed rule looks like a removed one (rename in one commit, change numbers in another), and generated or vendored paths must be excluded through `ignored_prefixes`.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

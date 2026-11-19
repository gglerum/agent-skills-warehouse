# Constraints

The floor of this project: what a change must not lower. Every rule below is either enforced by a command that fails, or listed under "Measured, not yet enforced" with the number that was actually measured. What is enforced nowhere is listed in the last table as a judgement.

`floor_guard.py` checks the diff from the merge base with `origin/main` to the working tree on every commit, plus untracked files. It reports only moves that lower the bar: a new suppression, a skipped or deleted test, a net loss of assertions in a test file, unfinished work, a growing baseline file, and a weakened rule in this file. Tightening is silent, loosening is loud. Exit 0 is clean, 1 is a violation, 2 means the check could not run (and blocks too).

## Floor

- Static analysis level: at least 5; there is no baseline file, every error is new and blocks.
- Complexity limit: at most 10 per function; no suppression comments.
- Baseline files: growth is a violation. Zero measurement: there are no baseline files.
- Tests: the full suite passes; no skipped or incomplete test; no net loss of assertions per test file.
- Target platform: runtime 3.12 (the lock file refuses packages that need a newer one).

## Enforced by a command

| What | Command | Where it runs |
| --- | --- | --- |
| Formatting | `<formatter> --check` | hook applies, CI checks |
| Tests | `<test command>` | hook (related tests), CI (full suite) |
| Types | `<type checker>` | hook |
| Dependency vulnerabilities | `<audit command>` | hook when a lock file changes |
| The floor itself | `python3 tools/floor_guard.py` | hook |

## Measured, not yet enforced

Line coverage: record the measured number, the date and the command here. No minimum is set until a second measurement exists; a number nobody enforces is not a rule.

## Rules and what enforces them

A rule without enforcement is a wish. When a mistake happens twice, add a row that says what stops it from now on: architecture first, then types, then a check whose error message names the fix, then a test, and prose last.

| Rule | What enforces it |
| --- | --- |
| No suppression, skipped test or empty catch is added silently | `tools/floor_guard.py` |
| A partially staged file is not committed whole | staging check in the pre-commit hook |
| Generated overviews are not edited by hand | the `check` command of the record tools (a stale overview fails) |
| A pull request never closes an issue (`Refs`, not `Closes`) | the `no-closing-keywords` CI check |
| No new dependency without explicit approval | judgement of the session (dependency-change skill) |

## Exceptions

A new row is a warning, not a block: a person must be able to add one without bypassing the hook. The check does require an owner and an expiry date in the future; without both the commit is blocked. An exception expires or is reviewed again.

| Id | Rule | Reason | Owner | Expires |
| --- | --- | --- | --- | --- |

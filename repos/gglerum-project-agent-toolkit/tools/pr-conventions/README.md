# Pull request conventions

A CI check that stops a pull request from closing issues by keyword, and a pull request template that asks for the evidence a review needs.

Copy `no-closing-keywords.yml` to `.github/workflows/` and `pull_request_template.md` to `.github/`. Nothing is installed or enabled by copying; adding a workflow changes the consumer's CI and needs its own authorization.

- `no-closing-keywords.yml` fails when the pull request title, body or any commit message contains `Closes`, `Fixes` or `Resolves` (and their variants) followed by an issue number, optionally with an `owner/repository` prefix. GitHub would otherwise close the issue on merge, although a merge is not a review. Authors write `Refs #<n>` and the reviewer closes the issue by hand. It needs only read permissions and plain shell, no third-party action. The pattern is tested in `tests/test_ops_tools.py`.
- `pull_request_template.md` keeps the `Refs` line first, a short description, the test and quality checklist, the design checklist for screens, and a "Not verified" section so unverified claims are stated rather than implied. Tick only what was done.

Adapt the checklist items to the project's real commands. The check is a policy choice: a project that wants merges to close issues should not copy it.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

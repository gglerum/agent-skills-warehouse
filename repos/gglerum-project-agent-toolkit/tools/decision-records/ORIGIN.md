# Component origin

The owner authorized copying useful material from the selected projects. This records permission to copy and adapt; applicable third-party licences and notices remain in force. No blanket publication, service-access or source-project permission is imported.

## Sources

- source-project-k, revision `d4202160a3132986ea40627dde1afc3b53221df4`, path `utils/decision.py`, SHA-256 `6233833dcfc05aaf832124b0f58a0023a3823409944a14df9050917bd6372619`.
- source-project-k, revision `d4202160a3132986ea40627dde1afc3b53221df4`, path `utils/decision.sh`, SHA-256 `b5a919632225641a23b8ffe0c0cdb98fe4d7d3edad66212e4de0ce993cf6a5b4`.

## Adaptations

- Parameterize id prefix, record and overview paths, tracker repository, reviewer login, comment marker and reference paths in a JSON configuration; remove all product, repository and language specific text.
- Rename statuses and messages to English (decided, proposed, open, superseded); keep supersede/archive, never-reused ids, reference checking and generated-overview staleness checks.
- Make mirror and strays optional (enabled only when a tracker repository is configured); keep the link-only section so decision text is never copied; allow a fake gh command for fixtures.
- Add the configuration example, README and regression tests; no tracker call runs unless the consumer invokes mirror or strays.

Keep this origin record and included licence files with the copied component. Exact source-file hashes distinguish working-copy material from a revision-only claim.

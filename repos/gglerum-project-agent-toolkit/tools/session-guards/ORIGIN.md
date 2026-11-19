# Component origin

The owner authorized copying useful material from the selected projects. This records permission to copy and adapt; applicable third-party licences and notices remain in force. No blanket publication, service-access or source-project permission is imported.

## Sources

- source-project-k, revision `d4202160a3132986ea40627dde1afc3b53221df4`, path `.claude/hooks/guard.py`, SHA-256 `3cfebedf6d3000efa03278d2cfdfb06a7d612a33c8fe503ed7896046d899637f`.
- source-project-k, revision `d4202160a3132986ea40627dde1afc3b53221df4`, path `.claude/hooks/context-guard.sh`, SHA-256 `baa643fe1769f5d2bade924fd916c7a587ce577609f3d37bff7ee3a183780237`.

## Adaptations

- Remove dotenv protection (covered by the hooks bundle) and project state-file prefixes; make rules switchable and state-file prefixes configurable by environment.
- Convert the shell-wrapped context guard into a Python script with configurable thresholds; translate messages to English and neutral wording.
- Add README with example hook entries and regression tests; no hook is activated.

Keep this origin record and included licence files with the copied component. Exact source-file hashes distinguish working-copy material from a revision-only claim.

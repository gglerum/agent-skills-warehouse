---
name: session-finish
description: "Close a coding change with relevant checks, review, handoff and explicit CI or deployment evidence."
---

# Session finish

Collect the complete changed scope, including staged/unstaged files and branch commits. Respect source ownership of vendored files. Run the consumer's relevant checks and tests; inspect final content after fixers. Use its coverage policy, not an imported universal threshold.

Review confirmed defects and their failure scenarios. Record rejected findings with reasons and unresolved follow-ups separately. Update relevant docs and the handoff. Commit, push, open a PR, reply externally or merge only within the consumer's authorization. Read current branch/PR state again immediately before authorized publication.

[Report helpers](../../tools/test-reports/README.md) summarize failures and per-file statement coverage. [Service readers](../../tools/service-readers/README.md) collect complete current-head evidence. A green build does not establish deployment or merge permission. When deployment matters, use a matching [receipt](../../tools/deployment-receipt/README.md) for the actual merged SHA. Stop on persistent auth/config errors rather than inventing retries.

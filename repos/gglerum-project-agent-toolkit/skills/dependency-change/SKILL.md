---
name: dependency-change
description: "Evaluate a proposed dependency or upgrade using maintenance, licensing, compatibility and regression evidence."
---

# Dependency change

Read the current manifest/lockfile, existing alternatives and the concrete capability gap. Check authoritative maintenance/licence/security information for the actual version under consideration. Separate what was verified from assumptions.

Assess runtime/platform support, transitive tools/services/credentials, upgrade/recovery cost and the project's trust boundaries. State the smallest useful choice, rejected alternatives only when actually considered, and unresolved requirements.

For an authorized upgrade, update the smallest coherent set, run relevant compatibility/security regressions and document unavoidable exceptions. Do not silently pin/downgrade to hide a regression or apply a blanket upgrade-everything policy. Follow existing dependency and external-call permissions.

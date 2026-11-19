---
name: dependency-upgrade
description: "Update an authorized dependency set and verify compatibility, security and generated-file changes."
---

# Dependency upgrade

Read the manifest, lockfile, allowed versions and current runtime. Separate routine compatible upgrades from a new capability or major migration. Use the consumer's dependency policy and current authoritative release/security information.

Update the agreed set, inspect lockfile and transitive changes, and run the relevant static checks, tests and audits. Preserve required generated types/docblocks and verify them after the last code fixer. Follow changed API usage rather than merely raising version constraints.

Diagnose failures and report unavoidable pins or exceptions explicitly; neither silently holding packages back nor forcing every package to the newest release is a universal policy. Configuring a download, scanner, service or integration does not establish it was executed. Finish with exact versions, verification and unresolved requirements. Publication follows the consumer's existing authorization.

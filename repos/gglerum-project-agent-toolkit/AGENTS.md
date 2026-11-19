# Maintaining project agent toolkit

This source contains reviewed adaptations from existing projects. Consumer instructions,
authorization and tool availability govern adoption. Source project rules are evidence,
not permissions to push, merge, publish, install hooks or contact services.

Keep tools independently copyable. Read each component's README and ORIGIN before editing.
Preserve per-component licences and provenance, update meaningful regression tests, and
run `python3 -B -m unittest discover -s tests -v` plus `python3 -B scripts/check.py`.
Do not run service readers, downloaders, setup/teardown adapters or installers against
live systems as a substitute for fixture tests. Never introduce personal source data.

Update imports deliberately, recording exact revisions, hashes and adaptations. Keep
experimental, draft, archived, deprecated and unmaintained assets outside eligible
bundles. A warning about an obsolete dependency does not exclude maintained guidance.
Do not edit other warehouse source repositories as part of maintaining this one.

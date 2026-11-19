# CI operations lessons

Cap memory, swap and concurrency for heavy test/scanner processes. A container can remain running while host memory exhaustion stalls the controller, proxy or tunnel. Measure host pressure as well as per-container OOM state. Raise a justified limit rather than removing caps.

Isolate per-project workspaces, databases, credentials and persistent agent SSH host keys. Match the controller's configured identity after a container rebuild. Treat mutable image tags and tool-version changes as explicit upgrades with recovery evidence.

A reverse proxy may retain an old upstream IP after a container is recreated; verify name resolution/reload behavior during rollout. A green PR job does not substitute for the base-branch/nightly job or an actual deployment receipt.

For mutation tests, warm the exact parallel worker databases only after establishing ownership and schema fingerprints. Do not turn a warm-up warning into correctness evidence or use a timeout increase to hide repeated migration work.

Backups are useful only when off-host preservation and a restore rehearsal establish recovery. Restore and provisioning commands are project-specific, potentially destructive operations; adapt and authorize them separately.

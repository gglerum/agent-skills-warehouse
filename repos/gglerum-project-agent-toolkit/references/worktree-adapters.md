# Worktree setup and teardown adapters

Keep setup/removal journals and owned-resource receipts outside the removable worktree. Identify repository, branch, topic and exact worktree path before any teardown. Keep setup retry-safe; record uncertain creation before contacting an external system and refuse to adopt an existing resource as newly owned.

If setup ran, cleanup requires the matching teardown adapter. A teardown failure preserves worktree and evidence. Match exact owned database/resource names and supported worker suffixes; broad prefix deletion is unsafe. Clean Git state alone does not prove external resources are disposable.

Keep dependency/env/database setup in a project adapter. Confirm devcontainer mounts include the chosen worktree path. Do not automatically share personal agent memory or local credentials. Recover a stale lock only after checking the owning operation has stopped.

Before any authorized closeout merge, run the consumer's required checks, verify both trees are clean and confirm the intended base can fast-forward. Do not automatically refresh a hash manifest to make a check green. Keep branches and evidence until the consumer's deletion policy permits removal.

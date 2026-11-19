---
name: recoverable-sessions
description: "Create, resume or remove an isolated Git worktree with explicit setup and teardown ownership."
---

# Recoverable sessions

Read the consumer's base branch, worktree mount and environment setup. Use [worktree tooling](../../tools/worktrees/README.md) only after its mutation is within the task's authorization. Project setup may install dependencies or create databases; inspect and authorize those effects separately.

Preserve the current checkout. Keep a journal outside the worktree, serialize operations per topic and bind recovery to repository, branch and path. Resume only when those identities match. On uncertain creation or failed teardown, retain resources and evidence rather than guessing ownership.

Removal requires clean intended work and the consumer's completed/merged-work policy. The helper retains the branch and journal. It does not automatically merge, push, delete a branch, share global agent memory or install client hooks.

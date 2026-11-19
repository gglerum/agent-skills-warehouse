---
name: issue-session
description: "Prepare and complete one issue-focused coding session with blocker checks and durable handoff."
---

# Issue session

Read the issue and its linked blockers, current repository state and previous handoff. Confirm the issue is still open and that the described failure or missing behavior exists. Identify the expected result and relevant checks before editing.

Use the consumer's issue/branch/container adapter, preserving current branch work. Keep checks tied to actual changed behavior and record what remains unverified. Update tracker status or comments only within the task's external-write authorization. A closed issue or green CI is not deployment evidence. Use [issue helpers](../../tools/issue-session/README.md) for configurable GitHub reads.

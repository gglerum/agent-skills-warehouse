# Issue session

Read one GitHub issue and explicit blocker evidence with configurable repository scope.

Python 3.10+ standard library and authenticated gh. No tracker writes.

```sh
python3 issue_brief.py 42 --repo owner/repository
```

Blockers are explicit whole lines `Blocked by: #123`; up to 20 are read. The helper validates returned issue identity/state and publishes the complete JSON only after reads succeed. It does not assume a specific board, issue prefix, assignee or status vocabulary. Raw issue text is private project data: keep output in the authorized task. Board edits/comments and container command execution remain project-specific adapters documented by the issue-session skill; they are not silently performed.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

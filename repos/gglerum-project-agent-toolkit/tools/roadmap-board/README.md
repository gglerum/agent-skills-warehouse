# Roadmap board

Pick the next unblocked issue, preflight it in one call, mark who a card waits on, and write handoffs, for a GitHub Project whose cards are issues.

Bash, `gh` (logged in, with the `project` scope) and `jq`. Copy the entire folder. Nothing runs against a service until the consumer invokes it.

```sh
cp roadmap.conf.example roadmap.conf      # set repository, owner, project number
bash board.sh next                         # unblocked Ready/Backlog issues; epics and waiting issues are left out
bash preflight.sh 42                       # issue + blockers + findings + decisions + design artifacts, read-only
bash board.sh waitingon 42 "needs a legal answer" --who reviewer
bash board.sh waitingon 42 --done
bash board.sh handoff 42 /tmp/handoff.md   # writes docs/handoffs/<date>-issue-42.md (commit it with the branch)
bash board.sh session-prompt 42 43 "show the wireframes on one page"
bash board.sh status 42 "In review"
```

## Behaviour

- `next` reads issues, board statuses and the GitHub "Blocked by" relation, and lists open issues in a ready status whose blockers are all closed, that are not epics (sub-issues or title prefix) and not labelled as waiting. If nothing qualifies it says why.
- `preflight.sh` is the single preflight call a session should make instead of several raw reads: it prints the issue with comments, each blocker's state, a warning when the issue names a gate issue (for example a design or decision issue listed in `PREFLIGHT_GATE_ISSUES`) without being blocked by it, the finding or feedback text named by the board's source field, the decisions that apply (`decision-records`) and the design artifacts (`design-register`). Unset a `PREFLIGHT_*_CMD` to skip a section.
- `waitingon` marks an issue as waiting with a label, an assignee and one dated line on top of the body, so waiting is filterable and visible; `--done` clears all three.
- `handoff` writes a session handoff into the repository (not a tracker comment) so the next session reads it with the branch.
- `session-prompt` prints a start prompt built only from issue and board data.

## Write boundaries

`status`, `waitingon <issue> ...` edit the board or issues. `next`, `preflight.sh`, `session-prompt` and listing `waitingon` are reads; `handoff` writes a local file. Do not run a writing command unless the consuming project's rules allow it for the task; a card moved to Done or an issue closed is a decision for the people who review, not for the session. Verify option names against the installed `gh` version (project commands changed between releases). The scripts are tested with a fake `gh`, not against a live board.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

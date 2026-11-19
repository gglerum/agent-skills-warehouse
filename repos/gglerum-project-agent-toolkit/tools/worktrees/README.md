# Worktrees

Create, resume and remove isolated worktrees while preserving recovery journals.

Bash, Git and standard Unix tools; a configured origin/base branch. No global agent configuration required.

```sh
bash new_session.sh feature-topic
bash new_session.sh --list
bash new_session.sh --resume feature-topic
bash new_session.sh --remove feature-topic
```

Create `.agent-toolkit/workflow.conf` with trusted shell assignments: `BASE_BRANCH`, `SESSION_PREFIX`, `WORKTREES_DIR`. The shell sources this file as code; never use untrusted configuration. Defaults are main/session/.worktrees. Creation explicitly fetches origin and creates a branch; it is a mutation.

Optional executable `.agent-toolkit/session-setup.sh` and `session-teardown.sh` receive worktree path/topic and `MAIN_ROOT`. Inspect these adapters before execution: they may install packages, copy an environment or create resources. The helper shares no personal agent memory and copies no local settings. It retains branch and journal on removal and refuses dirty or mismatched worktrees. Setup failure in an existing created worktree can resume; an interrupted creation/fetch requires inspecting the journal before retry. Teardown failure or missing teardown after setup retains resources. A lock serializes each topic. See the worktree-adapter reference for recovery/ownership requirements.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

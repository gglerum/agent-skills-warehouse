# Session closeout

Answer "is everything recorded, generated, committed and pushed?" in one call, instead of the user asking at the end of every session.

Bash and Git; `gh` only for the optional pull request lines. Copy the entire folder. Nothing is installed or published by copying.

```sh
cp closeout.conf.example closeout.conf     # list the record checks and the doc paths of this project
bash session_end.sh                         # configured checks, working tree, upstream, docs touched, pull request
bash session_end.sh --offline               # without the network checks
bash pr_status.sh 42                        # merge state, checks and the log tail of failed checks, read-only
bash project_status.sh [--short]            # status printed from tools only
echo "- bullet\n**Lesson:** ..." > /tmp/step.md && bash log_step.sh "Title" /tmp/step.md
```

## Behaviour

- `session_end.sh` runs every configured check and prints `ok` or `FAIL` with the first lines of its output, then reports uncommitted or untracked files, a missing or mismatching upstream, unpushed commits, which documentation areas the branch touched compared with the base, and the pull request. Exit 1 when anything failed, 2 when not in a work tree. It is read-only and never commits, pushes or opens anything: the user or the session's authorization decides what to do with a FAIL.
- `pr_status.sh` waits for GitHub's lazy `mergeable` answer, prints merge and review state, the checks, a hint on conflicts, and the last 40 log lines of every failed check run.
- `project_status.sh` prints git state, open pull requests, the board's next and waiting lists (through `STATUS_BOARD_CMD`) and any configured section. `--short` prints the branch and the newest handoff, suited to a session-start hook. Status is printed from tools so it cannot go stale in the repository.
- `log_step.sh` inserts a numbered step before `## Next steps` in a process log (`LOG_FILE`, default `docs/process-log.md`) and prints its number.

The checks and commands in the configuration run through `bash -c`: only configure commands the consuming project trusts. Test both scripts in a disposable repository before wiring them to a hook or skill.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

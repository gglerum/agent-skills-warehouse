# Service readers

Collect compact service and current-commit readiness evidence with explicit project configuration.

Python 3.10+ standard library, Git, authenticated gh for GitHub/Jenkins readers, the actual configured services. Copy the entire folder.

```sh
python3 ci_status.py 12 --json
python3 ci_status.py 12 --wait --timeout=60 --json
python3 asana.py --project 123456 open
python3 sonar_status.py 12
python3 dojo_findings.py feature-branch
python3 pr_review.py 12
```

Read `.agent-toolkit/workflow.conf` from the invoking repository, or set `TOOLKIT_CONFIG` to a file. Python parses simple `KEY=value` data without shell expansion; environment values override it. Configuration is project-local and contains no credentials by default. Asana accepts `--project` or `ASANA_PROJECT_ID`; its optional filters use `ASANA_OWNERSHIP_PATTERN`, `ASANA_OWNERSHIP_FIELDS`, `ASANA_SKIP_PREFIXES` and `ASANA_BUGS_SECTION` from the environment. Missing ownership configuration cannot imply an empty owned backlog.

Configure `GITHUB_REPO`, `BASE_BRANCH`, trusted HTTPS `JENKINS_URL`, `JENKINS_CONTEXT`, `JENKINS_JOB_PATH` (e.g. `job/example-pr`) and comma-separated `REQUIRED_STAGES` for PR readiness. Define all stages the consumer actually requires; a fixed list does not derive conditional applicability. Conditional policies need a project adapter with evidence for the captured head. No console-log text is used as proof. Raw comments/logs/error bodies are not printed by compact readiness output.

Use `JENKINS_USER`/`JENKINS_TOKEN`, `ASANA_TOKEN`, `SONAR_TOKEN`, `DEFECTDOJO_TOKEN` in the environment; Cloudflare Access headers are optional. Sonar requires `SONAR_URL` and `SONAR_PROJECT_KEY`; Dojo requires `DEFECTDOJO_URL` and exact `DEFECTDOJO_PRODUCT`. HTTPS pagination stays within its configured base, rejects repeated/incomplete pages and stops at a deadline/page/byte limit. Sonar/Dojo exit 5 for incomplete evidence; 1 means a failed gate or selected findings.

CI exit codes: 0 complete green, 1 failed, 2 running/budget exhausted, 3 missing, 4 moved head, 5 incomplete, 6 stable auth/config error. `--all` runs the sibling Sonar/Dojo readers within the remaining budget; their failure makes evidence incomplete. Asana returns COMPLETE only after all requested pages arrive; exit 5/6 never means an empty backlog. PR readiness exits 0 ready, 1 blocked, 2 malformed/unavailable evidence. Approval records cannot authenticate a same-login human. None of these tools merges or authorizes publication. Offline fixtures exercise contracts; no live authenticated service or installed agent-runtime validation is claimed.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

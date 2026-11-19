# Warehouse validation scenarios

Run from the warehouse root:

```bash
python3 scripts/warehouse.py check
python3 -m unittest discover -s tests -v
```

These are local structural, relocation and selected fixture-based CLI checks.
They do not invoke Claude Code, Codex, cloud agents, or live MCP servers.
The toolkit report converter runs on synthetic data; original third-party
workflows and installers are not executed. Temporary copy scenarios write only
inside disposable temporary directories.

| Scenario | What is checked | Practical limit |
| --- | --- | --- |
| Start a project | The specification route exposes Addy's spec/task breakdown and Matt's spec/ticket alternatives, with existing source targets. | Does not judge the resulting requirements or agent routing. |
| Diagnose a bug | The debugging route exposes two approaches and records them as alternatives. | No application is diagnosed. |
| Review code | The route exposes different review scopes and a security persona is available. | No multi-agent review is launched. |
| Add an integration | Google Sheets has discoverable MCP configuration plus authentication/client adaptation guidance. | No connection, OAuth flow, or service endpoint is tested. |
| Copy a dependency-heavy skill | Addy's TDD folder is copied; its shared checklist is made local, its path rewritten, and its license retained. The original is unchanged. | Named skills and browser tooling still require consuming-project decisions. |
| Borrow a verification generator | The generated Claude Code version of pstack's generator and maintenance skill is copied with adapter, examples, and license; explicit local links remain resolvable. | No app-specific harness is generated or run; deeper dynamic sibling dependencies need review. |
| Choose among competing testing policies | The task route and entries explain broad TDD, agreement on test boundaries, and pragmatic regression testing. | Policy descriptions support a decision; a structural test cannot make that decision for a project. |
| Respect maturity boundaries | Excluded buckets and Beta integrations are absent from eligible copy entries. | Source wording can be incomplete or ambiguous; inclusion is not maturity certification. |
| Copy a toolkit report converter | The catalog's complete converter bundle runs after relocation and rejects malformed input without replacing prior evidence; origin records travel with it. | Does not execute a real scanner or certify a producer's report format. |
| Copy toolkit skills with helpers | Every toolkit skill's declared copy bundle includes its linked tools, references and origin records in a disposable consumer layout. | Structural dependency validation does not establish agent behavior or client loading. |

The checker regression tests use disposable Git repositories. They exercise
supporting-file and license drift, executable mode changes, newly added assets,
deletions, changed maturity evidence, exclusion/bundle conflicts, broken links,
generated variants, explicit review recording, and read-only behavior.

Record a new review only after interpreting changed source evidence and updating
the metadata. See [maintenance](../README.md#maintenance). Test counts and the
review date are reported by commands rather than stored here as stale claims.

For the fourth source's broader fixture and relocation checks:

```bash
cd repos/gglerum-project-agent-toolkit
python3 -B -m unittest discover -s tests -v
python3 -B scripts/check.py
```

These exercise synthetic reports, fake service responses, disposable Git
worktrees, PHP configuration/fingerprints, fake database inventory and relocated
entrypoints. They do not access a live database, Docker daemon, authenticated
service, model, downloaded reference library or installed hook runtime.

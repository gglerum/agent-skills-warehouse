# Validation contract (1.0)

Copy the whole package. From an unrelated directory, run its full script path:

```sh
python3 -B /copied/cut-the-fluff/inventory.py verify
python3 -B /copied/cut-the-fluff/inventory.py verify --inventory /private/inventory.json \
  --trials /private/comparison.json
python3 -B -m unittest discover -s /copied/cut-the-fluff/tests -q
```

`verify` reads only this package and the JSON you name. It never launches an agent,
runs helpers or hooks, reads credentials, installs anything or reads a home. It
checks file bounds, Python and JSON syntax, skill metadata, relative Markdown links
(not links in code examples or remote URLs), origin records and notices, and
machine-specific paths. It does not check meaning or instruction quality.

Exit 0: structural checks passed. 1: structural failures. 2: invalid or unreadable
input. Read `behavior.status` separately; without `--trials` it is `not_run`, never
a pass. A supplied inventory adds file coverage and expected loading; effective
settings, permissions and tool advertisement stay unknown.

## Paired trials

The [fixture tasks](../tests/fixtures/behavior/tasks.json) cover three categories:
normal (needs no reference), newly routed (needs a newly linked reference), and rare
essential (recovery). Baseline and changed fixtures share every reference file and
policy; only the root instruction body differs. Answer each task; do not run a real
release, service or recovery action.

For host trials, use a fresh session per configuration and task, with the same
pinned model, runtime, provider, permissions, tools, prompt and worktree.
Counterbalance order, repeat, and record differences, hidden context and failures.
Confirm host settings and tools from runtime evidence; a parsed config is not
enough. Use approved isolated roots; disable unneeded hooks or MCP only for the
trial and never change global settings. A trial is a separate, user-scoped run,
never a side effect of auditing or `verify`. If authentication, model identity,
isolation or permissions are unavailable, record the gap instead of running a less
isolated trial.

Record observations as `schema.json#/$defs/behavior_trials`:

- `kind`: `live_agent`, `reviewer_walkthrough` or `synthetic`. A walkthrough by the
  fixture author in an existing chat has prior context; it is a demonstration, not
  a controlled comparison.
- Per task: category, baseline and changed observation, conditions (`model`,
  `runtime`, `version`, `surface`, `tools`, `isolation`, `task_sha256`, and the
  configuration SHA-256), metrics and evidence citations. `task_sha256` hashes the
  UTF-8 prompt alone; the configuration hash covers the root instruction file.
  Record every other context difference in `review_notes`.
- `quality`: fraction of task requirements met, 0–1. Discovery succeeds only when
  the run follows the needed route and produces every required element.
  `orientation_reads`: reads needed to find guidance. `repeated_reads`: reads past
  the first per file. `context_source_bytes`: unique guidance files delivered.
- `input_tokens`: runtime-recorded usage or null, never bytes divided by a guessed
  ratio. State whether it is uncached or aggregate input (including cache creation
  and reads); aggregate input counts repeated turns and is not peak context. Keep
  tool results, cached tokens and billing separate.
- Cite stable artifact or event IDs and hashes. Keep real sessions private and
  outside version control; never keep raw logs.

## Statuses

`verify` checks format and identities, compares conditions, and flags quality,
discovery, effort and context changes. Statuses rest on the reviewer's records;
they are not replayed or authenticated, and they do not show causation.

The first matching row wins:

| Status | When |
| --- | --- |
| `regression_or_incomparable` | Lower quality or lost discovery than baseline, missing categories, or different conditions |
| `baseline_incomplete` | Baseline quality below 1 or failed discovery (flagged per pair too): the change did no worse, but rerun after fixing the baseline |
| `review_required` | More effort or context (e.g. a routed task loading more bytes or tokens) |
| `observed_preservation` | Live-agent records, all three categories, perfect quality and discovery |
| `demonstration_only` | Walkthrough or synthetic records; never establishes savings |
| `not_run` | No `--trials` file |

Lower source bytes alone never approve a change. If a change loses required
behavior, fix the trigger or reference or keep the original guidance, then rerun.
Runtime certification needs real matched host sessions; structural and parser
tests cannot replace them. No blanket Codex or Claude certification is made. The
package's own [runtime validation](runtime-validation-summary.md) passed every
answer but kept `review_required`, because routed tasks used more input.

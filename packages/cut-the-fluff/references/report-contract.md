# Report contract (1.0)

```sh
python3 -B inventory.py report --project ROOT --inventory inventory.json \
  [--analysis analysis.json] --context FILE... --architecture FILE... \
  [--diagnostic FILE...] [--review review.json [--include-patches]] [--format FORMAT]
```

Inventory and analysis must come from the same project and runtime. Labels cannot
prove that, so check the pairing yourself. Versions, schemas and references are
validated; a runtime family mismatch is refused. File options take repeatable
**project-relative** names, without globs:

- `--context`: instruction, skill and tool-reference bodies to scan.
- `--architecture`: evidence of need, such as architecture docs, manifests, tests,
  CI workflows, runbooks and plans. You interpret them; the script does not read
  source code.
- `--diagnostic`: existing native diagnostic exports (e.g. `/doctor` output).
  Only their hashes are recorded. Treat their content as reported claims, check
  it against project files, and label it as reported in your rationale. They are
  never run.

Out-of-project targets and unreadable or oversized documents become gaps whose
`detail` names the limit. Limits: `--max-file-bytes` (1 MiB per document),
`--max-input-bytes` (256 MiB per inventory, analysis or review JSON, so large
`analyze` output fits), `--max-total-bytes` (512 MiB across all reads) and
`--max-files` (200). Refusals name the option, the file and the decision; see
`report --help` for every default.

`--format` chooses the output; keep every format private:

| Format | Reader | Contents |
| --- | --- | --- |
| `json` (default) | `apply`, approvals, audit trail | Full record, schema `#/$defs/report` |
| `agent` | An agent | Compact JSON, `kind: agent_report` (below) |
| `human` | The project owner | Plain-language prose, no codes or IDs |
| `markdown` | Either | Tables (below) |

Besides signals and findings, the full JSON has:

- `documents`: each `document:N` with its path and roles. Cite these IDs.
- `components`: each inventory ID with kind, origin and loading.
- `sessions`: selected, covered and file-read-covered session counts, once.
- `usage`: each analysis metric for a tool, skill or inventoried file, with the
  `inventory_ids` it joins to (by file origin, skill name or MCP server name) and
  `join`: `inventory`, `builtin_or_host_tool`, or `not_in_inventory` (deleted,
  plugin-provided or bundled).
- `file_activity`: counts for files read or searched that are not in the
  inventory, plus at most `--max-listed` (25) of them, ordered by failures, then
  repeated reads, then active sessions. These files get no signals.

The Markdown puts findings first, then signals grouped by code, usage, file
activity, the document table, coverage gaps grouped by code with counts, the
accounting, and only the cited evidence. Long lists stop at `--max-listed` rows;
the JSON keeps everything.

The `agent` summary keeps exact counts but lists at most `--max-listed` items:
findings (with `need`, `protected` and `change_sha256` joined in), `signals` by
code (`count`, `listed`, each with `evidence_ref_count` and three refs),
`coverage` grouped by code (`count`, `informational`, three example locators),
`usage` (`count`, `listed`), and `evidence` holding only references that a
finding, listed signal or document cites (`evidence_total` gives the full count).
It is not an apply input: approve and apply against the full `json` report.

The `human` report says what was found, what each suggested change is for, how
sure the review is, how much was visible and what happens next. It copies
`need`, `rationale` and `discovery_impact` from the review verbatim, so write
them as plain sentences the owner can follow.

## Signals

The first run gives **candidate signals only**:

- `large_context_body`: a `--context` body above `--large-context-bytes`
  (default 10 KiB);
- `duplicate_content`: two selected files with identical bytes;
- `stale_pointer`: missing local Markdown link targets (code examples are ignored;
  at most 200 links per file);
- `eager_import`: every import edge;
- `weak_trigger`: a skill's frontmatter `description` is empty, under 5 words, or
  says "any task", "all tasks", "everything" or "always use";
- `overlapping_discovery`: two skills with identical descriptions;
- `overlapping_configuration`: the same capability name in several config layers;
- `repeated_content_reads`, `broken_access_candidate` (failures) and
  `low_observed_activity`, from analysis.

Analysis signals fire only for tools, skills and inventoried files, never for files
outside the inventory. Low activity fires only when the metric's covered sessions
reach `--min-sessions` (default 10) and its active fraction is at most
`--low-use-threshold` (default 0.05), both set on `analyze`; with fewer covered
sessions, report usage as unknown. It also skips files that load at startup and
skill bodies: tool reads are not how those reach the model, and skill use is
measured by the `skill:NAME` metric. User-typed `/name` invocations are not
counted.

Each signal is a heuristic to investigate. A duplicate may be justified by
different scope or a suppressed copy. A missing target may be generated later.
Identical descriptions suggest overlap but do not prove it. Repeated reads do not
show how much of a file was read. Moving text behind another eager import saves
nothing. Unknown activity never justifies removal, and nothing is labeled unused.

## Review

Write a private `--review` JSON from the evidence you read. Copy evidence IDs from
an initial report rather than guessing them: `inventory:ID`, `analysis:ID`, and
`document:N` for selected files (numbered in context, architecture, diagnostic
order).

```json
{
  "schema_version": "1.0",
  "decisions": [{
    "component_ids": ["i1"],
    "action": "keep",
    "evidence_refs": ["inventory:e1", "document:2"],
    "confidence": "medium",
    "rationale": "Architecture evidence requires this recovery capability; activity is unknown.",
    "discovery_impact": "Retains the existing recovery route.",
    "need": "Recover failed deployments",
    "protected": true
  }]
}
```

Report refuses a decision unless:
- every component and evidence ID exists;
- at least one citation is an `--architecture` document;
- `need`, `rationale` and `discovery_impact` are nonempty;
- `action` is one of `keep`, `trim`, `deduplicate`, `narrow_scope`,
  `conditional`, `improve_trigger`, `defer`, `disable` or `archive`, and
  `confidence` is `low`, `medium` or `high`;
- `protected` is present on every decision: `true` only for a protected `keep`,
  otherwise `false`.

Record protected keep decisions for rare required capabilities before any
reduction. These decisions are your judgment; the script checks only their form.

Optional `patch` (`path`, `old`, `new`) makes a finding concrete. Report refuses it
unless:
- `--include-patches` is set and the action is not `keep`;
- `path` is a `--context` file whose `document:N` the decision cites;
- `old` is nonempty, occurs exactly once, and differs from `new`;
- the inventory snapshot of that file is current (rerun inventory after edits).

Each patch is an independent alternative against current source. With patches,
the report emits unified diffs that include source text, so review them for
secrets. It also emits exact `changes` entries (finding ID, hashes, `change_sha256`)
for the [change contract](change-contract.md). These are proposals, not approvals.

## Accounting

`source_bytes_by_loading` sums measured source bytes per loading class, counting
each file once per class. The classes are not additive runtime costs.

A patched finding's savings are an **estimated** reduction in UTF-8 source bytes
against the snapshot, with negative values clamped to zero. That is not tokens,
context, loads, cache or price; there is no bytes-per-token conversion. Other
findings have unknown savings. Findings on the same file share an `overlap_group`,
and `total_savings` is always null: **never add savings together**. Telemetry is
shown as supplied, never attributed or summed. Conditional-load, tool-result and
repeated-input tokens, caching and billing stay unknown. Every finding carries the
window, covered-session count, eligible denominator (usually null) and gaps.

A valid report proves only that its inputs were consistent. Review it yourself for
policy preservation, discovery, false positives and secrets. Discovery, quality
and real savings need the [validation contract](validation-contract.md).

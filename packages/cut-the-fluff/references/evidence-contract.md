# Evidence contract (1.0)

Read before running `analyze` on an authorized evidence store. The record shapes
below are documentation-based format profiles with synthetic tests, not certified
runtime releases. Codex is **validated on 1 rollout** (metadata shapes only,
2026-11-12); its outcomes and native file changes remain partial. Claude shape
checks are described below. Every unknown shape becomes a coverage gap, never
presumed non-use.

## Inputs and scope

`analyze --project ROOT --runtime codex|claude` reads only what you name:
`--evidence FILE`, `--handoff FILE`, `--telemetry FILE`, `--store DIR`.
`--discover --config-home DIR` adds Codex `sessions/` and `archived_sessions/`, or
Claude `projects/`. There is no default home, Git lookup, database, network or
agent run. Use only stores the user authorized. Discovery reads records from every
candidate file to check project identity, so in a store shared with sensitive
unrelated projects, name the files instead. Symlinked stores and discovered links
are skipped with gaps; explicit files may be symlinks. FIFOs are never waited on.

A session belongs to the project only if a recorded **absolute** cwd/project
resolves under `--project` or an explicit `--worktree ROOT`. Similar path
prefixes, directory names and encoded project keys prove nothing. Sessions with
conflicting or cross-project identities are excluded. A subagent links to its
parent only through recorded parent metadata, Claude `agentId`, or explicit
`--subagent CHILD=PARENT`. A child without a cwd inherits its matched parent's
project and is marked partial. Unmatched children, missing parents and cycles are
gaps. Worktrees are never guessed from `.git` files.

## Record shapes

| Profile | Accepted usage records |
| --- | --- |
| `codex-rollout-jsonl-1` | `session_meta.payload.id/cwd`, parent (`parent_session_id` or `source.subagent.thread_spawn.parent_thread_id`); `turn_context.payload.cwd`; `response_item` function/custom tool call and output; `event_msg` task completion/abort and token count; compaction |
| `claude-message-jsonl-1` | `sessionId`, `cwd`, `uuid`, optional `parentSessionId`/`agentId`; assistant `tool_use`; user `tool_result`; assistant `stop_reason: end_turn`; compact boundaries and summaries; `api-request-blob` request copies (checked, not counted) |
| `ctf-evidence-1` | Selected handoff/telemetry exports: `format`, `kind`, `session_id`, absolute `project`, `timestamp`, `component`, optional `state`/`measurements` |

Codex `world_state` (`full`/`state`, with an object state) and
`event_msg.thread_settings_applied` (object `thread_settings`) are bookkeeping,
with an informational `ignored_bookkeeping_record` gap. `token_usage_record.usage`
is a summary: its accepted numeric measurements must match
`event_msg.token_count.info.last_token_usage` in the same file and session,
including multiplicity. It adds `ignored_usage_summary`, never another telemetry
observation; an unmatched summary adds the session gap `unmatched_usage_summary`.
Empty summaries add `missing_usage_fields`. Turn/thread cumulative totals are not
summed. A `token_count` whose `info` is `null` carries rate limits only and adds
the informational `usage_not_yet_reported`; a missing or malformed `info` still adds
`missing_usage_fields`. `item_completed` text items (user/agent messages, reasoning,
plans, review-mode markers) are ignored and `ContextCompaction` adds `compaction`.
Native tool items (`FileChange`, `CommandExecution`, `McpToolCall`,
`CollabAgentToolCall`, `WebSearch`, `ImageView`) add `unsupported_native_tool`
because no call ID maps them to the response-item calls; any other item type adds
`unknown_native_item`. No second invocation or outcome is inferred. Only user/agent
messages and `FileChange` were seen in a real rollout; the other names follow the
Codex app-server item types.

Messages, reasoning and known bookkeeping records are ignored. Other typed Claude
records with no tool calls/results (titles, modes, timings, request metadata)
produce one audit-wide `ignored_bookkeeping_record` gap and keep session coverage.
An `api-request-blob` is a copy of the request sent to the model. It is never
counted. If every tool ID it names also appears in the same file's conversation,
it adds an audit-wide `ignored_request_copy` gap. Otherwise the file's sessions get
an `unmatched_request_copy` session gap. Validated on 228 real files: no
unmatched IDs.
Session gaps come from: untyped records, unknown records or content blocks that
carry tool calls, unsupported native tools, invalid UTF-8 or JSON (a BOM is not
stripped), missing identity, bad timestamps, oversized lines and an unterminated
final line. Invalid lines are skipped.

Outcomes: Codex needs a structured output with Boolean `success` or integer
`exit_code`; text and lists of text blocks stay unknown, even when they look
successful. In the one Codex rollout, all 32 matched results had those opaque
forms, so the session remains partial. Claude uses Boolean
`is_error` (absent means false). A result must match the full session and call ID
inside the window, in either order. Missing, orphan and unknown-outcome results are
gaps.

Handoff and telemetry exports look like this (`project` is your authorized root):

```json
{"format":"ctf-evidence-1","kind":"handoff","project":"/project","session_id":"full-id","timestamp":"2026-11-10T12:00:00Z","component":"skill:release","state":"invoked"}
{"format":"ctf-evidence-1","kind":"telemetry","project":"/project","session_id":"full-id","timestamp":"2026-11-10T12:00:00Z","component":"runtime:usage","measurements":{"input_tokens":200,"output_tokens":20}}
```

Handoff states are **reported claims**, never observed use. Telemetry keeps only
finite nonnegative `input_tokens`, `output_tokens`, `cached_input_tokens`,
`cache_read_tokens` and `duration_ms` (Codex `last_token_usage` too), and it is
never attributed to individual files. Convert other formats into this one
deliberately. The tool never enables collection.

## Reads and invocations

Direct recognition covers only `Read`, `read_file`, `functions.read_file` and
`Skill`/`skill`. Relative paths resolve against the calling record's absolute
`cwd` (else the session's), or an explicit absolute `workdir`. `~`, `~/PATH`,
`$HOME` and `${HOME}` resolve only with `--home DIR`: the absolute home the
recorded agent used. The directory need not exist on this machine. Without it,
these paths are unresolved. `~user` and every other variable stay unresolved.

Shell inference (`shell.py`) parses command text statically. It is never run, and
the files it names are never opened. It follows pipes, `&&`/`||`/`;`, newlines,
comments, quoting, heredocs, redirections, `cd`/`pushd` (scoped to subshells),
`( )`, `{ }`, `if`/`while` bodies, `$(...)` and backtick bodies, `bash -c`, and
wrappers such as `env`, `sudo`, `timeout` and `xargs`. Two kinds of access are
counted:

- **Reads** (`shell_read`): content readers `cat`, `tac`, `nl`, `head`, `tail`,
  `sed` (not `-i`), `less`, `more` and `bat`, including `< FILE`.
- **Searches** (`shell_search`): `grep`, `egrep`, `fgrep`, `rg`, `ag` and `ack`,
  for each explicit path operand after the pattern. A search shows only matching
  lines, so it counts as `searches`, never as a read. The operand may be a
  directory; files under it are not credited. A search with no path operand, or
  a listing mode (`rg --files`), counts nothing.

`find`, `ls`, other programs and scripts count nothing.

**Loops.** `for NAME in WORDS; do …; done` binds NAME to each word inside the
body, including nested loops, so `cat "$f"` resolves exactly. A loop over
anything dynamic, `while read`, and variables used after `done` stay unresolved.

**Wildcards** (`*`, `?`, `[…]`):
- A pattern rooted outside the project cannot match a project file. It resolves
  with nothing attributed and an informational `external_glob_not_listed` note,
  and is never listed. One limit: a symlink outside the project that points into
  it is not followed.
- Inside the project, a pattern is matched only with `--expand-globs`, against
  the tree **as it is now**, not as it was during the session. Matches count as
  inference with an informational `glob_matched_current_tree` note.
- A pattern still stays unresolved when nothing matches today, it matches more
  than 200 paths, it starts above the project root, it mixes quoted and unquoted
  wildcard characters, or `--expand-globs` is off.

A command is **unresolved** when an operand of a reader or searcher, or the
command itself, depends on runtime values: an unbound `$VAR`, `$(...)`, brace
expansion, a wildcard as above, or `~` without `--home`. It is also unresolved
when a relative operand follows a `cd` to an unknown directory, `xargs` or
`find -exec` feeds a reader or searcher, the text uses `eval`, `source` or
`case`, or it does not parse. Its static paths still count. Codex argv commands
are accepted only in the `[sh|bash, -c|-lc, SCRIPT]` form.

`unresolved_shell_access`, `unresolved_file_access` and `unresolved_shell_workdir`
mark only the session's file reads partial (`file_reads_partial: true`). The
session keeps its `covered` status for invocations and outcomes. External paths
are recorded as hashes. New tool wrappers need a reviewed adapter.

Metrics keep these separate: invocations; correlated successes, failures and
unknown results; read attempts; confirmed direct reads; repeated reads within a
session; shell-inferred reads; and shell searches (`searches`, never part of the
read counts). `last_observed_use` comes from direct attempts
only. A successful direct read means content was delivered, possibly one range.
It proves neither full-file context cost nor influence. A successful shell command
proves no file reached context. Files that load at startup (CLAUDE.md, AGENTS.md,
rules) reach the model without a tool call, so a tool read of one is not evidence
that it is used, and few or no reads are not evidence that it is unused.

## Sessions, windows and denominators

`--since`/`--until` are inclusive UTC dates. With a window, events without a
timestamp are excluded and reported. Metrics use in-window events only, while
out-of-window records can still set project identity. `--session-limit` caps
processing (it does not pick the newest sessions) and always leaves a gap.

A session is `covered` when its records are supported, it has a completion marker
(`end_turn`, task completion), and it has no session gaps. That is **not** proof of
complete history. `totals.file_read_covered_sessions` counts covered sessions that
are not `file_reads_partial`. Each `file:` metric's `covered_sessions` uses that
count, and every other metric uses `covered_sessions`. The report's low-activity
signal compares each metric's own count with `--min-sessions`; see the
[report contract](report-contract.md#signals) for which components get it. `eligible_sessions` is always null, because retention and
missing stores make the true denominator unknowable (`retention_unknown` is always
a gap). `--relevant-session ID` restricts denominators explicitly; relevance is
never inferred from prompts. Parent and subagent sessions count separately. The
audit session you are running is in the store too; it has no completion marker
yet, so it shows as partial (`incomplete_transcript`). Expect it, or set `--until`
to the day before.
Threshold options only feed report signals and never produce a removal finding.

`--alias OLD=NEW` merges component identities explicitly
(e.g. `file:project:old.md=file:project:new.md`). Cycles are rejected and every
mapping is noted. Inventory IDs are run-local; `report` joins usage IDs to them
(see its `usage` output).

## Identity and output

Session, event and call IDs are kept in full. Claude subagent identity is
`session/agent:ID`, with `native_id` holding the original. Duplicates (archive
copies, resumed sessions) are matched by session plus call ID and kind, or else by
event ID plus block index or a raw-record hash. They count once. Conflicting
payloads are gaps. Evidence references give source number, line and SHA-256 of
that line. Sources are numbered in input order, so keep your invocation to map
them back to paths. Source hashes cover only the bytes consumed.

Defaults: 1 MiB per line, 128 MiB total, 100,000 events, 1,000 files, 100
sessions. Discovery scans at most 4 × `--max-files` entries per store. Any limit
hit means partial coverage, and `analyze` prints one `WARNING:` line per cap on
stderr naming the option to raise (exit code stays 0). Real stores often exceed
the session and byte defaults; for example, pass `--session-limit 1000
--max-total-bytes 1073741824`. A gap tied to one session has the locator
`session:ID`, and each gap's `detail` says what it means and how to close it. Output goes to stdout only and contains no transcript
text; IDs, paths and hashes are still private metadata. Schema:
`schema.json#/$defs/analysis`. Pass the result to `report --analysis`.

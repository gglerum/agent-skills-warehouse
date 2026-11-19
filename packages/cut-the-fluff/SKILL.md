---
name: cut-the-fluff
description: Audit one project's agent context (instruction files, imports, skills, commands, MCP and tool configuration) for duplicated or stale guidance, eager loads, weak skill triggers, overlapping capabilities and repeated reads. Produces a cited report with proposed diffs; applies only user-approved project-local edits, with rollback.
---

# Cut the fluff

Remove context a project does not need while keeping every workflow it does.
The scripts measure; you judge, and every judgment cites project evidence.

Run `python3 -B <this folder>/inventory.py <command> ...`. Commands print JSON to
stdout. Save it in a private temporary directory outside version control. Exit 2
means the input was refused, and stderr names the failed check. Options are in the
[README](README.md).

## Ground rules

- **Scope.** Use only the project root, context roots (home, config, plugins),
  evidence files and observation window the user authorized. Never read implicit
  homes, other projects or private transcripts the user did not name.
- **Unknown is not unused.** Missing or partial evidence never justifies removal.
  Rare essentials (release, recovery, security, incident handling) stay, even
  with zero observed use.
- **Bytes are not tokens.** Byte deltas are labeled estimates of source size.
  Never convert them to tokens, cost or cache savings, and never sum alternatives.
- **Routing has a price.** Moving guidance behind a pointer saves startup context
  for tasks that skip it. Tasks that need it pay an extra read: in this package's
  [trials](references/runtime-validation-summary.md), routed tasks used about 50%
  more input. Route only guidance that few tasks need.
- **Read-only until approved.** Do not run hooks, servers, diagnostics or agents,
  enable telemetry, or edit global configuration.

## Audit

1. **Scope.** Confirm the project, authorized roots, evidence and window with the
   user. `--home` opens home-level agent files (for Claude Code:
   `~/.claude/settings.json`, `~/.claude.json`, `~/.claude/CLAUDE.md`, skills and
   rules), so name them when you ask. Read the project's own agent instructions.
   Done when the user has confirmed scope.
2. **Inventory.** Run `inventory` with `--runtime` and the host's actual
   `--runtime-version`, plus only the authorized `--home`/`--directory`/`--plugin`
   roots. Read the host notes for [Claude Code](references/claude-report.md) or
   [Codex](references/codex-report.md).
   Done when you have read every `coverage` gap.
3. **Usage (optional).** If transcript or export evidence is authorized, read the
   [evidence contract](references/evidence-contract.md), then run `analyze`.
   Real stores often exceed the defaults (100 sessions, 128 MiB); a stderr
   `WARNING:` names the option to raise. Your own running session appears as
   partial. With fewer covered sessions than `--min-sessions` (10), treat usage as
   unknown rather than low.
   Done when you know which sessions are covered, which are partial, and which
   have `file_reads_partial` (shell reads that could not be resolved).
4. **Needs.** Select and read the files that show what the project requires:
   architecture docs, manifests, CI workflows, tests, release/recovery runbooks
   and planned work. In large docs folders, read headings and indexes first.
   Docs about the agent workflow itself are context, not needs.
   Done when each inventoried context file and capability maps to a cited need,
   or is noted as having none found.
5. **Signals.** Run `report` with `--context` for every instruction/skill body and
   `--architecture` for every needs file (plus `--analysis` if available). Follow
   the [report contract](references/report-contract.md).
   Done when each signal is classified as fluff, justified, or unknown. For low
   activity, rule out failed access, poor discovery and missing data first.
6. **Review.** Write the review JSON described in the report contract. Add
   `protected` keep decisions for rare essentials first. Then record trim,
   deduplicate, narrow scope, conditional, improve trigger, defer, disable or
   archive decisions. Each must cite an architecture document and state need,
   rationale, confidence and discovery impact, written as plain sentences the
   owner can follow. Add an exact `patch` where you can.
   Rerun `report --review FILE --include-patches`; read it with `--format agent`.
   Done when the report validates.
7. **Present.** Save `report --format human` for the user and summarize it. For
   each finding, give: action, reason, confidence, evidence, window and
   denominator, discovery effect, labeled byte estimate, and the coverage gaps that
   limit it. Stop here unless the user asks for changes.

## Apply and recover

Only when the user asks for changes, read the
[change contract](references/change-contract.md). Show the exact diffs. After the
user explicitly approves named findings, write the approval JSON bound to that
report's hash. Then run `apply` with a new private `--state` directory and keep
that directory. `rollback` restores the originals and refuses to overwrite later
edits. Global or cross-project changes are out of scope; report them separately.

## Validate

Before calling a change an improvement, follow the
[validation contract](references/validation-contract.md). Compare normal, newly
routed and rare essential tasks before and after, in fresh sessions. Lost
guidance, or extra reads on routed tasks, is a regression to report, not a saving.
`verify` checks package structure and supplied trial records only.

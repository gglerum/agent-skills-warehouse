# Synthetic test coverage

Run `python3 -B -m unittest discover -s tests` from the package folder. Every
fixture is generated in a temporary directory: no real transcripts, live services,
installed agent binaries or private project data. These are parser and structural
checks. They do not show agent behavior, successful discovery in a running agent,
or runtime savings.

Codex synthetic cases mirror the metadata shapes observed in one real rollout:
bookkeeping, matched/unmatched usage summaries (same file/session and count),
opaque text-block results, native file changes and unsupported metadata shapes.
No private record bodies are fixtures.

| File | Covers |
| --- | --- |
| `test_inventory.py` | Codex and Claude complete projects (exact source sets); precedence, suppression and fallback modes; external targets refused, managed file with unknown scope, alias dedup, symlink loops and import cycles; eager import vs conditional link, escaped paths, ignored code examples, four-hop cap; malformed JSON/YAML/UTF-8, unsupported versions and surfaces; file, byte, item and edge limits; hook/server/credential text absent from output, command execution patched to fail, FIFOs never opened; no implicit home reads; relocated CLI from an unrelated cwd leaves every file hash unchanged; schema validation of all output |
| `test_evidence.py` | Streaming Codex/Claude JSONL and normalized exports: exact metrics and evidence refs, project and prefix isolation, worktrees, subagent inheritance, resume dedup, conflicting identities, malformed or truncated records, compaction, UTC windows, aliases, skill activation, failed vs confirmed reads, static shell parsing (shapes mirror real commands; dynamic commands qualify only file reads), per-record cwd, request copies, telemetry, caps; relocated CLI writes no bytecode or raw evidence |
| `test_report.py` | Candidate signals vs cited judgments, unknown usage and savings, protected keeps, every action, opt-in diffs, stale or ambiguous patch refusal, evidence identity, diagnostics, runtime mismatch, repeated reads vs failures vs low activity, overlap groups, accounting, privacy, limits, relocated read-only CLI |
| `test_changes.py` | Report/project/approval binding, selected-only edits, exact-once use, stale preflight, same-file conflict, byte-exact CRLF and no-newline edits, permission and owner retention, private backups, interrupted apply and rollback, hash and metadata conflicts, corrupt backups, journal locking, special files, write failures, relocated apply and recovery |
| `test_verify.py` | Relocation, metadata and links, Python/JSON syntax, notice hashes, missing dependencies, machine paths, symlinks, FIFOs, size bounds; paired-trial statuses (regression, changed conditions, more effort, missing categories, nullable usage); both host fixture profiles keep conditional ledger/recovery routes without hooks or MCP |

`fixtures/behavior/` holds public synthetic normal, routed-reference and
rare-essential tasks, not session evidence. No real recommendation is approved or
applied, and no CLI command launches a model.

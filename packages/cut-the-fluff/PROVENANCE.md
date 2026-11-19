# Provenance

Reviewed 2026-11-11. [provenance.json](provenance.json) records the exact source
commit, file hashes, original paths, upstream origins and dispositions. Source
paths there are historical identifiers, not runtime dependencies.

This package is an original standard-library implementation. All Python, schema,
references, tests and fixtures were written for it. No third-party executable code
and no upstream skill text was copied. Three components of the owner's
`project-agent-toolkit` were read completely and informed its design:

| Component | Concepts used | Deliberately not imported |
| --- | --- | --- |
| `session-analysis` | Explicit, scoped local evidence instead of implicit transcript discovery | Transcript aggregation, truncated IDs, cost weights, marker-file writes |
| `agent-writing` | Short entrypoint with conditional references; one source of truth | Skill text itself |
| `session-review` | Evidence first; proposals before changes | Handoff reader and wrap-up workflow |

`agent-writing` derives from Matt Pocock's `skills` (MIT). Its
[licence](notices/agent-writing/LICENSE-Matt-Pocock) and the origin records of all
three components are kept under [notices/](notices/), unmodified and hash-checked
by `verify`. These notices document attribution. They grant no publication,
service or project permissions, and no relicensing of owner material is asserted.

Dependencies: the Python 3.11+ standard library only (`tomllib` required; tests use
`unittest` and `subprocess`). No tokenizer, model SDK, YAML package, agent binary,
service client or telemetry dependency. Loading rules come from the official
documentation linked in the [runtime contract](references/runtime-contract.md).

Development history, validation records and the runtime-trial harness are kept
locally by the maintainer and are not published or part of this package.

# cut-the-fluff CLI

Command reference for the [skill](SKILL.md). Python 3.11+ standard library only.
`apply`/`rollback` need POSIX/Linux. On WSL a project on `/mnt/c` works; keep `--state` on the Linux filesystem. Copy the whole folder: references,
schema, tests, provenance and notices. Nothing is installed, and nothing contacts
a network, starts an agent, or runs hooks, servers or commands found in files.

## Commands

```sh
python3 -B inventory.py inventory --project /path/to/project \
  --runtime claude --runtime-version 2.1.322 \
  --home /authorized/home --directory src/payments
python3 -B inventory.py analyze --project /path/to/project --runtime claude \
  --store /authorized/transcripts --since 2026-11-01 --home /authorized/home \
  --expand-globs  # optional: match wildcards against today's tree
python3 -B inventory.py report --project /path/to/project \
  --inventory /private/inventory.json --analysis /private/analysis.json \
  --context CLAUDE.md --architecture docs/architecture.md \
  [--format json|agent|human|markdown]
python3 -B inventory.py apply --project P --report R --approval A --state S
python3 -B inventory.py rollback --project P --state S
python3 -B inventory.py verify [--inventory I] [--trials T]
python3 -B -m unittest discover -s tests
```

Run from this folder or by full script path. `<command> --help` lists every option.

| Command | Reads | Writes | Contract |
| --- | --- | --- | --- |
| `inventory` | Named context locations under explicit roots | stdout | [runtime](references/runtime-contract.md) |
| `analyze` | Named transcript/export files or stores | stdout | [evidence](references/evidence-contract.md) |
| `report` | Inventory/analysis JSON, named project files, review JSON | stdout | [report](references/report-contract.md) |
| `apply`, `rollback` | Report, approval, journal | Approved project files and a private journal | [change](references/change-contract.md) |
| `verify` | This package, optional inventory/trials JSON | stdout | [validation](references/validation-contract.md) |

`report --format` picks the reader. `json` (default) is the full record; approvals
bind to its hash and `apply` reads it. `agent` is a compact JSON summary for an
agent to read (exact counts, capped lists, cited evidence only; `apply` refuses it).
`human` is a plain-language report for the project owner. `markdown` is the
tabular view.

Exit codes: 0 means completed, possibly with coverage gaps; read `coverage`.
`analyze` also prints a `WARNING:` line on stderr for each cap it hit (real stores
often exceed the 100-session and 128 MiB defaults). 2 means refused input; stderr
names the failed check, the file or decision, and the option to change, and stdout
is empty.
`verify` exits 1 on structural failures; read `behavior.status` separately.

Output holds metadata only: logical paths, names, hashes and counts. It never
contains file bodies, commands, server arguments, URLs, environment values or
transcript excerpts. The exception is `report --include-patches`, which emits the
reviewed replacement text. Paths and names are still private: keep all output
local and outside version control, and never redirect it over a source file.

## Inventory options

| Option | Meaning |
| --- | --- |
| `--project` | Repository/worktree root; no Git lookup or root guessing |
| `--cwd` | Launch directory inside the project; defaults to the project |
| `--boundary` | Highest ancestor read for instruction files; defaults to the project |
| `--directory` | Repeatable nested project scope; there is no recursive crawl |
| `--home`, `--config-home` | Explicit user home and/or agent config directory; never implicit |
| `--allow-root` | Repeatable extra read root for references/plugins/config |
| `--plugin` | Repeatable Claude plugin root; outside roots also need `--allow-root` |
| `--instruction`, `--extra-config` | Explicit extra files (e.g. managed policy); effective scope stays unknown |
| `--memory` | Memory index file; linked topics become conditional references |
| `--runtime`, `--runtime-version`, `--surface` | Host identity; see version policy below |
| `--max-file-bytes`, `--max-total-bytes`, `--max-items` | Limits (1 MiB, 16 MiB, 2,000); a hit becomes a coverage gap |

Relative `--instruction`, `--memory`, `--plugin` and `--extra-config` paths resolve
against the shell's working directory, not the project. If such a path is missing
there but exists inside the project, the command stops and names the project path
to pass instead.

**Version policy.** Claude Code `2.1.285` and the Codex documentation snapshot
`docs-2026-11-11` are the modeled baselines. A newer Claude version or a later
`docs-YYYY-MM-DD` snapshot keeps loading values with low confidence and a
`newer_version` gap. Older versions, unparseable versions, Codex binary version
numbers and non-CLI surfaces make every loading value `unknown`.

## Reading inventory output

Each item records origin, aliases, authority `owner` (not OS ownership), scope,
precedence order, dependencies, evidence references, claim basis and confidence.
`precedence` is inventory order (global to project to launch directory). It is not
a resolved merge of settings or permissions.

| `loading` | Meaning under the selected profile |
| --- | --- |
| `startup_expected` | Body expected in context at startup |
| `metadata_expected` | Skill/command metadata expected; body loads on use |
| `conditional` | Linked reference, path rule, nested guidance or deferred body |
| `not_selected` | Suppressed by precedence rules |
| `unknown` | Needs runtime resolution, permission, version check or unsupported handling |

Loading is a documented expectation, never an observation. Usage `states` are
separate: inventory observes only `configured`. `advertised`, `loaded`, `invoked`
and `successful` need analysis evidence, and stay `unknown` otherwise. Item
`bytes` are source bytes, not tokens.

Schema: [schema.json](schema.json), version `1.0`. The default root is inventory;
`#/$defs/analysis`, `#/$defs/report` and the change/approval definitions cover the
rest. Reject other versions. Provenance: [PROVENANCE.md](PROVENANCE.md).

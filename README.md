# Agent development warehouse

A local warehouse of reusable material for any project that uses coding agents.
Project agents can select, copy, mix, and adapt assets to fit their own work.
Claude Code is the primary consumer; Codex and other agents can use the same
catalog and procedure.

Start with [AGENTS.md](AGENTS.md) for the procedure and
[CATALOG.md](CATALOG.md) to find material by task. `CLAUDE.md` points to the
same procedure, so there is one authoritative set of instructions.

## Sources

| Folder | Source | What to look for |
| --- | --- | --- |
| `repos/addyosmani-agent-skills/` | [Addy Osmani](https://github.com/addyosmani/agent-skills) | Engineering lifecycle skills, quality checklists, personas, commands, and skill evaluations. |
| `repos/mattpocock-skills/` | [Matt Pocock](https://github.com/mattpocock/skills) | Composable requirements, domain modeling, architecture, implementation, debugging, and handoff workflows. |
| `repos/cursor-plugins/` | [Cursor](https://github.com/cursor/plugins) | pstack, specialist workflows, verification harnesses, hooks, rules, and service integrations. |
| `repos/gglerum-project-agent-toolkit/` | [Project agent toolkit](repos/gglerum-project-agent-toolkit/README.md) | Reusable report/service readers, context tools, worktree and workflow checks, PHP/Laravel skills, evidence helpers, templates and operational lessons from eleven selected projects. |
| `repos/dietrichgebert-ponytail/` | [Ponytail](https://github.com/DietrichGebert/ponytail) | Lazy-senior-developer skills (minimal change, review, audit, shortcut ledger), always-on rule copies, and host hooks and manifests for 25+ agents. |

Source checkouts live under `repos/`, with owner-qualified folder names to make
their origin clear. Each third-party source remains a separate Git repository;
`repos/gglerum-project-agent-toolkit/` is warehouse-owned and tracked here as
plain files. The warehouse adds
guidance above them and does not install their plugins or change their contents.
Source revisions and content fingerprints are recorded in `warehouse.json`.

The third-party checkouts are not committed to this repository. After cloning,
run `scripts/fetch-repos.sh` to clone them at the commits pinned in `repos.lock`
(`--latest` follows each upstream's default branch instead, which needs a fresh
review).

The fourth source is a local independent repository of reusable adaptations from
eleven owner-selected projects. Its [inventory](repos/gglerum-project-agent-toolkit/inventory.json)
records group-level dispositions; [provenance](repos/gglerum-project-agent-toolkit/provenance/README.md)
retains origins, revisions, hashes and meaningful adaptations. Updates are manual
and reviewed; original projects and consumer copies do not change automatically.
No remote repository has been created or published.

## Warehouse-owned packages

[cut-the-fluff](packages/cut-the-fluff/README.md) audits project context and routing,
produces reviewed recommendations, and applies exact approved local changes with
rollback. Copy the entire package. Twelve controlled fresh Claude sessions preserve
fixture behavior while showing higher routed-task API input. This bounded result
does not certify other host profiles or general token savings. It is indexed
as a `warehouse-owned` source without an independent Git revision; maintenance
fingerprints the complete bundle, excluding Git internals and Python caches.
The four independently maintained source checkouts remain intact.

## Use from another project

Give your project agent this instruction, replacing the path for your machine:

```text
Consult /absolute/path/to/agent-harness-skills/AGENTS.md and the relevant task
routes in its CATALOG.md for this task. Select the smallest useful assets and
copy/adapt them into this project under its existing instructions and approval
rules. Check dependencies, retain attribution, verify the adapted result, and
briefly explain your selection and changes.
```

Agents
running outside WSL need a path they can access; a Windows process cannot assume
that a Linux path is directly readable. Give the actual accessible path or use
an accessible checkout. Request the needed read access through the agent's
normal mechanism when the warehouse is outside its allowed directories.

For repeated use, put a short pointer to the warehouse procedure in the
consuming project's existing agent instructions. The copied assets should use
project-relative paths and continue to work without access to the warehouse.
There is no need for global installation or symlinks.

Search without reading the whole catalog:

```bash
cd /absolute/path/to/agent-harness-skills
python3 scripts/warehouse.py search "debugging"
python3 scripts/warehouse.py search "google sheets"
python3 scripts/warehouse.py search "verification"
```

Search matches words across curated entries, task groups, source descriptions,
paths, dependency profiles, and notes. It is a lexical aid, not an agent router.

## What is included

The catalog covers eligible skills, personas, commands, rules, checklists,
scripts, harnesses, evaluations, integration configurations, and supporting
documentation. Folder bundles expose their internal components through the
linked source; individual bundled helper files need not be catalog entries.

Experimental, beta, in-progress, archived, deprecated, and comparable material
is excluded with reasons recorded in `warehouse.json`. A mixed bundle is
withheld until its eligible subset can be separated. Matt Pocock's `misc` bucket
is excluded because `SCOPE.md` declares it frozen and unmaintained. Absence of a
warning does not establish maturity.

These assets overlap and sometimes disagree. The catalog provides task routes,
alternatives, and adaptation notes so an agent can choose a coherent approach.
Read [AGENTS.md](AGENTS.md) before copying, including its dependency and
provenance requirements. Upstream source licenses apply to copied material.

## Maintenance

Requires Python 3.10+ and Git; no packages or network access are needed.
From this warehouse's root:

```bash
python3 scripts/warehouse.py check
python3 scripts/warehouse.py scan
```

`check` compares source commits and working-tree fingerprints, asset bundles,
discovered asset coverage, maturity signals, local catalog targets, and the
rendered catalog. It exits nonzero when something needs review. `scan` reports
the currently discovered entry points and maturity signals. Neither writes files.
The script resolves the warehouse from its own location, so absolute invocation
from another working directory also works.

After updating a source using your normal Git workflow:

1. Run `check` and `scan`. Review upstream changes and any new maturity signals
   in context. Source content can change even when its commit has not changed.
2. Update `warehouse.json`: entries, descriptions, task groups, dependency and
   compatibility profiles, alternatives, exclusions, and generated variants.
   Cover each discovered entry point with an eligible asset bundle, an explicit
   exclusion, or a generated-variant mapping. An excluded path must not also be
   exposed inside an eligible bundle. Do not change a source just to fit the index.
3. Review changed supporting files and any undeclared external dependencies.
   Structural discovery does not understand all prose or guarantee a complete
   dependency graph. New asset layouts may require extending discovery.
4. Explicitly record the completed review and render the catalog:

   ```bash
   python3 scripts/warehouse.py record-review --date YYYY-MM-DD
   python3 scripts/warehouse.py check
   python3 -m unittest discover -s tests -v
   ```

`record-review` is the only writing command. It requires valid metadata,
complete discovered coverage, and acknowledged maturity signals before updating
fingerprints. It records a maintainer's review; it does not perform one or certify
asset behavior. `CATALOG.md` is generated, so edit routing and judgments in
`warehouse.json`, then render through `record-review` after review.

To add a source, follow [ADD-REPOSITORY.md](ADD-REPOSITORY.md). It covers the
inventory, metadata format, exclusions, dependencies, discovery, and review
recording.

## Validation limits

The initial setup reviews source structure, documentation, representative
workflows, and dependencies. Local smoke scenarios and checker tests exercise
discovery and copying. They do not install integrations, authenticate accounts,
run the upstream workflows, or prove that an agent will follow a copied skill.
Verify the adapted asset in its consuming project.

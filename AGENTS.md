# Using the agent development warehouse

This folder is a source warehouse for projects that use coding agents. Select,
copy, mix, and adapt useful material. The consuming project's instructions,
user decisions, permissions, and approval rules govern the work.

## Select material

1. Read the consuming project's agent instructions and identify its task, stack,
   existing workflows, and available tools. Consult this warehouse when there
   is a concrete need; installing a complete workflow is optional.
2. Start at the task routes in [CATALOG.md](CATALOG.md). Search the relevant
   section or use `python3 scripts/warehouse.py search "your task"`. Read the
   matching entries and their source files, rather than loading every asset.
3. If practical, run `python3 scripts/warehouse.py check` from the warehouse.
   Drift means the recorded review may be stale. Reassess affected material
   before using it; the catalog's absence of a maturity warning is not proof.
4. Choose the smallest useful selection. Compare overlapping approaches before
   combining them. Use the catalog's alternatives and dependency profiles.
   Keep one coherent policy for testing, approvals, commits, and shipping.

## Copy and adapt

5. Follow the consuming project's approval rules. Reading the warehouse does
   not authorize publishing, pushing, merging, messaging, provisioning services,
   changing global configuration, or enabling hooks and integrations.
6. Inspect the complete asset folder, its local links, invoked skills, scripts,
   templates, and tool assumptions. Catalog dependency notes and related paths
   are a starting point, not a complete dependency resolver. Follow dependencies
   recursively until each is included, adapted, or deliberately removed.
7. Copy into the consuming project. For a skill, begin with its whole folder,
   including references and scripts. Bring any required shared files too.
   Rewrite paths after relocation. Translate tool calls, model assumptions,
   manifests, and frontmatter to the actual agent environment. If a required
   capability is unavailable, choose another asset or adapt the workflow openly.
8. Preserve the applicable license and attribution. Record the source repository,
   reviewed commit, original paths, destination paths, and meaningful adaptations
   in the project's existing provenance convention or a small local note.
   For mixed assets, retain an origin record for each contributing source.
9. Integrate with existing instructions. A source repository's root `AGENTS.md`
   or `CLAUDE.md` configures maintenance of that repository; it is not a project
   starter template. Read it when editing that source, not as a policy to import.

## Verify and report

10. Check relocated links and required tools. Use the consuming project's
    relevant checks and, where feasible, a representative invocation. Distinguish
    structural validation from an actual agent behavior test. Read executable
    helpers before running them and use the project's normal permissions.
11. Briefly report the selection, its purpose, adaptations, verification, and any
    unresolved requirement. Keep the copied result independent of this machine's
    absolute warehouse path so the project can move or be cloned elsewhere.

## Eligibility and source boundaries

- Include material without a known disqualifying maturity marker. This means
  eligible for consideration, not certified stable or behaviorally validated.
- Exclude experimental, beta, alpha, preview releases, in-progress, draft,
  archived, deprecated, retired, and otherwise unmaintained material. Read a
  warning in context: an integration rejecting an old deprecated server can
  still be eligible. A command that previews a change is not a preview release.
- Explicit exclusions and their evidence live in `warehouse.json`. Mixed stable
  and experimental bundles are withheld until a reusable eligible subset has
  been reviewed. Dependencies on excluded assets must be removed or replaced.
- Generated harness variants are associated with their canonical source. Prefer
  the supplied Claude Code variant when appropriate, retaining its adapter and
  dependencies. Do not edit generated upstream material independently.
- Source checkouts live under `repos/<owner>-<repository>/`, intact and
  independently updateable. Make warehouse changes at this root. Upstream
  changes require a fresh inventory review.

## Maintaining this warehouse

When asked to add a source repository, follow
[ADD-REPOSITORY.md](ADD-REPOSITORY.md) for onboarding, metadata examples,
eligibility review, and completion checks.

Read [README.md](README.md#maintenance) before changing the catalog. Curated
metadata and exclusions live in `warehouse.json`; `CATALOG.md` is rendered from
that metadata. `scripts/warehouse.py` is local Python standard library code.
It never pulls sources, installs tools, invokes agents, or runs source scripts.
The default command only checks and reports. The explicit `record-review`
command updates warehouse review fingerprints and renders the catalog after
the human or agent maintainer has reviewed the changes.

The fourth source, `repos/gglerum-project-agent-toolkit/`, contains reviewed
reusable adaptations from ten owner-selected projects. Its inventory records
retained items, alternatives and exclusions; provenance records the source
revisions, file hashes and adaptations. Updates are manual and reviewed. Adding
or updating this source does not authorize harvesting unrelated projects.

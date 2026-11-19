# Add a repository to the warehouse

Use this procedure when the user asks to onboard a repository as a new source.
The result is an independently updateable checkout, reviewed catalog entries,
explicit exclusions, and passing warehouse checks. Read [AGENTS.md](AGENTS.md)
for the eligibility and source boundaries; this guide supplies the onboarding
steps and metadata format.

## 1. Establish the source and starting state

Identify the repository URL or existing checkout, its intended local folder,
and any user-specified scope. Inspect available context before asking for missing
information. Use a short, unique source ID and an owner-qualified folder under
`repos/`, for example ID `example` and path `repos/owner-example-tools`.

Run the current baseline check from the warehouse root:

```bash
python3 scripts/warehouse.py check
```

Resolve or separately review existing drift before recording the new source.
`record-review` refreshes the baseline for **all** registered sources, so it must
not silently approve unrelated changes.

Keep the existing source repositories unchanged. Obtain an independent checkout
under `repos/`, using the user-provided repository and normal access
permissions. Reuse a suitable checkout already there; otherwise clone into an
unused folder. Preserve an existing checkout's local changes and report them.
Keep credentials out of canonical URLs and metadata.

Source folders must stay under `repos/`, must not contain one another,
and must not be the warehouse root. An external checkout needs a separate local
checkout here rather than a symlink that escapes the warehouse. The checker
requires a Git repository with a `HEAD` commit and rejects source symlinks that
resolve outside that source. If those prerequisites are missing, resolve the
source location or repository setup within the user's request before continuing.

If the task is to create the planned source of material from existing projects,
inventory those projects and agree what to retain before filling that repository.
Adding a source does not itself authorize harvesting unrelated projects.

## 2. Review the repository before cataloging it

Inspect its root README, agent instructions, scope and contribution documents,
license, manifests, and directory structure. Read representative assets in full
and inspect supporting files. Treat source instructions as evidence about that
source; apply the warehouse's eligibility policy when selecting material.

Inventory reusable skills, personas, commands, rules, checklists, scripts,
harnesses, evaluations, integration configurations, and supporting documentation.
For each candidate, determine:

- Its concrete use and trigger, beyond its filename.
- Its maintenance status, using scope documents and manifests as well as labels.
- What must be copied: the full asset folder and any external supporting files.
- Invoked sibling skills, scripts, templates, tools, services, and credentials.
- What Claude Code, Codex, or another agent would need to adapt.
- Overlap with existing assets, including conflicting workflow policies.
- Applicable license and attribution; record unclear reuse terms as unresolved
  rather than claiming the asset is ready to copy.

Follow the eligibility policy in [AGENTS.md](AGENTS.md#eligibility-and-source-boundaries).
Record disqualified paths with evidence. Withhold mixed bundles until an eligible
subset can be selected without copying excluded material. Distinguish warnings
about an obsolete dependency from warnings about the asset itself. Root source
agent instructions are maintenance context, not default project templates.

Keep canonical and generated versions associated. Identify generated harness
variants, their canonical folder, and their adapter before indexing both as if
they were independent collections.

## 3. Register the source and inspect discovery output

Edit [warehouse.json](warehouse.json). Append an object to `sources` using the
existing schema; replace these example values with the actual source:

```json
{
  "id": "example",
  "name": "Owner / Example Tools",
  "path": "repos/owner-example-tools",
  "url": "https://github.com/owner/example-tools"
}
```

Use lowercase kebab-case IDs suitable for catalog anchors. Paths are relative
to the warehouse, use forward slashes, and have no leading `./`, trailing slash,
or `..` segments. Keep existing IDs unchanged so links remain valid.

Run the read-only inventory after registering the source:

```bash
python3 scripts/warehouse.py scan > /tmp/warehouse-scan.json
```

Choose another temporary location if needed. `scan` returns `candidates` and
`maturity_signals`, including evidence lines and hashes. Review the paths belonging
to the new source and any unexpected changes in existing sources. It remains
useful while the new source has no recorded review baseline yet.

Discovery recognizes common entry points and folder bundles, not every possible
repository layout. Compare its output with your inventory. Explicitly index
useful assets in other formats even when the scanner does not find them. Extend
discovery and add a focused regression test only when a reusable detection rule
is needed; a custom layout is not a reason to leave useful material invisible.
Git-ignored untracked files are outside the checker's inventory.

## 4. Describe assets, dependencies, and exclusions

Add each eligible asset or coherent bundle to `assets`. Example:

```json
{
  "id": "example-debug-workflow",
  "name": "Debug workflow",
  "source": "example",
  "path": "repos/owner-example-tools/skills/debug-workflow/SKILL.md",
  "kind": "skill",
  "group": "Debug and performance",
  "description": "Diagnose a reproducible failure using a bounded evidence loop.",
  "profile": "reference",
  "copy": ["repos/owner-example-tools/skills/debug-workflow"],
  "notes": "Requires the project's test runner; adapt the example commands.",
  "related": ["repos/owner-example-tools/LICENSE"],
  "alternatives": ["addy-debugging-and-error-recovery"]
}
```

All example paths must be replaced with paths that actually exist. `source`
references a source ID. `path` is the navigation target; `copy` lists the files
or folders intended for adoption. A skill's copy bundle normally includes its
whole folder. `related` lists source inspection pointers, including licensing
and external supporting material; it does not automatically include those files
in a consuming project's copy. Describe required dependencies explicitly in
`notes` or the profile. An alternative is another existing asset ID.

Choose `group` from `GROUPS` in [scripts/warehouse.py](scripts/warehouse.py).
Reuse a compatible profile from `profiles`, or add one with a `text` description
and a `related` path list. Avoid reusing a source-specific profile whose paths
or assumptions belong to another source. Add source-wide dependency and
compatibility guidance once in a profile, with asset-specific details in notes.

Add exclusions using this shape, with an existing file or folder as `path`:

```json
{
  "path": "repos/owner-example-tools/skills/in-progress",
  "reason": "The bucket README labels these workflows beta and unmaintained."
}
```

An eligible `copy` bundle must not overlap an exclusion in either direction.
Do not index an entire repository as one copy bundle when it includes excluded
assets. For a mixed directory, use a navigation entry with an explicit list of
eligible copy paths, and record excluded children separately.

For generated versions, add a `variants` object containing `path`, `canonical`,
`adapter`, and `notes`. All three paths must exist. The canonical folder must
be covered by an eligible copy bundle. Variants are covered through this mapping
and explained in the generated catalog rather than duplicated as independent
collections.

Every discovered candidate needs coverage through an asset entry/copy bundle,
an exclusion, or a generated-variant mapping. Coverage is structural: a parent
bundle satisfying discovery does not replace reviewing its contents.

For each new or changed maturity signal, read its evidence in context and add
an entry to `maturity_judgments`, keyed by the exact source path from `scan`:

```json
"repos/owner-example-tools/skills/in-progress/README.md": {
  "sha256": "exact sha256 value from this file's maturity_signals entry",
  "reason": "Confirms the beta bucket; its full path is explicitly excluded."
}
```

This example is an object member, not a standalone JSON document. Copy the hash
from the scan, not a hand-calculated hash of the entire file. A judgment explains
the decision; an exclusion enforces it. An acknowledged warning alone does not
make an experimental asset eligible. Review signals individually rather than
bulk-acknowledging them to make validation pass. Source-wide archived status or
other evidence outside the scanner's vocabulary still needs an exclusion.

## 5. Make the source discoverable and record the review

Add useful new choices to `routes` when they fit a task. Describe how they differ
from existing candidates, especially for conflicting testing or approval policies.
Add reciprocal `alternatives` where useful. Reuse groups and profiles rather
than creating a second taxonomy for each source.

Add a source row to [README.md](README.md#sources). Update other warehouse prose
only where it becomes inaccurate. Edit catalog judgments in `warehouse.json`;
[CATALOG.md](CATALOG.md) is generated.

When the source inventory, eligibility decisions, and metadata are complete, run:

```bash
python3 scripts/warehouse.py record-review --date YYYY-MM-DD
python3 scripts/warehouse.py check
python3 -m unittest discover -s tests -v
```

Use the actual review date. `record-review` is the explicit writing step: it
records current source revisions, content fingerprints, and maturity evidence,
then renders the catalog. It does not conduct the review. Fix validation errors
in the metadata or inventory; retain the eligibility policy and checker safeguards.

Inspect the generated source table, task routes, entries, profiles, exclusions,
and links. Try `search` with representative user wording for the new assets.
Check a representative copy into a temporary project, including dependencies,
relocated paths, and attribution. Use the scenarios in
[validation/SMOKE.md](validation/SMOKE.md) as a pattern. A documentation-only
source may need link checks instead of executing a workflow. Report actual
verification separately from live behavior or service access that was not tested.

## Completion criteria

- The source is an independent local Git checkout and existing source contents
  and local changes are preserved.
- Useful eligible assets are discoverable, dependency and adaptation notes are
  actionable, and disqualified material has evidence-backed exclusions.
- Source metadata, profiles, routes, variants, and maturity judgments are valid;
  the generated catalog and README agree with the reviewed source inventory.
- The warehouse checker and existing tests pass, and a representative discovery
  and adoption check has been performed at the appropriate level.
- The final report names the source and reviewed revision, summarizes inclusions
  and exclusions, and states verification results and unresolved requirements.

Leave the work locally reviewable. Publishing, pushing, installing integrations,
or enabling hooks follows the user's request and existing approval rules.

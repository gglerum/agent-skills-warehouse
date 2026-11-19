# Approved changes and recovery (1.0)

Read only when the user asks to apply reviewed proposals or recover a change.
A proposal, a filesystem grant or permission to build this package is not
approval. Approval is the user's explicit acceptance of the exact diffs of named
findings in one saved report. Record it; never infer it from findings.

## Approve

1. Regenerate the **JSON** report with `--include-patches` and save it. Its
   `changes` list holds, per proposal, the exact replacement, project-relative
   path, before/after SHA-256, finding ID and `change_sha256`.
2. Show the user the diffs and get explicit approval of named findings. Any edit
   to the saved report needs renewed approval of the new bytes.
3. Write a private approval file:

```json
{
  "schema_version": "1.0",
  "kind": "change_approval",
  "scope": "project",
  "project": "/resolved/absolute/project/root",
  "report_sha256": "SHA-256 of the exact saved report file bytes",
  "selections": [
    {"finding_id": "finding:2", "change_sha256": "copied from that finding's entry in changes"}
  ]
}
```

`change_sha256` is SHA-256 of the proposal object without that field, serialized
with `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=True)`. The
approval is a workflow record, not a signature. Apply refuses: empty, unknown or
duplicate selections; a wrong project or report hash; `keep` findings; global
scope; and **two selections for one file**, even if they look disjoint. For two
edits to one file, write one combined review decision and approve the new report.

## Scope limits

Only existing project-local regular files are edited, by exact replacement. No new
files, deletions, archives, global or user configuration, arbitrary patches or
semantic config merges. Those need a separate manual workflow. Put a global
recommendation in a separate discussion that names the owner, affected projects,
cross-project effects, recovery plan, and why a project-local fix is not enough.
Do not relabel a user or global directory as a project to get around this.
Approval must preserve policy, retained routes and unrelated content; the CLI
checks bytes, not meaning.

## Apply

```sh
python3 -B inventory.py apply --project /approved/project \
  --report /private/report.json --approval /private/approval.json \
  --state /private/new-recovery-directory
```

`--state` must be a new directory, outside and separate from the project, whose
parent exists, with no symlink ancestors. It is created mode 0700. Its
`manifest.json` (mode 0600) holds **full before/after file contents**, hashes,
the approval binding, modes and owner/group IDs. Keep it private and out of
version control until recovery is no longer needed.

Before any write, every selected file is checked for before hash, exactly one
occurrence of the replacement, resulting hash, type, ownership and mode. Then a
`prepared` manifest is saved. Each file is rechecked and replaced atomically.
Other bytes stay exact (CRLF, missing final newline), as do owner/group and
permission bits. Refused targets: symlinks, hardlinks, special files, setuid-style
mode bits, extended attributes/ACLs, files you do not own, and `.git` paths. A
filesystem that reports no xattr support (`ENOTSUP`) is treated as having none.
Mutation needs POSIX/Linux; native Windows does not work. On WSL the project may
be on `/mnt/<drive>`, but `--state` must be on the Linux filesystem (e.g. under
`~`): drvfs ignores `chmod`, so a state directory there is refused before any
project write. Drvfs reports every file as mode 0777, and a mode change there can't
be detected.

A lock blocks two commands sharing a journal. It does not stop editors or other
writers. Stop them first: a racing writer can slip between the final check and
the rename, so this is a cooperative tool, not a sandbox.

Results:
- Success: status `applied`. Rerunning the same apply returns `already_applied`
  while the applied bytes and metadata still match.
- Failure: exit 2 with no JSON, and **some files may already be changed**.
  Preserve the state directory, inspect `manifest.json`, then run rollback. If it
  failed before the manifest was saved, nothing changed. An empty or partial
  state directory then needs inspection and a fresh path, never blind reuse.

## Roll back

```sh
python3 -B inventory.py rollback --project /approved/project \
  --state /private/new-recovery-directory
```

The approved change workflow covers rollback, unless the user excluded recovery
from scope. Rollback needs only the journal. It validates backups against their hashes and
checks **every** file before restoring any:
- still original bytes: skipped;
- exactly the applied bytes and metadata: restored;
- anything else: conflict, and nothing is restored.

A conflict means later work exists. Preserve it, inspect the private backup and
reconcile manually with the user's approval. There is no three-way merge and no
force option. After a crash, rerun rollback: it skips restored files and finishes
the rest. The final status is `rolled_back`. Repeating it is a no-op while the
originals still match, and a conflict after any later edit. A rolled-back journal
cannot be used to apply again: regenerate the report, get fresh approval and use
a new state directory. Backups are never deleted automatically.

A successful apply says nothing about token savings, discovery or task quality.
Check those with the [validation contract](validation-contract.md).

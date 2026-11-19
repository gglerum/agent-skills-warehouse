# Exact patch

Apply a reviewed batch of exact-text edits with prevalidation.

Python 3.10+ standard library.

```sh
python3 patch.py edits.json --dry-run
python3 patch.py edits.json
```

Input is a list of `{"file":"path","old":"exact text","new":"replacement","count":1}`. All matches are checked before writing; a mismatch exits 1 without writing any file. Successful replacement preserves file modes and is atomic per file. A later filesystem failure can leave a partial multi-file write; this is not a cross-file transaction. Review symlinks/paths and concurrent edits before invoking. `--then COMMAND` explicitly runs a shell command after writing and returns its status; use only an authorized command. Exit 0 means the requested operation completed.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

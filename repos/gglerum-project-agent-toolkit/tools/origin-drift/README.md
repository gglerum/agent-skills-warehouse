# Origin drift

Compare a copied component's original file hashes with source folders you explicitly select.
Python 3.10+ standard library. It reads local files only; it does not fetch, sync or modify anything.

```sh
python3 check.py ../exact-patch/ORIGIN.json --source source-project-g=/path/to/source-project
```

Supply one NAME=FOLDER mapping for each origin project in that component. Exit 0 means the recorded files match, 1 means content changed, and 2 means comparison is incomplete. The origin revision is a provenance pointer; matching a revision alone would miss working-tree changes, so this helper checks actual file hashes. Differences require review and deliberate adaptation, not automatic overwrite of source or consumer assets.

Copy this folder with ORIGIN.md/ORIGIN.json and retain the component's applicable notices.

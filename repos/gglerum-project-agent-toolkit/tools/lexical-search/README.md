# Lexical search

Index explicitly selected tracked project files for local SQLite lexical search.

Python 3.10+ standard library, SQLite with FTS5, Git. Copy fts.py, tokens.py and search.py together.

```sh
python3 search.py build --root /path/to/project --db /chosen/private/index.db
python3 search.py query --root /path/to/project --db /chosen/private/index.db --query "invoice validation"
python3 search.py refresh --root /path/to/project --db /chosen/private/index.db
```

This is the independently extracted closed R1 lexical subset, not the unfinished semantic/pilot augmentation system. No models, embeddings, services or automatic Claude integration are included. The CLI uses tracked files only, skips symlinks, common secrets/binaries and large files, and binds the index to its source root. Filtering is not a complete secret detector: review the selected repository before indexing and protect the index as source data. Build refuses an existing DB; refresh hashes live files and drops missing paths. Results are ranked paths, not proof that the answer exists. Stored FTS5 tables avoid a newer contentless-delete SQLite requirement. Synthetic tests verify query and refresh behavior, not quality gains on a consumer corpus.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

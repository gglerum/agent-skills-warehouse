# Finding records

Review findings and user-feedback items as one file per item, with generated overview documents and a `check`.

Python 3.10+ standard library; no network access. Copy the entire folder.

```sh
python3 findings.py --config findings.config.example.json add S9 --group "Security" --severity High \
    --found-by "review of 2026-01-15" --text-file /tmp/one-line.txt
python3 findings.py --config findings.config.example.json status S9 fixed "released in 1.4"
python3 findings.py --config findings.config.example.json list --status open
python3 findings.py --config findings.config.example.json fb status FB-003 "triaged, scheduled"
python3 findings.py --config findings.config.example.json index
python3 findings.py --config findings.config.example.json check
```

## Model

- A finding is a front-matter record plus one line of text (it becomes a table cell). Fields: id (default pattern one letter, digits, optional letter), group, position inside the group, severity (`Blocker`, `High`, `Medium`, `Low`, `Info`, `False positive`), who found it, status (`open`, `fixed`, `accepted`, `wont-fix`, `decided`) and an optional note.
- Groups are `_groups/NN-slug.md` files: front matter `title`, then free text, the table header and the line `<!-- findings-table -->`. Findings of that group replace the marker; groups render in file order, findings by position.
- A feedback item (`FB-nnn`) is a longer record whose body starts with `### FB-nnn title` and whose status is free text. The overview lists them in one table followed by the sections.
- `index` regenerates the two overview documents. `check` fails on missing fields, duplicate or mismatching ids, unknown groups, invalid severity or status, an empty text, or a stale overview. Never edit the overviews by hand; on a merge conflict run `index` again.

Wire `check` into a pre-commit hook for the finding paths and into a session-end check (see [session closeout](../session-closeout/README.md)). `findings.py` never contacts a service.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

# Design register

Answer "is this state or text designed anywhere, and which issue and decision does it belong to?" from a register instead of memory.

Python 3.10+ standard library; no network access. Copy the entire folder.

```sh
python3 register.py --config register.config.example.json add checkout_flow --write-ids
python3 register.py --config register.config.example.json find "order confirmed"
python3 register.py --config register.config.example.json for 42 DEC-007
python3 register.py --config register.config.example.json show checkout_flow#f16
python3 register.py --config register.config.example.json index
python3 register.py --config register.config.example.json check
```

## Model

- One JSON record per prototype or wireframe HTML file (`register_dir/<stem>.json`), hand-owned so parallel branches rarely collide.
- A frame is a `<figure id="fN">` inside that file; its reference is `stem#fN`. `add --write-ids` gives figures without an id one derived from their caption number.
- A record names its kind (`wireframe` or `prototype`), status (`proposed`, `approved`, `superseded`, `existing`), the page of an external design export it follows (`design_ref`), the view that implements it, and the issues and decisions it belongs to. A frame adds its own issues and decisions.
- A superseded frame must name `replaced_by` (an existing frame) or `removed_because`. A proposed or approved wireframe must name its issue.
- `find <text>` searches the register first and then the visible text of every artifact, maps text hits to their frame, and prints `NOT FOUND` together with what was searched. Only that output supports the statement that no design exists. External design exports are not searched.
- `for <issue | decision id>` lists the artifacts and frames that belong to it.
- `check` fails on a file without a record, a record without a file, a figure without an id or with a duplicate id, a frame that exists on only one side, an unknown decision id (when `decisions_dir` is configured), an unreplaced superseded frame, a stale overview, and any code matching `visible_code_pattern` in visible text (comments, ids and attributes are exempt). The pattern keeps tracker or decision codes out of pages that readers cannot look them up from; the register carries the link instead.

Wire `check` into a pre-commit hook for the artifact and register paths. The tool reads and writes only files under the configured directories.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

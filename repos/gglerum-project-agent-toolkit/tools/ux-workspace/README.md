# Ux workspace

Validate prototype registry and shared UI fragments separately from human acceptance.

Python 3.10+ standard library and an explicit lab manifest.

```sh
python3 check.py labs.example.json --root /path/to/design-workspace
python3 sync.py labs.example.json --root /path/to/design-workspace
python3 sync.py labs.example.json --root /path/to/design-workspace --write
python3 feedback.py acceptance.md --from-file observations.txt --write
```

Manifest has `labs` entries with file/acceptance/tests paths and optional `shared` entries with source/begin/end markers. Each referenced file must exist; shared markers must occur exactly once in order and match their source. No product labs or in-progress acceptance records are copied. This static helper does not execute browser tests, inspect screenshots or pass a human gate. Use the consumer's browser driver for real interaction and record actual participant feedback separately.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

Shared-block refresh prevalidates every target before writing and replaces each file atomically; it is not a cross-file transaction. Participant feedback appends observations and never passes an acceptance gate. Preview is the default for both write helpers.

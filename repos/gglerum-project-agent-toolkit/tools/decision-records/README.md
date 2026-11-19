# Decision records

One file per decision, a generated overview, and a `check` that fails on drift.

Python 3.10+ standard library. `mirror` and `strays` also need an authenticated `gh`; every other command is local. Copy the entire folder.

```sh
python3 decisions.py --config decisions.config.example.json add --title "Use optimistic locking" --status decided \
    --text-file /tmp/text.md --on 2026-01-15 --by "team" --sources "https://example.test/thread"
python3 decisions.py --config decisions.config.example.json supersede DEC-001 DEC-004
python3 decisions.py --config decisions.config.example.json show DEC-004
python3 decisions.py --config decisions.config.example.json for 42 F10
python3 decisions.py --config decisions.config.example.json index
python3 decisions.py --config decisions.config.example.json check
```

## Model

- `<records_dir>/<PREFIX>-nnn.md` holds the front matter (id, title, status, date, who, issue, stories, related ids, supersession links, source URLs, tracker link) and the decision text. **The record is the only place with the decision text.** Other documents, issues and wireframes name the id and never copy the text.
- Status is `decided`, `proposed` (awaiting approval), `open` (a person must decide) or `superseded`.
- `supersede <old> <new>` moves the old record to `archive/`. `list` and `for` stop showing it, `show` warns, and `check` fails on any document that still names it (files listed in `history_files` may). Ids are never reused.
- The overview file is generated and must not be edited by hand. `check` fails when a record is invalid, an id is referenced without a record, supersession links disagree, a decided record has no date, author and place, or the overview is stale.
- `for <issue number | related id>` is the lookup used when starting work on an issue.

## Tracker integration (optional)

Set `tracker_repo` to `owner/repository` to enable:

- `mirror <ID>` writes a section into the body of the decision's issue and of its stories: a line per current decision with a direct link to the file, between markers so a rerun touches only those lines. The text is not copied. This puts decisions where tracker readers look without creating a second source of truth.
- `strays` lists what in the tracker is not a record yet: comments that start with `decision_marker`, comments by `reviewer_login` that are neither recorded (`--sources`/mirror link) nor acknowledged, and open issues that still name a superseded decision. `ack <comment url> <reason>` marks a comment as read without a decision.

Both call `gh` and write to or read from a remote service. Run them only when the consuming project authorizes tracker access; `mirror --dry-run` prints what would be written. Set `DECISIONS_GH` to a fake command for fixtures.

## Configuration

Copy `decisions.config.example.json` and adjust. Paths are relative to the configuration file. `command` is only the text used in messages. `_intro.md` in the records directory holds the title (first line) and any text above the generated tables.

Copy this complete folder with its ORIGIN.md and licence files. The consuming project's instructions, tools and permissions govern use.

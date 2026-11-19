---
name: record-keeping
description: "Record decisions, findings, user feedback and design artifacts as one file per item with a generated overview and a failing check, and look them up instead of re-deriving or guessing."
---

# Record keeping

Use when a session makes or learns a decision, finds a problem, receives user feedback, adds or changes a screen, or must answer "was this decided or designed already?". Read existing records first; add a record only for something durable.

## Principles
- **One source per fact.** A decision's text lives in its record file only. Issues, stories, wireframes, skills, other docs and handoffs name the id and never copy the text; a copy goes stale and the stale copy gets built.
- **One file per item, generated overview.** Records are hand-owned files so parallel branches rarely conflict; overviews are generated, committed and never edited by hand (on a merge conflict, regenerate). A `check` command fails on invalid records, unknown references and a stale overview, and runs from the commit hook and the session-end check.
- **Supersede, do not edit history.** A replaced decision moves to an archive, `show` warns, and `check` fails on live documents that still name it. Ids are never reused.
- **Look up, then say.** Before writing "no design exists" or "no decision was made", run the lookup (`find`, `for`, `show`, `list`); only its NOT FOUND, which names what was searched, supports that sentence.
- **Record in the same session.** An answer in chat or a design session that changes a decision becomes a record (or a supersession) now. Never leave "a new decision is needed" as a note in a handoff. Do not claim a person approved something unless their approval is recorded.

## Tools
- [Decision records](../../tools/decision-records/README.md): add, status, supersede, show, list, for, index, check; with a tracker, `mirror` (links into issue bodies, no copied text) and `strays` (answers in the tracker that are not records yet; `ack` marks a comment as read without a decision).
- [Finding records](../../tools/finding-records/README.md): findings with group, severity and status, and feedback items with free-text status.
- [Design register](../../tools/design-register/README.md): one record per wireframe or prototype, one entry per frame (`file#fN`), linked to issues and decisions; `find <text>` before claiming a state was not designed.

## Routine
1. At session start read what applies: `for <issue>` on decisions and design, `show` on the finding or feedback item the task names.
2. During work: new decision, `add` (or `supersede`); new problem, finding `add` with severity and a one-line text; a changed status, `status`; a new or changed wireframe, register `add --write-ids`, fill in issues and decisions, `index`.
3. Before stopping: run every `check` (the [session closeout](../../tools/session-closeout/README.md) does it) and fix what fails instead of silencing it.
4. Record every mistake made along the way, not only its fix, in the finding or process log the project keeps.

Writing to a tracker (`mirror`, edits to issue bodies) is an external write: do it only when the task authorizes it, and prefer `--dry-run` first.

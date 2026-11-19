---
name: roadmap-session
description: "Run one roadmap session end to end: one issue group, one branch, one pull request, with a single preflight call, test-first work, a quality gate, records, and a written handoff."
---

# Roadmap session

One session is one issue group, one branch and one pull request. Read only what the issue points to; keep the session small. When the context passes the project's split point (a context guard can warn at about 150k tokens), finish the current step, write the handoff and suggest a fresh session instead of carrying on.

Tools used: [roadmap board](../../tools/roadmap-board/README.md), [session closeout](../../tools/session-closeout/README.md), [record keeping](../record-keeping/SKILL.md), [worktrees](../../tools/worktrees/README.md), [throwaway container](../../tools/throwaway-container/README.md). Use the consumer's equivalents when it has its own.

## 1. Preflight (stop here if anything fails)
- Run the project status, then **one** preflight call per issue (`preflight.sh <n>`) instead of raw issue reads plus grep: it prints the issue with comments, the state of every blocker, the finding or feedback text, the decisions that apply and the design artifacts. A design question is answered from the register and the design issues, not from memory.
- Every blocking issue (the tracker's "Blocked by" relation) must be closed. A decision or design blocker needs a recorded approval. If not, stop and say which one is missing; do not guess product choices.
- A card that needs a decision or confirmation means the user has not confirmed the default yet: ask first.
- A decision, spike or design issue is not a coding task: discuss with the user, write the outcome into the issue (a long outcome in `docs/` with a link), and record every decision with the decision tool, then mirror it to the issue when authorized. Run `strays` in the preflight: an unrecorded answer in the tracker is either a decision (record it) or gets `ack` with a reason.
- Large or unclear scope: plan before editing. Another session active in this checkout (uncommitted files you did not write, another worktree)? Do not share it: start a worktree and work from there.

## 2. Read only what you need
The source ids the board names, the issue's design artifacts (`for <n>`), the files its technical notes name, and the project guidance for the area (auth, admin, tests, language). If the issue adds or changes a screen, read the design notes and compare with the design before building and again after (see [design conformance](../design-conformance/SKILL.md)).

## 3. Branch and move the card
Branch from an up-to-date base, one branch per session, and move the card to its started status when the project's board rules allow it.

## 4. Build, test first
Write the failing test first and run it narrowly. A change that touches registration, login, mail or another flow with faked collaborators also needs the end-to-end check that shows the real flow. Follow the project's rules for dependencies (none added without approval; name the package), languages, privacy (no personal or location data in logs) and test doubles for external services. An unexplained bug after two tries: stop guessing and use [bounded-debugging](../bounded-debugging/SKILL.md). Before writing "it works": gather evidence. A new or upgraded package: [dependency-change](../dependency-change/SKILL.md).

## 5. Everything the story produces
List what the story makes the application send or show (a mail, a notification, a PDF, a screen) and look each up in the design register. Build output from the design's own markup, not a framework default. After building, produce the real output and compare it element by element (text, order, logo, colours); a test on a subject line is not a comparison. Only then write "follows the design".

## 6. Quality gate
Run the project's full check command and the hook's tools in the project's toolchain. Never skip hooks (`--no-verify`). Review what automatic fixers changed. The floor guard (see [floor guard](../../tools/floor-guard/README.md)) must stay clean: no new suppression, skipped test, lost assertion or weaker rule.

## 7. Docs and records
Update only what applies: design notes and register, findings and their status, process log (step plus lesson), deployment notes, decisions through the tool. Never edit a generated overview by hand.

## 8. Commit, push, pull request
Commit, push and open the pull request without asking for a go-ahead only when the project says so; otherwise ask. Stop and ask when the gate fails, a criterion is not covered, or the issue says wait. The pull request follows the template, references issues with `Refs #<n>` (never `Closes`, `Fixes` or `Resolves`: a merge is not a review; see [pull request conventions](../../tools/pr-conventions/README.md)), and states what was not verified. Read branch and pull request state again right before pushing; the base moves. Do not merge. Use `pr_status.sh` for merge state and failed checks.

## 9. Handoff and stop
Run `session_end.sh` first and fix what it reports, or say plainly what stays open. Write the handoff with `board.sh handoff`: changed files, tests run and results, anything skipped or failing, what the next session must know, new finding ids; state what was not verified (real device, camera, location). Then print the next session's start prompt (`session-prompt`) and suggest a fresh session.

## Never
Merge without the user; close an issue or move a card to Done (the people who review do that); put a closing keyword in a pull request or commit; edit unrelated issues; mark a criterion done that no test or check covered; change product rules recorded in decisions without a recorded decision.

---
name: design-conformance
description: "Keep built screens conforming to the design export: compare against the design, hold a baseline, and have a different reviewer judge the result."
---

# Design conformance

Use when an issue adds or changes a screen, mail, PDF or other visual output, or when someone claims an output "follows the design".

Tools: [design compare](../../tools/design-compare/README.md), [design register](../../tools/design-register/README.md), the [design-reviewer agent](../../agents/design-reviewer.md).

## Steps
1. **Find the design.** Run the register lookups (`for <issue>`, `find "<text>"`) and list the design pages. Before writing "no design exists", the lookup must say NOT FOUND and the design export's pages must have been checked.
2. **Compare before building.** Run `compare <design page> <target>` on the current state and read `compare.png` (design | page | difference) before the table. Note which rows are real, which are content differences (placeholder text in the design) and which are tool artefacts.
3. **Build** from the design's own markup and the project's handoff rules. Follow the project's fidelity bar; the tool defaults to "close is enough" (6 px position, 8 px size).
4. **Compare again** and run `all --check`: no screen may be worse than the baseline. Raise the baseline only with a stated reason in the pull request; save it deliberately (`--save-baseline`).
5. **Independent review.** Spawn the `design-reviewer` agent with the screens, design pages, targets and head commit; the builder never reviews their own screen. Put its verdict (`PASS | ISSUES | BLOCKED_BY_SETUP`) in the pull request. Skip steps 4 and 5 for changes that touch no screen.
6. **Register the artifact.** A new or changed wireframe gets a register record (frames with ids, issues, decisions; a replaced frame names its replacement), no tracker or decision codes in its visible text, and a regenerated overview.
7. **Non-screen output** (mail, notification, PDF): produce the real output, compare element by element with the design, report that comparison in the pull request. A test on a subject line is not a comparison.

## Honest reporting
A command that could not run (no browser, no poppler, application not reachable, a redirect to a login page) is BLOCKED_BY_SETUP, not a pass. Nothing measured here is verified on a real device, real mail client or real screen reader: say so. When the design has no page for a screen, say that nothing was measured and name the nearest layout used as precedent.

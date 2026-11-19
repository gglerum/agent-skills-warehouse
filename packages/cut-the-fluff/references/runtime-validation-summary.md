# Scoped runtime validation (2026-11-11)

Twelve fresh Claude Code 2.1.322 sessions: first-party `claude-opus-5-5`, low
effort, restricted mode, Read tool only, no MCP. Three fixture tasks ran under
baseline and changed instructions twice, with variant order reversed in round 2.
Every run reported the same tools, model and permissions. The author chat and
answers were not passed to the test model.

All 12 answers met the rubric. Changed routed and recovery tasks read their
required reference; normal tasks read neither. No repeated, denied or outside read
and no source change occurred.

| Task | Aggregate input tokens, baseline → changed | Guidance reads |
| --- | --- | --- |
| Normal local checks | 5,587 → 5,517 | 1 → 1 |
| Newly routed ledger | 5,617 → 8,589 | 1 → 2 |
| Rare essential recovery | 5,603 → 8,581 | 1 → 2 |

Aggregate input is the runtime-reported sum of uncached, cache-creation and
cache-read input across all API calls; it is not peak context. Caches were warm.
No billing claim is made.

**What this supports.** Trimming kept required behavior on the normal task. Routed
tasks stayed correct but used about 50% more input, so `verify` keeps
`review_required` and a general routing optimization stays unapproved. Keep
guidance inline when the tasks that need it are frequent. Lower file bytes alone
never justify a change.

**Limits.** One model and runtime, two repeats, three small answer-only synthetic
tasks, manual grading. The prompt told the model to Read AGENTS.md, so native
startup loading and automatic skill discovery are untested. No production recovery
or real skill activation ran. Inventory version profiles are unchanged. Codex was
not tested live. Separately, its transcript adapter is validated on 1 rollout
(metadata shapes only, 2026-11-12); see [Codex notes](codex-report.md) for gaps.

The curated records and harness are kept locally and are not published; the
package does not need them. SHA-256:

- `cut-the-fluff-milestone-5-runtime-trials.json`: `85ee79a9cdad33bfc1cfae2b4e93f1ddef4d6d1dac314c46a9c7c6d7ede66557`.
- `cut-the-fluff-milestone-5-runtime-observations.json`: `032c9a895adcaa96f6cf4f65c56240ead478daa74b0247195fb1054edd2f5351`.

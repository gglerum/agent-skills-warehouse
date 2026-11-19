# Project agent toolkit

Reusable tools, skills and workflow references adapted from eleven existing projects.
Choose a component for the task; no shared installation, symlink, service or hook activation is required.
Claude Code is the primary consumer. Most tools also work with other coding agents;
translate client-specific instructions and permissions to the actual environment.

## Find material by task

| Need | Start here |
| --- | --- |
| Test/report evidence | [Test reports](tools/test-reports/README.md), [converters](tools/report-converters/README.md) |
| CI, tracker and release evidence | [Service readers](tools/service-readers/README.md), [deployment receipts](tools/deployment-receipt/README.md), [issue preflight](tools/issue-session/README.md) |
| Small context and edits | [Code navigation](tools/code-navigation/README.md), [exact patches](tools/exact-patch/README.md), [lexical search](tools/lexical-search/README.md) |
| Session improvement | [Transcript analysis](tools/session-analysis/README.md), [conversation indexing](tools/conversation-index/README.md), [session review skill](skills/session-review/SKILL.md) |
| Reliable workflow checks | [Git/index checks](tools/git-checks/README.md), [recoverable worktrees](tools/worktrees/README.md), [project-state gates](tools/project-state/README.md), [scaffold/spec checks](tools/project-checks/README.md) |
| PHP/Laravel projects | [Quality configuration](tools/php-quality-config/README.md), [test/database adapters](tools/laravel-tests/README.md), framework reference skills below |
| UX and security evidence | [UX consistency](tools/ux-workspace/README.md), [reference lookup](tools/reference-library/README.md), [fixture evidence](tools/fixture-evidence/README.md), [proof discipline](references/proof-discipline.md) |
| Optional hooks and operations | [Hook adapters](tools/hooks/README.md), [session guards](tools/session-guards/README.md), [container status](tools/container-status/README.md), [throwaway container](tools/throwaway-container/README.md), [CI lessons](references/ci-operations.md) |
| Decisions, findings and design records | [Decision records](tools/decision-records/README.md), [finding records](tools/finding-records/README.md), [design register](tools/design-register/README.md), [record keeping skill](skills/record-keeping/SKILL.md) |
| Quality floor and review conventions | [Floor guard](tools/floor-guard/README.md), [pull request conventions](tools/pr-conventions/README.md), [security scan configuration](tools/security-scan-config/README.md), [local SonarQube scan](tools/local-sonar/README.md), [design reviewer](agents/design-reviewer.md), [doubt reviewer](agents/doubt-reviewer.md) |
| Roadmap sessions and closeout | [Roadmap board](tools/roadmap-board/README.md), [session closeout](tools/session-closeout/README.md), [roadmap session skill](skills/roadmap-session/SKILL.md) |
| Design conformance | [Design compare](tools/design-compare/README.md), [design register](tools/design-register/README.md), [design conformance skill](skills/design-conformance/SKILL.md) |

## Copy and adapt

Copy the complete selected tool or skill folder, including ORIGIN.md, notices and supporting files.
Skills that link to tools require the linked tool bundles too; the warehouse catalog lists these explicitly.
Preserve the relative skills/tools/references layout or rewrite those links for the chosen destination.
Read the local README before invoking a tool; service/configuration adapters are deliberate consumer choices.
No consuming project needs this source's original project folders or an absolute warehouse path.

Existing consumer authorization, testing, commit and publication policies take precedence.
Optional installers, live service calls, downloads, database adapters and hook activation are separate operations.
Use the component's stated exit/completeness contract; a successful conversion or a stored approval name is not proof a scan ran or a human approved it.

## Skills

- [agent-writing](skills/agent-writing/SKILL.md)
- [bounded-debugging](skills/bounded-debugging/SKILL.md)
- [clarify-explanation](skills/clarify-explanation/SKILL.md)
- [decision-map](skills/decision-map/SKILL.md)
- [decision-questionnaire](skills/decision-questionnaire/SKILL.md)
- [design-conformance](skills/design-conformance/SKILL.md)
- [dependency-change](skills/dependency-change/SKILL.md)
- [dependency-upgrade](skills/dependency-upgrade/SKILL.md)
- [evidence-review](skills/evidence-review/SKILL.md)
- [fixture-evidence](skills/fixture-evidence/SKILL.md)
- [issue-session](skills/issue-session/SKILL.md)
- [project-conductor](skills/project-conductor/SKILL.md)
- [record-keeping](skills/record-keeping/SKILL.md)
- [recoverable-sessions](skills/recoverable-sessions/SKILL.md)
- [roadmap-session](skills/roadmap-session/SKILL.md)
- [session-finish](skills/session-finish/SKILL.md)
- [session-review](skills/session-review/SKILL.md)
- [session-start](skills/session-start/SKILL.md)
- [spec-traceability](skills/spec-traceability/SKILL.md)
- [ux-validation](skills/ux-validation/SKILL.md)

## Agents

- [design-reviewer](agents/design-reviewer.md): read-only reviewer of one screen against the design export; never the builder of that screen.
- [doubt-reviewer](agents/doubt-reviewer.md): read-only adversarial reviewer that reports only what is wrong (MIT-licensed prompt origin, see [LICENSE-addyosmani](agents/LICENSE-addyosmani)).

Agents are Claude Code subagent definitions: copy the file into the consumer's agent directory and adapt tools and model to its runtime.

## Origins and updates

[Provenance](provenance/README.md) records exact source revisions, hashes, notices and adaptations.
[Inventory](inventory.json) records each reviewed group's disposition, including better alternatives and unresolved requirements.
This mixed-origin collection has no blanket relicensing: retain component licences and the owner's recorded permission.
Use [origin drift](tools/origin-drift/README.md) to compare explicitly selected local sources.
Updates are manual, reviewed adaptations. Source projects retain their own ownership and update workflows;
consumer copies do not update automatically.

## Validation

Run `python3 -B -m unittest discover -s tests -v` and `python3 -B scripts/check.py`.
Tests use disposable Git repositories, synthetic reports, fake service responses and fake database inventory.
PHP CLI exercises fingerprints/configuration; no live database, daemon, authenticated service,
model workload, network download or installed agent hook runtime is used.
Structural/fixture validation does not establish agent behavior or service deployment readiness.

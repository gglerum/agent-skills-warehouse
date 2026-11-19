# Claude Code notes

Read with the [runtime](runtime-contract.md), [evidence](evidence-contract.md) and
[report](report-contract.md) contracts.

**Scope.** Pass `--home`, `--plugin` or managed files only when the user authorized
them. With `--home`, inventory opens `~/.claude/settings.json`, `~/.claude.json`,
`~/.claude/CLAUDE.md`, `~/.claude/skills/` and `~/.claude/rules/`. The memory index
is `~/.claude/projects/<encoded-project>/memory/MEMORY.md`; pass it with `--memory`.
Never infer the project from an encoded directory name. Profiles, settings layers
and model versions can change loading and tool deferral.

**Imports and routes.** An `@import` loads with its parent, so moving text into an
import saves no startup context. A conditional Markdown link saves it only for
tasks that skip the link; see the routing cost in [SKILL.md](../SKILL.md). Keep
CLAUDE.md and rule scope, policy and precedence. Overlapping skills or descriptions
are candidates for cited architecture review, not proof of redundancy.

**Diagnostics.** If `/doctor` or prompt-audit output already exists and the user
permits it, pass it with `--diagnostic`, cite its claims as reported, and check them
against local files. Do not run diagnostics, enable telemetry, change permissions
or adopt unrelated configuration suggestions. Fixture profiles do not certify an
installed Claude release or agent behavior.

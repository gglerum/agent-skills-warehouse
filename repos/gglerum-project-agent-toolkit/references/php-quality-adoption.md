# Adopting PHP quality tooling

Detect framework, runtime, source/test layout and installed plugins before generating configurations. Treat generated rules as a reviewable starting point. Keep list overrides as replacements; re-scan new directories unless an explicit override owns that setting.

Separate rendering configuration from installing binaries, activating Composer plugins, editing scripts and installing Git hooks. Those are distinct mutations with separate consumer permissions. Pin downloads and verify checksums when installation is actually requested.

Auto-fixers operate on whole files. Check index/worktree identity first and preserve unstaged edits. A crashed fixer is not success. Run relevant tests after final formatting, and distinguish skipped optional tools from missing explicitly required checks.

Taint findings require following the source-to-sink path and the applicable security property. Baselines and suppressions need a reason and a regression case where appropriate; do not mistake suppressions for fixes. Tool APIs/versions must match the installed dependencies.

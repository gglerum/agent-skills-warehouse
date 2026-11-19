# Runtime contract: documentation profile 2026-11-11

Inventory rules were checked against official documentation on 2026-11-11.
"Supported" below means synthetic file-inventory compatibility, not behavioral
certification. The [scoped runtime trials](runtime-validation-summary.md) tested
one restricted Claude profile; they do not widen these profiles or show automatic
startup loading.

| Runtime | Baseline profile | Surface |
| --- | --- | --- |
| Codex | `docs-2026-11-11`, a documentation snapshot, **not a binary version** | Local CLI file layout |
| Claude Code | `2.1.285`, the instruction-plugin ID transition | Local CLI file layout |

**Version policy.** A newer Claude version (compared numerically) or a later
`docs-YYYY-MM-DD` Codex snapshot keeps the documented loading values at low
confidence, with a `newer_version` gap: the rules are assumed unchanged until
someone rechecks the docs. Older or unparseable versions get `unverified_version`,
and so do Codex binary versions, because the docs name no binary range. Non-CLI
surfaces get `unsupported_surface`. In those cases every loading value is
`unknown`. When loading rules change, recheck the sources below and move the
baseline.

## Official sources

- [Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md):
  global override before base; at most one nonempty override, base or fallback per
  directory from project to launch directory; later is more specific; a source byte
  cap. Suppressed candidates are kept, and cap uncertainty is flagged.
- [Codex skills](https://learn.chatgpt.com/docs/build-skills): repository
  `.agents/skills` along that chain and explicit user `.agents/skills`; metadata
  discovery is separate from body loading. Duplicate names are kept. Legacy
  config-home skills get unknown loading. Sidecar YAML is kept as configuration with
  an unsupported-policy gap.
- [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-basic)
  ([reference](https://learn.chatgpt.com/docs/config-file/config-reference)): user
  then project layers; project trust and runtime overrides can change the result.
  Rules are inventoried without evaluating them.
- [Claude memory](https://code.claude.com/docs/en/memory): ancestor instructions
  concatenate; nested guidance and path rules are conditional; imports expand
  eagerly up to four hops, skipping code examples. The AGENTS.md fallback and the
  user instruction-plugin mode are modeled. Memory paths are passed explicitly, not
  guessed. Index limits and enablement need runtime evidence.
- [Claude skills](https://code.claude.com/docs/en/skills): metadata and body loads
  differ; commands, personal, project and nested skills, and explicit plugin skill
  paths are inventoried. Name collisions are kept as uncertainty.
- [Claude settings](https://code.claude.com/docs/en/settings): precedence is user,
  project, local, command line, managed, with per-field merges. Inventory keeps the
  file layers and flags unresolved effective values; it is not a settings resolver.
- [Claude plugins](https://code.claude.com/docs/en/plugins-reference): explicit
  manifests, standard and custom skill/command paths, hook files and MCP configs are
  inspected. Being installed or enabled does not show runtime activation.

## Coverage limits

- Host prompts, managed delivery, system roots, built-in or synced skills, active
  profiles, CLI overrides, worktree fallbacks, extra-directory flags and the tools
  actually advertised need supplied files or runtime evidence; otherwise they are
  gaps. `--instruction` and `--extra-config` record a known external or managed file
  under an allowed root, with unknown effective scope.
- Only the launch chain and explicitly named nested directories are inspected.
  Ancestors above `--boundary` and unlisted nested directories are gaps.
- TOML and JSON are parsed as data. Hooks and MCP entries are never run. Complex
  YAML, unknown shapes and unmodeled keys become gaps, and an unknown format never
  shows non-use. Permissions and environment values are not exported or resolved.
  Disabled built-ins, exclusions and overrides stay uncertain, not absent.
- Local Markdown links and Claude imports are followed inside allowed roots;
  non-Markdown targets get a parsing gap. No code runs and nothing is fetched.
  References stop after 20 hops; eager imports after four.
- A file snapshot is not a runtime observation. It does not prove agent behavior,
  injected content, optimal size or task quality.

No experimental Codex usage adapter, community audit executable, telemetry
collector or tracing dependency was adopted.

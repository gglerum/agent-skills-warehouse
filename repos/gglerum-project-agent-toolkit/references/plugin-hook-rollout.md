# Hook rollout and validation

Keep informational hooks separate from policy-enforcing hooks. Source code present in a vendored folder does not prove a plugin is installed, enabled or loaded in the interactive runtime. Record the actual client version, configuration and loaded hook source.

Test malformed input, missing interpreter/script, timeout and command failure, not only a successful block. Define whether each hook should fail open or closed. Test safe command arguments and quoted text so a commit message naming a forbidden command is not misclassified as execution.

Shell-token heuristics are not a security sandbox: indirect execution, aliases, interpreters and unsupported syntax can bypass them. Use runtime permissions and isolated environments for actual trust boundaries.

Roll out source changes, vendored updates and installed plugin updates as separate steps under the consumer's authorization. Use disposable inputs first. Avoid stop-hook retry loops and recheck the actual worktree rather than another session's checkout.

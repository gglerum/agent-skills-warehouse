# Proof scripts and fixture evidence

Name the property and its independent oracle. Run a positive control that demonstrates the action is possible, then the constrained treatment. A flag or exit code alone is not an observed boundary.

Use explicit outcomes: PASS, FAIL, BLOCKED_BY_SETUP, INCONCLUSIVE and BROKEN_TEST. Empty output is unavailable evidence. Keep expectations separate from observations and record unsupported/untested paths.

Collect logs, process status, OOM/resource counters and filesystem effects before cleanup. Never use automatic deletion when it removes the evidence needed for the decision. Pin versions and record actual preconditions. Test values on both sides of a threshold and account for load produced by the test itself.

Make a failed part individually reproducible. Check shell error handling, lint and dry-run support before asking someone to execute a privileged script. Only operate on environments within the consumer's explicit scope. A worksheet or generated persona is not a human approval.

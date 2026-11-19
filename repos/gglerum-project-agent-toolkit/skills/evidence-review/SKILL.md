---
name: evidence-review
description: "Review a change against code behavior, canonical requirements and meaningful failure evidence."
---

# Evidence review

Fix the comparison point (commit, branch or merge base) and inspect the full relevant diff plus callers/tests. Separate correctness, requirement conformance, security boundaries, test value and unnecessary complexity.

Report actionable findings with a concrete trigger, affected path and consequence. Verify a suspected defect rather than asserting it from style preference. Distinguish unverified risk from a reproduced failure and keep unrelated follow-ups separate. Review changes to tests/expectations against their independent oracle. Use a focused second pass only when meaningful fixes require it.

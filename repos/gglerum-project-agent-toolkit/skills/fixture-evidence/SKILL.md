---
name: fixture-evidence
description: "Design deterministic adversarial fixtures and compare expected versus observed results without allowing failures of the harness to become passes."
---

# Fixture evidence

Name the property, scope and independent oracle before implementing a fixture. Pair a vulnerable/blocked case with a healthy positive control that proves the action is possible. Bound size, memory, time and network capabilities in the runner.

Record expectation separately from observation. Classify PASS, FAIL, BLOCKED_BY_SETUP, INCONCLUSIVE and BROKEN_TEST distinctly; an exit code, empty output, reflected marker or a security flag alone is not proof. Retain exact versions, hashes, preconditions and replay evidence. Collect process/log/resource evidence before cleanup.

Keep labels and policy approval independent from the implementation agent where the consumer requires it. Do not import a source project's product fixtures or schemas as universal security policy. Use [proof discipline](../../references/proof-discipline.md) for the executable-evidence checklist.

---
name: bounded-debugging
description: "Diagnose a difficult or intermittent bug with explicit hypotheses, bounded experiments and preserved reproduction evidence."
---

# Bounded debugging

Start with the failing behavior and a minimal reproduction. List plausible causes and identify the cheapest observation that distinguishes them. Change one relevant variable per experiment and record the actual outcome, including setup failure or inconclusive results.

Trace callers and state transitions before patching symptoms. Keep user-operated actions under human control; use the adjacent [reproduction loop](hitl-loop.template.sh) for observations, never credentials. Bound repeated attempts according to the consumer's policy and report when the evidence stops distinguishing hypotheses.

Verify the final fix against the reproduction and relevant negative cases. Preserve exact commands and outcomes in the handoff; do not relax an assertion simply to make the run pass.

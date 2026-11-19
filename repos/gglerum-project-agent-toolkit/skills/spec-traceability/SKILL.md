---
name: spec-traceability
description: "Trace a change or review finding to its owning canonical specification and preserve the project authority order."
---

# Spec traceability

Locate the owning rule through the consumer's specification index; read only the relevant sections. State the exact invariant or acceptance condition being implemented or reviewed and the tests/evidence that demonstrate it.

Follow cross-spec references only when the change crosses that boundary. If implementation would require changing an authoritative rule, surface the conflict and use the consumer's spec-revision process. Do not edit expectations or canonical specs merely to fit existing code. Derivative exports and agent guidance do not override the configured authority order.

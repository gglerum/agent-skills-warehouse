---
name: session-start
description: "Collect compact repository and backlog evidence, prioritize unfinished work, and start an authorized coding session."
---

# Session start

Collect branch/HEAD, dirty state, unpushed work, open PR state and the relevant backlog using compact readers. Keep unavailable signals distinct from empty results. Reuse an existing handoff when its task is already authorized.

Rank unfinished work and confirmed defects before new work, subject to the owner's requested priority. Check that a reported defect still exists before presenting it. Present the proposed scope and verification briefly. Ask only for a decision that is actually missing; existing authorization remains valid.

Use the consumer's branch and tracker conventions. Check whether the branch's PR is merged/closed before adding work to it. Claim tracker items or create branches only under the consumer's permissions. Use [Git checks](../../tools/git-checks/README.md) for local evidence and [service readers](../../tools/service-readers/README.md) when configured.

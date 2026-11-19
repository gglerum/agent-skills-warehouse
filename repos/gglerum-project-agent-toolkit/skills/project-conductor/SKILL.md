---
name: project-conductor
description: "Choose next work from explicit project state and prerequisites while keeping human gates separate from automated checks."
---

# Project conductor

Read current state, the active queue, relevant roadmap/gate definitions and recorded evidence. Offer executable work, human work due and blocked downstream work separately. Do not infer passed gates from chat memory or a worksheet alone.

AUTO gates require objective evidence; REVIEW gates collect a recommendation and the required review; HUMAN gates require explicit approval of that exact gate. Existing task authorization is not approval of a different gate. Generated personas or automated UI checks are not human participation.

Use [project-state](../../tools/project-state/README.md) as an optional local mechanism. Replace its example gates with the consumer's real policy. Approval records are assertions requiring human provenance; the script cannot authenticate who gave an approval. Keep remote board synchronization a separately authorized adapter.

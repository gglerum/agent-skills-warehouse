# Deployment claims need deployment evidence

Resolve the actual merged commit, including squash/rebase results. Require a deployment identity, exact deployed SHA, target environment, timestamp with timezone and a passing health observation associated with that deployment.

CI success, a merge record, a newer branch head or a generic healthy endpoint cannot replace a matching receipt. Keep availability unconfirmed when required fields are absent or stale. The receipt's producer must be trusted independently; matching JSON fields do not prove authenticity.

Bind human acceptance instructions to the confirmed environment and revision. Tracker updates and external messages remain subject to the consumer's authorization and should avoid duplicates for the same deployment.

# Benchmarking an agent tool

State the actual task and the simplest existing baseline. Freeze queries, labels, metrics and acceptance thresholds before the measured run. Keep tuning and untouched evaluation sets separate; test a fix suggested by results on fresh data.

Record exact versions, workload, commands, cold/warm state, latency, CPU/RAM/working-set, disk/index size, foreground responsiveness and quality. Give sample size and what one example contributes to the reported percentage. A result on one corpus or machine does not establish performance on another.

Store each run in a new directory and retain raw evidence. Treat no-answer queries, index freshness and unavailable-tool behavior as part of the evaluation. Prefer a tool only when measured benefit justifies complexity. Installing services and running paid agent experiments requires the consuming task's authorization and budget.

This method does not endorse the source project's unresolved augmentation candidates.

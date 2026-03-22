---
id: verification.run_evaluator
version: 1.0.0
phase: phase3
allowed_operators:
  - run_finalize
outputs:
  - run_summary
  - artifact_review
capabilities:
  - artifact_manifest_validation
  - metric_summary_review
risk_level: low
---

Validates run artifacts and helps summarize the completed execution in durable lineage and reports.
